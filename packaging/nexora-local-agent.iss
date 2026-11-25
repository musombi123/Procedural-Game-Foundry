#define MyAppName "NEXORA Local Agent"
#ifndef MyAppVersion
  #define MyAppVersion "1.0.0"
#endif
#define MyAppPublisher "RevelaCode"
#define MyAppExeName "NEXORA.LocalAgent.exe"

[Setup]
AppId={{7A8EB9D5-BB0B-4E2A-A2DA-6E7FC4DAA801}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\NEXORA\Local Agent
DefaultGroupName=NEXORA
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64
OutputDir=..\artifacts\windows
OutputBaseFilename=NEXORA-Local-Agent-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\{#MyAppExeName}
CloseApplications=yes
RestartApplications=no
SetupLogging=yes

[Dirs]
Name: "{localappdata}\NEXORA\Agent"
Name: "{localappdata}\NEXORA\Agent\logs"
Name: "{localappdata}\NEXORA\Foundry"

[Files]
Source: "..\dist\NEXORA.LocalAgent\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\NEXORA Local Agent"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"
Name: "{userstartup}\NEXORA Local Agent"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Start NEXORA Local Agent now"; Flags: postinstall nowait

[UninstallRun]
Filename: "{sys}\taskkill.exe"; Parameters: "/IM {#MyAppExeName} /T /F"; Flags: runhidden; RunOnceId: "StopNexoraLocalAgent"

[UninstallDelete]
Type: filesandordirs; Name: "{app}"
