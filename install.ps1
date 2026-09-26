<#
.SYNOPSIS
    Harness Agent Scaffolding Script for Windows PowerShell.
    Copies Agent.md, AGENTS.md, and workflow templates to a new target repository.

.EXAMPLE
    .\install.ps1 -TargetDir "..\my-new-project"
#>

[CmdletBinding()]
param (
    [Parameter(Position = 0)]
    [string]$TargetDir = "."
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

# Resolve target directory
if (-not (Test-Path $TargetDir)) {
    New-Item -ItemType Directory -Path $TargetDir -Force | Out-Null
}
$ResolvedTarget = (Resolve-Path $TargetDir).Path

Write-Host "==> Setting up Harness Agent & agy-cli rules in: $ResolvedTarget" -ForegroundColor Cyan

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

Write-Host ""
Write-Host "========================================================================" -ForegroundColor Yellow
Write-Host " Setup complete! agy-cli is now ready in: $ResolvedTarget" -ForegroundColor Green
Write-Host "========================================================================" -ForegroundColor Yellow
Write-Host ""
Write-Host "Next steps in your new project:"
Write-Host "  1. cd '$ResolvedTarget'"
Write-Host "  2. Run agy: agy 'Doc file AGENTS.md va tom tat quy tac du an nay'"
Write-Host "  3. Use agy directly for Git: agy 'Tao branch feat/init va commit'"
Write-Host ""
