$ErrorActionPreference = 'Stop'
$root = [IO.Path]::GetFullPath((Split-Path -Parent $MyInvocation.MyCommand.Path))
$target = [IO.Path]::GetFullPath((Join-Path $root '.venv-research'))
$python = Join-Path $target 'Scripts\python.exe'

function Invoke-PythonCode {
    param([Parameter(Mandatory=$true)][string]$PythonPath, [Parameter(Mandatory=$true)][string]$Code, [string[]]$ArgumentList = @(), [Parameter(Mandatory=$true)][string]$FailureMessage)
    $Code | & $PythonPath -I -B - @ArgumentList
    if ($LASTEXITCODE -ne 0) { throw "$FailureMessage (exit code $LASTEXITCODE)" }
}

$verifyCode = @'
import importlib.metadata as metadata
from pathlib import Path
import sys

target = Path(sys.argv[1]).resolve()
root = Path(sys.argv[2]).resolve()
if sys.version_info[:2] != (3, 12):
    raise SystemExit(f"Python 3.12 required, got {sys.version.split()[0]}")
if Path(sys.prefix).resolve() != target or sys.base_prefix == sys.prefix:
    raise SystemExit(f"Interpreter is not the target virtual environment: {sys.prefix}")
cfg = target / "pyvenv.cfg"
if not cfg.is_file():
    raise SystemExit(f"Missing venv configuration: {cfg}")
include_flags = [line.split("=", 1)[1].strip().lower() for line in cfg.read_text(encoding="utf-8").splitlines() if "=" in line and line.split("=", 1)[0].strip().lower() == "include-system-site-packages"]
if include_flags != ["false"]:
    raise SystemExit("Target venv must have include-system-site-packages = false")
installed = sorted((dist.metadata.get("Name") or "<unnamed>").lower() for dist in metadata.distributions())
if installed != ["pip"]:
    raise SystemExit(f"Research runtime must contain pip only; found {installed}")
sys.path.insert(0, str(root))
import research_runner
import analytics.market_universe
import analytics.execution_scan
import analytics.implication_scan
print(f"Verified isolated Python {sys.version.split()[0]} and runner closure")
'@

try {
    $targetExists = Test-Path -LiteralPath $target
    if ($targetExists -and ((Get-Item -LiteralPath $target).Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw "Target is a reparse point; refusing to verify through an alias: $target" }
    if ($targetExists -and -not (Test-Path -LiteralPath $python -PathType Leaf)) { throw "Target exists but is not a valid Python venv; refusing to modify it: $target" }
    if (-not $targetExists) {
        Write-Host "Creating isolated Python 3.12 environment: $target"
        & py -3.12 -m venv $target
        if ($LASTEXITCODE -ne 0) { throw "Research environment creation failed (exit code $LASTEXITCODE)" }
        if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw "venv creation returned success but Python was not found: $python" }
    } else { Write-Host "Existing research environment found; verifying without installation: $target" }
    Invoke-PythonCode -PythonPath $python -Code $verifyCode -ArgumentList @($target, $root) -FailureMessage 'Research runtime verification failed'
    Write-Host "Research runtime ready: $python"
    exit 0
} catch {
    Write-Error "Research runtime is NOT ready: $($_.Exception.Message)" -ErrorAction Continue
    exit 1
}
