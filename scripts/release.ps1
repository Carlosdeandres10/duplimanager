param(
    [string]$Version,
    [ValidateSet("github", "local")]
    [string]$Target,
    [ValidateSet("client", "support")]
    [string]$Mode = "client"
)

$ErrorActionPreference = "Stop"

function Try-ParseSemVer {
    param([string]$VersionText)
    $s = [string]$VersionText
    if ($null -eq $s) { $s = "" }
    if ($s -match '^v?(\d+)\.(\d+)\.(\d+)(?:[-+].*)?$') {
        return [pscustomobject]@{
            Major = [int]$Matches[1]
            Minor = [int]$Matches[2]
            Patch = [int]$Matches[3]
            Normalized = "$($Matches[1]).$($Matches[2]).$($Matches[3])"
        }
    }
    return $null
}

function Get-LatestRemoteReleaseVersion {
    try {
        $lines = @(git ls-remote --tags --refs origin "v*")
        $best = $null
        foreach ($line in $lines) {
            if (-not $line) { continue }
            $parts = $line -split '\s+'
            if ($parts.Count -lt 2) { continue }
            $ref = $parts[1]
            if ($ref -notmatch 'refs/tags/(v.+)$') { continue }
            $tag = $Matches[1]
            $parsed = Try-ParseSemVer -VersionText $tag
            if (-not $parsed) { continue }
            if (-not $best) {
                $best = $parsed
                continue
            }
            if (
                $parsed.Major -gt $best.Major -or
                ($parsed.Major -eq $best.Major -and $parsed.Minor -gt $best.Minor) -or
                ($parsed.Major -eq $best.Major -and $parsed.Minor -eq $best.Minor -and $parsed.Patch -gt $best.Patch)
            ) {
                $best = $parsed
            }
        }
        return $best
    } catch {
        return $null
    }
}

function Get-SuggestedNextVersion {
    param($Latest)
    if (-not $Latest) { return "1.0.0" }
    return "$($Latest.Major).$($Latest.Minor).$([int]$Latest.Patch + 1)"
}

function Ask-YesNo {
    param(
        [string]$Prompt,
        [bool]$DefaultYes = $true
    )
    $suffix = if ($DefaultYes) { "[Y/n]" } else { "[y/N]" }
    $raw = Read-Host "$Prompt $suffix"
    if ($null -eq $raw) { $raw = "" }
    $ans = $raw.Trim().ToLower()
    if (-not $ans) { return $DefaultYes }
    return @("y", "yes", "s", "si", "sí") -contains $ans
}

function Ask-Choice {
    param(
        [string]$Prompt,
        [string[]]$Choices,
        [string]$Default
    )
    while ($true) {
        $raw = Read-Host "$Prompt [$($Choices -join '/')] (default: $Default)"
        if ($null -eq $raw) { $raw = "" }
        $v = $raw.Trim().ToLower()
        if (-not $v) { return $Default }
        foreach ($c in $Choices) {
            if ($v -eq $c.ToLower()) { return $c }
        }
        Write-Host "Valor no válido." -ForegroundColor Yellow
    }
}

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Push-Location $repoRoot
try {
    if (-not $Target) {
        $Target = Ask-Choice -Prompt "Tipo de release" -Choices @("github", "local") -Default "github"
    }

    if (-not $Version) {
        $latestRemote = $null
        $suggestedVersion = "1.0.0"
        if ($Target -eq "github") {
            $latestRemote = Get-LatestRemoteReleaseVersion
            $suggestedVersion = Get-SuggestedNextVersion -Latest $latestRemote
            if ($latestRemote) {
                Write-Host "Última versión detectada en GitHub (tags origin): $($latestRemote.Normalized)" -ForegroundColor Cyan
            } else {
                Write-Host "No se detectaron tags remotos en origin. Primera versión sugerida: 1.0.0" -ForegroundColor Yellow
            }
        }
        while ($true) {
            $prompt = if ($Target -eq "github") {
                "Versión (ej: 1.0.2, Enter = $suggestedVersion)"
            } else {
                "Versión (ej: 1.0.2)"
            }
            $rawVersion = Read-Host $prompt
            if ($null -eq $rawVersion) { $rawVersion = "" }
            $Version = $rawVersion.Trim()
            if (-not $Version -and $Target -eq "github") {
                $Version = $suggestedVersion
                Write-Host "Usando versión sugerida: $Version" -ForegroundColor Green
            }
            if ($Version -match '^\d+\.\d+\.\d+(?:[-+][A-Za-z0-9.\-]+)?$') { break }
            Write-Host "Formato inválido. Usa semver (ej: 1.0.2)." -ForegroundColor Yellow
        }
    }

    if ($Target -eq "github") {
        $runLocalFirst = Ask-YesNo -Prompt "¿Preparar release local antes de publicar en GitHub?" -DefaultYes:$false
        $allowDirty = $false
        if (-not $runLocalFirst) {
            $allowDirty = Ask-YesNo -Prompt "¿Permitir árbol sucio? (normalmente NO)" -DefaultYes:$false
        }

        Write-Host ""
        Write-Host "Resumen:" -ForegroundColor Cyan
        Write-Host "  Tipo    : github"
        Write-Host "  Versión : $Version"
        Write-Host "  Modo    : client (GitHub workflow compila cliente por defecto)"
        Write-Host "  Local   : $runLocalFirst"
        Write-Host ""

        if (-not (Ask-YesNo -Prompt "¿Continuar?" -DefaultYes $true)) { return }

        & "$repoRoot\scripts\release-github.ps1" -Version $Version -RunLocalRelease:$runLocalFirst -AllowDirty:$allowDirty
        return
    }

    # local
    $updateChangelog = Ask-YesNo -Prompt "¿Actualizar CHANGELOG.md?" -DefaultYes:$false
    $skipTests = Ask-YesNo -Prompt "¿Omitir tests MVP?" -DefaultYes:$false
    $skipSyntax = Ask-YesNo -Prompt "¿Omitir checks de sintaxis?" -DefaultYes:$false

    Write-Host ""
    Write-Host "Resumen:" -ForegroundColor Cyan
    Write-Host "  Tipo    : local"
    Write-Host "  Versión : $Version"
    Write-Host "  Modo    : $Mode"
    Write-Host "  Changelog: $updateChangelog"
    Write-Host ""

    if (-not (Ask-YesNo -Prompt "¿Continuar?" -DefaultYes $true)) { return }

    & "$repoRoot\scripts\release-local.ps1" `
        -Version $Version `
        -Mode $Mode `
        -UpdateChangelog:$updateChangelog `
        -SkipTests:$skipTests `
        -SkipSyntaxChecks:$skipSyntax
}
finally {
    Pop-Location
}
