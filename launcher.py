# launcher.py - универсальный лаунчер для Windows
import os
import sys
import subprocess
import tkinter as tk
from tkinter import messagebox
import threading


class AppLauncher:
    def __init__(self, root):
        self.root = root
        self.root.title("TSNFinance - Учёт банковских выписок")
        self.root.geometry("400x300")
        self.root.resizable(False, False)

        # Центрирование окна
        self.center_window()

        # UI элементы
        self.create_widgets()

    def center_window(self):
        self.root.update_idletasks()
        width = 400
        height = 300
        x = (self.root.winfo_screenwidth() // 2) - (width // 2)
        y = (self.root.winfo_screenheight() // 2) - (height // 2)
        self.root.geometry(f'{width}x{height}+{x}+{y}')

    def create_widgets(self):
        # Заголовок
        title = tk.Label(self.root, text="TSNFinance", font=("Arial", 20, "bold"))
        title.pack(pady=20)

        desc = tk.Label(self.root, text="Система учёта банковских выписок и смет", font=("Arial", 10))
        desc.pack(pady=5)

        # Кнопки
        btn_frame = tk.Frame(self.root)
        btn_frame.pack(pady=30)

        start_btn = tk.Button(btn_frame, text="🚀 Запустить приложение",
                              command=self.start_app, bg="#28a745", fg="white",
                              font=("Arial", 12), width=25, height=2)
        start_btn.pack(pady=10)

        init_btn = tk.Button(btn_frame, text="🔧 Инициализация (создание БД)",
                             command=self.init_db, bg="#17a2b8", fg="white",
                             font=("Arial", 10), width=25)
        init_btn.pack(pady=5)

        open_folder_btn = tk.Button(btn_frame, text="📁 Открыть папку с данными",
                                    command=self.open_data_folder, bg="#6c757d", fg="white",
                                    font=("Arial", 10), width=25)
        open_folder_btn.pack(pady=5)

        # Статус
        self.status_label = tk.Label(self.root, text="Готов к запуску", fg="gray", font=("Arial", 9))
        self.status_label.pack(pady=20)

    def get_base_dir(self):
        if getattr(sys, 'frozen', False):
            return os.path.dirname(sys.executable)
        else:
            return os.path.dirname(os.path.abspath(__file__))

    def init_db(self):
        try:
            self.status_label.config(text="Инициализация...", fg="orange")
            self.root.update()

            # Запуск init_app.py
            base_dir = self.get_base_dir()
            python_exe = sys.executable if not getattr(sys, 'frozen', False) else 'python'

            if getattr(sys, 'frozen', False):
                # В скомпилированном виде запускаем подпроцесс
                result = subprocess.run([sys.executable, '-c',
                                         "from app import app, db; app.app_context().push(); db.create_all(); print('OK')"],
                                        capture_output=True, text=True, cwd=base_dir)
            else:
                result = subprocess.run([python_exe, 'init_app.py'],
                                        capture_output=True, text=True, cwd=base_dir)

            if result.returncode == 0:
                self.status_label.config(text="Инициализация завершена успешно!", fg="green")
                messagebox.showinfo("Успех", "База данных успешно создана!")
            else:
                self.status_label.config(text="Ошибка инициализации", fg="red")
                messagebox.showerror("Ошибка", f"Ошибка инициализации:\n{result.stderr}")

        except Exception as e:
            self.status_label.config(text="Ошибка", fg="red")
            messagebox.showerror("Ошибка", str(e))

    def start_app(self):
        try:
            self.status_label.config(text="Запуск сервера...", fg="orange")
            self.root.update()

            base_dir = self.get_base_dir()

            if getattr(sys, 'frozen', False):
                # В скомпилированном виде запускаем сервер в отдельном процессе
                subprocess.Popen([sys.executable, '-c',
                                  "from app import app; app.run(host='127.0.0.1', port=5000, debug=False, use_reloader=False)"],
                                 cwd=base_dir, creationflags=subprocess.CREATE_NO_WINDOW)
            else:
                # Из исходников
                subprocess.Popen(['python', 'run_app.py'], cwd=base_dir)

            # Открываем браузер
            import webbrowser
            webbrowser.open('http://127.0.0.1:5000')

            self.status_label.config(text="Сервер запущен", fg="green")

        except Exception as e:
            self.status_label.config(text="Ошибка запуска", fg="red")
            messagebox.showerror("Ошибка", str(e))

    def open_data_folder(self):
        base_dir = self.get_base_dir()
        data_folder = os.path.join(base_dir, 'data')
        if os.path.exists(data_folder):
            os.startfile(data_folder)
        else:
            messagebox.showwarning("Папка не найдена", "Папка с данными еще не создана")


if __name__ == '__main__':
    root = tk.Tk()
    app = AppLauncher(root)
    root.mainloop()