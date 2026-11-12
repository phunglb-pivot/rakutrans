@echo off
setlocal enabledelayedexpansion

REM ==============================================================================
REM RakuTrans AI - Windows Launcher
REM ==============================================================================

set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

set "VENV_PY=%SCRIPT_DIR%.venv\Scripts\python.exe"

set "NEED_SETUP=0"
if not exist "%VENV_PY%" (
    set "NEED_SETUP=1"
) else (
    "%VENV_PY%" -c "import sys" >nul 2>&1
    if errorlevel 1 (
        echo [Notice] .venv is invalid or was moved from another path.
        set "NEED_SETUP=1"
    )
)

if "!NEED_SETUP!"=="1" (
    echo [RakuTrans AI] Initializing environment...
    call "%SCRIPT_DIR%setup_env.bat"
    if errorlevel 1 (
        echo [Error] Setup failed.
        pause
        exit /b 1
    )
)

"%VENV_PY%" "%SCRIPT_DIR%main.py" %*
if errorlevel 1 (
    if "%~1"=="" (
        echo.
        echo Application exited with an error.
        pause
    )
)

