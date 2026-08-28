; Inno Setup script for DMXReplay's Windows installer.
; Produces DMXReplay-Setup.exe: Install -> Start Menu/Desktop shortcut ->
; double-click DMXReplay -> GUI opens. No Python, terminal, or CLI required
; by the end user (docs/DEMO_MODE.md SS6).
;
; UNVERIFIED IN CI/dev sandbox: written without access to a real Windows
; machine or Inno Setup itself (see docs/BUILD_AND_DISTRIBUTION.md). This
; is standard, widely-used Inno Setup syntax (https://jrsoftware.org/ishelp/),
; not project-specific guesswork -- but has not been compiled with ISCC.exe
; here. Compile with:
;   "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" packaging\windows\dmxreplay.iss
; after packaging\build_windows.ps1 has produced dist\DMXReplay\,
; dist\DMXReplay Player\, and dist\DMXReplay Recorder\ (this script expects
; all three onedir folders to already exist under ..\..\dist relative to
; this file).

#define MyAppName "DMXReplay"
#define MyAppVersion "0.1.0"
#define MyAppPublisher "DMXReplay"
#define MyAppExeName "DMXReplay.exe"
#define DistDir "..\..\dist"

[Setup]
AppId={{64FED2EC-3AE8-470A-8843-0E36D553F43E}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
; No admin rights required -- installs to the current user's AppData by
; default via {autopf}'s per-user resolution when run without elevation;
; Inno Setup handles the elevation prompt itself if the user picks an
; all-users location instead. Not forcing admin keeps "just install it" as
; simple as possible for a single-user desktop app.
PrivilegesRequired=lowest
OutputDir={#DistDir}
OutputBaseFilename=DMXReplay-Setup
Compression=lzma
SolidCompression=yes
WizardStyle=modern
; Not code-signed here -- see docs/BUILD_AND_DISTRIBUTION.md's open items
; (same caveat as macOS notarization/signing). An unsigned installer will
; trigger a Windows SmartScreen warning until it accrues enough reputation
; or is signed with a real certificate.

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Files]
; The primary app -- the Welcome launcher (docs/DEMO_MODE.md SS6) that opens
; Player/Recorder itself. This is what most users should run.
Source: "{#DistDir}\DMXReplay\*"; DestDir: "{app}\DMXReplay"; Flags: ignoreversion recursesubdirs createallsubdirs
; Player/Recorder directly, for anyone who wants one without the launcher.
Source: "{#DistDir}\DMXReplay Player\*"; DestDir: "{app}\DMXReplay Player"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#DistDir}\DMXReplay Recorder\*"; DestDir: "{app}\DMXReplay Recorder"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\DMXReplay\{#MyAppExeName}"
Name: "{group}\DMXReplay Player"; Filename: "{app}\DMXReplay Player\DMXReplay Player.exe"
Name: "{group}\DMXReplay Recorder"; Filename: "{app}\DMXReplay Recorder\DMXReplay Recorder.exe"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\DMXReplay\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\DMXReplay\{#MyAppExeName}"; Description: "Launch {#MyAppName} now"; Flags: nowait postinstall skipifsilent
