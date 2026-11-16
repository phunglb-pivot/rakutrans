#!/usr/bin/env bash
# ==============================================================================
# RakuTrans AI - Environment Setup & Self-Healing Script (macOS / Linux)
# ==============================================================================
# Detects Python 3.10+ across system PATH, Homebrew, python.org Framework,
# pyenv, asdf, mise, and uv (prioritizing Tkinter support), heals/rebuilds
# broken virtual environments, and installs all required dependencies.
#
# Optional override:
#   RAKUTRANS_PYTHON=/path/to/python3 ./setup_env.sh
# ==============================================================================
set -e

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

echo "============================================="
echo "   RakuTrans AI - Environment Setup          "
echo "============================================="

OVERRIDE_PY="${RAKUTRANS_PYTHON:-${PYTHON_BIN:-}}"

is_valid_python() {
    local py="$1"
    if [[ "$py" == */* ]]; then
        [ -x "$py" ] || return 1
    else
        command -v "$py" >/dev/null 2>&1 || return 1
    fi
    "$py" -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" 2>/dev/null
}

has_tkinter() {
    local py="$1"
    "$py" -c "import tkinter" 2>/dev/null
}

# 1. Locate the best Python 3 interpreter (>= 3.10, prioritizing Tkinter support)
find_python() {
    if [ -n "$OVERRIDE_PY" ]; then
        if is_valid_python "$OVERRIDE_PY"; then
            echo "$OVERRIDE_PY"
            return 0
        else
            echo "ERROR_OVERRIDE"
            return 0
        fi
    fi

    local prev_nullglob
    prev_nullglob="$(shopt -p nullglob || true)"
    shopt -s nullglob

    local candidates=(
        # Versioned commands on PATH (prefer well-supported 3.10-3.14)
        "python3.12"
        "python3.11"
        "python3.13"
        "python3.10"
        "python3.14"
        # Homebrew (Apple Silicon)
        "/opt/homebrew/opt/python@3.12/bin/python3.12"
        "/opt/homebrew/opt/python@3.11/bin/python3.11"
        "/opt/homebrew/opt/python@3.13/bin/python3.13"
        "/opt/homebrew/opt/python@3.10/bin/python3.10"
        "/opt/homebrew/opt/python@3.14/bin/python3.14"
        "/opt/homebrew/bin/python3.12"
        "/opt/homebrew/bin/python3.11"
        "/opt/homebrew/bin/python3.13"
        "/opt/homebrew/bin/python3.10"
        "/opt/homebrew/bin/python3"
        # Homebrew (Intel / Linuxbrew)
        "/usr/local/opt/python@3.12/bin/python3.12"
        "/usr/local/opt/python@3.11/bin/python3.11"
        "/usr/local/opt/python@3.13/bin/python3.13"
        "/usr/local/opt/python@3.10/bin/python3.10"
        "/usr/local/bin/python3.12"
        "/usr/local/bin/python3.11"
        "/usr/local/bin/python3.13"
        "/usr/local/bin/python3.10"
        "/usr/local/bin/python3"
        # Official python.org macOS Framework installers
        /Library/Frameworks/Python.framework/Versions/3.*/bin/python3
        # Version managers (even when shims aren't active in non-interactive shells)
        "$HOME/.pyenv/versions/"*/bin/python3
        "$HOME/.asdf/installs/python/"*/bin/python3
        "$HOME/.local/share/mise/installs/python/"*/bin/python3
        "$HOME/.local/share/uv/python/"*/bin/python3
        # Generic fallbacks on PATH
        "python3"
        "python"
    )

    eval "$prev_nullglob"

    local best_py=""
    local fallback_py=""

    for py in "${candidates[@]}"; do
        if is_valid_python "$py"; then
            if [ -z "$fallback_py" ]; then
                fallback_py="$py"
            fi
            if has_tkinter "$py"; then
                best_py="$py"
                break
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

if [ "$PYTHON_BIN" = "ERROR_OVERRIDE" ]; then
    echo ""
    echo "❌ Error: Specified Python interpreter '$OVERRIDE_PY' was not found or is < 3.10."
    exit 1
fi

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
    echo "Tip: If Python 3.10+ is installed in a custom path, run:"
    echo "      RAKUTRANS_PYTHON=/path/to/python3 ./setup_env.sh"
    echo ""
    exit 1
fi

PY_VER="$("$PYTHON_BIN" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')")"
PY_MM="$("$PYTHON_BIN" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")"
echo "Found system Python: $PYTHON_BIN ($PY_VER)"

# 2. Check existing virtual environment integrity
VENV_DIR="$SCRIPT_DIR/.venv"
RECREATE_VENV=0

if [ -d "$VENV_DIR" ]; then
    if [ ! -f "$VENV_DIR/bin/python" ] || ! "$VENV_DIR/bin/python" -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >/dev/null 2>&1; then
        echo "[Notice] Existing .venv is invalid, < 3.10, moved from another path, or corrupted."
        echo "Recreating clean environment..."
        rm -rf "$VENV_DIR"
        RECREATE_VENV=1
    elif [ -n "$OVERRIDE_PY" ]; then
        VENV_VER="$("$VENV_DIR/bin/python" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')" 2>/dev/null || echo "")"
        if [ "$VENV_VER" != "$PY_VER" ]; then
            echo "[Notice] Rebuilding .venv to match requested Python $PY_VER (was $VENV_VER)..."
            rm -rf "$VENV_DIR"
            RECREATE_VENV=1
        fi
    elif ! has_tkinter "$VENV_DIR/bin/python" && has_tkinter "$PYTHON_BIN"; then
        echo "[Notice] Upgrading .venv to use $PYTHON_BIN ($PY_VER) with Tkinter support..."
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
if has_tkinter "$VENV_PY"; then
    echo "✓ Environment is ready! (GUI and CLI supported)"
else
    echo "⚠️ Warning: Tkinter is not found in this environment ($PY_VER)."
    echo "  • Headless CLI translation will work: ./run.sh --cli --file doc.xlsx --tgt Vietnamese"
    echo "  • For Desktop GUI on macOS (Homebrew), run: brew install python-tk@$PY_MM"
fi

echo "============================================="
echo "Setup complete! Launch with: ./run.sh"
echo "============================================="
