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
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

# 1. Ask for project name if not provided
if (-not $ProjectName -and -not $TargetDir) {
    Write-Host "=== THIET LAP REPO MOI CHO HARNESS AGENT ===" -ForegroundColor Cyan
    $ProjectName = Read-Host "Nhap ten du an cua ban (vi du: my-awesome-project)"
    while ([string]::IsNullOrWhiteSpace($ProjectName)) {
        $ProjectName = Read-Host "Ten du an khong duoc de trong. Vui long nhap lai"
    }
}

# Determine target directory
if (-not $TargetDir) {
    $TargetDir = Join-Path ".." $ProjectName
}

# 2. Check if project directory already exists
$Exists = Test-Path $TargetDir
if ($Exists) {
    $ResolvedTarget = (Resolve-Path $TargetDir).Path
    Write-Host "`n[CANH BAO] Thu muc du an '$ResolvedTarget' DA TON TAI tren may!" -ForegroundColor Yellow
    if (-not $Force) {
        Write-Host "Chon hanh dong:"
        Write-Host "  [1] Cap nhat / Bo sung quy chuan (Agent.md, skills) vao du an hien co (Khong xoa code cu)" -ForegroundColor Green
        Write-Host "  [2] Huy thao tac (Abort)" -ForegroundColor Red
        $Choice = Read-Host "Lua chon cua ban [1/2] (Mac dinh: 1)"
        if ($Choice -eq "2") {
            Write-Host "Da huy qua trinh thiet lap." -ForegroundColor Yellow
            exit 0
        }
    }
    Write-Host "--> Tien hanh bo sung / cap nhat quy chuan vao du an: $ResolvedTarget" -ForegroundColor Cyan
} else {
    New-Item -ItemType Directory -Path $TargetDir -Force | Out-Null
    $ResolvedTarget = (Resolve-Path $TargetDir).Path
    Write-Host "--> Da tao thu muc moi: $ResolvedTarget" -ForegroundColor Green
}

Write-Host "==> Dang sao chep quy tac Harness Agent, SDLC Skills & cau hinh agy-cli vao: $ResolvedTarget" -ForegroundColor Cyan

# 1. Copy compliance and rule files
Copy-Item -Path (Join-Path $ScriptDir "Agent.md") -Destination (Join-Path $ResolvedTarget "Agent.md") -Force
Copy-Item -Path (Join-Path $ScriptDir "AGENTS.md") -Destination (Join-Path $ResolvedTarget "AGENTS.md") -Force
Write-Host "  [+] Created Agent.md and AGENTS.md" -ForegroundColor Green

# 2. Copy pre-commit config if not exists
$TargetPreCommit = Join-Path $ResolvedTarget ".pre-commit-config.yaml"
$SourcePreCommit = Join-Path $ScriptDir ".pre-commit-config.yaml"
if ((-not (Test-Path $TargetPreCommit)) -and (Test-Path $SourcePreCommit)) {
    Copy-Item -Path $SourcePreCommit -Destination $TargetPreCommit -Force
    Write-Host "  [+] Created .pre-commit-config.yaml" -ForegroundColor Green
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

Write-Host ""
Write-Host "========================================================================" -ForegroundColor Yellow
Write-Host " Thiet lap hoan tat! agy-cli da san sang trong: $ResolvedTarget" -ForegroundColor Green
Write-Host "========================================================================" -ForegroundColor Yellow
Write-Host ""
Write-Host "Cac buoc tiep theo trong du an moi cua ban:"
Write-Host "  1. cd '$ResolvedTarget'"
Write-Host "  2. Chay agy: agy 'Doc file AGENTS.md va tom tat quy tac du an nay'"
Write-Host "  3. Thao tac Git qua agy: agy 'Tao branch feat/init va commit'"
Write-Host ""
