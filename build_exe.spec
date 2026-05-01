# build_exe.spec
# -*- mode: python ; coding: utf-8 -*-

import sys
import os
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

# Пути к шаблонам и статике
template_files = []
for root, dirs, files in os.walk('templates'):
    for file in files:
        template_files.append((os.path.join(root, file), os.path.join('templates', file)))

static_files = []
for root, dirs, files in os.walk('static'):
    for file in files:
        static_files.append((os.path.join(root, file), os.path.join('static', file)))

# Файлы шрифтов
font_files = []
if os.path.exists('fonts'):
    for root, dirs, files in os.walk('fonts'):
        for file in files:
            font_files.append((os.path.join(root, file), os.path.join('fonts', file)))

a = Analysis(
    ['run.py'],
    pathex=[],
    binaries=[],
    datas=template_files + static_files + font_files,
    hiddenimports=[
        'flask',
        'flask_sqlalchemy',
        'sqlalchemy',
        'pandas',
        'openpyxl',
        'reportlab',
        'PyPDF2',
        'fitz',  # PyMuPDF
        'werkzeug',
        'jinja2',
        'click',
        'markupsafe',
        'itsdangerous',
        'sqlite3',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='TSNFinance',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,  # Для отладки - показывает окно консоли
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='static/favicon.ico' if os.path.exists('static/favicon.ico') else None,
)

# Для Windows GUI приложения (без консоли)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='TSNFinance',
)