#Requires -Version 5.1
[CmdletBinding()]
param(
    [switch]$SkipDependencyInstall
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$LocalRoot = Join-Path $env:LOCALAPPDATA "NEXORA"
$Venv = Join-Path $LocalRoot "local-agent-venv"
$DataRoot = Join-Path $LocalRoot "Foundry"
$AgentData = Join-Path $LocalRoot "Agent"
$Python = Join-Path $Venv "Scripts\python.exe"

Write-Host ""
Write-Host "NEXORA LOCAL COMPUTE ENVIRONMENT" -ForegroundColor Cyan
Write-Host "This installs the local agent and Python dependencies on this computer."
Write-Host "Game production runs here. NEXORA cloud does not receive CPU/GPU jobs."
Write-Host ""

if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
    throw "Python Launcher was not found. Install Python 3.11 or newer from https://www.python.org/downloads/windows/ and rerun this script."
}

$PythonVersion = (& py -3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')").Trim()
if ($LASTEXITCODE -ne 0 -or [version]$PythonVersion -lt [version]"3.11") {
    throw "Python 3.11+ is required. Install it from https://www.python.org/downloads/windows/."
}

New-Item -ItemType Directory -Force -Path $LocalRoot, $DataRoot, $AgentData | Out-Null

if (-not (Test-Path $Python)) {
    Write-Host "Creating isolated NEXORA Python environment..."
    & py -3 -m venv $Venv
    if ($LASTEXITCODE -ne 0) { throw "Could not create the NEXORA Python virtual environment." }
}

if (-not $SkipDependencyInstall) {
    Write-Host "Installing NEXORA's local runtime dependencies..."
    & $Python -m pip install --upgrade pip
    if ($LASTEXITCODE -ne 0) { throw "Could not update pip." }
    & $Python -m pip install -e $RepoRoot
    if ($LASTEXITCODE -ne 0) { throw "Could not install the NEXORA local runtime." }
}

$env:PGF_DATA_DIR = $DataRoot
$env:NEXORA_LOCAL_AGENT_DATA = $AgentData
$env:NEXORA_LOCAL_AGENT = "true"
$env:NEXORA_AUTH_REQUIRED = "true"
$env:NEXORA_ENV = "local"
$env:NEXORA_LOCAL_ALLOWED_ORIGINS = "https://revelacode.co.ke,http://localhost:5174,http://127.0.0.1:5174,http://localhost:5173,http://127.0.0.1:5173,tauri://localhost"

Write-Host ""
Write-Host "Local environment installed." -ForegroundColor Green
Write-Host "Project data: $DataRoot"
Write-Host "Agent data:   $AgentData"
Write-Host ""
Write-Host "Keep this PowerShell window open while using NEXORA Studio."
Write-Host "A one-time 8-digit pairing code will appear below."
Write-Host "Pair the browser from NEXORA > Device Lab > Local Compute Agent."
Write-Host ""
Write-Host "Optional tools are detected, not silently installed: Blender, Godot 4, FFmpeg/FFprobe, Android SDK/ADB, Java and a compatible CUDA GPU."
Write-Host "Install only the tools required by your selected workload, then restart this agent."
Write-Host ""

Push-Location $RepoRoot
try {
    & $Python -m services.worker.local_agent
    if ($LASTEXITCODE -ne 0) {
        throw "NEXORA Local Compute Agent exited with an error (exit code $LASTEXITCODE)."
    }
}
finally {
    Pop-Location
}
