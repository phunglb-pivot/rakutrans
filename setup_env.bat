@echo off
setlocal enabledelayedexpansion

REM ==============================================================================
REM RakuTrans AI - Environment Setup & Self-Healing Script (Windows)
REM ==============================================================================
REM Detects Python 3.10+, automatically heals/rebuilds broken virtual environments
REM (e.g. after moving project directories or cloning to a new machine), and installs
REM all required dependencies for both GUI and CLI operation.
REM ==============================================================================

set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

echo =============================================
echo    RakuTrans AI - Environment Setup (Windows)
echo =============================================

REM 1. Detect Python 3.10+
set "PY_CMD="
for %%P in (py python python3) do (
    if not defined PY_CMD (
        %%P -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
        if not errorlevel 1 (
            set "PY_CMD=%%P"
        )
    )
)

if not defined PY_CMD (
    echo.
    echo [Error] Python 3.10 or higher is required.
    echo Please install Python from https://www.python.org/downloads/
    echo Make sure to check "Add python.exe to PATH" during installation.
    echo.
    pause
    exit /b 1
)

for /f "delims=" %%V in ('!PY_CMD! -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')"') do set "PY_VER=%%V"
echo Found Python: !PY_CMD! (!PY_VER!)

REM 2. Check virtual environment integrity
set "VENV_DIR=%SCRIPT_DIR%.venv"
set "VENV_PY=%VENV_DIR%\Scripts\python.exe"
set "RECREATE_VENV=0"

if exist "%VENV_DIR%" (
    if not exist "%VENV_PY%" (
        echo [Notice] Existing .venv is incomplete or invalid.
        set "RECREATE_VENV=1"
    ) else (
        "%VENV_PY%" -c "import sys" >nul 2>&1
        if errorlevel 1 (
            echo [Notice] Existing .venv was moved from another path or is corrupted.
            set "RECREATE_VENV=1"
        )
    )
) else (
    set "RECREATE_VENV=1"
)

if "!RECREATE_VENV!"=="1" (
    echo Recreating clean virtual environment at %VENV_DIR%...
    if exist "%VENV_DIR%" rmdir /s /q "%VENV_DIR%"
    !PY_CMD! -m venv "%VENV_DIR%"
    if errorlevel 1 (
        echo [Error] Failed to create virtual environment.
        pause
        exit /b 1
    )
)

REM 3. Install / update packages
echo Upgrading pip...
"%VENV_PY%" -m pip install -q --upgrade pip

if exist "%SCRIPT_DIR%requirements.txt" (
    echo Installing application dependencies...
    "%VENV_PY%" -m pip install -q -r "%SCRIPT_DIR%requirements.txt" pyinstaller
    if errorlevel 1 (
        echo [Error] Failed to install dependencies.
        pause
        exit /b 1
    )
)

REM 4. Validate readiness
echo.
"%VENV_PY%" -c "import tkinter" >nul 2>&1
if not errorlevel 1 (
    echo [OK] Environment is ready! (GUI and CLI supported)
) else (
    echo [Warning] Tkinter is not found. GUI may not start.
)

echo =============================================
echo Setup complete! Launch with: run_windows.bat
echo =============================================

