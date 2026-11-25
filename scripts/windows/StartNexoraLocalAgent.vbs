Option Explicit

Dim fso, shell, root, foundryRoot, dataRoot, agentData, logRoot, logFile
Dim pythonExe, request, command, launcher, environment

Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")

root = fso.GetParentFolderName(WScript.ScriptFullName)
foundryRoot = fso.BuildPath(root, "foundry")
dataRoot = shell.ExpandEnvironmentStrings("%LOCALAPPDATA%") & "\NEXORA\Foundry"
agentData = shell.ExpandEnvironmentStrings("%LOCALAPPDATA%") & "\NEXORA\Agent"
logRoot = fso.BuildPath(agentData, "logs")
logFile = fso.BuildPath(logRoot, "local-agent.log")
pythonExe = fso.BuildPath(root, "python.exe")

If Not fso.FileExists(pythonExe) Or Not fso.FolderExists(foundryRoot) Then
  WScript.Quit 2
End If

' Avoid spawning duplicate local agents when the user clicks Start repeatedly
' or Windows invokes the sign-in startup entry while the agent is already up.
On Error Resume Next
Set request = CreateObject("WinHttp.WinHttpRequest.5.1")
request.SetTimeouts 500, 500, 700, 700
request.Open "GET", "http://127.0.0.1:8765/health", False
request.Send
If Err.Number = 0 Then
  If request.Status = 200 Then
    If InStr(1, request.ResponseText, "NEXORA Local Compute Agent", vbTextCompare) > 0 Then
      WScript.Quit 0
    End If
  End If
End If
Err.Clear
On Error GoTo 0

If Not fso.FolderExists(logRoot) Then
  fso.CreateFolder logRoot
End If
If Not fso.FolderExists(dataRoot) Then
  fso.CreateFolder dataRoot
End If
If Not fso.FolderExists(agentData) Then
  fso.CreateFolder agentData
End If

shell.CurrentDirectory = foundryRoot
Set environment = shell.Environment("PROCESS")
environment("PGF_DATA_DIR") = dataRoot
environment("NEXORA_LOCAL_AGENT_DATA") = agentData
environment("NEXORA_LOCAL_AGENT") = "true"
environment("NEXORA_AUTH_REQUIRED") = "true"
environment("NEXORA_ENV") = "local"
environment("NEXORA_CLOUD_API_URL") = "https://nexora-foundry-api.onrender.com"
environment("NEXORA_LOCAL_ALLOWED_ORIGINS") = "https://revelacode.co.ke"
environment("NEXORA_CORS_ORIGINS") = "https://revelacode.co.ke"

' Run headless in the background and retain a bounded diagnostic log for support.
command = """" & pythonExe & """ -m services.worker.local_agent >> """ & logFile & """ 2>&1"
launcher = shell.ExpandEnvironmentStrings("%ComSpec%") & " /d /c """ & command & """"
shell.Run launcher, 0, False
