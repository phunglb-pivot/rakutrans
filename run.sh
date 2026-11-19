#!/usr/bin/env bash
# ==============================================================================
# RakuTrans AI - macOS / Linux Launcher
# ==============================================================================
set -e

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

VENV_PY="$SCRIPT_DIR/.venv/bin/python"

# Check if .venv exists, meets Python >= 3.10, has core dependencies, and matches requirements.txt
if [ ! -f "$VENV_PY" ] || ! "$VENV_PY" "$SCRIPT_DIR/scripts/check_env.py" >/dev/null 2>&1; then
    echo "[RakuTrans AI] Virtual environment (.venv) is missing or needs sync."
    echo "[RakuTrans AI] Running automatic setup..."
    bash "$SCRIPT_DIR/scripts/setup_env.sh"
fi

exec "$VENV_PY" "$SCRIPT_DIR/main.py" "$@"
