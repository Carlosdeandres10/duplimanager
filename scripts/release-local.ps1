param(
    [Parameter(Mandatory = $true)]
    [string]$Version,
    [ValidateSet("client", "support")]
    [string]$Mode = "client",
    [switch]$SkipTests,
    [switch]$SkipSyntaxChecks,
    [switch]$SkipBuild,
    [switch]$UpdateChangelog,
    [switch]$NoDownloadDeps,
    [string]$DuplicacyVersion = "latest"
)

$ErrorActionPreference = "Stop"

function Get-RepoRoot {
    return (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
}

function Sync-AppVersionFile {
    param([string]$Version)
    $repoRoot = Get-RepoRoot
    $versionPath = Join-Path $repoRoot "server_py\version.py"
    if (-not (Test-Path $versionPath)) {
        throw "No se encontró archivo de versión: $versionPath"
    }
    $content = Get-Content $versionPath -Raw -Encoding utf8
    $updated = [regex]::Replace(
        $content,
        '(?m)^__version__\s*=\s*"[^"]*"\s*$',
        ('__version__ = "{0}"' -f $Version)
    )
    if ($updated -ne $content) {
        $updated | Out-File -FilePath $versionPath -Encoding utf8
        Write-Host "Versión sincronizada en server_py/version.py -> $Version" -ForegroundColor Green
        return $true
    }
    return $false
}

function Get-PreviousTag {
    param([string]$CurrentTag)
    $tags = @(git tag --sort=-creatordate)
    foreach ($t in $tags) {
        if (-not $t) { continue }
        if ($CurrentTag -and $t -eq $CurrentTag) { continue }
        return $t
    }
    return $null
}

function Get-ReleaseNotesLines {
    param([string]$Version)

    $currentTag = "v$Version"
    $prevTag = Get-PreviousTag -CurrentTag $currentTag
    $logLines = @()
    if ($prevTag) {
        $logLines = @(git log --pretty=format:"- %h %s" "$prevTag..HEAD")
    } else {
        $logLines = @(git log --pretty=format:"- %h %s" -20)
    }
    if (-not $logLines -or $logLines.Count -eq 0) {
        $logLines = @("- Sin cambios detectados por git log")
    }

    $header = @(
        "# DupliManager $Version"
        ""
        "## Cambios"
        ""
    )
    $footer = @(
        ""
        "## Notas operativas"
        ""
        "- Verificar instalación del servicio Windows `DupliManager` (WinSW) tras desplegar."
        "- Comprobar acceso al panel en `http://127.0.0.1:8500`."
    )
    return @($header + $logLines + $footer)
}

function Update-ChangelogFile {
    param(
        [string]$Version,
        [string[]]$ReleaseNotesLines
    )
    $repoRoot = Get-RepoRoot
    $changelogPath = Join-Path $repoRoot "CHANGELOG.md"

    if (-not (Test-Path $changelogPath)) {
        @(
            "# CHANGELOG"
            ""
            "Historial de versiones de DupliManager (resumen operativo)."
            ""
        ) | Out-File -FilePath $changelogPath -Encoding utf8
    }

    $date = (Get-Date).ToString("yyyy-MM-dd")
    $bodyLines = @()
    foreach ($line in $ReleaseNotesLines) {
        if ($line -like "# *") { continue }
        if ($line -eq "## Cambios") { continue }
        if ($line -eq "## Notas operativas") { continue }
        $bodyLines += $line
    }

    $existing = Get-Content $changelogPath -Raw -Encoding utf8
    $entry = @(
        "## $Version - $date"
        ""
    ) + $bodyLines + @("", "")

    # Inserta después del encabezado principal
    if ($existing -match "(?s)\A# CHANGELOG\s*\r?\n(?:.*?\r?\n)?\r?\n") {
        $match = [regex]::Match($existing, "(?s)\A(# CHANGELOG\s*\r?\n(?:.*?\r?\n)?\r?\n)")
        $prefix = $match.Groups[1].Value
        $suffix = $existing.Substring($prefix.Length)
        ($prefix + ($entry -join [Environment]::NewLine) + $suffix) | Out-File -FilePath $changelogPath -Encoding utf8
    } else {
        (($entry -join [Environment]::NewLine) + $existing) | Out-File -FilePath $changelogPath -Encoding utf8
    }
}

$repoRoot = Get-RepoRoot
Push-Location $repoRoot
try {
    $version = $Version.Trim()
    if (-not ($version -match '^\d+\.\d+\.\d+(?:[-+][A-Za-z0-9.\-]+)?$')) {
        throw "Versión inválida '$Version'. Usa formato semántico (ej: 1.0.2)."
    }

    Sync-AppVersionFile -Version $version | Out-Null

    $outDir = Join-Path $repoRoot "installer\output"
    New-Item -ItemType Directory -Force -Path $outDir | Out-Null

    if (-not $NoDownloadDeps -and $Mode -eq "client") {
        if (-not (Test-Path "installer\vendor\winsw\WinSW-x64.exe")) {
            & "$repoRoot\scripts\download-winsw.ps1"
        }
        if (-not (Test-Path "bin\duplicacy.exe")) {
            & "$repoRoot\scripts\download-duplicacy.ps1" -Version $DuplicacyVersion -Arch x64
        }
    }

    if (-not $SkipTests) {
        Write-Host "==> Tests MVP" -ForegroundColor Cyan
        python -m unittest discover -s tests -v
    }

    if (-not $SkipSyntaxChecks) {
        Write-Host "==> Validación sintaxis backend/frontend" -ForegroundColor Cyan
        python -m py_compile server_py/routers/backups.py server_py/routers/restore.py server_py/routers/system.py server_py/services/notifications.py
        node --check web/js/modules/views/repositories.js
        node --check web/js/modules/views/restore.js
        node --check web/js/modules/views/settings.js
        node --check web/js/api.js
    }

    if (-not $SkipBuild) {
        Write-Host "==> Build instalador local ($Mode $version)" -ForegroundColor Cyan
        & "$repoRoot\scripts\build-installer.ps1" -Mode $Mode -Version $version -BuildPyInstallerFirst
    }

    $installerName = "DupliManager-$Mode-setup-$version.exe"
    $installerPath = Join-Path $repoRoot "installer\output\$installerName"
    if (-not (Test-Path $installerPath)) {
        throw "No se encontró el instalador esperado: $installerPath"
    }

    $hash = (Get-FileHash -Path $installerPath -Algorithm SHA256).Hash.ToLower()
    $size = (Get-Item $installerPath).Length
    $shaFile = Join-Path $outDir "SHA256SUMS.txt"
    "$hash *$installerName" | Out-File -FilePath $shaFile -Encoding ascii

    $notesLines = Get-ReleaseNotesLines -Version $version
    $notesPath = Join-Path $outDir "release-notes.md"
    $notesLines | Out-File -FilePath $notesPath -Encoding utf8

    $meta = [ordered]@{
        version = $version
        mode = $Mode
        installer = [ordered]@{
            file = $installerName
            path = $installerPath
            sha256 = $hash
            size = $size
        }
        generatedAtUtc = (Get-Date).ToUniversalTime().ToString("o")
        previousTag = (Get-PreviousTag -CurrentTag ("v$version"))
    }
    $metaPath = Join-Path $outDir "release-metadata.local.json"
    $meta | ConvertTo-Json -Depth 8 | Out-File -FilePath $metaPath -Encoding utf8

    if ($UpdateChangelog) {
        Update-ChangelogFile -Version $version -ReleaseNotesLines $notesLines
        Write-Host "CHANGELOG actualizado: CHANGELOG.md" -ForegroundColor Green
    }

    Write-Host ""
    Write-Host "Release local listo" -ForegroundColor Green
    Write-Host "  Instalador : $installerPath"
    Write-Host "  SHA256     : $hash"
    Write-Host "  Tamaño     : $size bytes"
    Write-Host "  Notas      : $notesPath"
    Write-Host "  Metadata   : $metaPath"
}
finally {
    Pop-Location
}
