param(
    [ValidateSet("client", "support")]
    [string]$Mode = "client",
    [string]$Version = "1.0.0",
    [switch]$BuildPyInstallerFirst,
    [string]$ISCCPath
)

$ErrorActionPreference = "Stop"

function Resolve-ISCC {
    param([string]$Override)
    if ($Override) {
        if (-not (Test-Path $Override)) { throw "ISCC no encontrado en '$Override'" }
        return (Resolve-Path $Override).Path
    }

    $candidates = @(
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
    ) | Where-Object { $_ -and (Test-Path $_) }

    if ($candidates) { return @($candidates)[0] }

    $cmd = Get-Command ISCC.exe -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }

    throw "No se encontró ISCC.exe (Inno Setup 6). Instálalo o pasa -ISCCPath."
}

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$iscc = Resolve-ISCC -Override $ISCCPath
$issFile = Join-Path $repoRoot "installer\DupliManager.iss"
$distFolder = if ($Mode -eq "client") { "dist\DupliManager" } else { "dist\DupliManagerMaintenance" }
$winSWPath = Join-Path $repoRoot "installer\vendor\winsw\WinSW-x64.exe"

if (-not (Test-Path $issFile)) {
    throw "No se encontró el script Inno Setup: $issFile"
}

Push-Location $repoRoot
try {
    if ($BuildPyInstallerFirst) {
        if ($Mode -eq "client") {
            & "$repoRoot\scripts\build-client.ps1"
        }
        else {
            & "$repoRoot\scripts\build-support-maintenance.ps1"
        }
    }

    $distPath = Join-Path $repoRoot $distFolder
    if (-not (Test-Path $distPath)) {
        throw "No se encontró la build PyInstaller en '$distPath'. Ejecuta primero el build correspondiente o usa -BuildPyInstallerFirst."
    }
    if ($Mode -eq "client" -and -not (Test-Path $winSWPath)) {
        throw "Falta WinSW para el instalador cliente: '$winSWPath'. Ejecuta .\\scripts\\download-winsw.ps1"
    }

    Write-Host "==> Compilando instalador Inno Setup ($Mode)..." -ForegroundColor Cyan
    & $iscc "/DAppVersion=$Version" "/DBuildMode=$Mode" $issFile
}
finally {
    Pop-Location
}
