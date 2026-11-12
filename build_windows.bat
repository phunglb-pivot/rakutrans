@echo off
setlocal enabledelayedexpansion

REM ==============================================================================
REM Script to build standalone Windows Application (.exe) for RakuTrans AI
REM ==============================================================================

set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

echo =============================================
echo    Building RakuTrans AI for Windows (.exe)   
echo =============================================

set "VENV_PY=%SCRIPT_DIR%.venv\Scripts\python.exe"
set "PYINSTALLER=%SCRIPT_DIR%.venv\Scripts\pyinstaller.exe"

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
    echo [RakuTrans AI] Setting up environment first...
    call "%SCRIPT_DIR%setup_env.bat"
    if errorlevel 1 (
        echo [Error] Setup failed.
        pause
        exit /b 1
    )
)

if not exist "%PYINSTALLER%" (
    echo Installing PyInstaller into .venv...
    "%VENV_PY%" -m pip install -q pyinstaller
)

echo Cleaning previous builds...
if exist "build" rmdir /s /q build
if exist "dist" rmdir /s /q dist

echo Compiling standalone Windows executable...
"%PYINSTALLER%" --noconfirm --clean ^
    --name "RakuTrans" ^
    --icon "assets\icon.ico" ^
    --windowed ^
    --onedir ^
    --add-data "components;components" ^
    --add-data "assets;assets" ^
    --add-data "config.py;." ^
    --add-data "i18n.py;." ^
    --add-data "translation_cache.py;." ^
    --collect-all customtkinter ^
    --collect-all tkinterdnd2 ^
    --collect-all magika ^
    --collect-all markitdown ^
    --collect-all docx ^
    --collect-all pptx ^
    --collect-all google.genai ^
    --hidden-import sqlite3 ^
    --hidden-import tkinter ^
    main.py

if errorlevel 1 (
    echo.
    echo [Error] PyInstaller build failed.
    pause
    exit /b 1
)

echo.
echo =============================================
echo    Build completed successfully!
echo    Standalone executable created at:
echo    dist\RakuTrans\RakuTrans.exe
echo =============================================
pause
