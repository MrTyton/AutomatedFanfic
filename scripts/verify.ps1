<#
.SYNOPSIS
    Unified CI verification script. Runs the exact same checks performed in GitHub Actions CI.
.DESCRIPTION
    Runs:
    1. Pre-commit hooks (Black, Ruff, YAML/TOML, whitespace, Pyright)
    2. Explicit Pyright type check (0 errors required)
    3. Full pytest test suite excluding CI-flaky tests
#>
[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Split-Path -Parent $scriptDir

Set-Location $repoRoot

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "Step 1: Running pre-commit hooks..." -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan
pre-commit run --all-files
if ($LASTEXITCODE -ne 0) {
    Write-Error "Pre-commit checks failed! Please fix the formatting/linting issues."
    exit $LASTEXITCODE
}

Write-Host "`n==========================================" -ForegroundColor Cyan
Write-Host "Step 2: Running Pyright type checker..." -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan
npx --yes pyright
if ($LASTEXITCODE -ne 0) {
    Write-Error "Pyright type checking failed! Zero errors are required before pushing."
    exit $LASTEXITCODE
}

Write-Host "`n==========================================" -ForegroundColor Cyan
Write-Host "Step 3: Running pytest suite..." -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan
python -m pytest --tb=short -m "not flaky_ci" -q
if ($LASTEXITCODE -ne 0) {
    Write-Error "Pytest suite failed!"
    exit $LASTEXITCODE
}

Write-Host "`n==========================================" -ForegroundColor Green
Write-Host "All CI verification gates passed cleanly!" -ForegroundColor Green
Write-Host "==========================================" -ForegroundColor Green
exit 0
