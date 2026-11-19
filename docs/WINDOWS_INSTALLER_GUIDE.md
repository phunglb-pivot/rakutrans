# Building a Windows Installer for RakuTrans AI with Inno Setup

This guide explains how to package the standalone PyInstaller output (`dist\RakuTrans\`) into a standard Windows installer (`RakuTrans-Installer-Windows.exe`) using **Inno Setup 6** and the included `packaging\installer_windows.iss` script.

---

## Why Use Inno Setup?

Running `packaging\build_windows.bat` creates a portable folder (`dist\RakuTrans\RakuTrans.exe` + `_internal\`) from `packaging\RakuTrans.spec` and, when Inno Setup 6 is installed, automatically wraps it into `dist\RakuTrans-Installer-Windows.exe` that:

- Installs RakuTrans AI into `%LOCALAPPDATA%\Programs\RakuTrans` (no Administrator privileges required) or system-wide if chosen.
- Creates **Start Menu** and optional **Desktop** shortcuts using `assets\icon.ico`.
- Registers the app in **Windows Settings -> Apps (Installed Apps)** with a clean uninstaller (`unins000.exe`).
- Automatically closes any running `RakuTrans.exe` instance during upgrades when `AppId` is preserved.

---

## Step 1: Install Inno Setup 6

1. Download the latest **Inno Setup 6** installer (`innosetup-6.x.x.exe`) from:
   https://jrsoftware.org/isdl.php
2. Run the installer with default options. Once installed, you get:
   - **Inno Setup Compiler** (GUI)
   - **`ISCC.exe`** (CLI compiler, typically located at `C:\Program Files (x86)\Inno Setup 6\ISCC.exe`, `C:\Program Files\Inno Setup 6\ISCC.exe`, or `%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe`)

---

## Step 2: Run the Automated Windows Build Script

Run from Command Prompt or double-click:

```bat
packaging\build_windows.bat
```

`packaging\build_windows.bat` automatically:
1. Sets up `.venv` with build dependencies via `scripts\setup_env.bat --with-build` if needed.
2. Compiles `dist\RakuTrans\RakuTrans.exe` + `_internal\` using the shared cross-platform `packaging\RakuTrans.spec`.
3. Reads `APP_VERSION` from `rakutrans\core\config.py` and runs `ISCC.exe /DMyAppVersion=<version> packaging\installer_windows.iss` (when Inno Setup 6 is installed) to output `dist\RakuTrans-Installer-Windows.exe`.

---

## Step 3: Manual Installer Compilation (Optional)

If you want to customize or compile `packaging\installer_windows.iss` directly after `dist\RakuTrans\` has been built:

### Option A: Using Inno Setup Compiler (GUI)
1. Open **Inno Setup Compiler**.
2. Click **File -> Open** and select `packaging\installer_windows.iss`.
3. Click **Build -> Compile** (or press `Ctrl+F9`).
4. The installer will be created at `dist\RakuTrans-Installer-Windows.exe`.

### Option B: Using the Command Line (`ISCC.exe`)
Run from the repository root:

```bat
"C:\Program Files (x86)\Inno Setup 6\ISCC.exe" /DMyAppVersion=1.0.0 packaging\installer_windows.iss
```

---

## Language & Customization Notes (`packaging\installer_windows.iss`)

- **Fixed `AppId`:** `{{8D4F2E1A-9C3B-4B7E-A21D-6F0C5E8A1B42}` must never be changed across releases so upgrades replace existing installations cleanly.
- **Clean upgrades (`[InstallDelete]`):** `packaging\installer_windows.iss` removes the previous `{app}\_internal` runtime directory and `RakuTrans.exe` before copying the new build, preventing stale DLLs/packages across version upgrades while keeping user settings (`~/.rakutrans/`) untouched.
- **Installer Languages:** `english` (`compiler:Default.isl`) and `japanese` (`compiler:Languages\Japanese.isl`) use Inno Setup 6's official built-in translations. If you want a Vietnamese wizard translation, place a community `Vietnamese.isl` file at `assets\Vietnamese.isl` — `packaging\installer_windows.iss` checks `#ifexist "..\assets\Vietnamese.isl"` and enables it automatically.
- **Version Sync:** Keep `APP_VERSION` in `rakutrans\core\config.py` updated for each release; `packaging\build_windows.bat` injects it via `/DMyAppVersion=...` without needing manual edits to `packaging\installer_windows.iss`.
- **Always keep `recursesubdirs createallsubdirs` in `[Files]`:** PyInstaller `--onedir` places Python DLLs, `assets/`, and bundled libraries inside `dist\RakuTrans\_internal\`.
- **Windows SmartScreen warning:** Unsigned installers may trigger a SmartScreen prompt (*More info -> Run anyway*) on first launch unless signed with a Code Signing Certificate.
