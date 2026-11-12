#!/usr/bin/env bash
# ==============================================================================
# RakuTrans AI - macOS / Linux Launcher
# ==============================================================================
set -e

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

VENV_PY="$SCRIPT_DIR/.venv/bin/python"

# Check if .venv exists and has a working Python interpreter
if [ ! -f "$VENV_PY" ] || ! "$VENV_PY" -c "import sys" >/dev/null 2>&1; then
    echo "[RakuTrans AI] Virtual environment (.venv) is missing or needs repair."
    echo "[RakuTrans AI] Running automatic setup..."
    bash "$SCRIPT_DIR/setup_env.sh"
fi

exec "$VENV_PY" "$SCRIPT_DIR/main.py" "$@"
