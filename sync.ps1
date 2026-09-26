<#
.SYNOPSIS
    Synchronize Agent.md, AGENTS.md, and SDLC skills from harness_agent to working repositories.

.EXAMPLE
    .\sync.ps1 -TargetDir "..\du-an-moi"
    .\sync.ps1 -All
    .\sync.ps1 -TargetDir "..\du-an-moi" -Link
#>

param (
    [Parameter(Position = 0)]
    [string]$TargetDir = "",

    [switch]$All,
    [switch]$Link
)

$ErrorActionPreference = "Stop"
$env:PYTHONIOENCODING = "utf-8"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

# Run via python CLI
$ArgsList = @("run", "-n", "pytorch", "harness-agent", "sync")

if ($All) {
    $ArgsList += "--all"
} elseif ($TargetDir) {
    $ArgsList += $TargetDir
} else {
    Write-Host "=== DONG BO QUY CHUAN HARNESS AGENT & SDLC SKILLS ===" -ForegroundColor Cyan
    Write-Host "Chon che do dong bo:"
    Write-Host "  [1] Dong bo tat ca cac du an da dang ky (--all)" -ForegroundColor Green
    Write-Host "  [2] Nhap duong dan du an cu the" -ForegroundColor Yellow
    $Choice = Read-Host "Lua chon cua ban [1/2] (Mac dinh: 1)"
    if ($Choice -eq "2") {
        $CustomPath = Read-Host "Nhap duong dan du an (vi du: ..\du-an-moi)"
        $ArgsList += $CustomPath
    } else {
        $ArgsList += "--all"
    }
}

if ($Link) {
    $ArgsList += "--link"
}

Write-Host "Dang thuc hien dong bo..." -ForegroundColor Cyan
& conda @ArgsList
