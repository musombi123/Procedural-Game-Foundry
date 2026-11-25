#Requires -Version 5.1
[CmdletBinding()]
param(
    [string]$InstallRoot = (Join-Path $env:LOCALAPPDATA "NEXORA\source")
)

$ErrorActionPreference = "Stop"
$RepositoryArchive = "https://github.com/musombi123/Procedural-Game-Foundry/archive/refs/heads/main.zip"
$WorkRoot = Join-Path $env:TEMP ("NEXORA-Agent-Bootstrap-" + [guid]::NewGuid().ToString("N"))
$ArchivePath = Join-Path $WorkRoot "foundry.zip"
$ExtractRoot = Join-Path $WorkRoot "source"

Write-Host ""
Write-Host "NEXORA LOCAL AGENT INSTALLER" -ForegroundColor Cyan
Write-Host "This installs the local compute service on this Windows computer."
Write-Host "The browser cannot start a local service by itself; this installer starts it for you."
Write-Host ""

try {
    $ExistingHealth = $null
    try {
        $ExistingHealth = Invoke-RestMethod -Uri "http://127.0.0.1:8765/health" -TimeoutSec 2
    } catch {
        $ExistingHealth = $null
    }

    if ($ExistingHealth -and $ExistingHealth.service -eq "NEXORA Local Compute Agent") {
        Write-Host "NEXORA Local Agent is already running at http://127.0.0.1:8765." -ForegroundColor Green
        Write-Host "Return to NEXORA Studio > Device Lab and select Check connection."
        return
    }

    if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
        throw "Python Launcher was not found. Install Python 3.11 or newer from https://www.python.org/downloads/windows/ and rerun this installer."
    }

    $PythonVersion = (& py -3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')").Trim()
    if ($LASTEXITCODE -ne 0 -or [version]$PythonVersion -lt [version]"3.11") {
        throw "Python 3.11+ is required. Install it from https://www.python.org/downloads/windows/."
    }

    New-Item -ItemType Directory -Force -Path $WorkRoot, $ExtractRoot, $InstallRoot | Out-Null
    Write-Host "Downloading NEXORA local runtime..."
    Invoke-WebRequest -Uri $RepositoryArchive -OutFile $ArchivePath -UseBasicParsing
    Expand-Archive -LiteralPath $ArchivePath -DestinationPath $ExtractRoot -Force

    $RepositoryRoot = Join-Path $ExtractRoot "Procedural-Game-Foundry-main"
    if (-not (Test-Path (Join-Path $RepositoryRoot "scripts\install-nexora-local-environment.ps1"))) {
        throw "The downloaded NEXORA runtime archive is incomplete. Please retry or contact NEXORA support."
    }

    Write-Host "Installing local runtime files into $InstallRoot..."
    Copy-Item -Path (Join-Path $RepositoryRoot "*") -Destination $InstallRoot -Recurse -Force

    $EnvironmentInstaller = Join-Path $InstallRoot "scripts\install-nexora-local-environment.ps1"
    Write-Host ""
    Write-Host "Starting the NEXORA Local Agent. Keep this PowerShell window open." -ForegroundColor Green
    & $EnvironmentInstaller
    if ($LASTEXITCODE -ne 0) {
        throw "NEXORA Local Agent exited with an error (exit code $LASTEXITCODE)."
    }
}
finally {
    if (Test-Path $WorkRoot) {
        Remove-Item -Path $WorkRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}
