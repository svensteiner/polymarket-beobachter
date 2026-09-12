$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$venv = Join-Path $root '.venv-research'
if (-not (Test-Path (Join-Path $venv 'Scripts\python.exe'))) {
    py -3.12 -m venv $venv
    if ($LASTEXITCODE -ne 0) { throw 'Research environment creation failed' }
}
$python = Join-Path $venv 'Scripts\python.exe'
Push-Location -LiteralPath $root
try {
    & $python -c "import research_runner, analytics.market_universe, analytics.execution_scan, analytics.implication_scan; print('runner closure OK')"
    if ($LASTEXITCODE -ne 0) { throw 'Research runtime import verification failed' }
} finally {
    Pop-Location
}
Write-Host "Research runtime ready: $python"
