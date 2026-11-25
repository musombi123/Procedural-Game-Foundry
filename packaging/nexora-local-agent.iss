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
Filename: "{app}\{#MyAppExeName}"; Flags: runhidden nowait

[UninstallRun]
Filename: "{sys}\schtasks.exe"; Parameters: "/Delete /TN ""NEXORA Local Agent"" /F"; Flags: runhidden; RunOnceId: "RemoveNexoraLocalAgentTask"
Filename: "{sys}\taskkill.exe"; Parameters: "/IM {#MyAppExeName} /T /F"; Flags: runhidden; RunOnceId: "StopNexoraLocalAgent"

[UninstallDelete]
Type: filesandordirs; Name: "{app}"

[Code]
procedure RegisterManagedAgentTask;
var
  AgentPath: String;
  ResultCode: Integer;
  Parameters: String;
begin
  AgentPath := ExpandConstant('{app}\\{#MyAppExeName}');

  { The Startup shortcut starts the agent as soon as the user signs in.
    This one-minute task is a lightweight supervisor: if the agent has
    crashed, it starts it again. The executable's named mutex exits
    immediately when an instance is already running. /IT keeps this
    user-scoped task inside the signed-in interactive session. }
  Parameters :=
    '/Create /SC MINUTE /MO 1 /TN "NEXORA Local Agent" /TR "' +
    AgentPath +
    '" /RL LIMITED /IT /F';

  if Exec(ExpandConstant('{sys}\\schtasks.exe'), Parameters, '',
    SW_HIDE, ewWaitUntilTerminated, ResultCode) and (ResultCode = 0) then
  begin
    Log('NEXORA Local Agent per-user supervisor task registered (every minute; single-instance mutex prevents duplicate workers).');
    Exec(ExpandConstant('{sys}\\schtasks.exe'),
      '/Run /TN "NEXORA Local Agent"', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  end
  else
  begin
    Log(Format('NEXORA Local Agent supervisor task was not registered (schtasks exit %d). The per-user Startup shortcut remains the sign-in fallback.',
      [ResultCode]));
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
    RegisterManagedAgentTask;
end;
