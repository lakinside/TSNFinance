import os
import hashlib
import pandas as pd
from datetime import datetime
from werkzeug.utils import secure_filename
from flask import Flask, render_template, request, redirect, url_for, flash, send_file, jsonify
from models import db, Budget, BudgetSection, BudgetArticle, Operation, Document, StatementImport, SplitOperation, DocumentLibrary, OperationDocumentLink
import threading
import uuid
from transliterate import translit
from datetime import timedelta
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import os

import io
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak, Image
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm, cm
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import PyPDF2
from PyPDF2 import PdfReader, PdfWriter

task_status = {}

import sys

# Или используйте простую функцию без транслитерации
def generate_safe_filename(original_filename):
    """Генерация безопасного имени файла с сохранением расширения"""
    # Получаем расширение файла
    ext = ''
    if '.' in original_filename:
        ext = original_filename.rsplit('.', 1)[1].lower()

    # Генерируем уникальное имя
    unique_name = str(uuid.uuid4())

    if ext:
        return f"{unique_name}.{ext}"
    return unique_name


# Или с транслитерацией (если установлен пакет transliterate)
def generate_safe_filename_translit(original_filename):
    """Генерация имени файла с транслитерацией кириллицы"""
    from transliterate import translit

    # Разделяем имя и расширение
    if '.' in original_filename:
        name_part = original_filename.rsplit('.', 1)[0]
        ext = original_filename.rsplit('.', 1)[1].lower()
    else:
        name_part = original_filename
        ext = ''

    # Транслитерируем кириллицу
    safe_name = translit(name_part, 'ru', reversed=True)
    # Заменяем пробелы и спецсимволы
    safe_name = ''.join(c for c in safe_name if c.isalnum() or c in '._-')
    safe_name = safe_name.replace(' ', '_')

    # Добавляем уникальный суффикс
    unique_suffix = str(uuid.uuid4())[:8]

    if ext:
        return f"{safe_name}_{unique_suffix}.{ext}"
    return f"{safe_name}_{unique_suffix}"

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key-change-this'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///bank_statement.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['REPORT_FOLDER'] = 'reports'
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024  # 500MB max

# Создание необходимых папок
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['REPORT_FOLDER'], exist_ok=True)
ALLOWED_EXTENSIONS = {'xlsx', 'xls', 'txt'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

db.init_app(app)

def generate_unique_hash(row, statement_filename):
    """Генерация уникального хэша для операции"""
    unique_str = f"{row.get('Дата проводки', '')}_{row.get('Назначение платежа', '')}_{row.get('Счет Дебет', '')}_{row.get('Счет Кредит', '')}_{row.get('Сумма по дебету', 0)}_{row.get('Сумма по кредиту', 0)}_{statement_filename}"
    return hashlib.md5(unique_str.encode('utf-8')).hexdigest()


def parse_sber_statement(filepath, filename):
    """Парсинг выписки СберБизнес"""
    try:
        df = pd.read_excel(filepath, header=None)

        # Поиск заголовков
        header_row = None
        for idx, row in df.iterrows():
            if 'Дата проводки' in str(row.values):
                header_row = idx
                break

        if header_row is None:
            raise Exception("Не найден заголовок с 'Дата проводки'")

        # Чтение данных
        df.columns = df.iloc[header_row]
        df = df[header_row + 1:].reset_index(drop=True)

        operations = []
        for _, row in df.iterrows():
            # Пропускаем пустые строки
            if pd.isna(row.get('Дата проводки')) and pd.isna(row.get('Сумма по дебету')) and pd.isna(
                    row.get('Сумма по кредиту')):
                continue

            print(row)

            # Парсим дату
            date_str = row.get('Дата проводки')
            if pd.isna(date_str):
                continue

            try:
                if isinstance(date_str, str):
                    trans_date = datetime.strptime(date_str.split()[0], '%Y-%m-%d')
                else:
                    trans_date = date_str
            except:
                continue

            # Безопасное получение суммы с обработкой None/NaN
            debit_raw = row.get('Сумма по дебету', 0)
            credit_raw = row.get('Сумма по кредиту', 0)

            # Преобразуем в float, обрабатывая None и NaN
            try:
                debit = float(debit_raw) if pd.notna(debit_raw) else 0.0
            except (ValueError, TypeError):
                debit = 0.0

            try:
                credit = float(credit_raw) if pd.notna(credit_raw) else 0.0
            except (ValueError, TypeError):
                credit = 0.0

            # Определяем тип операции
            trans_type = 'debit' if debit > 0 else 'credit'

            if debit == 0 and credit == 0:
                continue

            # Безопасное получение текстовых полей
            doc_number = row.get('№ документа', '')
            doc_number = str(doc_number) if pd.notna(doc_number) else ''

            purpose = row.get('Назначение платежа', '')
            purpose = str(purpose) if pd.notna(purpose) else ''

            counterparty = row.get('Счет Кредит', '') if debit > 0 else row.get('Счет Дебет', '')
            counterparty = str(counterparty) if pd.notna(counterparty) else ''

            bank_name = row.get('Банк (БИК и наименование)', '')
            bank_name = str(bank_name) if pd.notna(bank_name) else ''

            operation = {
                'transaction_date': trans_date,
                'doc_number': doc_number,
                'debit_amount': debit,
                'credit_amount': credit,
                'purpose': purpose,
                'counterparty': counterparty,
                'bank_name': bank_name,
                'transaction_type': trans_type,
            }
            operations.append(operation)

        return operations
    except Exception as e:
        raise Exception(f"Ошибка парсинга файла: {str(e)}")

@app.route('/')
def index():
    return render_template('index.html')


@app.route('/statements')
def statements():
    imports = StatementImport.query.order_by(StatementImport.import_date.desc()).all()
    operations = Operation.query.order_by(Operation.transaction_date.desc()).limit(100).all()
    return render_template('statements.html', imports=imports, operations=operations)


# Добавьте эти функции в app.py

def parse_1c_statement(filepath, filename):
    """Парсинг выписки в формате 1С:Предприятие"""
    operations = []

    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()

        # Разбиваем на секции документов
        sections = content.split('СекцияДокумент=')

        for section in sections[1:]:
            lines = section.strip().split('\n')

            operation = {}
            for line in lines:
                if '=' in line:
                    key, value = line.split('=', 1)
                    key = key.strip()
                    value = value.strip()

                    if key == 'Номер':
                        operation['doc_number'] = value
                    elif key == 'Дата':
                        try:
                            operation['transaction_date'] = datetime.strptime(value, '%d.%m.%Y')
                        except:
                            pass
                    elif key == 'Сумма':
                        try:
                            operation['amount'] = float(value)
                        except:
                            operation['amount'] = 0
                    elif key == 'НазначениеПлатежа':
                        operation['purpose'] = value
                    elif key == 'Плательщик':
                        operation['payer'] = value
                    elif key == 'Получатель':
                        operation['payee'] = value
                    elif key == 'ПлательщикСчет':
                        operation['payer_account'] = value
                    elif key == 'ПолучательСчет':
                        operation['payee_account'] = value
                    elif key == 'ПлательщикБанк1':
                        operation['payer_bank'] = value
                    elif key == 'ПолучательБанк1':
                        operation['payee_bank'] = value
                    elif key == 'ВидОплаты':
                        operation['payment_type'] = value

            our_account = "40703810640000401049"

            if operation:
                if operation.get('payee_account') == our_account:
                    operation['transaction_type'] = 'credit'
                    operation['credit_amount'] = operation.get('amount', 0)
                    operation['debit_amount'] = 0
                    operation['counterparty'] = operation.get('payer', '')
                    operation['bank_name'] = operation.get('payer_bank', '')
                elif operation.get('payer_account') == our_account:
                    operation['transaction_type'] = 'debit'
                    operation['debit_amount'] = operation.get('amount', 0)
                    operation['credit_amount'] = 0
                    operation['counterparty'] = operation.get('payee', '')
                    operation['bank_name'] = operation.get('payee_bank', '')
                else:
                    continue

                # Устанавливаем operation_type = None (пустое значение)
                operation['operation_type'] = None

                if operation.get('transaction_date') and operation.get('amount', 0) > 0:
                    operations.append(operation)

        return operations
    except Exception as e:
        raise Exception(f"Ошибка парсинга файла 1С: {str(e)}")


def generate_unique_hash_1c(operation_data):
    """Генерация уникального хэша для операции из 1С"""
    date_str = operation_data['transaction_date'].strftime('%Y-%m-%d') if operation_data['transaction_date'] else ''
    amount = operation_data.get('amount', 0)
    doc_number = str(operation_data.get('doc_number', ''))[:30]
    purpose = operation_data.get('purpose', '')[:100]

    unique_str = f"{date_str}_{amount}_{doc_number}_{purpose}"
    return hashlib.md5(unique_str.encode('utf-8')).hexdigest()


# Обновите функцию upload_statement для поддержки обоих форматов:

@app.route('/upload_statement', methods=['POST'])
def upload_statement():
    if 'file' not in request.files:
        flash('Файл не выбран', 'error')
        return redirect(url_for('statements'))

    file = request.files['file']
    if file.filename == '':
        flash('Файл не выбран', 'error')
        return redirect(url_for('statements'))

    if not allowed_file(file.filename):
        flash('Поддерживаются только файлы Excel (.xlsx, .xls) и текстовые файлы (.txt) формата 1С', 'error')
        return redirect(url_for('statements'))

    filename = secure_filename(file.filename)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], f"{timestamp}_{filename}")
    file.save(filepath)

    # Определяем тип файла
    is_1c_format = False
    is_excel_format = filename.endswith(('.xlsx', '.xls'))

    # Проверяем содержимое для определения формата 1С
    if not is_excel_format:
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            first_line = f.readline()
            if '1CClientBankExchange' in first_line:
                is_1c_format = True

    try:
        if is_1c_format:
            operations_data = parse_1c_statement(filepath, filename)
            # Для 1С используем другой метод генерации хэша
            generate_hash = generate_unique_hash_1c
        else:
            operations_data = parse_sber_statement(filepath, filename)
            generate_hash = generate_unique_hash

        new_operations = []
        duplicates = 0
        duplicate_details = []

        for op_data in operations_data:
            # Проверяем на дубликат
            is_dup, dup_id = check_duplicate_operation(op_data)

            if is_dup:
                duplicates += 1
                duplicate_details.append({
                    'date': op_data['transaction_date'],
                    'amount': op_data.get('debit_amount', 0) if op_data.get('debit_amount', 0) > 0 else op_data.get(
                        'credit_amount', 0),
                    'purpose': op_data.get('purpose', '')[:50]
                })
                continue

            # Генерируем хэш
            unique_hash = generate_hash(op_data)

            operation = Operation(
                transaction_date=op_data['transaction_date'],
                doc_number=op_data.get('doc_number', ''),
                debit_amount=op_data.get('debit_amount', 0),
                credit_amount=op_data.get('credit_amount', 0),
                purpose=op_data.get('purpose', ''),
                counterparty=op_data.get('counterparty', ''),
                bank_name=op_data.get('bank_name', ''),
                transaction_type=op_data.get('transaction_type', 'credit'),
                unique_hash=unique_hash,
                statement_file=filename
            )
            db.session.add(operation)
            new_operations.append(operation)

        db.session.commit()

        # Сохраняем историю импорта
        statement_import = StatementImport(
            filename=filename,
            operations_count=len(new_operations),
            status='success'
        )
        db.session.add(statement_import)
        db.session.commit()

        file_type = "1С" if is_1c_format else "Excel"
        flash_msg = f'✅ Загружено {len(new_operations)} новых операций (формат {file_type}). Пропущено дубликатов: {duplicates}'
        if duplicate_details and len(duplicate_details) <= 5:
            flash_msg += f'\n\nПропущенные операции:'
            for dup in duplicate_details[:5]:
                flash_msg += f'\n- {dup["date"].strftime("%d.%m.%Y")}: {dup["amount"]:.2f}₽ - {dup["purpose"]}'
        if len(duplicate_details) > 5:
            flash_msg += f'\n\n...и еще {len(duplicate_details) - 5} операций'

        flash(flash_msg, 'success')
    except Exception as e:
        flash(f'Ошибка при загрузке файла: {str(e)}', 'error')
        statement_import = StatementImport(
            filename=filename,
            status='error',
            error_message=str(e)
        )
        db.session.add(statement_import)
        db.session.commit()

    return redirect(url_for('statements'))


def check_duplicate_operation(operation_data):
    """Проверка на дубликат для операций из 1С"""
    trans_date = operation_data['transaction_date']
    amount = operation_data.get('debit_amount', 0) if operation_data.get('debit_amount', 0) > 0 else operation_data.get(
        'credit_amount', 0)

    # Ищем операции за ту же дату с той же суммой
    date_start = datetime(trans_date.year, trans_date.month, trans_date.day, 0, 0, 0)
    date_end = datetime(trans_date.year, trans_date.month, trans_date.day, 23, 59, 59)

    potential_duplicates = Operation.query.filter(
        Operation.transaction_date >= date_start,
        Operation.transaction_date <= date_end,
        ((Operation.debit_amount == amount) | (Operation.credit_amount == amount))
    ).all()

    current_purpose = operation_data.get('purpose', '')[:100]

    for dup in potential_duplicates:
        dup_purpose = (dup.purpose or '')[:100]

        # Сравниваем назначение платежа
        if current_purpose == dup_purpose:
            return True, dup.id
        # Или номер документа
        current_doc = str(operation_data.get('doc_number', ''))
        dup_doc = str(dup.doc_number or '')
        if current_doc and dup_doc and current_doc == dup_doc:
            return True, dup.id

    return False, None

@app.route('/update_operation/<int:operation_id>', methods=['POST'])
def update_operation(operation_id):
    operation = Operation.query.get_or_404(operation_id)

    article_id = request.form.get('article_id')
    if article_id and article_id != '':
        operation.article_id = int(article_id)
    else:
        operation.article_id = None

    db.session.commit()
    flash('Статья сметы обновлена', 'success')
    return redirect(url_for('operation_detail', operation_id=operation_id))


@app.route('/upload_document/<int:operation_id>', methods=['POST'])
def upload_document(operation_id):
    operation = Operation.query.get_or_404(operation_id)

    if 'document' not in request.files:
        flash('Файл не выбран', 'error')
        return redirect(url_for('operation_detail', operation_id=operation_id))

    file = request.files['document']
    if file.filename == '':
        flash('Файл не выбран', 'error')
        return redirect(url_for('operation_detail', operation_id=operation_id))

    if not file.filename.endswith('.pdf'):
        flash('Поддерживаются только PDF файлы', 'error')
        return redirect(url_for('operation_detail', operation_id=operation_id))

    original_filename = secure_filename(file.filename)
    filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{operation_id}_{original_filename}"
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(filepath)

    # Определяем номер приложения
    max_num = db.session.query(db.func.max(Document.attachment_number)).filter_by(
        operation_id=operation_id).scalar() or 0

    document = Document(
        operation_id=operation_id,
        filename=filename,
        original_filename=original_filename,
        file_path=filepath,
        attachment_number=max_num + 1
    )
    db.session.add(document)
    db.session.commit()

    flash(f'Документ "{original_filename}" прикреплен (Приложение {max_num + 1})', 'success')
    return redirect(url_for('operation_detail', operation_id=operation_id))


@app.route('/delete_document/<int:document_id>')
def delete_document(document_id):
    document = Document.query.get_or_404(document_id)
    operation_id = document.operation_id

    # Удаляем файл
    if os.path.exists(document.file_path):
        os.remove(document.file_path)

    db.session.delete(document)
    db.session.commit()

    flash('Документ удален', 'success')
    return redirect(url_for('operation_detail', operation_id=operation_id))



@app.route('/generate_report_with_files', methods=['POST'])
def generate_report_with_files():
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import SimpleDocTemplate as DocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    import PyPDF2

    start_date = request.form.get('start_date')
    end_date = request.form.get('end_date')
    article_ids = request.form.getlist('article_ids')

    # Фильтрация операций
    query = Operation.query
    if start_date:
        query = query.filter(Operation.transaction_date >= datetime.strptime(start_date, '%Y-%m-%d'))
    if end_date:
        query = query.filter(Operation.transaction_date <= datetime.strptime(end_date, '%Y-%m-%d'))
    if article_ids:
        query = query.filter(Operation.article_id.in_([int(aid) for aid in article_ids if aid]))

    operations = query.order_by(Operation.transaction_date).all()

    if not operations:
        flash('Нет операций для выбранных фильтров', 'error')
        return redirect(url_for('report'))

    # Создаем директорию
    os.makedirs(app.config['REPORT_FOLDER'], exist_ok=True)

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    report_path = os.path.join(app.config['REPORT_FOLDER'], f"report_{timestamp}.pdf")

    # Создаем основной отчет
    doc = DocTemplate(report_path, pagesize=A4)
    styles = getSampleStyleSheet()
    story = []

    # Заголовок
    title_style = ParagraphStyle('CustomTitle', parent=styles['Heading1'], fontSize=16, alignment=1, spaceAfter=30)
    story.append(Paragraph("Отчет по операциям", title_style))

    filter_text = f"Период: {start_date or 'начало'} - {end_date or 'конец'}"
    story.append(Paragraph(filter_text, styles['Normal']))
    story.append(Spacer(1, 20))

    # Таблица
    table_data = [['№', 'Дата', 'Сумма (₽)', 'Тип', 'Назначение', 'Статья', 'Приложение']]

    for idx, op in enumerate(operations, 1):
        amount = op.debit_amount if (op.debit_amount or 0) > 0 else (op.credit_amount or 0)
        attachments = op.documents
        attachment_text = ', '.join([f"Приложение {doc.attachment_number}" for doc in attachments]) if attachments else '-'

        table_data.append([
            str(idx),
            op.transaction_date.strftime('%d.%m.%Y') if op.transaction_date else '-',
            f"{amount:,.2f}",
            'Расход' if (op.debit_amount or 0) > 0 else 'Доход',
            (op.purpose or '-')[:80],
            op.article.name if op.article else '-',
            attachment_text
        ])

    table = Table(table_data, repeatRows=1)
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
    ]))

    story.append(table)

    # Добавляем список приложений
    all_docs = [(doc.attachment_number, doc.file_path, doc.original_filename, op)
                for op in operations for doc in op.documents
                if doc.file_path and os.path.exists(doc.file_path)]

    if all_docs:
        story.append(PageBreak())
        story.append(Paragraph("Приложения", title_style))
        story.append(Spacer(1, 20))

        for attach_num, file_path, orig_name, op in all_docs:
            story.append(Paragraph(f"<b>Приложение {attach_num}:</b> {orig_name}", styles['Normal']))
            story.append(Paragraph(f"Операция: {(op.purpose or '-')[:100]}", styles['Normal']))
            story.append(Spacer(1, 10))

    # Строим PDF
    try:
        doc.build(story)
    except Exception as e:
        flash(f'Ошибка при создании отчета: {str(e)}', 'error')
        return redirect(url_for('report'))

    # Отправляем файл
    return send_file(report_path, as_attachment=True, download_name=f"отчет_{timestamp}.pdf")


@app.route('/generate_report', methods=['POST'])
def generate_report():
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import SimpleDocTemplate as DocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    import PyPDF2

    start_date = request.form.get('start_date')
    end_date = request.form.get('end_date')
    article_ids = request.form.getlist('article_ids')

    # Фильтрация операций
    query = Operation.query
    if start_date:
        query = query.filter(Operation.transaction_date >= datetime.strptime(start_date, '%Y-%m-%d'))
    if end_date:
        query = query.filter(Operation.transaction_date <= datetime.strptime(end_date, '%Y-%m-%d'))
    if article_ids:
        query = query.filter(Operation.article_id.in_([int(aid) for aid in article_ids if aid]))

    operations = query.order_by(Operation.transaction_date).all()

    if not operations:
        flash('Нет операций для выбранных фильтров', 'error')
        return redirect(url_for('report'))

    # Создаем директорию если не существует
    os.makedirs(app.config['REPORT_FOLDER'], exist_ok=True)

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    report_filename = f"report_{timestamp}.pdf"
    report_path = os.path.join(app.config['REPORT_FOLDER'], report_filename)

    # Создаем PDF документ
    doc = DocTemplate(report_path, pagesize=A4,
                      topMargin=20 * mm, bottomMargin=20 * mm,
                      leftMargin=15 * mm, rightMargin=15 * mm)
    styles = getSampleStyleSheet()
    story = []

    # Создаем стили
    title_style = ParagraphStyle('CustomTitle', parent=styles['Heading1'],
                                 fontSize=16, alignment=1, spaceAfter=30)
    heading_style = ParagraphStyle('Heading', parent=styles['Heading2'],
                                   fontSize=12, alignment=0, spaceAfter=10)

    # Заголовок отчета
    story.append(Paragraph("Отчет по операциям", title_style))

    # Информация о фильтрах
    filter_text = f"Период: {start_date or 'начало'} - {end_date or 'конец'}"
    story.append(Paragraph(filter_text, styles['Normal']))

    story.append(Spacer(1, 20))

    # Подсчет сумм
    total_debit = sum((op.debit_amount or 0) for op in operations)
    total_credit = sum((op.credit_amount or 0) for op in operations)

    story.append(Paragraph(f"Итого расходов: {total_debit:,.2f} ₽", styles['Normal']))
    story.append(Paragraph(f"Итого доходов: {total_credit:,.2f} ₽", styles['Normal']))
    story.append(Spacer(1, 20))

    # Таблица с операциями
    table_data = [['№', 'Дата', 'Сумма (₽)', 'Тип', 'Назначение', 'Статья', 'Приложение']]

    for idx, op in enumerate(operations, 1):
        # Получаем сумму
        amount = 0
        if op.debit_amount and op.debit_amount > 0:
            amount = op.debit_amount
        elif op.credit_amount and op.credit_amount > 0:
            amount = op.credit_amount

        # Получаем приложения
        attachments = op.documents
        attachment_text = ', '.join([f"Приложение {doc.attachment_number}" for doc in attachments]) if attachments else '-'

        # Ограничиваем длину назначения
        purpose_text = (op.purpose or '-')
        if len(purpose_text) > 80:
            purpose_text = purpose_text[:80] + '...'

        table_data.append([
            str(idx),
            op.transaction_date.strftime('%d.%m.%Y') if op.transaction_date else '-',
            f"{amount:,.2f}",
            'Расход' if (op.debit_amount or 0) > 0 else 'Доход',
            Paragraph(purpose_text, styles['Normal']),
            op.article.name if op.article else '-',
            attachment_text
        ])

    # Создаем таблицу
    table = Table(table_data, repeatRows=1)
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 9),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('ALIGN', (2, 1), (2, -1), 'RIGHT'),
        ('FONTSIZE', (0, 1), (-1, -1), 8),
    ]))

    story.append(table)

    # Собираем все приложения
    all_docs = []
    for op in operations:
        for doc in op.documents:
            if doc.file_path and os.path.exists(doc.file_path):
                all_docs.append((doc.attachment_number, doc.file_path, doc.original_filename, op))

    if all_docs:
        story.append(PageBreak())
        story.append(Paragraph("Список приложений", title_style))
        story.append(Spacer(1, 20))

        # Сортируем по номеру приложения
        all_docs.sort(key=lambda x: x[0] or 0)

        for attach_num, file_path, orig_name, op in all_docs:
            story.append(Paragraph(f"<b>Приложение {attach_num}:</b> {orig_name}", styles['Normal']))
            story.append(Paragraph(
                f"Операция от {op.transaction_date.strftime('%d.%m.%Y') if op.transaction_date else '-'}: {(op.purpose or '-')[:100]}",
                styles['Normal']))
            story.append(Spacer(1, 10))

    # Строим PDF
    try:
        doc.build(story)
        print(f"PDF создан: {report_path}")
    except Exception as e:
        print(f"Ошибка при создании PDF: {e}")
        flash(f'Ошибка при создании отчета: {str(e)}', 'error')
        return redirect(url_for('report'))

    # Проверяем, что файл создан
    if not os.path.exists(report_path):
        flash('Не удалось создать PDF отчет', 'error')
        return redirect(url_for('report'))

    # Отправляем файл пользователю
    return send_file(
        report_path,
        as_attachment=True,
        download_name=f"отчет_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf"
    )

@app.route('/api/statistics')
def statistics():
    total_operations = Operation.query.count()
    total_with_article = Operation.query.filter(Operation.article_id.isnot(None)).count()
    total_with_docs = Operation.query.join(Document).distinct().count()

    return jsonify({
        'total_operations': total_operations,
        'total_with_article': total_with_article,
        'total_with_docs': total_with_docs,
        'percent_classified': round(total_with_article / total_operations * 100, 1) if total_operations > 0 else 0
    })


@app.route('/budgets')
def budgets():
    budgets_list = Budget.query.order_by(Budget.year.desc(), Budget.name).all()
    return render_template('budgets.html', budgets=budgets_list)


@app.route('/add_budget', methods=['POST'])
def add_budget():
    name = request.form.get('name')
    year = request.form.get('year')
    description = request.form.get('description')

    budget = Budget(
        name=name,
        year=int(year) if year else None,
        description=description
    )
    db.session.add(budget)
    db.session.commit()

    flash('Смета добавлена', 'success')
    return redirect(url_for('budgets'))


@app.route('/edit_budget/<int:budget_id>', methods=['POST'])
def edit_budget(budget_id):
    budget = Budget.query.get_or_404(budget_id)
    budget.name = request.form.get('name')
    budget.year = int(request.form.get('year')) if request.form.get('year') else None
    budget.description = request.form.get('description')
    db.session.commit()

    flash('Смета обновлена', 'success')
    return redirect(url_for('budgets'))


@app.route('/delete_budget/<int:budget_id>')
def delete_budget(budget_id):
    budget = Budget.query.get_or_404(budget_id)
    budget.is_active = False
    db.session.commit()

    flash('Смета деактивирована', 'success')
    return redirect(url_for('budgets'))


# ========== Управление разделами сметы ==========

@app.route('/budget/<int:budget_id>/sections')
def budget_sections(budget_id):
    budget = Budget.query.get_or_404(budget_id)
    sections = BudgetSection.query.filter_by(budget_id=budget_id).order_by(BudgetSection.sort_order).all()
    return render_template('budget_sections.html', budget=budget, sections=sections)


@app.route('/add_section', methods=['POST'])
def add_section():
    budget_id = request.form.get('budget_id')
    code = request.form.get('code')
    name = request.form.get('name')
    description = request.form.get('description')
    sort_order = request.form.get('sort_order', 0)

    section = BudgetSection(
        budget_id=int(budget_id),
        code=code,
        name=name,
        description=description,
        sort_order=int(sort_order)
    )
    db.session.add(section)
    db.session.commit()

    flash('Раздел добавлен', 'success')
    return redirect(url_for('budget_sections', budget_id=budget_id))


@app.route('/edit_section/<int:section_id>', methods=['POST'])
def edit_section(section_id):
    section = BudgetSection.query.get_or_404(section_id)
    section.code = request.form.get('code')
    section.name = request.form.get('name')
    section.description = request.form.get('description')
    section.sort_order = int(request.form.get('sort_order', 0))
    db.session.commit()

    flash('Раздел обновлен', 'success')
    return redirect(url_for('budget_sections', budget_id=section.budget_id))


@app.route('/delete_section/<int:section_id>')
def delete_section(section_id):
    section = BudgetSection.query.get_or_404(section_id)
    budget_id = section.budget_id
    db.session.delete(section)
    db.session.commit()

    flash('Раздел удален', 'success')
    return redirect(url_for('budget_sections', budget_id=budget_id))


# ========== Управление статьями сметы ==========

@app.route('/section/<int:section_id>/articles')
def section_articles(section_id):
    section = BudgetSection.query.get_or_404(section_id)
    articles = BudgetArticle.query.filter_by(section_id=section_id).order_by(BudgetArticle.sort_order).all()
    return render_template('budget_articles.html', section=section, articles=articles)


@app.route('/add_article', methods=['POST'])
def add_article():
    section_id = request.form.get('section_id')
    code = request.form.get('code')
    name = request.form.get('name')
    description = request.form.get('description')
    planned_amount = request.form.get('planned_amount', 0)
    sort_order = request.form.get('sort_order', 0)

    article = BudgetArticle(
        section_id=int(section_id),
        code=code,
        name=name,
        description=description,
        planned_amount=float(planned_amount) if planned_amount else 0,
        sort_order=int(sort_order)
    )
    db.session.add(article)
    db.session.commit()

    flash('Статья добавлена', 'success')
    return redirect(url_for('section_articles', section_id=section_id))


@app.route('/edit_article/<int:article_id>', methods=['POST'])
def edit_article(article_id):
    article = BudgetArticle.query.get_or_404(article_id)
    article.code = request.form.get('code')
    article.name = request.form.get('name')
    article.description = request.form.get('description')
    article.planned_amount = float(request.form.get('planned_amount', 0))
    article.sort_order = int(request.form.get('sort_order', 0))
    db.session.commit()

    flash('Статья обновлена', 'success')
    return redirect(url_for('section_articles', section_id=article.section_id))


@app.route('/delete_article/<int:article_id>')
def delete_article(article_id):
    article = BudgetArticle.query.get_or_404(article_id)
    section_id = article.section_id
    db.session.delete(article)
    db.session.commit()

    flash('Статья удалена', 'success')
    return redirect(url_for('section_articles', section_id=section_id))


# ========== Редактирование операций (новая страница) ==========

@app.route('/operations')
def operations_list():
    budgets = Budget.query.filter_by(is_active=True).all()
    # Получаем уникальных контрагентов для фильтра
    counterparties = db.session.query(Operation.counterparty).filter(Operation.counterparty != '').distinct().all()
    counterparties = [c[0] for c in counterparties if c[0]]

    return render_template('operations.html', budgets=budgets, counterparties=counterparties)


@app.route('/api/operations')
def api_operations():
    """API для получения операций с фильтрацией"""
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    counterparty = request.args.get('counterparty')
    transaction_type = request.args.get('transaction_type')  # 'income' или 'expense'
    purpose_search = request.args.get('purpose_search')
    budget_id = request.args.get('budget_id')
    operation_type = request.args.get('operation_type')
    has_documents = request.args.get('has_documents')  # 'yes', 'no', или None

    query = Operation.query

    # Фильтр по дате
    if start_date:
        query = query.filter(Operation.transaction_date >= datetime.strptime(start_date, '%Y-%m-%d'))
    if end_date:
        query = query.filter(Operation.transaction_date <= datetime.strptime(end_date, '%Y-%m-%d') + timedelta(days=1))

    # Фильтр по контрагенту
    if counterparty and counterparty != '':
        query = query.filter(Operation.counterparty == counterparty)

    # Фильтр по типу (доход/расход)
    if transaction_type and transaction_type != '':
        if transaction_type == 'income':
            query = query.filter(Operation.credit_amount > 0)
        elif transaction_type == 'expense':
            query = query.filter(Operation.debit_amount > 0)

    # Фильтр по назначению платежа
    if purpose_search and purpose_search != '':
        query = query.filter(Operation.purpose.ilike(f'%{purpose_search}%'))

    # Фильтр по смете (включая вариант "без сметы")
    if budget_id and budget_id != '':
        if budget_id == 'null':
            query = query.filter(Operation.budget_id.is_(None))
        else:
            query = query.filter(Operation.budget_id == int(budget_id))

    # Фильтр по типу операции (включая вариант "не задан")
    if operation_type and operation_type != '':
        if operation_type == 'null':
            query = query.filter(Operation.operation_type.is_(None))
        else:
            query = query.filter(Operation.operation_type == operation_type)

    # Фильтр по наличию документов
    if has_documents and has_documents != '':
        if has_documents == 'yes':
            # Операции, у которых есть хотя бы один прикрепленный документ
            query = query.filter(Operation.id.in_(
                db.session.query(OperationDocumentLink.operation_id).distinct()
            ))
        elif has_documents == 'no':
            # Операции, у которых нет прикрепленных документов
            query = query.filter(~Operation.id.in_(
                db.session.query(OperationDocumentLink.operation_id).distinct()
            ))

    operations = query.order_by(Operation.transaction_date.desc()).all()

    return jsonify([op.to_dict() for op in operations])


@app.route('/api/operations/<int:operation_id>', methods=['PUT'])
def update_operation_api(operation_id):
    """API для обновления операции"""
    operation = Operation.query.get_or_404(operation_id)
    data = request.get_json()

    if 'operation_type' in data:
        operation.operation_type = data['operation_type'] if data['operation_type'] else None
    if 'budget_id' in data:
        operation.budget_id = data['budget_id'] if data['budget_id'] else None
    if 'section_id' in data:
        operation.section_id = data['section_id'] if data['section_id'] else None
    if 'article_id' in data:
        operation.article_id = data['article_id'] if data['article_id'] else None

    db.session.commit()
    return jsonify({'success': True, 'operation': operation.to_dict()})


@app.route('/api/operations/<int:operation_id>/splits', methods=['GET'])
def get_splits(operation_id):
    """Получить все разделения для операции"""
    splits = SplitOperation.query.filter_by(parent_operation_id=operation_id).all()
    return jsonify([s.to_dict() for s in splits])


@app.route('/api/operations/<int:operation_id>/splits', methods=['POST'])
def add_split(operation_id):
    """Добавить разделение для операции"""
    operation = Operation.query.get_or_404(operation_id)
    data = request.get_json()

    amount = float(data.get('amount', 0))
    description = data.get('description', '')

    # Проверяем сумму
    existing_splits = SplitOperation.query.filter_by(parent_operation_id=operation_id).all()
    current_total = sum(s.amount for s in existing_splits)
    original_amount = operation.debit_amount if operation.debit_amount > 0 else operation.credit_amount

    if current_total + amount > original_amount + 0.01:  # Добавляем небольшую погрешность
        return jsonify({
                           'error': f'Сумма разделений ({current_total + amount:.2f}) превышает исходную сумму ({original_amount:.2f})'}), 400

    split = SplitOperation(
        parent_operation_id=operation_id,
        amount=amount,
        description=description
    )
    db.session.add(split)

    # Если это первое разделение, отмечаем операцию как разделенную
    if not operation.is_split and len(existing_splits) == 0:
        operation.is_split = True

    db.session.commit()

    return jsonify({'success': True, 'split': split.to_dict(), 'remaining': original_amount - (current_total + amount)})


@app.route('/api/splits/<int:split_id>', methods=['PUT'])
def update_split(split_id):
    """Обновить разделение"""
    split = SplitOperation.query.get_or_404(split_id)
    data = request.get_json()

    operation = split.parent_operation
    original_amount = operation.debit_amount if operation.debit_amount > 0 else operation.credit_amount

    if 'amount' in data:
        new_amount = float(data['amount'])
        other_splits = SplitOperation.query.filter(
            SplitOperation.parent_operation_id == split.parent_operation_id,
            SplitOperation.id != split_id
        ).all()
        other_total = sum(s.amount for s in other_splits)

        if other_total + new_amount > original_amount + 0.01:
            return jsonify({
                               'error': f'Сумма разделений ({other_total + new_amount:.2f}) превышает исходную сумму ({original_amount:.2f})'}), 400
        split.amount = new_amount

    if 'description' in data:
        split.description = data['description']

    if 'budget_id' in data:
        split.budget_id = data['budget_id'] if data['budget_id'] else None
    if 'section_id' in data:
        split.section_id = data['section_id'] if data['section_id'] else None
    if 'article_id' in data:
        split.article_id = data['article_id'] if data['article_id'] else None

    db.session.commit()

    remaining = original_amount - (
        sum(s.amount for s in SplitOperation.query.filter_by(parent_operation_id=split.parent_operation_id).all()))
    return jsonify({'success': True, 'split': split.to_dict(), 'remaining': remaining})


@app.route('/api/splits/<int:split_id>', methods=['DELETE'])
def delete_split(split_id):
    """Удалить разделение"""
    split = SplitOperation.query.get_or_404(split_id)
    operation_id = split.parent_operation_id

    db.session.delete(split)

    # Проверяем, остались ли еще разделения
    remaining_splits = SplitOperation.query.filter_by(parent_operation_id=operation_id).count()
    if remaining_splits == 0:
        operation = Operation.query.get(operation_id)
        if operation:
            operation.is_split = False

    db.session.commit()

    operation = Operation.query.get(operation_id)
    original_amount = operation.debit_amount if operation.debit_amount > 0 else operation.credit_amount
    remaining = original_amount - sum(
        s.amount for s in SplitOperation.query.filter_by(parent_operation_id=operation_id).all())

    return jsonify({'success': True, 'remaining': remaining})


@app.route('/api/operations/<int:operation_id>/splits/auto_distribute', methods=['POST'])
def auto_distribute_splits(operation_id):
    """Автоматическое распределение суммы по выбранным статьям"""
    operation = Operation.query.get_or_404(operation_id)
    data = request.get_json()

    articles = data.get('articles', [])  # список {article_id, percent}
    original_amount = operation.debit_amount if operation.debit_amount > 0 else operation.credit_amount

    # Удаляем существующие разделения
    SplitOperation.query.filter_by(parent_operation_id=operation_id).delete()

    # Создаем новые
    total_percent = sum(a['percent'] for a in articles)
    if abs(total_percent - 100) > 0.01:
        return jsonify({'error': f'Сумма процентов ({total_percent}%) не равна 100%'}), 400

    for article_data in articles:
        amount = original_amount * article_data['percent'] / 100
        if amount > 0:
            split = SplitOperation(
                parent_operation_id=operation_id,
                amount=round(amount, 2),
                description=f"Автоматическое распределение ({article_data['percent']}%)",
                article_id=article_data['article_id']
            )
            # Получаем section_id и budget_id из статьи
            article = BudgetArticle.query.get(article_data['article_id'])
            if article:
                split.section_id = article.section_id
                split.budget_id = article.section.budget_id
            db.session.add(split)

    operation.is_split = True
    db.session.commit()

    return jsonify({'success': True})

@app.route('/api/budgets')
def api_budgets():
    budgets = Budget.query.filter_by(is_active=True).all()
    return jsonify([b.to_dict() for b in budgets])

@app.route('/api/budgets/<int:budget_id>/sections')
def api_budget_sections(budget_id):
    sections = BudgetSection.query.filter_by(budget_id=budget_id).order_by(BudgetSection.sort_order).all()
    return jsonify([s.to_dict() for s in sections])


@app.route('/api/sections/<int:section_id>/articles')
def api_section_articles(section_id):
    articles = BudgetArticle.query.filter_by(section_id=section_id).order_by(BudgetArticle.sort_order).all()
    return jsonify([a.to_dict() for a in articles])


@app.route('/api/counterparties')
def api_counterparties():
    counterparties = db.session.query(Operation.counterparty).filter(Operation.counterparty != '').distinct().order_by(
        Operation.counterparty).all()
    return jsonify([c[0] for c in counterparties if c[0]])


@app.route('/api/operations/<int:operation_id>/documents', methods=['POST'])
def upload_operation_document(operation_id):
    """Загрузить документ для операции (старый способ)"""
    operation = Operation.query.get_or_404(operation_id)

    if 'document' not in request.files:
        return jsonify({'error': 'Файл не выбран'}), 400

    file = request.files['document']
    if file.filename == '':
        return jsonify({'error': 'Файл не выбран'}), 400

    if not file.filename.lower().endswith('.pdf'):
        return jsonify({'error': 'Поддерживаются только PDF файлы'}), 400

    original_filename = file.filename
    safe_filename = generate_safe_filename(original_filename)
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], safe_filename)
    file.save(filepath)

    # Определяем номер приложения
    max_num = db.session.query(db.func.max(Document.attachment_number)).filter_by(
        operation_id=operation_id).scalar() or 0

    document = Document(
        operation_id=operation_id,
        filename=safe_filename,
        original_filename=original_filename,
        file_path=filepath,
        attachment_number=max_num + 1
    )
    db.session.add(document)
    db.session.commit()

    return jsonify({'success': True, 'document_id': document.id})

@app.route('/api/documents/<int:document_id>/view')
def view_document(document_id):
    """Просмотр документа"""
    document = Document.query.get_or_404(document_id)
    actual_file_path = doc.file_path.replace('/root/finance/uploads/',
                                             'C:\\Users\\lahturov.IS_HQ\\PycharmProjects\\TSNFinance\\uploads\\')
    return send_file(actual_file_path, as_attachment=False)


@app.route('/api/documents/<int:document_id>', methods=['DELETE'])
def delete_document_api(document_id):
    """Удалить документ"""
    document = Document.query.get_or_404(document_id)

    if os.path.exists(document.file_path):
        os.remove(document.file_path)

    db.session.delete(document)
    db.session.commit()

    return jsonify({'success': True})


@app.route('/documents_library')
def documents_library():
    """Страница библиотеки документов"""
    return render_template('documents_library.html')




@app.route('/api/documents_library/<int:document_id>', methods=['PUT'])
def api_update_document(document_id):
    """Обновить информацию о документе"""
    document = DocumentLibrary.query.get_or_404(document_id)
    data = request.get_json()

    if 'name' in data:
        document.name = data['name']
    if 'description' in data:
        document.description = data['description']
    if 'tags' in data:
        document.tags = data['tags']

    db.session.commit()
    return jsonify({'success': True})


@app.route('/api/documents_library/<int:document_id>', methods=['DELETE'])
def api_delete_document(document_id):
    """Удалить документ из библиотеки"""
    document = DocumentLibrary.query.get_or_404(document_id)

    # Проверяем, прикреплен ли документ к операциям
    if document.usage_count > 0:
        return jsonify(
            {'error': f'Документ прикреплен к {document.usage_count} операциям. Сначала открепите его.'}), 400

    if os.path.exists(document.file_path):
        os.remove(document.file_path)

    db.session.delete(document)
    db.session.commit()

    return jsonify({'success': True})


@app.route('/api/documents_library/<int:document_id>/view')
def api_view_document(document_id):
    """Просмотр документа из библиотеки"""
    document = DocumentLibrary.query.get_or_404(document_id)
    actual_file_path = document.file_path.replace('/root/finance/uploads/',
                                             'C:\\Users\\lahturov.IS_HQ\\PycharmProjects\\TSNFinance\\uploads\\')
    return send_file(actual_file_path, as_attachment=False)


# ========== Прикрепление документов к операциям ==========

@app.route('/api/operations/<int:operation_id>/library_documents', methods=['GET'])
def api_get_operation_library_documents(operation_id):
    """Получить документы из библиотеки, прикрепленные к операции"""
    links = OperationDocumentLink.query.filter_by(operation_id=operation_id).all()
    return jsonify([{
        'id': link.document.id,
        'name': link.document.name,
        'original_filename': link.document.original_filename,
        'attached_at': link.attached_at.strftime('%d.%m.%Y %H:%M') if link.attached_at else None,
        'note': link.note
    } for link in links])


@app.route('/api/operations/<int:operation_id>/library_documents', methods=['POST'])
def api_attach_document_to_operation(operation_id):
    """Прикрепить существующий документ к операции"""
    data = request.get_json()
    document_id = data.get('document_id')
    note = data.get('note', '')

    if not document_id:
        return jsonify({'error': 'Не указан ID документа'}), 400

    # Проверяем, не прикреплен ли уже
    existing = OperationDocumentLink.query.filter_by(
        operation_id=operation_id,
        document_id=document_id
    ).first()

    if existing:
        return jsonify({'error': 'Документ уже прикреплен к этой операции'}), 400

    link = OperationDocumentLink(
        operation_id=operation_id,
        document_id=document_id,
        note=note
    )
    db.session.add(link)

    # Увеличиваем счетчик использования
    document = DocumentLibrary.query.get(document_id)
    if document:
        document.usage_count += 1

    db.session.commit()

    return jsonify({'success': True})


@app.route('/api/operations/<int:operation_id>/library_documents/<int:document_id>', methods=['DELETE'])
def api_detach_document_from_operation(operation_id, document_id):
    """Открепить документ от операции"""
    link = OperationDocumentLink.query.filter_by(
        operation_id=operation_id,
        document_id=document_id
    ).first_or_404()

    # Уменьшаем счетчик использования
    document = DocumentLibrary.query.get(document_id)
    if document and document.usage_count > 0:
        document.usage_count -= 1

    db.session.delete(link)
    db.session.commit()

    return jsonify({'success': True})


@app.route('/api/operations/<int:operation_id>/documents/available', methods=['GET'])
def api_get_available_documents(operation_id):
    """Получить документы для прикрепления к операции"""
    try:
        # 1. Получаем ID уже прикрепленных документов к этой операции
        attached_ids = db.session.query(OperationDocumentLink.document_id).filter_by(
            operation_id=operation_id
        ).all()
        attached_ids = [a[0] for a in attached_ids]

        # 2. Получаем общие документы из библиотеки (is_shared = True), которые еще не прикреплены к этой операции
        query = DocumentLibrary.query.filter(
            DocumentLibrary.is_shared == True  # Только общие документы
        )

        if attached_ids:
            query = query.filter(DocumentLibrary.id.notin_(attached_ids))

        documents = query.order_by(DocumentLibrary.name).all()

        return jsonify([{
            'id': d.id,
            'name': d.name,
            'original_filename': d.original_filename,
            'description': d.description,
            'tags': d.tags,
            'usage_count': d.usage_count,
            'is_shared': d.is_shared
        } for d in documents])
    except Exception as e:
        print(f"Error in api_get_available_documents: {e}")
        return jsonify([])


@app.route('/api/operations/<int:operation_id>/documents/personal', methods=['GET'])
def api_get_personal_documents(operation_id):
    """Получить личные документы операции (загруженные напрямую)"""
    try:
        # Получаем документы, которые прикреплены только к этой операции и не являются общими
        personal_docs = db.session.query(DocumentLibrary).join(
            OperationDocumentLink,
            OperationDocumentLink.document_id == DocumentLibrary.id
        ).filter(
            OperationDocumentLink.operation_id == operation_id,
            DocumentLibrary.is_shared == False  # Только личные документы
        ).all()

        return jsonify([{
            'id': d.id,
            'name': d.name,
            'original_filename': d.original_filename,
            'description': d.description,
            'attached_at': next((link.attached_at.strftime('%d.%m.%Y %H:%M') for link in d.operation_links if
                                 link.operation_id == operation_id), None)
        } for d in personal_docs])
    except Exception as e:
        print(f"Error in api_get_personal_documents: {e}")
        return jsonify([])


@app.route('/api/operations/<int:operation_id>/documents/direct', methods=['POST'])
def upload_direct_document(operation_id):
    """Загрузить документ напрямую для операции (личный документ)"""
    operation = Operation.query.get_or_404(operation_id)

    if 'document' not in request.files:
        return jsonify({'error': 'Файл не выбран'}), 400

    file = request.files['document']
    if file.filename == '':
        return jsonify({'error': 'Файл не выбран'}), 400

    if not file.filename.lower().endswith('.pdf'):
        return jsonify({'error': 'Поддерживаются только PDF файлы'}), 400

    # Сохраняем оригинальное имя
    original_filename = file.filename

    # Генерируем безопасное имя для сохранения на диске
    safe_filename = generate_safe_filename(original_filename)
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], safe_filename)
    file.save(filepath)

    file_size = os.path.getsize(filepath)

    # Создаем ЛИЧНЫЙ документ (is_shared = False)
    document = DocumentLibrary(
        name=original_filename.replace('.pdf', '').replace('.PDF', ''),
        filename=safe_filename,
        original_filename=original_filename,
        file_path=filepath,
        file_size=file_size,
        description=f"Документ операции #{operation_id}",
        tags="",
        is_shared=False,  # Личный документ
        usage_count=1
    )
    db.session.add(document)
    db.session.flush()  # Получаем ID документа

    # Создаем связь с операцией
    link = OperationDocumentLink(
        operation_id=operation_id,
        document_id=document.id,
        note=""
    )
    db.session.add(link)

    db.session.commit()

    return jsonify({'success': True, 'document_id': document.id})

@app.route('/api/documents_library', methods=['GET'])
def api_get_documents_library():
    """Получить все документы из библиотеки"""
    try:
        documents = DocumentLibrary.query.order_by(DocumentLibrary.uploaded_at.desc()).all()
        return jsonify([{
            'id': d.id,
            'name': d.name,
            'original_filename': d.original_filename,
            'file_size': d.file_size,
            'description': d.description,
            'tags': d.tags,
            'uploaded_at': d.uploaded_at.strftime('%d.%m.%Y %H:%M') if d.uploaded_at else None,
            'usage_count': d.usage_count
        } for d in documents])
    except Exception as e:
        print(f"Error in api_get_documents_library: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/documents_library', methods=['POST'])
def api_upload_document():
    """Загрузить документ в библиотеку (общий документ)"""
    if 'document' not in request.files:
        return jsonify({'error': 'Файл не выбран'}), 400

    file = request.files['document']
    if file.filename == '':
        return jsonify({'error': 'Файл не выбран'}), 400

    if not file.filename.lower().endswith('.pdf'):
        return jsonify({'error': 'Поддерживаются только PDF файлы'}), 400

    name = request.form.get('name', '')
    description = request.form.get('description', '')
    tags = request.form.get('tags', '')

    if not name:
        name = file.filename.replace('.pdf', '').replace('.PDF', '')

    original_filename = file.filename
    safe_filename = generate_safe_filename(original_filename)
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], safe_filename)
    file.save(filepath)

    file_size = os.path.getsize(filepath)

    # Создаем ОБЩИЙ документ (is_shared = True)
    document = DocumentLibrary(
        name=name,
        filename=safe_filename,
        original_filename=original_filename,
        file_path=filepath,
        file_size=file_size,
        description=description,
        tags=tags,
        is_shared=True,  # Общий документ
        usage_count=0
    )
    db.session.add(document)
    db.session.commit()

    return jsonify({'success': True, 'document_id': document.id})

# Регистрируем шрифт с поддержкой кириллицы
def register_russian_font():
    """Регистрация шрифта с поддержкой кириллицы"""
    font_path = os.path.join(os.path.dirname(__file__), 'fonts', 'DejaVuSans.ttf')
    if os.path.exists(font_path):
        pdfmetrics.registerFont(TTFont('DejaVuSans', font_path))
        pdfmetrics.registerFont(TTFont('DejaVuSans-Bold', font_path))
        return True
    else:
        # Если шрифт не найден, используем стандартный (латиница только)
        print(f"Warning: Font file not found at {font_path}")
        return False

# Вызываем регистрацию при старте
HAS_RUSSIAN_FONT = register_russian_font()

def get_russian_style(base_style, font_name='DejaVuSans', size=10):
    """Создание стиля с поддержкой кириллицы"""
    if HAS_RUSSIAN_FONT:
        return ParagraphStyle(
            base_style,
            fontName=font_name,
            fontSize=size,
            encoding='utf-8'
        )
    return base_style

def generate_report_async(task_id, params):
    """Асинхронная генерация отчета (с контекстом приложения)"""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    import tempfile
    import os
    import io
    from PyPDF2 import PdfReader, PdfWriter
    import fitz
    import shutil

    # Создаем контекст приложения для работы с БД
    with app.app_context():
        try:
            task_status[task_id] = {'status': 'processing', 'progress': 0, 'message': 'Начало генерации отчета...'}

            # Извлекаем параметры
            start_date = params.get('start_date')
            end_date = params.get('end_date')
            counterparty = params.get('counterparty')
            transaction_type = params.get('transaction_type')
            purpose_search = params.get('purpose_search')
            budget_id = params.get('budget_id')
            operation_type = params.get('operation_type')
            has_documents_filter = params.get('has_documents')

            task_status[task_id]['progress'] = 5
            task_status[task_id]['message'] = 'Загрузка операций из базы данных...'

            # Создаем запрос к базе данных
            query = Operation.query

            if start_date:
                query = query.filter(Operation.transaction_date >= datetime.strptime(start_date, '%Y-%m-%d'))
            if end_date:
                query = query.filter(
                    Operation.transaction_date <= datetime.strptime(end_date, '%Y-%m-%d') + timedelta(days=1))
            if counterparty and counterparty != '':
                query = query.filter(Operation.counterparty == counterparty)
            if transaction_type and transaction_type != '':
                if transaction_type == 'income':
                    query = query.filter(Operation.credit_amount > 0)
                elif transaction_type == 'expense':
                    query = query.filter(Operation.debit_amount > 0)
            if purpose_search and purpose_search != '':
                query = query.filter(Operation.purpose.ilike(f'%{purpose_search}%'))
            if budget_id and budget_id != '':
                if budget_id == 'null':
                    query = query.filter(Operation.budget_id.is_(None))
                else:
                    query = query.filter(Operation.budget_id == int(budget_id))
            if operation_type and operation_type != '':
                if operation_type == 'null':
                    query = query.filter(Operation.operation_type.is_(None))
                else:
                    query = query.filter(Operation.operation_type == operation_type)
            if has_documents_filter and has_documents_filter != '':
                if has_documents_filter == 'yes':
                    query = query.filter(Operation.id.in_(
                        db.session.query(OperationDocumentLink.operation_id).distinct()
                    ))
                elif has_documents_filter == 'no':
                    query = query.filter(~Operation.id.in_(
                        db.session.query(OperationDocumentLink.operation_id).distinct()
                    ))

            operations = query.order_by(Operation.transaction_date).all()

            if not operations:
                task_status[task_id] = {'status': 'failed', 'progress': 0, 'message': 'Нет операций для отчета',
                                        'error': 'Нет операций'}
                return

            task_status[task_id]['progress'] = 15
            task_status[task_id]['message'] = 'Обработка операций...'

            # Создаем временный файл для основного отчета
            temp_dir = tempfile.mkdtemp()

            # Собираем все уникальные документы (один документ - один раз)
            unique_docs = {}
            operation_apps = {}

            for op in operations:
                operation_apps[op.id] = []
                if hasattr(op, 'library_documents'):
                    for link in op.library_documents:
                        doc = link.document
                        actual_file_path = doc.file_path.replace('/root/finance/uploads/',
                                                                 'C:\\Users\\lahturov.IS_HQ\\PycharmProjects\\TSNFinance\\uploads\\')
                        if os.path.exists(actual_file_path):
                            if doc.id not in unique_docs:
                                unique_docs[doc.id] = {
                                    'number': len(unique_docs) + 1,
                                    'path': actual_file_path,
                                    'name': doc.name,
                                    'operation_id': op.id,
                                    'original_filename': doc.original_filename
                                }
                            doc_number = unique_docs[doc.id]['number']
                            if doc_number not in operation_apps[op.id]:
                                operation_apps[op.id].append(doc_number)

            all_docs = list(unique_docs.values())

            # Загружаем разделения
            splits_data = {}
            for op in operations:
                splits = SplitOperation.query.filter_by(parent_operation_id=op.id).all()
                if splits:
                    splits_data[op.id] = splits

            task_status[task_id]['progress'] = 30
            task_status[task_id]['message'] = 'Формирование PDF...'

            # Регистрируем шрифт для кириллицы
            font_path = os.path.join(os.path.dirname(app.instance_path), 'fonts', 'DejaVuSans.ttf')
            if not os.path.exists(font_path):
                font_path = os.path.join(os.getcwd(), 'fonts', 'DejaVuSans.ttf')

            if os.path.exists(font_path):
                pdfmetrics.registerFont(TTFont('DejaVuSans', font_path))
                pdfmetrics.registerFont(TTFont('DejaVuSans-Bold', font_path))
                has_cyrillic = True
            else:
                alt_font_path = 'C:/Windows/Fonts/arial.ttf'
                if os.path.exists(alt_font_path):
                    pdfmetrics.registerFont(TTFont('Arial', alt_font_path))
                    pdfmetrics.registerFont(TTFont('Arial-Bold', alt_font_path))
                    has_cyrillic = True
                else:
                    has_cyrillic = False

            # Создаем основной PDF
            report_path = os.path.join(temp_dir, 'report.pdf')

            doc = SimpleDocTemplate(report_path, pagesize=landscape(A4),
                                    topMargin=8 * mm, bottomMargin=8 * mm,
                                    leftMargin=8 * mm, rightMargin=8 * mm)

            page_width, page_height = landscape(A4)
            available_width = page_width - (8 * mm * 2)
            apps_page_width, apps_page_height = A4
            apps_available_width = apps_page_width - (8 * mm * 2)

            styles = getSampleStyleSheet()

            if has_cyrillic:
                font_name = 'DejaVuSans' if os.path.exists(font_path) else 'Arial'
                font_bold = 'DejaVuSans-Bold' if os.path.exists(font_path) else 'Arial-Bold'

                table_style = ParagraphStyle('TableStyle', parent=styles['Normal'], fontName=font_name, fontSize=7,
                                             encoding='utf-8', leading=9)
                header_style = ParagraphStyle('HeaderStyle', parent=styles['Normal'], fontName=font_bold, fontSize=8,
                                              textColor=colors.whitesmoke, alignment=1, encoding='utf-8')
                normal_style = ParagraphStyle('Normal', parent=styles['Normal'], fontName=font_name, fontSize=9,
                                              encoding='utf-8')
                title_style = ParagraphStyle('CustomTitle', parent=styles['Heading1'], fontName=font_bold, fontSize=14,
                                             alignment=1, spaceAfter=20, encoding='utf-8')
                split_style = ParagraphStyle('SplitStyle', parent=styles['Normal'], fontName=font_name, fontSize=7,
                                             textColor=colors.black, encoding='utf-8', leading=8)
            else:
                table_style = styles['Normal']
                header_style = styles['Normal']
                normal_style = styles['Normal']
                title_style = styles['Heading1']
                split_style = styles['Normal']

            story = []

            # Заголовок
            if start_date and end_date:
                start_date_text = datetime.strftime(datetime.strptime(start_date, "%Y-%m-%d"), "%d.%m.%Y")
                end_date_text = datetime.strftime(datetime.strptime(end_date, "%Y-%m-%d"), "%d.%m.%Y")
                dates_text = f" с {start_date_text} по {end_date_text}"
            else:
                dates_text = ""

            story.append(Paragraph(f"Отчет по расходам ТСН Сантория{dates_text}", title_style))

            total_debit = sum((op.debit_amount or 0) for op in operations)
            story.append(Paragraph(f"<b>Итого расходов:</b> {total_debit:,.2f} ₽", normal_style))
            story.append(Spacer(1, 15))

            # Таблица с операциями
            headers = ['№', 'Дата', 'Сумма', 'Контрагент', 'Назначение', 'Смета', 'Раздел', 'Статья', 'Документ']
            table_data = [[Paragraph(h, header_style) for h in headers]]

            row_counter = 1
            for op in operations:
                amount = op.debit_amount if (op.debit_amount or 0) > 0 else (op.credit_amount or 0)
                has_splits = op.id in splits_data

                apps = operation_apps.get(op.id, [])
                app_text = ', '.join([f'Приложение {app_num}' for app_num in sorted(apps)]) if apps else '-'

                counterparty_text = (op.counterparty or '-')[:80]
                purpose_text = (op.purpose or '-')[:200]
                if len(op.purpose or '') > 200:
                    purpose_text += '...'

                if has_splits:
                    row = [
                        Paragraph(str(row_counter), table_style),
                        Paragraph(op.transaction_date.strftime('%d.%m.%Y') if op.transaction_date else '-',
                                  table_style),
                        Paragraph(f"{amount:,.2f}", table_style),
                        Paragraph(counterparty_text, table_style),
                        Paragraph(purpose_text, table_style),
                        Paragraph("(разделено)", table_style),
                        Paragraph("", table_style),
                        Paragraph("", table_style),
                        Paragraph(app_text, table_style)
                    ]
                else:
                    row = [
                        Paragraph(str(row_counter), table_style),
                        Paragraph(op.transaction_date.strftime('%d.%m.%Y') if op.transaction_date else '-',
                                  table_style),
                        Paragraph(f"{amount:,.2f}", table_style),
                        Paragraph(counterparty_text, table_style),
                        Paragraph(purpose_text, table_style),
                        Paragraph(op.budget.name if op.budget else '-', table_style),
                        Paragraph(op.section.name if op.section else '-', table_style),
                        Paragraph(op.article_ref.name if op.article_ref else '-', table_style),
                        Paragraph(app_text, table_style)
                    ]
                table_data.append(row)
                row_counter += 1

                if has_splits:
                    for split in splits_data[op.id]:
                        split_amount = split.amount or 0
                        split_desc = split.description or '-'
                        split_budget = split.budget.name if split.budget else '-'
                        split_section = split.section.name if split.section else '-'
                        split_article = split.article.name if split.article else '-'

                        split_row = [
                            Paragraph("", table_style),
                            Paragraph("", table_style),
                            Paragraph(f"{split_amount:,.2f}", split_style),
                            Paragraph("", table_style),
                            Paragraph(f"↳ {split_desc}", split_style),
                            Paragraph(split_budget, split_style),
                            Paragraph(split_section, split_style),
                            Paragraph(split_article, split_style),
                            Paragraph("", table_style)
                        ]
                        table_data.append(split_row)

            table = Table(table_data, repeatRows=1)
            table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('ALIGN', (3, 1), (3, -1), 'LEFT'),
                ('ALIGN', (4, 1), (4, -1), 'LEFT'),
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('FONTSIZE', (0, 0), (-1, 0), 8),
                ('FONTSIZE', (0, 1), (-1, -1), 7),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 6),
                ('TOPPADDING', (0, 1), (-1, -1), 3),
                ('BOTTOMPADDING', (0, 1), (-1, -1), 3),
                ('GRID', (0, 0), (-1, -1), 0.3, colors.black),
                ('BACKGROUND', (0, 1), (-1, -1), colors.white),
            ]))

            col_ratios = [0.4, 0.8, 0.8, 1.5, 3, 0.6, 1.6, 1.2, 1.2]
            total_ratio = sum(col_ratios)
            col_widths = [(ratio / total_ratio) * available_width for ratio in col_ratios]
            table._argW = col_widths
            story.append(table)
            story.append(PageBreak())

            # Список приложений
            apps_report_path = None
            if all_docs:
                task_status[task_id]['progress'] = 60
                task_status[task_id]['message'] = 'Формирование списка приложений...'

                apps_report_path = os.path.join(temp_dir, 'apps_report.pdf')
                apps_doc = SimpleDocTemplate(apps_report_path, pagesize=A4,
                                             topMargin=8 * mm, bottomMargin=8 * mm,
                                             leftMargin=8 * mm, rightMargin=8 * mm)

                apps_story = []
                apps_story.append(Paragraph("Список приложений", title_style))
                apps_story.append(Spacer(1, 10))

                apps_headers = ['№ приложения', 'Наименование']
                apps_table_data = [[Paragraph(h, header_style) for h in apps_headers]]
                for doc_info in sorted(all_docs, key=lambda x: x['number']):
                    apps_table_data.append([
                        Paragraph(str(doc_info['number']), table_style),
                        Paragraph(doc_info['name'], table_style)
                    ])

                apps_table = Table(apps_table_data, repeatRows=1)
                apps_table.setStyle(TableStyle([
                    ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
                    ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                    ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                    ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                    ('FONTSIZE', (0, 0), (-1, 0), 8),
                    ('FONTSIZE', (0, 1), (-1, -1), 7),
                    ('TOPPADDING', (0, 1), (-1, -1), 3),
                    ('BOTTOMPADDING', (0, 1), (-1, -1), 3),
                    ('GRID', (0, 0), (-1, -1), 0.3, colors.black),
                    ('BACKGROUND', (0, 1), (-1, -1), colors.white),
                ]))

                apps_col_widths = [apps_available_width * 0.15, apps_available_width * 0.85]
                apps_table._argW = apps_col_widths
                apps_story.append(apps_table)
                apps_doc.build(apps_story)

            # Строим основной PDF
            doc.build(story)

            task_status[task_id]['progress'] = 30
            task_status[task_id]['message'] = 'Объединение PDF файлов...'

            temp_pdfs = []

            # Сохраняем основной отчет во временный файл
            temp_main = os.path.join(temp_dir, 'temp_main.pdf')
            with open(report_path, 'rb') as f:
                with open(temp_main, 'wb') as out:
                    out.write(f.read())
            temp_pdfs.append(temp_main)

            docs_count = len(all_docs)
            docs_added = 0

            # Для каждого документа создаем новый PDF с колонтитулами
            for doc_info in sorted(all_docs, key=lambda x: x['number']):
                try:
                    # Открываем оригинальный PDF
                    doc = fitz.open(doc_info['path'])

                    # Создаем новый PDF для результата
                    temp_doc_path = os.path.join(temp_dir, f'temp_doc_{doc_info["number"]}.pdf')
                    new_doc = fitz.open()

                    for page_num, page in enumerate(doc, 1):
                        # Создаем новый лист такого же размера
                        new_page = new_doc.new_page(width=page.rect.width, height=page.rect.height)

                        # Вставляем содержимое оригинальной страницы
                        new_page.show_pdf_page(new_page.rect, doc, page_num - 1)

                        # Добавляем колонтитулы
                        font_name_pymupdf = "hebo"  # helv для латиницы, hebo для кириллицы

                        # Верхний колонтитул
                        new_page.insert_text(
                            (50, new_page.rect.height - 30),
                            f"Приложение {doc_info['number']}",
                            fontsize=8,
                            fontname=font_name,
                            fontfile=font_path
                        )
                        # Нижний колонтитул
                        new_page.insert_text(
                            (50, 20),
                            f"Приложение {doc_info['number']} - стр. {page_num}",
                            fontsize=8,
                            fontname=font_name,
                            fontfile=font_path
                        )

                    new_doc.save(temp_doc_path)
                    new_doc.close()
                    doc.close()
                    temp_pdfs.append(temp_doc_path)

                    docs_added += 1

                    task_status[task_id]['progress'] = int(30 + 30 * (docs_added / docs_count))
                    task_status[task_id]['message'] = 'Объединение PDF файлов...'

                except Exception as e:
                    print(f"Error processing document {doc_info['number']}: {e}")
                    import traceback
                    traceback.print_exc()

            task_status[task_id]['progress'] = 60
            task_status[task_id]['message'] = 'Объединение PDF файлов...'
            docs_added = 0

            # Объединяем все PDF
            final_path = os.path.join(temp_dir, 'final_report.pdf')
            final_doc = fitz.open()

            for pdf_path in temp_pdfs:
                try:
                    src_doc = fitz.open(pdf_path)
                    final_doc.insert_pdf(src_doc)
                    src_doc.close()
                    docs_added += 1

                    task_status[task_id]['progress'] = int(60 + 40 * (docs_added / docs_count))
                    task_status[task_id]['message'] = 'Объединение PDF файлов...'
                except Exception as e:
                    print(f"Error merging {pdf_path}: {e}")

            final_doc.save(final_path)
            final_doc.close()

            # Очищаем временные PDF файлы
            for pdf_path in temp_pdfs:
                try:
                    os.remove(pdf_path)
                except:
                    pass

            task_status[task_id] = {
                'status': 'completed',
                'progress': 100,
                'message': 'Готово',
                'file_path': final_path,
                'filename': f"отчет_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
            }

        except Exception as e:
            import traceback
            traceback.print_exc()
            task_status[task_id] = {
                'status': 'failed',
                'progress': 0,
                'message': str(e),
                'error': str(e)
            }

@app.route('/api/generate_report_async', methods=['POST'])
def generate_report_async_endpoint():
    """Запуск асинхронной генерации отчета"""
    # Получаем параметры из запроса
    params = request.get_json()

    # Генерируем уникальный ID задачи
    task_id = str(uuid.uuid4())

    # Запускаем генерацию в отдельном потоке
    thread = threading.Thread(target=generate_report_async, args=(task_id, params))
    thread.daemon = True
    thread.start()

    return jsonify({'task_id': task_id, 'status': 'started'})


@app.route('/api/report_status/<task_id>')
def get_report_status(task_id):
    """Получение статуса генерации отчета"""
    status = task_status.get(task_id, {'status': 'not_found'})

    # Если отчет готов, возвращаем URL для скачивания
    if status.get('status') == 'completed':
        # Сохраняем файл с постоянным именем
        filename = status.get('filename')
        file_path = status.get('file_path')

        # Отдаем временный URL для скачивания
        return jsonify({
            'status': 'completed',
            'progress': 100,
            'message': status.get('message'),
            'download_url': f'/api/download_report/{task_id}'
        })

    return jsonify(status)


@app.route('/api/download_report/<task_id>')
def download_report(task_id):
    """Скачивание готового отчета"""
    status = task_status.get(task_id)
    if not status or status.get('status') != 'completed':
        return jsonify({'error': 'Report not ready'}), 404

    file_path = status.get('file_path')
    filename = status.get('filename')
    print(file_path)

    if not os.path.exists(file_path):
        return jsonify({'error': 'File not found'}), 404
    print('returning file')
    return send_file(file_path, as_attachment=True, download_name=filename)


@app.route('/api/cleanup_report/<task_id>')
def cleanup_report(task_id):
    """Очистка временных файлов отчета"""
    status = task_status.get(task_id)
    if status and status.get('file_path'):
        try:
            # Удаляем временную папку с файлами
            temp_dir = os.path.dirname(status['file_path'])
            import shutil
            shutil.rmtree(temp_dir, ignore_errors=True)
        except Exception as e:
            print(f"Cleanup error: {e}")

    if task_id in task_status:
        del task_status[task_id]

    return jsonify({'success': True})

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)