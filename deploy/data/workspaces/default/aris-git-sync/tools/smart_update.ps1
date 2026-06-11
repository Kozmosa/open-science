#Requires -Version 5.1
# ARIS Smart Skill Update (PowerShell)
# Intelligently compares local skills with upstream, detects personal
# customizations, and recommends safe update strategy per skill.
#
# Usage:
#   Global (default):
#     .\tools\smart_update.ps1 [-Apply]
#   Project-level (Claude Code):
#     .\tools\smart_update.ps1 -ProjectPath <path> [-Apply]
#   Project-level (Codex CLI):
#     .\tools\smart_update.ps1 -ProjectPath <path> -TargetSubdir '.agents/skills/aris' [-Apply]
#   Custom paths:
#     .\tools\smart_update.ps1 -UpstreamPath <path> -LocalPath <path> [-Apply]
#
#   -Apply: actually perform the updates (default: dry-run analysis only)
#   -ProjectPath: project root — upstream is always the repo's skills/; local targets <ProjectPath>/<TargetSubdir>
#   -TargetSubdir: project-mode skill subdirectory (default: .claude/skills)
#                  common: .claude/skills, .claude/skills/aris, .agents/skills, .agents/skills/aris
#                  must be a relative path
#   -UpstreamPath: explicit upstream skills directory
#   -LocalPath: explicit local skills directory

[CmdletBinding(DefaultParameterSetName = 'Global')]
param(
    [switch]$Apply,

    [Parameter(ParameterSetName = 'Project', Mandatory = $true)]
    [string]$ProjectPath,

    [Parameter(ParameterSetName = 'Project', Mandatory = $false)]
    [string]$TargetSubdir = '.claude/skills',

    [Parameter(ParameterSetName = 'Explicit', Mandatory = $true)]
    [string]$UpstreamPath,

    [Parameter(ParameterSetName = 'Explicit', Mandatory = $true)]
    [string]$LocalPath
)

$ErrorActionPreference = 'Stop'

# ─── Resolve upstream & local paths ───────────────────────────────────────────
if ($PSCmdlet.ParameterSetName -eq 'Project') {
    if ([System.IO.Path]::IsPathRooted($TargetSubdir)) {
        Write-Host "Error: -TargetSubdir must be a relative path (got: $TargetSubdir)" -ForegroundColor Red
        Write-Host "Hint: use -LocalPath for absolute paths" -ForegroundColor Yellow
        exit 1
    }

    $ProjectRoot = if ([System.IO.Path]::IsPathRooted($ProjectPath)) {
        $ProjectPath
    } else {
        Join-Path (Get-Location) $ProjectPath
    }
    $ProjectRoot = (Resolve-Path $ProjectRoot -ErrorAction SilentlyContinue).Path
    if (-not $ProjectRoot) {
        Write-Host "Project path not found: $ProjectPath" -ForegroundColor Red
        exit 1
    }
    # Upstream always comes from the repo (same as global)
    $UpstreamDir = Join-Path (Split-Path $PSScriptRoot -Parent) 'skills'
    if (-not (Test-Path $UpstreamDir)) {
        $resolved = Join-Path $PSScriptRoot '..\skills' | Resolve-Path -ErrorAction SilentlyContinue
        if ($resolved) { $UpstreamDir = $resolved.Path }
    }
    $TargetSubdirNormalized = $TargetSubdir -replace '/', '\'
    $LocalDir = Join-Path $ProjectRoot $TargetSubdirNormalized
    $Scope = "Project: $ProjectRoot (subdir: $TargetSubdir)"

    # ─── Deprecate nested -TargetSubdir (.claude/skills/aris, .agents/skills/aris) ──
    if ($TargetSubdir -in @('.claude/skills/aris', '.agents/skills/aris')) {
        Write-Host ""
        Write-Host "⚠️  -TargetSubdir $TargetSubdir is DEPRECATED" -ForegroundColor Yellow
        Write-Host ""
        Write-Host "  Reason: nested 'aris/' subdirectory hides skills from Claude Code's slash-command discovery" -ForegroundColor Yellow
        Write-Host "          (CC only scans .claude/skills/ one level deep)." -ForegroundColor Yellow
        Write-Host ""
        Write-Host "  Switch to the flat install (use the bash version via WSL, or manual junctions —" -ForegroundColor Yellow
        Write-Host "  see install_aris.ps1 docstring for the manual one-liner)." -ForegroundColor Yellow
        Write-Host ""
        if ($Apply) {
            Write-Host "Refusing to -Apply with deprecated nested target." -ForegroundColor Red
            exit 2
        }
        Write-Host "(continuing dry-run analysis for backward compatibility — no changes will be made)" -ForegroundColor Yellow
    }

    # Platform marker auto-detect: warn on mismatch
    $hasClaudeMarkers = (Test-Path (Join-Path $ProjectRoot 'CLAUDE.md')) -or `
                       (Test-Path (Join-Path $ProjectRoot '.claude\skills')) -or `
                       (Test-Path (Join-Path $ProjectRoot '.claude\settings.json'))
    $hasCodexMarkers  = (Test-Path (Join-Path $ProjectRoot 'AGENTS.md')) -or `
                       (Test-Path (Join-Path $ProjectRoot '.agents\skills')) -or `
                       (Test-Path (Join-Path $ProjectRoot '.codex\config.toml'))
    if ($hasClaudeMarkers -and (-not $hasCodexMarkers) -and $TargetSubdir.StartsWith('.agents')) {
        Write-Host "⚠️  Warning: project has Claude markers but -TargetSubdir points to Codex path ($TargetSubdir)" -ForegroundColor Yellow
    }
    if ($hasCodexMarkers -and (-not $hasClaudeMarkers) -and $TargetSubdir.StartsWith('.claude')) {
        Write-Host "⚠️  Warning: project has Codex markers but -TargetSubdir points to Claude path ($TargetSubdir)" -ForegroundColor Yellow
    }

} elseif ($PSCmdlet.ParameterSetName -eq 'Explicit') {
    $UpstreamDir = $UpstreamPath
    $LocalDir = $LocalPath
    $Scope = "Custom"
} else {
    # Global default
    $UpstreamDir = Join-Path (Split-Path $PSScriptRoot -Parent) 'skills'
    if (-not (Test-Path $UpstreamDir)) {
        $resolved = Join-Path $PSScriptRoot '..\skills' | Resolve-Path -ErrorAction SilentlyContinue
        if ($resolved) { $UpstreamDir = $resolved.Path }
    }
    $LocalDir = Join-Path $env:USERPROFILE '.claude\skills'
    $Scope = 'Global'
}

# ─── Refuse to operate on symlinked installs ──────────────────────────────────
if (Test-Path $LocalDir) {
    $item = Get-Item $LocalDir -Force -ErrorAction SilentlyContinue
    if ($item -and ($item.LinkType -in @('Junction', 'SymbolicLink'))) {
        Write-Host ""
        Write-Host "✗ Local skill directory is a symlink/junction: $LocalDir" -ForegroundColor Red
        Write-Host "  → $($item.Target)"
        Write-Host ""
        Write-Host "smart_update is for COPIED installs. Symlinked installs are updated by:"
        Write-Host "  cd <aris-repo>; git pull"
        Write-Host ""
        Write-Host "If you need per-project customization, switch to a copied install:"
        Write-Host "  Remove-Item $LocalDir -Force"
        Write-Host "  .\tools\smart_update.ps1 -ProjectPath <project> -TargetSubdir $TargetSubdir -Apply"
        exit 2
    }
}

# ─── Personal info patterns ───────────────────────────────────────────────────
$PersonalPatterns = @(
    'ssh '
    'SJTUServer'
    'rfyang'
    'yangruofeng'
    'api_key'
    'API_KEY'
    'sk-'
    'token'
    '@sjtu'
    '@gmail'
    '/home/'
    '/Users/'
    'CUDA_VISIBLE'
    'wandb_project'
    'server_ip'
    'gpu_server'
    'screen -'
    'conda activate'
    '192\.168\.'
    '10\.\d+\.'
    '122\.'
)

# Patterns that are actual regex (contain backslash-dot or \d)
function Test-IsRegexPattern {
    param([string]$Pat)
    return ($Pat.Contains('\.') -or $Pat.Contains('\d'))
}

# ─── Header ────────────────────────────────────────────────────────────────────
Write-Host ''
Write-Host '=== ARIS Smart Skill Update ===' -ForegroundColor Cyan
Write-Host "Scope:    $Scope"
Write-Host "Upstream: $UpstreamDir"
Write-Host "Local:    $LocalDir"
Write-Host ''

if (-not (Test-Path $LocalDir)) {
    Write-Host "Local skills directory not found: $LocalDir" -ForegroundColor Red
    exit 1
}

if (-not (Test-Path $UpstreamDir)) {
    Write-Host "Upstream skills directory not found: $UpstreamDir" -ForegroundColor Red
    exit 1
}

# ─── Core comparison function ──────────────────────────────────────────────────
function Compare-SkillDirs {
    param(
        [string]$SrcDir,
        [string]$DstDir,
        [string[]]$Patterns
    )

    $result = @{
        New          = [System.Collections.Generic.List[string]]::new()
        Identical    = [System.Collections.Generic.List[string]]::new()
        Safe         = [System.Collections.Generic.List[string]]::new()
        Merge        = [System.Collections.Generic.List[string]]::new()
        LocalOnly    = [System.Collections.Generic.List[string]]::new()
        UpstreamNames = [System.Collections.Generic.HashSet[string]]::new()
    }

    # Check each upstream skill
    foreach ($skillDir in Get-ChildItem -Path $SrcDir -Directory) {
        $skillName = $skillDir.Name
        if ($skillName -eq 'skills-codex' -or $skillName -eq 'shared-references') { continue }

        [void]$result.UpstreamNames.Add($skillName)

        $upstreamFile = Join-Path $skillDir.FullName 'SKILL.md'
        $localSkillDir = Join-Path $DstDir $skillName
        $localFile = Join-Path $localSkillDir 'SKILL.md'

        if (-not (Test-Path $upstreamFile)) { continue }

        if ((-not (Test-Path $localSkillDir)) -or (-not (Test-Path $localFile))) {
            $result.New.Add($skillName)
            continue
        }

        $upstreamContent = Get-Content -Path $upstreamFile -Raw
        $localContent = Get-Content -Path $localFile -Raw

        if ($upstreamContent -eq $localContent) {
            $result.Identical.Add($skillName)
            continue
        }

        # Different - check for personal info unique to local
        $hasPersonal = $false
        foreach ($pat in $Patterns) {
            $isRegex = Test-IsRegexPattern $pat
            if ($isRegex) {
                $lc = ([regex]::Matches($localContent, $pat)).Count
                $uc = ([regex]::Matches($upstreamContent, $pat)).Count
            } else {
                $lc = ([regex]::Matches($localContent, [regex]::Escape($pat))).Count
                $uc = ([regex]::Matches($upstreamContent, [regex]::Escape($pat))).Count
            }
            if ($lc -gt $uc) {
                $hasPersonal = $true
                break
            }
        }

        if ($hasPersonal) {
            $result.Merge.Add($skillName)
        } else {
            $result.Safe.Add($skillName)
        }
    }

    # Check for local-only skills
    foreach ($skillDir in Get-ChildItem -Path $DstDir -Directory) {
        $skillName = $skillDir.Name
        if ($skillName -eq 'shared-references') { continue }
        if (-not $result.UpstreamNames.Contains($skillName)) {
            $result.LocalOnly.Add($skillName)
        }
    }

    return $result
}

function Show-Section {
    param([string]$Label, $Items, [string]$Color)
    Write-Host "${Label}: $($Items.Count)" -ForegroundColor $Color
    foreach ($s in $Items) { Write-Host "   $s" }
    Write-Host ''
}

function Show-MergeReport {
    param($Items, [string]$Dir, [string[]]$Patterns)
    foreach ($s in $Items) {
        Write-Host "   $s"
        $f = Join-Path $Dir "$s\SKILL.md"
        if (Test-Path $f) {
            $content = Get-Content -Path $f -Raw
            foreach ($pat in $Patterns) {
                $isRegex = Test-IsRegexPattern $pat
                if ($isRegex) {
                    $escaped = $pat
                } else {
                    $escaped = [regex]::Escape($pat)
                }
                $m = [regex]::Match($content, ".*$escaped.*")
                if ($m.Success) {
                    Write-Host "     -> contains: $($m.Value.Trim())" -ForegroundColor Yellow
                    break
                }
            }
        }
    }
}

function Invoke-SafeUpdate {
    param(
        $NewList,
        $SafeList,
        [string]$SrcDir,
        [string]$DstDir,
        [string]$SharedDir
    )
    foreach ($s in $NewList) {
        $src = Join-Path $SrcDir $s
        $dst = Join-Path $DstDir $s
        if (Test-Path $dst) { Remove-Item $dst -Recurse -Force }
        Copy-Item -Path $src -Destination $dst -Recurse -Force
        Write-Host "  + Added: $s" -ForegroundColor Green
    }

    foreach ($s in $SafeList) {
        $src = Join-Path $SrcDir $s
        $dst = Join-Path $DstDir $s
        if (Test-Path $dst) { Remove-Item $dst -Recurse -Force }
        Copy-Item -Path $src -Destination $dst -Recurse -Force
        Write-Host "  ^ Updated: $s" -ForegroundColor Cyan
    }

    if ($SharedDir -and (Test-Path $SharedDir)) {
        Copy-Item -Path $SharedDir -Destination (Join-Path $DstDir 'shared-references') -Recurse -Force
        Write-Host '  ^ Updated: shared-references' -ForegroundColor Cyan
    }
}

# ─── Run comparison ─────────────────────────────────────────────────────────────
$r = Compare-SkillDirs -SrcDir $UpstreamDir -DstDir $LocalDir -Patterns $PersonalPatterns

# ─── Report ────────────────────────────────────────────────────────────────────
Show-Section 'Identical (no action needed)' $r.Identical 'Green'
Show-Section 'New skills (safe to add)' $r.New 'Green'
Show-Section 'Updated upstream, no personal info (safe to replace)' $r.Safe 'Cyan'

Write-Host "Updated upstream + local customizations (needs manual merge): $($r.Merge.Count)" -ForegroundColor Yellow
Show-MergeReport $r.Merge $LocalDir $PersonalPatterns
Write-Host ''

Write-Host "Local-only skills (yours, not in upstream): $($r.LocalOnly.Count)"
foreach ($s in $r.LocalOnly) { Write-Host "   $s" }
Write-Host ''

# ─── Summary ───────────────────────────────────────────────────────────────────
$Total = $r.New.Count + $r.Identical.Count + $r.Safe.Count + $r.Merge.Count
Write-Host '=== Summary ===' -ForegroundColor Cyan
Write-Host "Total upstream skills: $Total"
Write-Host "  Up to date:  $($r.Identical.Count)" -ForegroundColor Green
Write-Host "  New to add:  $($r.New.Count)" -ForegroundColor Green
Write-Host "  Safe update: $($r.Safe.Count)" -ForegroundColor Cyan
Write-Host "  Need merge:  $($r.Merge.Count)" -ForegroundColor Yellow
Write-Host "  Local only:  $($r.LocalOnly.Count)"
Write-Host ''

if ($Apply) {
    Write-Host 'Applying safe updates...' -ForegroundColor Cyan

    $sharedUpstream = Join-Path $UpstreamDir 'shared-references'
    Invoke-SafeUpdate -NewList $r.New -SafeList $r.Safe -SrcDir $UpstreamDir -DstDir $LocalDir -SharedDir $sharedUpstream

    Write-Host ''
    Write-Host "Done! $($r.New.Count) new + $($r.Safe.Count) updated." -ForegroundColor Green

    if ($r.Merge.Count -gt 0) {
        Write-Host "$($r.Merge.Count) skills have personal customizations and were NOT updated." -ForegroundColor Yellow
        Write-Host "   Review manually: $($r.Merge -join ', ')" -ForegroundColor Yellow
        Write-Host "   Tip: diff the local and upstream SKILL.md files to merge changes" -ForegroundColor Yellow
    }
} else {
    switch ($PSCmdlet.ParameterSetName) {
        'Project'  { $cmdHint = ".\tools\smart_update.ps1 -ProjectPath `"$ProjectRoot`" -Apply" }
        'Explicit' { $cmdHint = ".\tools\smart_update.ps1 -UpstreamPath `"$UpstreamDir`" -LocalPath `"$LocalDir`" -Apply" }
        default    { $cmdHint = '.\tools\smart_update.ps1 -Apply' }
    }
    Write-Host 'Dry run complete. Run with -Apply to perform updates:' -ForegroundColor Yellow
    Write-Host "  $cmdHint" -ForegroundColor Green
}
Write-Host ''
