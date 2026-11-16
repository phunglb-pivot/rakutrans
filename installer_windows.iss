; ==============================================================================
; RakuTrans AI - Inno Setup 6 Script
; ==============================================================================

#ifndef MyAppVersion
  #define MyAppVersion "1.0.0"
#endif

#define MyAppName "RakuTrans AI"
#define MyAppPublisher "RakuTrans AI"
#define MyAppExeName "RakuTrans.exe"

[Setup]
; Keep this GUID fixed across all future releases!
AppId={{8D4F2E1A-9C3B-4B7E-A21D-6F0C5E8A1B42}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
VersionInfoVersion={#MyAppVersion}
DefaultDirName={autopf}\RakuTrans
DefaultGroupName={#MyAppName}
AllowNoIcons=yes

; Per-user install by default (%LOCALAPPDATA%\Programs\RakuTrans) - no UAC prompt needed
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
#ifexist "assets\Vietnamese.isl"
Name: "vietnamese"; MessagesFile: "assets\Vietnamese.isl"
#endif

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[InstallDelete]
; Clean stale PyInstaller runtime files from previous releases while keeping user data (~/.rakutrans) untouched
Type: filesandordirs; Name: "{app}\_internal"
Type: files; Name: "{app}\{#MyAppExeName}"

[Files]
; Copy the entire PyInstaller --onedir output including _internal\
Source: "dist\RakuTrans\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
