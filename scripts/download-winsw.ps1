param(
    [string]$Url = "https://github.com/winsw/winsw/releases/latest/download/WinSW-x64.exe",
    [string]$OutFile = "installer/vendor/winsw/WinSW-x64.exe"
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$target = Join-Path $repoRoot $OutFile
$targetDir = Split-Path -Parent $target

if (-not (Test-Path $targetDir)) {
    New-Item -ItemType Directory -Path $targetDir -Force | Out-Null
}

Write-Host "==> Descargando WinSW..." -ForegroundColor Cyan
Write-Host "URL: $Url"
Write-Host "Destino: $target"

Invoke-WebRequest -Uri $Url -OutFile $target

if (-not (Test-Path $target)) {
    throw "No se pudo descargar WinSW en '$target'."
}

$size = (Get-Item $target).Length
Write-Host "OK - WinSW descargado ($size bytes)" -ForegroundColor Green
Write-Host "Siguiente paso: .\\scripts\\build-installer.ps1 -Mode client -BuildPyInstallerFirst"

