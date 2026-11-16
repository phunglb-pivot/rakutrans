#!/usr/bin/env bash
# ==============================================================================
# RakuTrans AI - macOS / Linux Launcher
# ==============================================================================
set -e

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

VENV_PY="$SCRIPT_DIR/.venv/bin/python"

# Check if .venv exists, meets Python >= 3.10, has core dependencies, and matches requirements.txt
if [ ! -f "$VENV_PY" ] || ! "$VENV_PY" -c "import hashlib, pathlib, sys, customtkinter, tkinterdnd2, PIL, openpyxl, docx, pptx, fitz, pypdf, pdf2docx, reportlab, charset_normalizer; req = pathlib.Path('requirements.txt'); stamp = pathlib.Path('.venv/.req_stamp'); ok_stamp = (not req.exists()) or (stamp.exists() and stamp.read_text().strip() == hashlib.sha256(req.read_bytes()).hexdigest()); sys.exit(0 if (sys.version_info >= (3, 10) and ok_stamp) else 1)" >/dev/null 2>&1; then
    echo "[RakuTrans AI] Virtual environment (.venv) is missing or needs sync."
    echo "[RakuTrans AI] Running automatic setup..."
    bash "$SCRIPT_DIR/setup_env.sh"
fi

exec "$VENV_PY" "$SCRIPT_DIR/main.py" "$@"
