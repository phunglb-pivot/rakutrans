@echo off
setlocal enabledelayedexpansion

REM ==============================================================================
REM Script to build standalone Windows Application (.exe) & Installer for RakuTrans AI
REM ==============================================================================

set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

set "NO_PAUSE=0"
if defined CI set "NO_PAUSE=1"
if "%RAKUTRANS_NO_PAUSE%"=="1" set "NO_PAUSE=1"
if /I "%~1"=="--ci" set "NO_PAUSE=1"
if /I "%~1"=="--no-pause" set "NO_PAUSE=1"

echo =============================================
echo    Building RakuTrans AI for Windows (.exe)
echo =============================================

set "VENV_PY=%SCRIPT_DIR%.venv\Scripts\python.exe"
set "PYINSTALLER=%SCRIPT_DIR%.venv\Scripts\pyinstaller.exe"

set "NEED_SETUP=0"
if not exist "%VENV_PY%" (
    set "NEED_SETUP=1"
) else (
    "%VENV_PY%" "%SCRIPT_DIR%check_env.py" >nul 2>&1
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
        call :maybe_pause
        exit /b 1
    )
)

if not exist "%PYINSTALLER%" (
    echo Installing PyInstaller into .venv...
    "%VENV_PY%" -m pip install -q pyinstaller
    if errorlevel 1 (
        echo [Error] Failed to install PyInstaller.
        call :maybe_pause
        exit /b 1
    )
)

for /f "delims=" %%V in ('call "%VENV_PY%" "%SCRIPT_DIR%check_env.py" --meta APP_VERSION') do set "APP_VERSION=%%V"
if not defined APP_VERSION (
    echo [Error] Failed to read APP_VERSION from config.py.
    call :maybe_pause
    exit /b 1
)
for /f "delims=" %%N in ('call "%VENV_PY%" "%SCRIPT_DIR%check_env.py" --meta APP_NAME') do set "APP_NAME=%%N"
if not defined APP_NAME (
    echo [Error] Failed to read APP_NAME from config.py.
    call :maybe_pause
    exit /b 1
)
for /f "delims=" %%E in ('call "%VENV_PY%" "%SCRIPT_DIR%check_env.py" --meta APP_EXECUTABLE_NAME') do set "APP_EXEC_NAME=%%E"
if not defined APP_EXEC_NAME (
    echo [Error] Failed to read APP_EXECUTABLE_NAME from config.py.
    call :maybe_pause
    exit /b 1
)

echo Cleaning previous builds...
tasklist /FI "IMAGENAME eq !APP_EXEC_NAME!.exe" 2>nul | find /I "!APP_EXEC_NAME!.exe" >nul
if not errorlevel 1 (
    echo [Notice] Closing running !APP_EXEC_NAME!.exe so dist\ can be replaced...
    taskkill /F /IM "!APP_EXEC_NAME!.exe" >nul 2>&1
    timeout /t 1 /nobreak >nul
)

if exist "build" rmdir /s /q build
if exist "build" (
    echo [Error] Cannot remove "build" directory because files inside it are locked.
    call :maybe_pause
    exit /b 1
)
if exist "dist" rmdir /s /q dist
if exist "dist\!APP_EXEC_NAME!" (
    echo.
    echo [Error] Cannot remove "dist\!APP_EXEC_NAME!" because a file inside it is locked by another process.
    echo         Please close !APP_EXEC_NAME!.exe, Explorer windows, or terminal tabs using "dist\!APP_EXEC_NAME!" and retry.
    call :maybe_pause
    exit /b 1
)

echo Compiling standalone Windows executable via RakuTrans.spec...
"%PYINSTALLER%" --noconfirm --clean "%SCRIPT_DIR%RakuTrans.spec"

if errorlevel 1 (
    echo.
    echo [Error] PyInstaller build failed.
    call :maybe_pause
    exit /b 1
)

set "ISCC_EXE="
if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC_EXE=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not defined ISCC_EXE if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC_EXE=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if not defined ISCC_EXE if exist "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" set "ISCC_EXE=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"

if defined ISCC_EXE (
    echo.
    echo Creating Windows installer with Inno Setup 6 ^(v!APP_VERSION!^)...
    "%ISCC_EXE%" "/DMyAppName=!APP_NAME!" "/DMyAppPublisher=!APP_NAME!" "/DMyAppVersion=!APP_VERSION!" "/DMyAppExecBase=!APP_EXEC_NAME!" "/DMyAppExeName=!APP_EXEC_NAME!.exe" "%SCRIPT_DIR%installer_windows.iss"
    if errorlevel 1 (
        echo.
        echo [Error] Inno Setup installer compilation failed.
        call :maybe_pause
        exit /b 1
    )
) else (
    echo.
    echo [Notice] Inno Setup 6 not found. Skipping Setup.exe creation.
    echo          Install from https://jrsoftware.org/isdl.php to build !APP_EXEC_NAME!-Installer-Windows.exe.
)

echo.
echo =============================================
echo    Build completed successfully!
echo    Standalone executable:
echo      dist\!APP_EXEC_NAME!\!APP_EXEC_NAME!.exe
if defined ISCC_EXE (
    echo    Windows installer:
    echo      dist\!APP_EXEC_NAME!-Installer-Windows.exe
)
echo =============================================
call :maybe_pause
goto :eof

:maybe_pause
if "%NO_PAUSE%"=="0" pause
goto :eof
