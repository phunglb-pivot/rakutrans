# -*- mode: python ; coding: utf-8 -*-
import sys
from PyInstaller.utils.hooks import collect_all

datas = [('assets', 'assets')]
binaries = []
hiddenimports = [
    'sqlite3',
    'tkinter',
    'fitz',
    'pdf2docx',
    'pypdf',
    'openpyxl',
    'openai',
    'anthropic',
    'google.generativeai',
]

for pkg in (
    'customtkinter',
    'tkinterdnd2',
    'magika',
    'markitdown',
    'docx',
    'pptx',
    'google.genai',
    'pymupdf',
    'reportlab',
    'charset_normalizer',
):
    tmp_ret = collect_all(pkg)
    datas += tmp_ret[0]
    binaries += tmp_ret[1]
    hiddenimports += tmp_ret[2]

is_mac = sys.platform == 'darwin'
icon_path = 'assets/icon.icns' if is_mac else 'assets/icon.ico'

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
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
    [],
    exclude_binaries=True,
    name='RakuTrans',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=[icon_path],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='RakuTrans',
)

if is_mac:
    app = BUNDLE(
        coll,
        name='RakuTrans.app',
        icon='assets/icon.icns',
        bundle_identifier='com.rakutrans.app',
    )
