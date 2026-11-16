@echo off
setlocal enabledelayedexpansion

REM ==============================================================================
REM RakuTrans AI - Environment Setup & Self-Healing Script (Windows)
REM ==============================================================================
REM Detects Python 3.10+ across py launcher, PATH, and standard install paths
REM (prioritizing Tkinter support), heals/rebuilds broken virtual environments,
REM and installs all required dependencies.
REM
REM Optional override:
REM   set RAKUTRANS_PYTHON=C:\Path\To\python.exe
REM   setup_env.bat
REM ==============================================================================

set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

echo =============================================
echo    RakuTrans AI - Environment Setup (Windows)
echo =============================================

set "PY_CMD="
set "FALLBACK_PY="
set "OVERRIDE_PY=%RAKUTRANS_PYTHON%"

if defined OVERRIDE_PY (
    "%OVERRIDE_PY%" -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
    if errorlevel 1 (
        echo.
        echo [Error] Specified RAKUTRANS_PYTHON "%OVERRIDE_PY%" was not found or is ^< 3.10.
        pause
        exit /b 1
    )
    set "PY_CMD="%OVERRIDE_PY%""
    goto :found_python
)

REM 1. Detect Python 3.10+ (preferring interpreters with Tkinter support)
for %%P in ("py -3.12" "py -3.11" "py -3.13" "py -3.10" "py -3.14" "py -3" "py" "python" "python3") do (
    if not defined PY_CMD (
        call :check_cmd %%~P
    )
)

REM Also check standard per-user / system Python install directories if still needed
if not defined PY_CMD (
    for %%D in (Python312 Python311 Python313 Python310 Python314) do (
        if not defined PY_CMD (
            if exist "%LocalAppData%\Programs\Python\%%D\python.exe" (
                call :check_exe "%LocalAppData%\Programs\Python\%%D\python.exe"
            )
        )
    )
)

if not defined PY_CMD (
    if defined FALLBACK_PY (
        set "PY_CMD=!FALLBACK_PY!"
    )
)

:found_python
if not defined PY_CMD (
    echo.
    echo [Error] Python 3.10 or higher is required.
    echo Please install Python from https://www.python.org/downloads/
    echo Make sure to check "Add python.exe to PATH" during installation.
    echo.
    echo Tip: If Python 3.10+ is installed in a custom location, set:
    echo   set RAKUTRANS_PYTHON=C:\Path\To\python.exe
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
        "%VENV_PY%" -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
        if errorlevel 1 (
            echo [Notice] Existing .venv is ^< 3.10, was moved from another path, or is corrupted.
            set "RECREATE_VENV=1"
        ) else if defined OVERRIDE_PY (
            for /f "delims=" %%V in ('"%VENV_PY%" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')" 2^>nul') do set "VENV_VER=%%V"
            if not "!VENV_VER!"=="!PY_VER!" (
                echo [Notice] Rebuilding .venv to match requested Python !PY_VER! ^(was !VENV_VER!^)...
                set "RECREATE_VENV=1"
            )
        ) else (
            "%VENV_PY%" -c "import tkinter" >nul 2>&1
            if errorlevel 1 (
                !PY_CMD! -c "import tkinter" >nul 2>&1
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
    echo [OK] Environment is ready! ^(GUI and CLI supported^)
) else (
    echo [Warning] Tkinter is not found in this environment ^(!PY_VER!^). GUI may not start.
)

echo =============================================
echo Setup complete! Launch with: run_windows.bat
echo =============================================
goto :eof

:check_cmd
set "CAND=%*"
%CAND% -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
if errorlevel 1 goto :eof
if not defined FALLBACK_PY set "FALLBACK_PY=%CAND%"
%CAND% -c "import tkinter" >nul 2>&1
if not errorlevel 1 set "PY_CMD=%CAND%"
goto :eof

:check_exe
set "CAND=%~1"
"%CAND%" -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
if errorlevel 1 goto :eof
if not defined FALLBACK_PY set "FALLBACK_PY="%CAND%""
"%CAND%" -c "import tkinter" >nul 2>&1
if not errorlevel 1 set "PY_CMD="%CAND%""
goto :eof
