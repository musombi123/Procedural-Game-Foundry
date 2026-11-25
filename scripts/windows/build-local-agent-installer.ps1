[CmdletBinding()]
param(
    [string]$Version = "1.0.0"
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$BuildRoot = Join-Path $RepoRoot "build"
$PayloadRoot = Join-Path $BuildRoot "agent-payload"
$SitePackages = Join-Path $PayloadRoot "Lib\site-packages"
$FoundryRoot = Join-Path $PayloadRoot "foundry"
$DistRoot = Join-Path $RepoRoot "dist"

Write-Host "Building NEXORA Local Agent installer $Version" -ForegroundColor Cyan

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    throw "Python 3.11 is required on the build machine."
}

$PythonVersion = (& python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')").Trim()
if ($LASTEXITCODE -ne 0 -or -not $PythonVersion.StartsWith("3.11.")) {
    throw "The installer must be built with Python 3.11; detected '$PythonVersion'."
}

if (Test-Path $PayloadRoot) { Remove-Item $PayloadRoot -Recurse -Force }
if (Test-Path $DistRoot) { Remove-Item $DistRoot -Recurse -Force }
New-Item -ItemType Directory -Force -Path $PayloadRoot, $SitePackages, $FoundryRoot, $DistRoot | Out-Null

Write-Host "Installing the Local Agent runtime into the portable package..."
& python -m pip install --disable-pip-version-check --no-warn-script-location --target $SitePackages $RepoRoot
if ($LASTEXITCODE -ne 0) { throw "Could not package the Local Agent dependencies." }

Write-Host "Bundling the Foundry runtime and its local assets..."
& robocopy $RepoRoot $FoundryRoot /E /NFL /NDL /NJH /NJS /NC /NS /XD ".git" ".github" "tests" "build" "dist" ".venv" "venv" "node_modules" "__pycache__" ".pytest_cache" /XF ".env" ".env.*" "*.pyc"
$CopyExitCode = $LASTEXITCODE
if ($CopyExitCode -gt 7) {
    throw "Could not stage the Foundry runtime (robocopy exit code $CopyExitCode)."
}

Write-Host "Downloading the matching official Python embeddable runtime..."
$EmbedArchive = Join-Path $BuildRoot "python-embed.zip"
$EmbedUrl = "https://www.python.org/ftp/python/$PythonVersion/python-$PythonVersion-embed-amd64.zip"
Invoke-WebRequest -Uri $EmbedUrl -OutFile $EmbedArchive
Expand-Archive -LiteralPath $EmbedArchive -DestinationPath $PayloadRoot -Force
Remove-Item $EmbedArchive -Force

$PthFile = Join-Path $PayloadRoot "python311._pth"
if (-not (Test-Path $PthFile)) {
    throw "The Python embeddable runtime did not contain python311._pth."
}
$PthContents = @(
    "python311.zip",
    ".",
    "Lib\site-packages",
    "foundry",
    "import site"
) -join [Environment]::NewLine
Set-Content -Path $PthFile -Value $PthContents -Encoding Ascii

Copy-Item (Join-Path $PSScriptRoot "StartNexoraLocalAgent.vbs") (Join-Path $PayloadRoot "StartNexoraLocalAgent.vbs") -Force
Set-Content -Path (Join-Path $PayloadRoot "AGENT-VERSION.txt") -Value $Version -Encoding Ascii

$ProgramFilesX86 = [Environment]::GetEnvironmentVariable("ProgramFiles(x86)")
$iscc = Join-Path $ProgramFilesX86 "Inno Setup 6\ISCC.exe"
if (-not (Test-Path $iscc)) {
    if (-not (Get-Command choco -ErrorAction SilentlyContinue)) {
        throw "Inno Setup 6 compiler was not found and Chocolatey is unavailable."
    }
    choco install innosetup --yes --no-progress
    if ($LASTEXITCODE -ne 0) { throw "Could not install Inno Setup 6." }
}
if (-not (Test-Path $iscc)) {
    throw "Inno Setup compiler is still unavailable after installation."
}

Write-Host "Compiling the click-to-install Windows setup program..."
Push-Location $RepoRoot
try {
    & $iscc "/DAppVersion=$Version" "scripts\windows\NEXORA.LocalAgent.iss"
    if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed to compile the Windows installer." }
}
finally {
    Pop-Location
}

$Installer = Join-Path $DistRoot "NEXORA-Local-Agent-Setup.exe"
if (-not (Test-Path $Installer)) { throw "The installer output was not created." }
$Hash = (Get-FileHash -Path $Installer -Algorithm SHA256).Hash.ToLowerInvariant()
Set-Content -Path "$Installer.sha256" -Value "$Hash  NEXORA-Local-Agent-Setup.exe" -Encoding Ascii

Write-Host ""
Write-Host "Installer ready: $Installer" -ForegroundColor Green
Write-Host "SHA-256: $Hash"
