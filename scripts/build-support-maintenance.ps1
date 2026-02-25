param(
    [string]$Name = "DupliManagerMaintenance",
    [switch]$OneFile
)

$ErrorActionPreference = "Stop"

function Require-Command([string]$CommandName) {
    if (-not (Get-Command $CommandName -ErrorAction SilentlyContinue)) {
        throw "No se encontro '$CommandName'. Instala PyInstaller en el entorno actual (`pip install pyinstaller`)."
    }
}

Require-Command "pyinstaller"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Push-Location $repoRoot
try {
    $entryPoint = "server_py\tools\maintenance.py"
    if (-not (Test-Path $entryPoint)) {
        throw "No se encontro el entrypoint '$entryPoint'."
    }

    $args = @(
        "--noconfirm",
        "--clean",
        "--name", $Name,
        "--console",
        "--paths", $repoRoot
    )

    if ($OneFile) {
        $args += "--onefile"
    }
    else {
        $args += "--onedir"
    }

    $args += $entryPoint

    Write-Host "==> Build soporte (maintenance CLI interno)..." -ForegroundColor Yellow
    & pyinstaller @args
}
finally {
    Pop-Location
}

