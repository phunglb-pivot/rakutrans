#!/usr/bin/env bash
# ==============================================================================
# RakuTrans AI - macOS / Linux Launcher
# ==============================================================================
set -e

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

VENV_PY="$SCRIPT_DIR/.venv/bin/python"

# Check if .venv exists, meets Python >= 3.10, and has core dependencies installed
if [ ! -f "$VENV_PY" ] || ! "$VENV_PY" -c "import sys, customtkinter; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >/dev/null 2>&1; then
    echo "[RakuTrans AI] Virtual environment (.venv) is missing or needs repair."
    echo "[RakuTrans AI] Running automatic setup..."
    bash "$SCRIPT_DIR/setup_env.sh"
fi

exec "$VENV_PY" "$SCRIPT_DIR/main.py" "$@"
