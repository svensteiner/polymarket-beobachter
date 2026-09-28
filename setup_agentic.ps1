$ErrorActionPreference = 'Stop'
$root = [IO.Path]::GetFullPath((Split-Path -Parent $MyInvocation.MyCommand.Path))
$productionVenv = [IO.Path]::GetFullPath((Join-Path $root '.venv-agentic'))
$target = [IO.Path]::GetFullPath((Join-Path $root '.venv-agentic-repro'))
$lock = Join-Path $root 'requirements-agentic-lock.txt'
$python = Join-Path $target 'Scripts\python.exe'

function Invoke-Native {
    param([Parameter(Mandatory=$true)][string]$FilePath, [string[]]$ArgumentList = @(), [Parameter(Mandatory=$true)][string]$FailureMessage)
    & $FilePath @ArgumentList
    if ($LASTEXITCODE -ne 0) { throw "$FailureMessage (exit code $LASTEXITCODE)" }
}
function Invoke-PythonCode {
    param([Parameter(Mandatory=$true)][string]$PythonPath, [Parameter(Mandatory=$true)][string]$Code, [string[]]$ArgumentList = @(), [Parameter(Mandatory=$true)][string]$FailureMessage)
    $Code | & $PythonPath - @ArgumentList
    if ($LASTEXITCODE -ne 0) { throw "$FailureMessage (exit code $LASTEXITCODE)" }
}

try {
    if (-not (Test-Path -LiteralPath $lock -PathType Leaf)) { throw "Lock file missing: $lock" }
    if ($target -eq $productionVenv) { throw 'Refusing to use the production .venv-agentic directory.' }
    $targetExists = Test-Path -LiteralPath $target
    if ($targetExists -and -not (Test-Path -LiteralPath $python -PathType Leaf)) { throw "Target exists but is not a valid Python venv; refusing to modify it: $target" }
    if (-not $targetExists) {
        Write-Host "Creating isolated Python 3.12 environment: $target"
        Invoke-Native -FilePath 'py' -ArgumentList @('-3.12','-m','venv',$target) -FailureMessage 'Python 3.12 venv creation failed'
        if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw "venv creation returned success but Python was not found: $python" }
        Write-Host 'Installing the pinned SDK closure (binary wheels only)...'
        Invoke-Native -FilePath $python -ArgumentList @('-m','pip','install','--disable-pip-version-check','--no-input','--only-binary=:all:','--timeout','30','--retries','1','-r',$lock) -FailureMessage 'Pinned SDK installation failed'
    } else { Write-Host "Existing reproducible environment found; verifying without installation: $target" }
    Invoke-Native -FilePath $python -ArgumentList @('-m','pip','check') -FailureMessage 'pip check failed'
    $verifyCode = @'
import importlib.metadata as metadata
import os
from pathlib import Path
import re
import sys

lock_path = Path(sys.argv[1]).resolve()
target = Path(sys.argv[2]).resolve()
def canonical(name):
    return re.sub(r"[-_.]+", "-", name).lower()
expected = {}
for number, raw in enumerate(lock_path.read_text(encoding="utf-8").splitlines(), 1):
    line = raw.strip()
    if not line or line.startswith("#"):
        continue
    match = re.fullmatch(r"([A-Za-z0-9_.-]+)==([^\s#]+)", line)
    if not match:
        raise SystemExit(f"Invalid lock entry on line {number}: {raw}")
    name, version = canonical(match.group(1)), match.group(2)
    if name in expected:
        raise SystemExit(f"Duplicate lock entry: {name}")
    expected[name] = version
if sys.version_info[:2] != (3, 12):
    raise SystemExit(f"Python 3.12 required, got {sys.version.split()[0]}")
if Path(sys.prefix).resolve() != target or sys.base_prefix == sys.prefix:
    raise SystemExit(f"Interpreter is not the target virtual environment: {sys.prefix}")
venv_cfg = target / "pyvenv.cfg"
if not venv_cfg.is_file() or not any(line.strip().lower() == "include-system-site-packages = false" for line in venv_cfg.read_text(encoding="utf-8").splitlines()):
    raise SystemExit("Target venv must have include-system-site-packages = false")
installed = {}
for distribution in metadata.distributions():
    name = distribution.metadata.get("Name")
    if name:
        installed[canonical(name)] = distribution.version
installed.pop("pip", None)
if installed != expected:
    missing = sorted(set(expected) - set(installed))
    extra = sorted(set(installed) - set(expected))
    wrong = sorted(name for name in set(expected) & set(installed) if expected[name] != installed[name])
    raise SystemExit(f"Lock mismatch: missing={missing}, extra={extra}, wrong={wrong}")
print(f"Verified isolated Python {sys.version.split()[0]} and {len(expected)} locked distributions")
'@
    Invoke-PythonCode -PythonPath $python -Code $verifyCode -ArgumentList @($lock,$target) -FailureMessage 'Pinned SDK version/closure verification failed'
    Write-Host "Agentic reproducible runtime ready: $python"
    exit 0
} catch {
    Write-Error "Agentic reproducible runtime is NOT ready: $($_.Exception.Message)" -ErrorAction Continue
    exit 1
}
