#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif

#define ProductName "NEXORA Local Agent"
#define PayloadDir "build\agent-payload"

[Setup]
AppId={{C41D6D5A-1C04-4BA6-BF33-7DDBF64A23C8}
AppName={#ProductName}
AppVersion={#AppVersion}
AppPublisher=NEXORA Interactive Studios
DefaultDirName={localappdata}\Programs\NEXORA\Local Agent
DefaultGroupName=NEXORA
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
OutputDir=dist
OutputBaseFilename=NEXORA-Local-Agent-Setup
SetupLogging=yes
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no
Uninstallable=yes
UninstallDisplayName={#ProductName}
VersionInfoCompany=NEXORA Interactive Studios
VersionInfoDescription=NEXORA local compute companion
VersionInfoProductName={#ProductName}
VersionInfoProductVersion={#AppVersion}
VersionInfoVersion={#AppVersion}.0

[Tasks]
Name: "startonlogin"; Description: "Start NEXORA automatically when I sign in to Windows"; GroupDescription: "Startup options:"; Flags: checkedonce

[Files]
Source: "{#PayloadDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "NEXORA Local Agent"; ValueData: """{sys}\wscript.exe"" ""{app}\StartNexoraLocalAgent.vbs"""; Tasks: startonlogin; Flags: uninsdeletevalue

[Icons]
Name: "{group}\NEXORA Local Agent"; Filename: "{sys}\wscript.exe"; Parameters: """{app}\StartNexoraLocalAgent.vbs"""
Name: "{group}\Uninstall NEXORA Local Agent"; Filename: "{uninstallexe}"

[Run]
Filename: "{sys}\wscript.exe"; Parameters: """{app}\StartNexoraLocalAgent.vbs"""; Description: "Start NEXORA Local Agent now"; Flags: postinstall runhidden skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}"
