@echo off
REM Script to build standalone Windows Application (.exe) for RakuTrans AI
echo =============================================
echo    Building RakuTrans AI for Windows (.exe)   
echo =============================================

if not exist ".venv\Scripts\pyinstaller.exe" (
    echo Installing PyInstaller into .venv...
    .venv\Scripts\pip install pyinstaller
)

echo Cleaning previous builds...
if exist "build" rmdir /s /q build
if exist "dist" rmdir /s /q dist

echo Compiling standalone Windows executable...
.venv\Scripts\pyinstaller.exe --noconfirm --clean ^
    --name "RakuTrans" ^
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

echo.
echo =============================================
echo    Build completed successfully!
echo    Standalone executable created at:
echo    dist\RakuTrans\RakuTrans.exe
echo =============================================
pause
