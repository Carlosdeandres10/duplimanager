param(
    [string]$Name = "DupliManager",
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
    $entryPoint = "server_py\main.py"
    if (-not (Test-Path $entryPoint)) {
        throw "No se encontro el entrypoint '$entryPoint'."
    }

    $args = @(
        "--noconfirm",
        "--clean",
        "--name", $Name,
        "--console",
        "--paths", $repoRoot,
        "--exclude-module", "server_py.tools.maintenance",
        "--exclude-module", "tkinter",
        "--exclude-module", "tkinter.filedialog",
        "--add-data", "web;web",
        "--add-data", "docs.html;.",
        "--add-data", "config\.gitkeep;config",
        "--add-data", "logs\.gitkeep;logs"
    )

    if (Test-Path "bin\duplicacy.exe") {
        $args += @("--add-binary", "bin\duplicacy.exe;bin")
    }
    else {
        Write-Warning "No se encontro bin\\duplicacy.exe. El binario cliente se generara sin Duplicacy embebido."
    }

    if ($OneFile) {
        $args += "--onefile"
    }
    else {
        $args += "--onedir"
    }

    $args += $entryPoint

    Write-Host "==> Build cliente (sin maintenance CLI)..." -ForegroundColor Cyan
    & pyinstaller @args
}
finally {
    Pop-Location
}

