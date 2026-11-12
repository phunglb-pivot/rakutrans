#!/usr/bin/env bash
# ==============================================================================
# RakuTrans AI - Environment Setup & Self-Healing Script (macOS / Linux)
# ==============================================================================
# Detects Python 3.10+, automatically heals/rebuilds broken virtual environments
# (e.g. after moving project directories or cloning to a new machine), and installs
# all required dependencies for both GUI and CLI operation.
# ==============================================================================
set -e

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

echo "============================================="
echo "   RakuTrans AI - Environment Setup          "
echo "============================================="

# 1. Locate the best Python 3 interpreter (>= 3.10, prioritizing Tkinter support)
find_python() {
    local candidates=(
        "/opt/homebrew/opt/python@3.12/bin/python3.12"
        "/opt/homebrew/opt/python@3.11/bin/python3.11"
        "/opt/homebrew/bin/python3.12"
        "/opt/homebrew/bin/python3.11"
        "/opt/homebrew/bin/python3"
        "/usr/local/bin/python3.12"
        "/usr/local/bin/python3.11"
        "/usr/local/bin/python3"
        "python3.12"
        "python3.11"
        "python3.10"
        "python3"
        "python"
    )

    local best_py=""
    local fallback_py=""

    for py in "${candidates[@]}"; do
        if command -v "$py" >/dev/null 2>&1; then
            # Verify version >= 3.10
            if "$py" -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" 2>/dev/null; then
                if [ -z "$fallback_py" ]; then
                    fallback_py="$py"
                fi
                # Check Tkinter availability
                if "$py" -c "import tkinter" 2>/dev/null; then
                    best_py="$py"
                    break
                fi
            fi
        fi
    done

    if [ -n "$best_py" ]; then
        echo "$best_py"
    elif [ -n "$fallback_py" ]; then
        echo "$fallback_py"
    else
        echo ""
    fi
}

PYTHON_BIN="$(find_python)"

if [ -z "$PYTHON_BIN" ]; then
    echo ""
    echo "❌ Error: Python 3.10 or higher could not be found."
    echo ""
    echo "Installation options:"
    echo "  • macOS (Homebrew):"
    echo "      brew install python@3.12 python-tk@3.12"
    echo "  • Ubuntu / Debian:"
    echo "      sudo apt-get update && sudo apt-get install python3 python3-venv python3-tk"
    echo "  • Other platforms: https://www.python.org/downloads/"
    echo ""
    exit 1
fi

PY_VER="$("$PYTHON_BIN" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')")"
echo "Found system Python: $PYTHON_BIN ($PY_VER)"

# 2. Check existing virtual environment integrity
VENV_DIR="$SCRIPT_DIR/.venv"
RECREATE_VENV=0

if [ -d "$VENV_DIR" ]; then
    if [ ! -f "$VENV_DIR/bin/python" ] || ! "$VENV_DIR/bin/python" -c "import sys" >/dev/null 2>&1; then
        echo "[Notice] Existing .venv is invalid, moved from another path, or corrupted."
        echo "Recreating clean environment..."
        rm -rf "$VENV_DIR"
        RECREATE_VENV=1
    fi
else
    RECREATE_VENV=1
fi

# 3. Create virtual environment if missing or rebuilt
if [ "$RECREATE_VENV" -eq 1 ]; then
    echo "Creating virtual environment at $VENV_DIR..."
    "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

# 4. Install / update packages
VENV_PY="$VENV_DIR/bin/python"
echo "Upgrading pip..."
"$VENV_PY" -m pip install -q --upgrade pip

if [ -f "$SCRIPT_DIR/requirements.txt" ]; then
    echo "Installing application dependencies..."
    "$VENV_PY" -m pip install -q -r "$SCRIPT_DIR/requirements.txt" pyinstaller
fi

# 5. Validate Tkinter readiness
echo ""
if "$VENV_PY" -c "import tkinter" >/dev/null 2>&1; then
    echo "✓ Environment is ready! (GUI and CLI supported)"
else
    echo "⚠️ Warning: Tkinter is not found in this environment."
    echo "  • Headless CLI translation will work: ./run.sh --file doc.xlsx --tgt Vietnamese"
    echo "  • For Desktop GUI on macOS, run: brew install python-tk@3.12"
fi

echo "============================================="
echo "Setup complete! Launch with: ./run.sh"
echo "============================================="

