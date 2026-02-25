param(
    [string]$Version = "latest",
    [ValidateSet("x64", "i386")]
    [string]$Arch = "x64",
    [string]$OutFile = "bin/duplicacy.exe"
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$target = Join-Path $repoRoot $OutFile
$targetDir = Split-Path -Parent $target

if (-not (Test-Path $targetDir)) {
    New-Item -ItemType Directory -Path $targetDir -Force | Out-Null
}

$headers = @{
    "User-Agent" = "DupliManager-BuildScript"
    "Accept" = "application/vnd.github+json"
}

$releaseApi = if ($Version -eq "latest") {
    "https://api.github.com/repos/gilbertchen/duplicacy/releases/latest"
} else {
    $v = if ($Version.StartsWith("v")) { $Version } else { "v$Version" }
    "https://api.github.com/repos/gilbertchen/duplicacy/releases/tags/$v"
}

Write-Host "==> Resolviendo release de Duplicacy..." -ForegroundColor Cyan
Write-Host "API: $releaseApi"

$release = Invoke-RestMethod -Uri $releaseApi -Headers $headers
if (-not $release) {
    throw "No se pudo resolver la release de Duplicacy."
}

$pattern = "duplicacy_win_${Arch}_.*\.exe$"
$asset = @($release.assets) | Where-Object { $_.name -match $pattern } | Select-Object -First 1
if (-not $asset) {
    throw "No se encontró asset Windows ($Arch) en la release $($release.tag_name)."
}

Write-Host "==> Descargando Duplicacy CLI..." -ForegroundColor Cyan
Write-Host "Release: $($release.tag_name)"
Write-Host "Asset:   $($asset.name)"
Write-Host "Destino: $target"

Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $target -Headers @{ "User-Agent" = "DupliManager-BuildScript" }

if (-not (Test-Path $target)) {
    throw "No se pudo descargar Duplicacy en '$target'."
}

$info = Get-Item $target
Write-Host "OK - Duplicacy descargado ($($info.Length) bytes)" -ForegroundColor Green
Write-Host "Ruta: $($info.FullName)"

