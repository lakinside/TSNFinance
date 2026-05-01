# run_app.py - точка входа для Windows-приложения
import os
import sys
import webbrowser
import threading
import time

# Получаем путь к исполняемому файлу или текущей директории
if getattr(sys, 'frozen', False):
    # Запуск из скомпилированного exe
    BASE_DIR = os.path.dirname(sys.executable)
else:
    # Запуск из исходного кода
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Устанавливаем рабочую директорию
os.chdir(BASE_DIR)

# Импортируем приложение
from app import app, init_database

# Функция открытия браузера
def open_browser():
    time.sleep(1.5)
    webbrowser.open('http://127.0.0.1:5000')

# Запускаем браузер в отдельном потоке
threading.Thread(target=open_browser, daemon=True).start()

if __name__ == '__main__':
    # Запуск сервера
    init_database()
    app.run(host='127.0.0.1', port=5000, debug=False, use_reloader=False)