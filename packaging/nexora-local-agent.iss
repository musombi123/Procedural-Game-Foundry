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
Source: "NEXORA-Local-Agent-Task.xml"; Flags: dontcopy

[Icons]
Name: "{group}\NEXORA Local Agent"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"
Name: "{userstartup}\NEXORA Local Agent"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Start NEXORA Local Agent now"; Flags: postinstall nowait

[UninstallRun]
Filename: "{sys}\schtasks.exe"; Parameters: "/Delete /TN ""NEXORA Local Agent"" /F"; Flags: runhidden; RunOnceId: "RemoveNexoraLocalAgentTask"
Filename: "{sys}\taskkill.exe"; Parameters: "/IM {#MyAppExeName} /T /F"; Flags: runhidden; RunOnceId: "StopNexoraLocalAgent"

[UninstallDelete]
Type: filesandordirs; Name: "{app}"

[Code]
function XmlEscape(const Value: String): String;
begin
  Result := Value;
  StringChangeEx(Result, '&', '&amp;', True);
  StringChangeEx(Result, '<', '&lt;', True);
  StringChangeEx(Result, '>', '&gt;', True);
end;

procedure RegisterManagedAgentTask;
var
  TaskTemplate, TaskFile, AgentPath, AgentDirectory, UserId: String;
  ResultCode: Integer;
begin
  ExtractTemporaryFile('NEXORA-Local-Agent-Task.xml');
  if not LoadStringFromFile(ExpandConstant('{tmp}\NEXORA-Local-Agent-Task.xml'), TaskTemplate) then
  begin
    Log('NEXORA scheduled-task template could not be loaded; Startup shortcut will be used.');
    exit;
  end;

  AgentPath := ExpandConstant('{app}\{#MyAppExeName}');
  AgentDirectory := ExpandConstant('{app}');
  UserId := GetUserNameString();

  StringChangeEx(TaskTemplate, '__USER_ID__', XmlEscape(UserId), True);
  StringChangeEx(TaskTemplate, '__AGENT_PATH__', XmlEscape(AgentPath), True);
  StringChangeEx(TaskTemplate, '__AGENT_WORKING_DIRECTORY__', XmlEscape(AgentDirectory), True);

  TaskFile := ExpandConstant('{tmp}\NEXORA-Local-Agent-Task.ready.xml');
  if not SaveStringToFile(TaskFile, TaskTemplate, False) then
  begin
    Log('NEXORA scheduled-task definition could not be written; Startup shortcut will be used.');
    exit;
  end;

  if Exec(ExpandConstant('{sys}\schtasks.exe'),
    '/Create /TN "NEXORA Local Agent" /XML "' + TaskFile + '" /F',
    '', SW_HIDE, ewWaitUntilTerminated, ResultCode) and (ResultCode = 0) then
  begin
    Log('NEXORA Local Agent sign-in and crash-recovery task registered.');
    Exec(ExpandConstant('{sys}\schtasks.exe'),
      '/Run /TN "NEXORA Local Agent"', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
    DeleteFile(ExpandConstant('{userstartup}\NEXORA Local Agent.lnk'));
  end
  else
  begin
    Log('NEXORA scheduled task could not be registered; Startup shortcut remains the fallback.');
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
    RegisterManagedAgentTask;
end;
