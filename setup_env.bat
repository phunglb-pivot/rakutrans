@echo off
setlocal enabledelayedexpansion

REM ==============================================================================
REM RakuTrans AI - Environment Setup & Self-Healing Script (Windows)
REM ==============================================================================
REM Detects Python 3.10+ across py launcher, PATH, and standard install paths
REM (prioritizing Tkinter support), heals/rebuilds broken virtual environments,
REM and installs all required dependencies.
REM
REM Optional flags / overrides:
REM   setup_env.bat --with-build          (also installs PyInstaller)
REM   set RAKUTRANS_PYTHON=C:\Path\To\python.exe
REM ==============================================================================

set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

set "NO_PAUSE=0"
if defined CI set "NO_PAUSE=1"
if "%RAKUTRANS_NO_PAUSE%"=="1" set "NO_PAUSE=1"

set "WITH_BUILD=0"
if /I "%~1"=="--with-build" set "WITH_BUILD=1"
if /I "%~2"=="--with-build" set "WITH_BUILD=1"
if /I "%~1"=="--no-pause" set "NO_PAUSE=1"
if /I "%~2"=="--no-pause" set "NO_PAUSE=1"
if "%RAKUTRANS_WITH_BUILD%"=="1" set "WITH_BUILD=1"

echo =============================================
echo    RakuTrans AI - Environment Setup (Windows)
echo =============================================

set "PY_EXE="
set "PY_ARGS="
set "FALLBACK_EXE="
set "FALLBACK_ARG="
set "OVERRIDE_PY=%RAKUTRANS_PYTHON%"
if defined OVERRIDE_PY set "OVERRIDE_PY=%OVERRIDE_PY:"=%"

if defined OVERRIDE_PY (
    "%OVERRIDE_PY%" -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
    if errorlevel 1 (
        echo.
        echo [Error] Specified RAKUTRANS_PYTHON "%OVERRIDE_PY%" was not found or is ^< 3.10.
        if "%NO_PAUSE%"=="0" pause
        exit /b 1
    )
    set "PY_EXE=%OVERRIDE_PY%"
    set "PY_ARGS="
    goto :found_python
)

REM 1. Detect Python 3.10+ (preferring interpreters with Tkinter support)
for %%P in ("py -3.12" "py -3.11" "py -3.13" "py -3.10" "py -3.14" "py -3" "py" "python" "python3") do (
    if not defined PY_EXE (
        call :check_cmd %%~P
    )
)

REM Also check standard per-user and system-wide Python install directories
if not defined PY_EXE (
    for %%D in (Python312 Python311 Python313 Python310 Python314) do (
        if not defined PY_EXE (
            if exist "%LocalAppData%\Programs\Python\%%D\python.exe" (
                call :check_cmd "%LocalAppData%\Programs\Python\%%D\python.exe"
            )
        )
        if not defined PY_EXE (
            if exist "%ProgramFiles%\%%D\python.exe" (
                call :check_cmd "%ProgramFiles%\%%D\python.exe"
            )
        )
    )
)

if not defined PY_EXE (
    if defined FALLBACK_EXE (
        set "PY_EXE=!FALLBACK_EXE!"
        set "PY_ARGS=!FALLBACK_ARG!"
    )
)

:found_python
if not defined PY_EXE (
    echo.
    echo [Error] Python 3.10 or higher is required.
    echo Please install Python from https://www.python.org/downloads/
    echo Make sure to check "Add python.exe to PATH" during installation.
    echo.
    echo Tip: If Python 3.10+ is installed in a custom location, set:
    echo   set RAKUTRANS_PYTHON=C:\Path\To\python.exe
    echo.
    if "%NO_PAUSE%"=="0" pause
    exit /b 1
)

for /f "delims=" %%V in ('""!PY_EXE!" !PY_ARGS! -c "import sys; print(chr(46).join(map(str, sys.version_info[:3])))"" 2^>nul') do set "PY_VER=%%V"
echo Found Python: !PY_EXE! !PY_ARGS! (!PY_VER!)

REM 2. Check virtual environment integrity
set "VENV_DIR=%SCRIPT_DIR%.venv"
set "VENV_PY=%VENV_DIR%\Scripts\python.exe"
set "RECREATE_VENV=0"

if exist "%VENV_DIR%" (
    if not exist "%VENV_PY%" (
        echo [Notice] Existing .venv is incomplete or invalid.
        set "RECREATE_VENV=1"
    ) else (
        "%VENV_PY%" -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
        if errorlevel 1 (
            echo [Notice] Existing .venv is ^< 3.10, was moved from another path, or is corrupted.
            set "RECREATE_VENV=1"
        ) else if defined OVERRIDE_PY (
            for /f "delims=" %%V in ('""%VENV_PY%" -c "import sys; print(chr(46).join(map(str, sys.version_info[:3])))"" 2^>nul') do set "VENV_VER=%%V"
            if not "!VENV_VER!"=="!PY_VER!" (
                echo [Notice] Rebuilding .venv to match requested Python !PY_VER! ^(was !VENV_VER!^)...
                set "RECREATE_VENV=1"
            )
        ) else (
            "%VENV_PY%" -c "import tkinter" >nul 2>&1
            if errorlevel 1 (
                "!PY_EXE!" !PY_ARGS! -c "import tkinter" >nul 2>&1
                if not errorlevel 1 (
                    echo [Notice] Upgrading .venv to use Python !PY_VER! with Tkinter support...
                    set "RECREATE_VENV=1"
                )
            )
        )
    )
) else (
    set "RECREATE_VENV=1"
)

if "!RECREATE_VENV!"=="1" (
    echo Recreating clean virtual environment at %VENV_DIR%...
    if exist "%VENV_DIR%" rmdir /s /q "%VENV_DIR%"
    if exist "%VENV_DIR%" (
        echo.
        echo [Error] Failed to remove existing "%VENV_DIR%" because a file inside it is in use.
        echo         Close open terminals, IDE interpreters, or RakuTrans windows using .venv and retry.
        if "%NO_PAUSE%"=="0" pause
        exit /b 1
    )
    "!PY_EXE!" !PY_ARGS! -m venv "%VENV_DIR%"
    if errorlevel 1 (
        echo [Error] Failed to create virtual environment.
        if "%NO_PAUSE%"=="0" pause
        exit /b 1
    )
)

REM 3. Install / update packages
echo Upgrading pip...
"%VENV_PY%" -m pip install -q --upgrade pip

if exist "%SCRIPT_DIR%requirements.txt" (
    echo Installing application dependencies...
    "%VENV_PY%" -m pip install -q -r "%SCRIPT_DIR%requirements.txt"
    if errorlevel 1 (
        echo [Error] Failed to install dependencies.
        if "%NO_PAUSE%"=="0" pause
        exit /b 1
    )
    "%VENV_PY%" "%SCRIPT_DIR%check_env.py" --write-stamp
)

if "!WITH_BUILD!"=="1" (
    echo Installing PyInstaller...
    "%VENV_PY%" -m pip install -q pyinstaller
    if errorlevel 1 (
        echo [Error] Failed to install PyInstaller.
        if "%NO_PAUSE%"=="0" pause
        exit /b 1
    )
)

REM 4. Validate readiness
echo.
"%VENV_PY%" -c "import tkinter" >nul 2>&1
if not errorlevel 1 (
    echo [OK] Environment is ready! ^(GUI and CLI supported^)
) else (
    echo [Warning] Tkinter is not found in this environment ^(!PY_VER!^). GUI may not start.
)

echo =============================================
echo Setup complete! Launch with: run_windows.bat
echo =============================================
goto :eof

:check_cmd
if "%~1"=="" goto :eof
"%~1" %~2 -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
if errorlevel 1 goto :eof
if not defined FALLBACK_EXE (
    set "FALLBACK_EXE=%~1"
    set "FALLBACK_ARG=%~2"
)
"%~1" %~2 -c "import tkinter" >nul 2>&1
if not errorlevel 1 (
    set "PY_EXE=%~1"
    set "PY_ARGS=%~2"
)
goto :eof
