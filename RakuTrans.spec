# -*- mode: python ; coding: utf-8 -*-
import ast
import os
from pathlib import Path
import sys
from PyInstaller.utils.hooks import collect_all


def _read_app_metadata():
    app_name = 'RakuTrans AI'
    app_version = '1.0.0'
    cfg_path = Path(SPECPATH) / 'config.py'
    try:
        tree = ast.parse(cfg_path.read_text(encoding='utf-8'))
        for node in tree.body:
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if (
                        isinstance(target, ast.Name)
                        and isinstance(node.value, ast.Constant)
                        and isinstance(node.value.value, str)
                    ):
                        if target.id == 'APP_NAME':
                            app_name = node.value.value
                        elif target.id == 'APP_VERSION':
                            app_version = node.value.value
    except Exception:
        pass
    return app_name, app_version


app_name, app_version = _read_app_metadata()
codesign_identity = os.environ.get('RAKUTRANS_CODESIGN_IDENTITY') or None

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

for optional_pkg in ('certifi',):
    try:
        tmp_ret = collect_all(optional_pkg)
        datas += tmp_ret[0]
        binaries += tmp_ret[1]
        hiddenimports += tmp_ret[2]
    except Exception:
        pass

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
    codesign_identity=codesign_identity,
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
        version=app_version,
        info_plist={
            'CFBundleName': app_name,
            'CFBundleDisplayName': app_name,
            'CFBundleShortVersionString': app_version,
            'CFBundleVersion': app_version,
            'NSHighResolutionCapable': True,
            'LSApplicationCategoryType': 'public.app-category.productivity',
        },
    )
