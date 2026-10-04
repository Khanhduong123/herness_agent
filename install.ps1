<#
.SYNOPSIS
    Harness Agent Scaffolding Script for Windows PowerShell.
    Copies Agent.md, AGENTS.md, SDLC skills, and workflow templates to a target repository.

.EXAMPLE
    .\install.ps1
    .\install.ps1 -ProjectName "my-cool-project"
    .\install.ps1 -TargetDir "..\du-an-moi" -Force
#>

param (
    [Parameter(Position = 0)]
    [string]$ProjectName = "",

    [string]$TargetDir = "",

    [switch]$Force
)

$ErrorActionPreference = "Stop"
if ($PSScriptRoot) {
    $ScriptDir = $PSScriptRoot
} elseif ($MyInvocation.MyCommand.Path) {
    $ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
} else {
    $ScriptDir = (Get-Location).Path
}

$CurrentDir = (Get-Location).Path

# 1. Ask for project name or target directory if not provided
if (-not $ProjectName -and -not $TargetDir) {
    # If run from outside harness_agent repo, default to current working directory
    if ($CurrentDir -ne $ScriptDir) {
        $TargetDir = $CurrentDir
        Write-Host "Phat hien dang chay tu thu muc du an: $TargetDir" -ForegroundColor Cyan
    } else {
        Write-Host "=== THIET LAP REPO MOI CHO HARNESS AGENT ===" -ForegroundColor Cyan
        $ProjectName = Read-Host "Nhap ten du an cua ban (vi du: my-awesome-project)"
        while ([string]::IsNullOrWhiteSpace($ProjectName)) {
            $ProjectName = Read-Host "Ten du an khong duoc de trong. Vui long nhap lai"
        }
        $TargetDir = Join-Path ".." $ProjectName
    }
} elseif (-not $TargetDir -and $ProjectName) {
    $TargetDir = Join-Path ".." $ProjectName
}

# 2. Resolve target directory path
if (Test-Path $TargetDir) {
    $ResolvedTarget = (Resolve-Path $TargetDir).Path
    $TargetExisted = $true
} else {
    New-Item -ItemType Directory -Path $TargetDir -Force | Out-Null
    $ResolvedTarget = (Resolve-Path $TargetDir).Path
    $TargetExisted = $false
    Write-Host "--> Da tao thu muc moi: $ResolvedTarget" -ForegroundColor Green
}

# Check if target already has files
$HasFiles = $false
if (Test-Path $ResolvedTarget) {
    $items = Get-ChildItem -Path $ResolvedTarget -Force -ErrorAction SilentlyContinue
    if ($items -and $items.Count -gt 0) {
        $HasFiles = $true
    }
}

if ($HasFiles -and $TargetExisted) {
    Write-Host "`n[THONG TIN] Thu muc '$ResolvedTarget' da chua code/du lieu hien co." -ForegroundColor Yellow
    if (-not $Force) {
        Write-Host "Chon hanh dong:"
        Write-Host "  [1] Cap nhat / Bo sung quy chuan (AGENTS.md, skills, .ai/plan) vao du an (Khong xoa code cu)" -ForegroundColor Green
        Write-Host "  [2] Huy thao tac (Abort)" -ForegroundColor Red
        $Choice = Read-Host "Lua chon cua ban [1/2] (Mac dinh: 1)"
        if ($Choice -eq "2") {
            Write-Host "Da huy qua trinh thiet lap." -ForegroundColor Yellow
            exit 0
        }
    }
    Write-Host "--> Tien hanh bo sung / cap nhat quy chuan vao: $ResolvedTarget" -ForegroundColor Cyan
}

Write-Host "==> Dang sao chep quy tac Harness Agent, SDLC Skills & cau hinh agy-cli vao: $ResolvedTarget" -ForegroundColor Cyan

# 1. Copy compliance and rule files
$AgentsMd = Join-Path $ScriptDir "AGENTS.md"
if (Test-Path $AgentsMd) {
    Copy-Item -Path $AgentsMd -Destination (Join-Path $ResolvedTarget "AGENTS.md") -Force
    Write-Host "  [+] Created AGENTS.md" -ForegroundColor Green
}
$AgentMd = Join-Path $ScriptDir "Agent.md"
if (Test-Path $AgentMd) {
    Copy-Item -Path $AgentMd -Destination (Join-Path $ResolvedTarget "Agent.md") -Force
    Write-Host "  [+] Created Agent.md" -ForegroundColor Green
}

# 2. Copy or update pre-commit config (ensuring branch protection hooks)
$TargetPreCommit = Join-Path $ResolvedTarget ".pre-commit-config.yaml"
$SourcePreCommit = Join-Path $ScriptDir ".pre-commit-config.yaml"
if (Test-Path $SourcePreCommit) {
    if (-not (Test-Path $TargetPreCommit)) {
        Copy-Item -Path $SourcePreCommit -Destination $TargetPreCommit -Force
        Write-Host "  [+] Created .pre-commit-config.yaml (Branch protection active)" -ForegroundColor Green
    } else {
        $content = Get-Content $TargetPreCommit -Raw -ErrorAction SilentlyContinue
        if ($content -notmatch "no-commit-to-branch") {
            Copy-Item -Path $SourcePreCommit -Destination $TargetPreCommit -Force
            Write-Host "  [+] Updated .pre-commit-config.yaml with no-commit-to-branch protection" -ForegroundColor Green
        }
    }
}

# 3. Copy sample orchestrator plan
$TargetExamples = Join-Path $ResolvedTarget "examples"
if (-not (Test-Path $TargetExamples)) {
    New-Item -ItemType Directory -Path $TargetExamples -Force | Out-Null
}
$TargetPlan = Join-Path $TargetExamples "orchestrator_plan.yaml"
$SourcePlan = Join-Path $ScriptDir "examples\orchestrator_plan.yaml"
if ((-not (Test-Path $TargetPlan)) -and (Test-Path $SourcePlan)) {
    Copy-Item -Path $SourcePlan -Destination $TargetPlan -Force
    Write-Host "  [+] Created examples/orchestrator_plan.yaml" -ForegroundColor Green
}

# 4. Copy SDLC Agent Skills
$SourceAgents = Join-Path $ScriptDir ".agents"
$TargetAgents = Join-Path $ResolvedTarget ".agents"
if (Test-Path $SourceAgents) {
    Copy-Item -Path $SourceAgents -Destination $TargetAgents -Recurse -Force
    Write-Host "  [+] Copied SDLC Skills to .agents\skills\" -ForegroundColor Green
}

# 5. Initialize 3-tier planning directories
$PlanDirs = @(
    ".runs",
    ".ai\plan",
    ".ai\plans",
    ".ai\decisions",
    ".ai\context"
)
foreach ($dir in $PlanDirs) {
    $fullDir = Join-Path $ResolvedTarget $dir
    if (-not (Test-Path $fullDir)) {
        New-Item -ItemType Directory -Path $fullDir -Force | Out-Null
    }
}
Write-Host "  [+] Initialized planning directories (.runs/, .ai/plan/, .ai/decisions/, .ai/context/)" -ForegroundColor Green

# 6. Ensure .gitignore has critical AI orchestrator entries
$TargetGitignore = Join-Path $ResolvedTarget ".gitignore"
$GitignoreEntries = @(
    "# AI Orchestrator & Plans",
    ".agents/",
    ".runs/",
    ".ai/",
    "AGENTS.md"
)
if (-not (Test-Path $TargetGitignore)) {
    $SourceGitignore = Join-Path $ScriptDir ".gitignore"
    if (Test-Path $SourceGitignore) {
        Copy-Item -Path $SourceGitignore -Destination $TargetGitignore -Force
        Write-Host "  [+] Created .gitignore from template" -ForegroundColor Green
    } else {
        Set-Content -Path $TargetGitignore -Value ($GitignoreEntries -join "`n") -Encoding utf8
        Write-Host "  [+] Created .gitignore" -ForegroundColor Green
    }
} else {
    $currentGitignore = Get-Content $TargetGitignore -Raw -ErrorAction SilentlyContinue
    $toAppend = @()
    foreach ($entry in $GitignoreEntries) {
        if ($currentGitignore -notmatch [regex]::Escape($entry)) {
            $toAppend += $entry
        }
    }
    if ($toAppend.Count -gt 0) {
        Add-Content -Path $TargetGitignore -Value ("`n" + ($toAppend -join "`n")) -Encoding utf8
        Write-Host "  [+] Updated .gitignore with AI rules" -ForegroundColor Green
    }
}

# 7. Register project in ~/.harness/projects.json
try {
    $HarnessDir = Join-Path $env:USERPROFILE ".harness"
    if (-not (Test-Path $HarnessDir)) {
        New-Item -ItemType Directory -Path $HarnessDir -Force | Out-Null
    }
    $RegistryFile = Join-Path $HarnessDir "projects.json"
    $ProjectList = @()
    if (Test-Path $RegistryFile) {
        $raw = Get-Content $RegistryFile -Raw -ErrorAction SilentlyContinue
        if ($raw) {
            $ProjectList = @(ConvertFrom-Json $raw)
        }
    }
    if ($ProjectList -notcontains $ResolvedTarget) {
        $ProjectList += $ResolvedTarget
        $ProjectList | ConvertTo-Json | Set-Content $RegistryFile -Encoding utf8
        Write-Host "  [+] Registered in ~/.harness/projects.json for sync updates" -ForegroundColor Green
    }
} catch {
    # Non-critical registration
}

# 8. Install Git Pre-commit Hooks in target if it is a Git repo
$TargetGit = Join-Path $ResolvedTarget ".git"
if (Test-Path $TargetGit) {
    if (Get-Command pre-commit -ErrorAction SilentlyContinue) {
        Push-Location $ResolvedTarget
        try {
            pre-commit install | Out-Null
            Write-Host "  [+] Activated Git pre-commit hooks (Protected branches: main, dev)" -ForegroundColor Green
        } catch {}
        finally {
            Pop-Location
        }
    }
}

Write-Host ""
Write-Host "========================================================================" -ForegroundColor Yellow
Write-Host " Thiet lap hoan tat! agy-cli da san sang trong: $ResolvedTarget" -ForegroundColor Green
Write-Host "========================================================================" -ForegroundColor Yellow
Write-Host ""
Write-Host "Cac buoc tiep theo trong du an cua ban:"
Write-Host "  1. cd '$ResolvedTarget'"
Write-Host "  2. Chay agy: agy 'Doc file AGENTS.md va bat dau nhiem vu'"
Write-Host "  3. Thao tac Git qua agy: agy 'Tao branch feat/init va commit'"
Write-Host ""
