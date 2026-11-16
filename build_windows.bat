@echo off
setlocal enabledelayedexpansion

REM ==============================================================================
REM Script to build standalone Windows Application (.exe) & Installer for RakuTrans AI
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
    "%VENV_PY%" -c "import hashlib, pathlib, sys, customtkinter, tkinterdnd2, PIL, openpyxl, docx, pptx, fitz, pypdf, pdf2docx, reportlab, charset_normalizer; req = pathlib.Path('requirements.txt'); stamp = pathlib.Path('.venv/.req_stamp'); ok_stamp = (not req.exists()) or (stamp.exists() and stamp.read_text().strip() == hashlib.sha256(req.read_bytes()).hexdigest()); sys.exit(0 if (sys.version_info >= (3, 10) and ok_stamp) else 1)" >nul 2>&1
    if errorlevel 1 (
        echo [Notice] .venv is invalid, incomplete, or requirements.txt changed.
        set "NEED_SETUP=1"
    )
)

if "!NEED_SETUP!"=="1" (
    echo [RakuTrans AI] Setting up environment first...
    call "%SCRIPT_DIR%setup_env.bat" --with-build
    if errorlevel 1 (
        echo [Error] Setup failed.
        pause
        exit /b 1
    )
)

if not exist "%PYINSTALLER%" (
    echo Installing PyInstaller into .venv...
    "%VENV_PY%" -m pip install -q pyinstaller
    if errorlevel 1 (
        echo [Error] Failed to install PyInstaller.
        pause
        exit /b 1
    )
)

echo Cleaning previous builds...
tasklist /FI "IMAGENAME eq RakuTrans.exe" 2>nul | find /I "RakuTrans.exe" >nul
if not errorlevel 1 (
    echo [Notice] Closing running RakuTrans.exe so dist\ can be replaced...
    taskkill /F /IM RakuTrans.exe >nul 2>&1
    timeout /t 1 /nobreak >nul
)

if exist "build" rmdir /s /q build
if exist "build" (
    echo [Error] Cannot remove "build" directory because files inside it are locked.
    pause
    exit /b 1
)
if exist "dist" rmdir /s /q dist
if exist "dist\RakuTrans" (
    echo.
    echo [Error] Cannot remove "dist\RakuTrans" because a file inside it is locked by another process.
    echo         Please close RakuTrans.exe, Explorer windows, or terminal tabs using "dist\RakuTrans" and retry.
    pause
    exit /b 1
)

echo Compiling standalone Windows executable via RakuTrans.spec...
"%PYINSTALLER%" --noconfirm --clean "%SCRIPT_DIR%RakuTrans.spec"

if errorlevel 1 (
    echo.
    echo [Error] PyInstaller build failed.
    pause
    exit /b 1
)

for /f "delims=" %%V in ('"%VENV_PY%" -c "import config; print(config.APP_VERSION)" 2^>nul') do set "APP_VERSION=%%V"
if not defined APP_VERSION set "APP_VERSION=1.0.0"

set "ISCC_EXE="
if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC_EXE=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not defined ISCC_EXE if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC_EXE=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if not defined ISCC_EXE if exist "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" set "ISCC_EXE=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"

if defined ISCC_EXE (
    echo.
    echo Creating Windows installer with Inno Setup 6 ^(v!APP_VERSION!^)...
    "%ISCC_EXE%" "/DMyAppVersion=!APP_VERSION!" "%SCRIPT_DIR%installer_windows.iss"
    if errorlevel 1 (
        echo.
        echo [Error] Inno Setup installer compilation failed.
        pause
        exit /b 1
    )
) else (
    echo.
    echo [Notice] Inno Setup 6 not found. Skipping Setup.exe creation.
    echo          Install from https://jrsoftware.org/isdl.php to build RakuTrans-Installer-Windows.exe.
)

echo.
echo =============================================
echo    Build completed successfully!
echo    Standalone executable:
echo      dist\RakuTrans\RakuTrans.exe
if defined ISCC_EXE (
    echo    Windows installer:
    echo      dist\RakuTrans-Installer-Windows.exe
)
echo =============================================
pause
