#!/usr/bin/env bash
# ==============================================================================
# Script to build standalone macOS Application (.app) and Disk Image (.dmg)
# ==============================================================================
set -e

echo "============================================="
echo "   Building RakuTrans AI for macOS (.app)    "
echo "============================================="

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

VENV_PY="$SCRIPT_DIR/.venv/bin/python"
PYINSTALLER="$SCRIPT_DIR/.venv/bin/pyinstaller"

# Ensure .venv is healthy and synced with requirements.txt
if [ ! -f "$VENV_PY" ] || ! "$VENV_PY" -c "import hashlib, pathlib, sys, customtkinter, tkinterdnd2, PIL, openpyxl, docx, pptx, fitz, pypdf, pdf2docx, reportlab, charset_normalizer; req = pathlib.Path('requirements.txt'); stamp = pathlib.Path('.venv/.req_stamp'); ok_stamp = (not req.exists()) or (stamp.exists() and stamp.read_text().strip() == hashlib.sha256(req.read_bytes()).hexdigest()); sys.exit(0 if (sys.version_info >= (3, 10) and ok_stamp) else 1)" >/dev/null 2>&1; then
    echo "[RakuTrans AI] Virtual environment (.venv) is missing or needs sync."
    echo "[RakuTrans AI] Running automatic setup..."
    bash "$SCRIPT_DIR/setup_env.sh" --with-build
fi

# Ensure pyinstaller is available
if [ ! -f "$PYINSTALLER" ]; then
    echo "Installing PyInstaller into .venv..."
    "$VENV_PY" -m pip install -q pyinstaller
fi

echo "Cleaning previous builds..."
rm -rf build dist

echo "Compiling standalone application bundle via RakuTrans.spec..."
"$PYINSTALLER" --noconfirm --clean "$SCRIPT_DIR/RakuTrans.spec"

echo ""
echo "✓ Standalone macOS Application created:"
echo "  -> dist/RakuTrans.app"

# Remove quarantine attribute so macOS doesn't block the app
xattr -dr com.apple.quarantine "dist/RakuTrans.app" 2>/dev/null || true

# Package into drag-and-drop .dmg installer with /Applications shortcut
if command -v hdiutil >/dev/null 2>&1; then
    echo ""
    echo "Creating drag-and-drop installer image (.dmg)..."
    DMG_PATH="dist/RakuTrans-Installer-macOS.dmg"
    DMG_STAGE="$(mktemp -d "${TMPDIR:-/tmp}/rakutrans_dmg.XXXXXX")"
    trap 'rm -rf "$DMG_STAGE"' EXIT

    cp -R "dist/RakuTrans.app" "$DMG_STAGE/RakuTrans.app"
    ln -s /Applications "$DMG_STAGE/Applications"

    rm -f "$DMG_PATH"
    hdiutil create -volname "RakuTrans AI" -srcfolder "$DMG_STAGE" -ov -format UDZO "$DMG_PATH"
    rm -rf "$DMG_STAGE"
    trap - EXIT
    echo "✓ Installer DMG created:"
    echo "  -> $DMG_PATH"
fi

echo ""
echo "============================================="
echo "   Build completed successfully!             "
echo "   Users can double-click RakuTrans.app      "
echo "   without needing Python or Terminal.       "
echo "============================================="
