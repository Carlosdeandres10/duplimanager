param(
    [Parameter(Mandatory = $true)]
    [string]$Version,
    [switch]$RunLocalRelease,
    [switch]$UpdateChangelog,
    [switch]$AllowDirty,
    [switch]$SkipPushMain,
    [switch]$SkipTagPush
)

$ErrorActionPreference = "Stop"

function Get-RepoRoot {
    return (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
}

$repoRoot = Get-RepoRoot
Push-Location $repoRoot
try {
    $version = $Version.Trim()
    if (-not ($version -match '^\d+\.\d+\.\d+(?:[-+][A-Za-z0-9.\-]+)?$')) {
        throw "Versión inválida '$Version'. Usa formato semántico (ej: 1.0.2)."
    }
    $tag = "v$version"

    if (-not $AllowDirty) {
        $status = @(git status --porcelain)
        if ($status.Count -gt 0) {
            throw "El árbol de trabajo no está limpio. Haz commit/stash o usa -AllowDirty."
        }
    }

    if ((git tag --list $tag)) {
        throw "El tag '$tag' ya existe."
    }

    if ($RunLocalRelease) {
        & "$repoRoot\scripts\release-local.ps1" -Version $version -Mode client @(
            if ($UpdateChangelog) { "-UpdateChangelog" }
        )
        if ($UpdateChangelog) {
            $statusAfter = @(git status --porcelain)
            if ($statusAfter.Count -gt 0) {
                Write-Host "Se detectaron cambios (ej. CHANGELOG.md). Haz commit antes de publicar el tag." -ForegroundColor Yellow
                git status --short
                return
            }
        }
    }

    if (-not $SkipPushMain) {
        Write-Host "==> Push branch main" -ForegroundColor Cyan
        git push origin main
    }

    Write-Host "==> Crear tag $tag" -ForegroundColor Cyan
    git tag $tag

    if (-not $SkipTagPush) {
        Write-Host "==> Push tag $tag" -ForegroundColor Cyan
        git push origin $tag
    }

    $repoUrl = (git remote get-url origin)
    if ($repoUrl -match 'github\.com[:/](.+?)(?:\.git)?$') {
        $slug = $Matches[1]
        Write-Host ""
        Write-Host "Release GitHub disparado (si tienes workflow configurado)." -ForegroundColor Green
        Write-Host "  Actions : https://github.com/$slug/actions"
        Write-Host "  Releases: https://github.com/$slug/releases"
    } else {
        Write-Host "Tag publicado: $tag" -ForegroundColor Green
    }
}
finally {
    Pop-Location
}

