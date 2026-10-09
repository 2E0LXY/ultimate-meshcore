; Ultimate MeshCore Desktop - Windows installer (Inno Setup 6)
; Built by build.py --installer; AppVersion and SourceDir are passed on the command line.

#ifndef AppVersion
  #define AppVersion "0.1.0"
#endif
#ifndef SourceDir
  #define SourceDir "..\dist\UltimateMeshCoreDesktop"
#endif
#ifndef OutputDir
  #define OutputDir "..\dist"
#endif

[Setup]
AppId={{6B0F3C52-2E0A-4C1B-9D6E-2E0A1C0D5A11}
AppName=Ultimate MeshCore Desktop
AppVersion={#AppVersion}
AppVerName=Ultimate MeshCore Desktop {#AppVersion}
AppPublisher=Daren Loxley 2E0LXY
AppPublisherURL=https://github.com/2E0LXY/ultimate-meshcore
AppSupportURL=https://github.com/2E0LXY/ultimate-meshcore/blob/main/docs/umc/MANUAL.md
AppUpdatesURL=https://github.com/2E0LXY/ultimate-meshcore/releases/tag/desktop-latest
AppCopyright=Daren Loxley 2E0LXY
VersionInfoCompany=Daren Loxley 2E0LXY
VersionInfoDescription=Ultimate MeshCore Desktop installer
DefaultDirName={autopf}\Ultimate MeshCore Desktop
DefaultGroupName=Ultimate MeshCore Desktop
DisableProgramGroupPage=yes
; installs for the current user without admin rights; "Install for all users" is offered too
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir={#OutputDir}
OutputBaseFilename=UltimateMeshCoreDesktop-Setup
SetupIconFile=..\icon.ico
UninstallDisplayIcon={app}\UltimateMeshCoreDesktop.exe
UninstallDisplayName=Ultimate MeshCore Desktop
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=force
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Ultimate MeshCore Desktop"; Filename: "{app}\UltimateMeshCoreDesktop.exe"
Name: "{group}\Uninstall Ultimate MeshCore Desktop"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Ultimate MeshCore Desktop"; Filename: "{app}\UltimateMeshCoreDesktop.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\UltimateMeshCoreDesktop.exe"; Description: "{cm:LaunchProgram,Ultimate MeshCore Desktop}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{sys}\taskkill.exe"; Parameters: "/F /IM UltimateMeshCoreDesktop.exe"; Flags: runhidden; RunOnceId: "StopApp"
