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
if [ ! -f "$VENV_PY" ] || ! "$VENV_PY" "$SCRIPT_DIR/check_env.py" >/dev/null 2>&1; then
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

APP_NAME="$("$VENV_PY" "$SCRIPT_DIR/check_env.py" --meta APP_NAME)"
APP_VERSION="$("$VENV_PY" "$SCRIPT_DIR/check_env.py" --meta APP_VERSION)"
APP_EXEC_NAME="$("$VENV_PY" "$SCRIPT_DIR/check_env.py" --meta APP_EXECUTABLE_NAME)"
if [ -z "$APP_NAME" ] || [ -z "$APP_VERSION" ] || [ -z "$APP_EXEC_NAME" ]; then
    echo "[Error] Failed to read app metadata from config.py" >&2
    exit 1
fi
APP_BUNDLE="${APP_EXEC_NAME}.app"
echo "Compiling standalone application bundle (v$APP_VERSION) via RakuTrans.spec..."
"$PYINSTALLER" --noconfirm --clean "$SCRIPT_DIR/RakuTrans.spec"

echo ""
echo "✓ Standalone macOS Application created (v$APP_VERSION):"
echo "  -> dist/$APP_BUNDLE"

# Remove quarantine attribute so macOS doesn't block the app locally
if [ -x /usr/bin/xattr ]; then
    /usr/bin/xattr -dr com.apple.quarantine "dist/$APP_BUNDLE" 2>/dev/null || true
else
    xattr -dr com.apple.quarantine "dist/$APP_BUNDLE" 2>/dev/null || true
fi

# Package into drag-and-drop .dmg installer with /Applications shortcut
if command -v hdiutil >/dev/null 2>&1; then
    echo ""
    echo "Creating drag-and-drop installer image (.dmg)..."
    DMG_PATH="dist/${APP_EXEC_NAME}-Installer-macOS.dmg"
    DMG_STAGE="$(mktemp -d "${TMPDIR:-/tmp}/rakutrans_dmg.XXXXXX")"
    trap 'rm -rf "$DMG_STAGE"' EXIT

    cp -R "dist/$APP_BUNDLE" "$DMG_STAGE/$APP_BUNDLE"
    ln -s /Applications "$DMG_STAGE/Applications"

    rm -f "$DMG_PATH"
    hdiutil create -volname "$APP_NAME" -srcfolder "$DMG_STAGE" -ov -format UDZO "$DMG_PATH"
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
