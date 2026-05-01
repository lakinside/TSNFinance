from pathlib import Path


class Config:
    """Конфигурация приложения"""

    # Корень приложения
    APP_ROOT = Path(__file__).parent.resolve()

    # Директории
    DATA_DIR = APP_ROOT / 'data'
    UPLOADS_DIR = APP_ROOT / 'uploads'
    REPORTS_DIR = APP_ROOT / 'reports'
    FONTS_DIR = APP_ROOT / 'fonts'
    LOGS_DIR = APP_ROOT / 'logs'
    STATIC_DIR = APP_ROOT / 'static'

    @classmethod
    def init_directories(cls):
        """Создание всех необходимых директорий"""
        for dir_name in ['DATA_DIR', 'UPLOADS_DIR', 'REPORTS_DIR', 'FONTS_DIR', 'LOGS_DIR', 'STATIC_DIR']:
            dir_path = getattr(cls, dir_name)
            dir_path.mkdir(parents=True, exist_ok=True)

    @classmethod
    def get_db_path(cls):
        return cls.DATA_DIR / 'bank_statement.db'

    @classmethod
    def get_font_path(cls, font_name='DejaVuSans.ttf'):
        """Поиск шрифта в нескольких местах"""
        # Пути для поиска шрифта
        font_paths = [
            cls.FONTS_DIR / font_name
        ]

        for path in font_paths:
            if path.exists():
                return str(path)

        return None

    # Настройки Flask
    SECRET_KEY = 'your-secret-key-change-this'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    MAX_CONTENT_LENGTH = 3500 * 1024 * 1024
    TSN_COMPANY_NAME = 'ТСН «Сантория»'
