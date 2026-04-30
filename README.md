# 🏦 TSNFinance — Учёт банковских выписок и смет

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue?logo=python&logoColor=white)](https://www.python.org/)
[![Flask](https://img.shields.io/badge/Flask-2.3.3-black?logo=flask&logoColor=white)](https://flask.palletsprojects.com/)
[![SQLite](https://img.shields.io/badge/SQLite-3.x-blue?logo=sqlite&logoColor=white)](https://www.sqlite.org/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

**Веб-приложение для автоматизации учёта банковских выписок, классификации расходов по сметам и формирования отчётности с приложениями.**

## 📌 Основные возможности

- **Загрузка выписок** в формате 1С (текстовый формат)
- **Управление сметами** — иерархическая структура: Смета → Раздел → Статья
- **Классификация операций** — назначение статей сметы с фильтрацией и массовым редактированием
- **Разделение операций** — распределение суммы одной операции по нескольким статьям
- **Библиотека документов** — централизованное хранение PDF-файлов с возможностью многократного использования
- **Гибкие фильтры** — по датам, контрагентам, типу операций, наличию документов
- **Формирование отчётов в PDF** — таблица операций с приложениями, автоматическая нумерация и встраивание документов

## 🖼️ Скриншоты

| Страница операций | Управление сметами |
|:---:|:---:|
| ![Операции](screenshots/operations.png) | ![Сметы](screenshots/budgets.png) |

| Библиотека документов | Сформированный отчёт |
|:---:|:---:|
| ![Документы](screenshots/documents.png) | ![Отчёт](screenshots/report.png) |

## 🚀 Быстрый старт

### Установка

```bash
# Клонирование репозитория
git clone https://github.com/yourusername/TSNFinance.git
cd TSNFinance

# Создание виртуального окружения
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
# или
.venv\Scripts\activate  # Windows

# Установка зависимостей
pip install -r requirements.txt

python app.py
