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

# Ensure .venv is healthy
if [ ! -f "$VENV_PY" ] || ! "$VENV_PY" -c "import sys" >/dev/null 2>&1; then
    echo "[RakuTrans AI] Virtual environment (.venv) is missing or needs repair."
    echo "[RakuTrans AI] Running automatic setup..."
    bash "$SCRIPT_DIR/setup_env.sh"
fi

# Ensure pyinstaller is available
if [ ! -f "$PYINSTALLER" ]; then
    echo "Installing PyInstaller into .venv..."
    "$VENV_PY" -m pip install -q pyinstaller
fi

echo "Cleaning previous builds..."
rm -rf build dist

echo "Compiling standalone application bundle with PyInstaller..."
"$PYINSTALLER" --noconfirm --clean \
    --name "RakuTrans" \
    --icon "assets/icon.icns" \
    --windowed \
    --onedir \
    --add-data "components:components" \
    --add-data "assets:assets" \
    --add-data "config.py:." \
    --add-data "i18n.py:." \
    --add-data "translation_cache.py:." \
    --collect-all customtkinter \
    --collect-all tkinterdnd2 \
    --collect-all magika \
    --collect-all markitdown \
    --collect-all docx \
    --collect-all pptx \
    --collect-all google.genai \
    --hidden-import sqlite3 \
    --hidden-import tkinter \
    main.py

echo ""
echo "✓ Standalone macOS Application created:"
echo "  -> dist/RakuTrans.app"

# Remove quarantine attribute so macOS doesn't block the app
xattr -dr com.apple.quarantine "dist/RakuTrans.app" 2>/dev/null || true

# Optional: Package into .dmg installer for distribution
if command -v hdiutil >/dev/null 2>&1; then
    echo ""
    echo "Creating drag-and-drop installer image (.dmg)..."
    DMG_PATH="dist/RakuTrans-Installer-macOS.dmg"
    rm -f "$DMG_PATH"
    hdiutil create -volname "RakuTrans AI" -srcfolder "dist/RakuTrans.app" -ov -format UDZO "$DMG_PATH"
    echo "✓ Installer DMG created:"
    echo "  -> $DMG_PATH"
fi

echo ""
echo "============================================="
echo "   Build completed successfully!             "
echo "   Users can double-click RakuTrans.app      "
echo "   without needing Python or Terminal.       "
echo "============================================="
