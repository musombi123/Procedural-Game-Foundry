[CmdletBinding()]
param(
    [switch]$SkipDependencyInstall
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Dist = Join-Path $RepoRoot "dist\NEXORA.LocalAgent"

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    throw "Python is required only by this developer/CI packaging step."
}

if (-not $SkipDependencyInstall) {
    python -m pip install --upgrade pip
    if ($LASTEXITCODE -ne 0) { throw "Could not update pip." }
    python -m pip install -e "$RepoRoot[local-agent]"
    if ($LASTEXITCODE -ne 0) { throw "Could not install the Local Agent build dependencies." }
}

Push-Location $RepoRoot
try {
    python -m PyInstaller --noconfirm --clean "packaging\nexora-local-agent.spec"
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller could not package the NEXORA Local Agent." }

    $AgentExe = Join-Path $Dist "NEXORA.LocalAgent.exe"
    if (-not (Test-Path $AgentExe)) { throw "The packaged NEXORA Local Agent executable was not produced." }

    & $AgentExe --self-test
    if ($LASTEXITCODE -ne 0) { throw "The packaged Local Agent failed its frozen-runtime self-test." }
}
finally {
    Pop-Location
}
