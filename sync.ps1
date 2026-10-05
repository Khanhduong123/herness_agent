<#
.SYNOPSIS
    Synchronize Agent.md, AGENTS.md, SDLC skills, and lifecycle hooks from harness_agent to working repositories.
    Enforces that updates are ONLY applied on the 'main' branch of working projects.

.EXAMPLE
    .\sync.ps1 -TargetDir "..\du-an-moi"
    .\sync.ps1 -All
    .\sync.ps1 -TargetDir "..\du-an-moi" -Link
#>

param (
    [Parameter(Position = 0)]
    [string]$TargetDir = "",

    [switch]$All,
    [switch]$Link,
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$env:PYTHONIOENCODING = "utf-8"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

# Function to verify branch is main
function Test-IsMainBranch([string]$ProjectPath) {
    if (Test-Path (Join-Path $ProjectPath ".git")) {
        try {
            $branch = (git -C $ProjectPath branch --show-current 2>$null).Trim()
            if ($branch -and $branch -ne "main" -and $branch -ne "master") {
                return $branch
            }
        } catch {}
    }
    return $null
}

# 1. Check single target
if ($TargetDir) {
    $resolved = (Resolve-Path $TargetDir -ErrorAction SilentlyContinue)
    if ($resolved) {
        $nonMain = Test-IsMainBranch $resolved.Path
        if ($nonMain -and (-not $Force)) {
            Write-Host "[TU CHOI] Du an '$($resolved.Path)' dang o nhanh '$nonMain'!" -ForegroundColor Red
            Write-Host "QUY TAC: Chi duoc phep update quy chuan & skills tren nhanh 'main' de tranh gay xung dot code tinh nang." -ForegroundColor Yellow
            Write-Host "Huong dan:" -ForegroundColor Cyan
            Write-Host "  1. Chuyen ve nhanh main: cd '$($resolved.Path)' ; git checkout main"
            Write-Host "  2. Chay lai lenh sync tu harness_agent"
            Write-Host "  3. Merge main vao nhanh tinh nang cua ban: git checkout $nonMain ; git merge main"
            exit 1
        }
    }
}

# Run via python CLI
$ArgsList = @("run", "-n", "pytorch", "harness-agent", "sync")

if ($All) {
    $ArgsList += "--all"
} elseif ($TargetDir) {
    $ArgsList += $TargetDir
} else {
    Write-Host "=== DONG BO QUY CHUAN HARNESS AGENT, SDLC SKILLS & LIFECYCLE HOOKS ===" -ForegroundColor Cyan
    Write-Host "Chon che do dong bo:"
    Write-Host "  [1] Dong bo tat ca cac du an da dang ky (--all)" -ForegroundColor Green
    Write-Host "  [2] Nhap duong dan du an cu the" -ForegroundColor Yellow
    $Choice = Read-Host "Lua chon cua ban [1/2] (Mac dinh: 1)"
    if ($Choice -eq "2") {
        $CustomPath = Read-Host "Nhap duong dan du an (vi du: ..\du-an-moi)"
        $resolved = (Resolve-Path $CustomPath -ErrorAction SilentlyContinue)
        if ($resolved) {
            $nonMain = Test-IsMainBranch $resolved.Path
            if ($nonMain -and (-not $Force)) {
                Write-Host "[TU CHOI] Du an '$($resolved.Path)' dang o nhanh '$nonMain'!" -ForegroundColor Red
                Write-Host "Vui long checkout ve nhanh main truoc: git checkout main" -ForegroundColor Yellow
                exit 1
            }
        }
        $ArgsList += $CustomPath
    } else {
        $ArgsList += "--all"
    }
}

if ($Link) {
    $ArgsList += "--link"
}

Write-Host "Dang thuc hien dong bo (Kiem tra an toan nhanh 'main')..." -ForegroundColor Cyan
& conda @ArgsList
