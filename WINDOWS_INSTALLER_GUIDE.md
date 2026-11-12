# Building a Windows Installer for RakuTrans AI with Inno Setup

This guide explains how to package the standalone PyInstaller output (`dist\RakuTrans\`) into a standard Windows installer (`RakuTrans-Installer-Windows.exe`) using **Inno Setup 6**.

---

## Why Use Inno Setup?

Running `build_windows.bat` creates a portable folder (`dist\RakuTrans\RakuTrans.exe` + `_internal\`). Wrapping that folder with **Inno Setup** produces a single installer executable that:

- Installs RakuTrans AI into `%LOCALAPPDATA%\Programs\RakuTrans` (no Administrator privileges required) or system-wide if chosen.
- Creates **Start Menu** and optional **Desktop** shortcuts using `assets\icon.ico`.
- Registers the app in **Windows Settings → Apps (Installed Apps)** with a clean uninstaller (`unins000.exe`).
- Automatically closes any running `RakuTrans.exe` instance during upgrades when `AppId` is preserved.

---

## Step 1: Install Inno Setup 6

1. Download the latest **Inno Setup 6** installer (`innosetup-6.x.x.exe`) from:
   https://jrsoftware.org/isdl.php
2. Run the installer with default options. Once installed, you get:
   - **Inno Setup Compiler** (GUI)
   - **`ISCC.exe`** (CLI compiler, typically located at `C:\Program Files (x86)\Inno Setup 6\ISCC.exe`)

---

## Step 2: Build the Standalone App First

Before compiling the installer, generate the PyInstaller `--onedir` bundle by running:

```bat
build_windows.bat
```

Verify that `dist\RakuTrans\RakuTrans.exe` and `dist\RakuTrans\_internal\` exist.

---

## Step 3: Create the Inno Setup Script (`installer_windows.iss`)

Create a file named `installer_windows.iss` in the project root with the following configuration:

> **Important:** Generate a unique GUID once (in Inno Setup Compiler: **Tools → Generate GUID**) and **never change `AppId` across future versions**. Keeping the same `AppId` ensures Windows upgrades existing installations cleanly instead of creating duplicate entries in *Installed Apps*. Note the double opening brace `{{` required by Inno Setup to escape `{`.

```ini
; ==============================================================================
; RakuTrans AI - Inno Setup 6 Script
; ==============================================================================

#define MyAppName "RakuTrans AI"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "RakuTrans AI"
#define MyAppExeName "RakuTrans.exe"

[Setup]
; Keep this GUID fixed across all future releases!
AppId={{8D4F2E1A-9C3B-4B7E-A21D-6F0C5E8A1B42}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\RakuTrans
DefaultGroupName={#MyAppName}
AllowNoIcons=yes

; Per-user install by default (%LOCALAPPDATA%\Programs\RakuTrans) — no UAC prompt needed
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog

; Output installer path & filename
OutputDir=dist
OutputBaseFilename=RakuTrans-Installer-Windows

; Icons & UI style
SetupIconFile=assets\icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
WizardStyle=modern
Compression=lzma2
SolidCompression=yes

; Close running RakuTrans.exe automatically during upgrade/uninstall
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "japanese"; MessagesFile: "compiler:Languages\Japanese.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; Copy the entire PyInstaller --onedir output including _internal\
Source: "dist\RakuTrans\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
```

---

## Step 4: Compile the Installer

You can compile `installer_windows.iss` either via the GUI or from the command line.

### Option A: Using Inno Setup Compiler (GUI)
1. Open **Inno Setup Compiler**.
2. Click **File → Open** and select `installer_windows.iss`.
3. Click **Build → Compile** (or press `Ctrl+F9`).
4. The installer will be created at `dist\RakuTrans-Installer-Windows.exe`.

### Option B: Using the Command Line (`ISCC.exe`)
Run in Command Prompt or PowerShell from the repository root:

```bat
"C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer_windows.iss
```

---

## Step 5 (Optional): Automate Inside `build_windows.bat`

To make `build_windows.bat` automatically produce the installer after PyInstaller finishes (mirroring `.dmg` creation in `build_macos.sh`), add the following snippet after the PyInstaller step:

```bat
set "ISCC_EXE="
if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC_EXE=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not defined ISCC_EXE if exist "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" set "ISCC_EXE=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"

if defined ISCC_EXE (
    echo Creating Windows installer with Inno Setup...
    "%ISCC_EXE%" "%SCRIPT_DIR%installer_windows.iss"
) else (
    echo [Notice] Inno Setup 6 not found. Skipping installer creation.
    echo          Install from https://jrsoftware.org/isdl.php to build Setup.exe.
)
```

---

## Key Gotchas & Best Practices

1. **Always include `recursesubdirs createallsubdirs` in `[Files]`:** PyInstaller `--onedir` places Python DLLs, `assets/`, and `components/` inside `dist\RakuTrans\_internal\`. Omitting `recursesubdirs` will break the installed app.
2. **Never change `AppId` between releases:** Changing the GUID causes Windows to treat new versions as separate applications.
3. **Update `MyAppVersion` on each release:** Bump `#define MyAppVersion` before compiling so *Installed Apps* displays the accurate version.
4. **Windows SmartScreen warning:** Unsigned installers downloaded from the internet may trigger a SmartScreen prompt (*More info → Run anyway*) on first launch unless signed with a Code Signing Certificate.

