from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()

class Budget(db.Model):
    """Смета (главный документ)"""
    __tablename__ = 'budgets'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    year = db.Column(db.Integer)
    description = db.Column(db.Text)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    sections = db.relationship('BudgetSection', backref='budget', lazy=True, cascade='all, delete-orphan')

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'year': self.year,
            'description': self.description,
            'is_active': self.is_active
        }



class BudgetSection(db.Model):
    """Раздел сметы"""
    __tablename__ = 'budget_sections'

    id = db.Column(db.Integer, primary_key=True)
    budget_id = db.Column(db.Integer, db.ForeignKey('budgets.id'), nullable=False)
    code = db.Column(db.String(50), nullable=False)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    sort_order = db.Column(db.Integer, default=0)

    articles = db.relationship('BudgetArticle', backref='section', lazy=True, cascade='all, delete-orphan')

    def to_dict(self):
        return {
            'id': self.id,
            'budget_id': self.budget_id,
            'code': self.code,
            'name': self.name,
            'description': self.description,
            'sort_order': self.sort_order
        }


class BudgetArticle(db.Model):
    """Статья сметы (внутри раздела)"""
    __tablename__ = 'budget_articles'

    id = db.Column(db.Integer, primary_key=True)
    section_id = db.Column(db.Integer, db.ForeignKey('budget_sections.id'), nullable=False)
    code = db.Column(db.String(50), nullable=False)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    planned_amount = db.Column(db.Float, default=0)
    sort_order = db.Column(db.Integer, default=0)

    def to_dict(self):
        return {
            'id': self.id,
            'section_id': self.section_id,
            'code': self.code,
            'name': self.name,
            'description': self.description,
            'planned_amount': self.planned_amount,
            'sort_order': self.sort_order
        }


class Operation(db.Model):
    """Операция из банковской выписки"""
    __tablename__ = 'operations'

    id = db.Column(db.Integer, primary_key=True)
    transaction_date = db.Column(db.DateTime, nullable=False)
    doc_number = db.Column(db.String(50), default='')
    debit_amount = db.Column(db.Float, default=0.0)
    credit_amount = db.Column(db.Float, default=0.0)
    purpose = db.Column(db.Text, default='')
    counterparty = db.Column(db.String(500), default='')
    bank_name = db.Column(db.String(200), default='')
    transaction_type = db.Column(db.String(10))  # 'debit' or 'credit'
    operation_type = db.Column(db.String(20), default=None)  # 'payment', 'expense', 'refund', 'deposit'

    # Новые поля для смет
    budget_id = db.Column(db.Integer, db.ForeignKey('budgets.id'), nullable=True)
    section_id = db.Column(db.Integer, db.ForeignKey('budget_sections.id'), nullable=True)
    article_id = db.Column(db.Integer, db.ForeignKey('budget_articles.id'), nullable=True)

    # Уникальный идентификатор для проверки дубликатов
    unique_hash = db.Column(db.String(100), unique=True, nullable=False)

    # Метаданные
    statement_file = db.Column(db.String(200))
    import_date = db.Column(db.DateTime, default=datetime.utcnow)
    is_split = db.Column(db.Boolean, default=False)
    split_note = db.Column(db.String(500), default='')

    documents = db.relationship('Document', backref='operation', lazy=True, cascade='all, delete-orphan')

    budget = db.relationship('Budget', backref='operations')
    section = db.relationship('BudgetSection', backref='operations')
    article_ref = db.relationship('BudgetArticle', backref='operations')

    library_documents = db.relationship('OperationDocumentLink', backref='operation', lazy=True, cascade='all, delete-orphan')

    def to_dict(self):
        amount = self.debit_amount if self.debit_amount > 0 else self.credit_amount
        operation_type_display = {
            'payment': '💰 Оплата начисления',
            'expense': '📤 Расход',
            'refund': '🔄 Возврат',
            'deposit': '💵 Депозит',
            'other_income': '💰 Прочий доход'
        }.get(self.operation_type, None)

        return {
            'id': self.id,
            'transaction_date': self.transaction_date.strftime('%Y-%m-%d %H:%M:%S') if self.transaction_date else None,
            'date_display': self.transaction_date.strftime('%d.%m.%Y') if self.transaction_date else '',
            'doc_number': self.doc_number,
            'debit_amount': self.debit_amount or 0,
            'credit_amount': self.credit_amount or 0,
            'amount': amount,
            'amount_display': f"{amount:,.2f}",
            'type': 'Расход' if self.debit_amount > 0 else 'Доход',
            'type_class': 'expense' if self.debit_amount > 0 else 'income',
            'operation_type': self.operation_type,
            'operation_type_display': operation_type_display,
            'purpose': self.purpose,
            'counterparty': self.counterparty,
            'budget_id': self.budget_id,
            'budget_name': self.budget.name if self.budget else None,
            'section_id': self.section_id,
            'section_name': self.section.name if self.section else None,
            'article_id': self.article_id,
            'article_name': self.article_ref.name if self.article_ref else None,
            'has_documents': (len(self.documents) > 0 or len(self.library_documents) > 0) if hasattr(self, 'library_documents') or hasattr(self, 'documents')  else False,
            'documents_count': len(self.library_documents) if hasattr(self, 'library_documents') else 0 + len(self.documents) if hasattr(self, 'documents') else 0,
            'documents': [d.to_dict() for d in self.documents],
            'is_split': self.is_split or False
        }

class Document(db.Model):
    """Прикрепленный документ (PDF)"""
    __tablename__ = 'documents'

    id = db.Column(db.Integer, primary_key=True)
    operation_id = db.Column(db.Integer, db.ForeignKey('operations.id'), nullable=False)
    filename = db.Column(db.String(200), nullable=False)
    original_filename = db.Column(db.String(200), nullable=False)
    file_path = db.Column(db.String(500), nullable=False)
    attachment_number = db.Column(db.Integer)
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'filename': self.filename,
            'original_filename': self.original_filename,
            'attachment_number': self.attachment_number
        }


class SplitOperation(db.Model):
    """Разделенная операция (часть исходной операции)"""
    __tablename__ = 'split_operations'

    id = db.Column(db.Integer, primary_key=True)
    parent_operation_id = db.Column(db.Integer, db.ForeignKey('operations.id'), nullable=False)
    amount = db.Column(db.Float, default=0.0)
    description = db.Column(db.String(500), default='')

    # Статьи сметы для разделенной части
    budget_id = db.Column(db.Integer, db.ForeignKey('budgets.id'), nullable=True)
    section_id = db.Column(db.Integer, db.ForeignKey('budget_sections.id'), nullable=True)
    article_id = db.Column(db.Integer, db.ForeignKey('budget_articles.id'), nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Связи
    parent_operation = db.relationship('Operation', backref='splits', foreign_keys=[parent_operation_id])
    budget = db.relationship('Budget', backref='split_operations')
    section = db.relationship('BudgetSection', backref='split_operations')
    article = db.relationship('BudgetArticle', backref='split_operations')

    def to_dict(self):
        return {
            'id': self.id,
            'parent_operation_id': self.parent_operation_id,
            'amount': self.amount,
            'amount_display': f"{self.amount:,.2f}",
            'description': self.description,
            'budget_id': self.budget_id,
            'budget_name': self.budget.name if self.budget else None,
            'section_id': self.section_id,
            'section_name': self.section.name if self.section else None,
            'article_id': self.article_id,
            'article_name': self.article.name if self.article else None
        }

class StatementImport(db.Model):
    """История импорта выписок"""
    __tablename__ = 'statement_imports'

    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(200), nullable=False)
    import_date = db.Column(db.DateTime, default=datetime.utcnow)
    operations_count = db.Column(db.Integer, default=0)
    status = db.Column(db.String(20), default='success')
    error_message = db.Column(db.Text)


class DocumentLibrary(db.Model):
    """Библиотека документов (центральное хранилище)"""
    __tablename__ = 'document_library'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(500), nullable=False)
    filename = db.Column(db.String(200), nullable=False)
    original_filename = db.Column(db.String(200), nullable=False)
    file_path = db.Column(db.String(500), nullable=False)
    file_size = db.Column(db.Integer, default=0)
    mime_type = db.Column(db.String(100), default='application/pdf')
    description = db.Column(db.Text)
    tags = db.Column(db.String(500))
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)
    uploaded_by = db.Column(db.String(100), default='')
    usage_count = db.Column(db.Integer, default=0)
    is_shared = db.Column(db.Boolean, default=True)  # True - общий документ, False - личный

    operation_links = db.relationship('OperationDocumentLink', backref='document', lazy=True,
                                      cascade='all, delete-orphan')


class OperationDocumentLink(db.Model):
    """Связь между операцией и документом из библиотеки"""
    __tablename__ = 'operation_document_links'

    id = db.Column(db.Integer, primary_key=True)
    operation_id = db.Column(db.Integer, db.ForeignKey('operations.id'), nullable=False)
    document_id = db.Column(db.Integer, db.ForeignKey('document_library.id'), nullable=False)
    attached_at = db.Column(db.DateTime, default=datetime.utcnow)
    note = db.Column(db.String(500))

    __table_args__ = (
        db.UniqueConstraint('operation_id', 'document_id', name='unique_op_doc'),
    )