# -*- mode: python ; coding: utf-8 -*-
import ast
import os
from pathlib import Path
import sys
from PyInstaller.utils.hooks import collect_all


SPEC_DIR = Path(globals().get('SPECPATH', '.')).resolve()
ROOT_DIR = SPEC_DIR.parent


def _read_app_metadata():
    required_keys = ('APP_NAME', 'APP_VERSION', 'APP_EXECUTABLE_NAME', 'APP_BUNDLE_ID')
    metadata = {}
    cfg_path = ROOT_DIR / 'rakutrans' / 'core' / 'config.py'
    if not cfg_path.is_file():
        raise RuntimeError(f"Cannot find config.py at {cfg_path}")
    tree = ast.parse(cfg_path.read_text(encoding='utf-8'))
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if (
                    isinstance(target, ast.Name)
                    and target.id in required_keys
                    and isinstance(node.value, ast.Constant)
                    and isinstance(node.value.value, str)
                ):
                    metadata[target.id] = node.value.value.strip()
    missing = [k for k in required_keys if not metadata.get(k)]
    if missing:
        raise RuntimeError(
            f"Missing required metadata in {cfg_path}: {', '.join(missing)}"
        )
    return (
        metadata['APP_NAME'],
        metadata['APP_VERSION'],
        metadata['APP_EXECUTABLE_NAME'],
        metadata['APP_BUNDLE_ID'],
    )


app_name, app_version, app_exec_name, app_bundle_id = _read_app_metadata()
codesign_identity = os.environ.get('RAKUTRANS_CODESIGN_IDENTITY') or None

datas = [(str(ROOT_DIR / 'assets'), 'assets')]
binaries = []
hiddenimports = [
    'sqlite3',
    'tkinter',
    'PIL',
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
icon_path = str(ROOT_DIR / 'assets' / ('icon.icns' if is_mac else 'icon.ico'))

a = Analysis(
    [str(ROOT_DIR / 'main.py')],
    pathex=[str(ROOT_DIR)],
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
    name=app_exec_name,
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
    name=app_exec_name,
)

if is_mac:
    app = BUNDLE(
        coll,
        name=f'{app_exec_name}.app',
        icon=str(ROOT_DIR / 'assets' / 'icon.icns'),
        bundle_identifier=app_bundle_id,
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
