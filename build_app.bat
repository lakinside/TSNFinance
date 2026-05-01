@echo off
echo ========================================
echo Building TSNFinance Windows Application
echo ========================================

REM Активация виртуального окружения
call .venv\Scripts\activate

REM Очистка старых сборок
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

REM Сборка приложения
pyinstaller --onefile ^
    --name "TSNFinance" ^
    --add-data "templates;templates" ^
    --add-data "static;static" ^
    --add-data "fonts;fonts" ^
    --hidden-import flask ^
    --hidden-import flask_sqlalchemy ^
    --hidden-import sqlalchemy ^
    --hidden-import pandas ^
    --hidden-import openpyxl ^
    --hidden-import reportlab ^
    --hidden-import PyPDF2 ^
    --hidden-import fitz ^
    --hidden-import werkzeug ^
    --hidden-import jinja2 ^
    --collect-data flask ^
    --collect-data flask_sqlalchemy ^
    run_app.py

echo ========================================
echo Build complete! Check dist folder
echo ========================================
pause