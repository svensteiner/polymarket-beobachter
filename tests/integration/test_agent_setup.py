"""Installer refusal paths must never repurpose an existing directory."""
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows installer")


@pytest.mark.parametrize("invalid_target", [False, True])
def test_setup_refuses_missing_lock_or_invalid_target_without_mutation(tmp_path, invalid_target):
    script_root = tmp_path / "project with spaces"
    script_root.mkdir()
    script = script_root / "setup_agentic.ps1"
    shutil.copyfile(ROOT / script.name, script)
    target = script_root / ".venv-agentic-repro"
    if invalid_target:
        shutil.copyfile(ROOT / "requirements-agentic-lock.txt", script_root / "requirements-agentic-lock.txt")
        target.mkdir()
        (target / "keep.txt").write_bytes(b"existing user data")
    before = {str(p.relative_to(script_root)): p.read_bytes() for p in script_root.rglob("*") if p.is_file()}
    run = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                          "-File", str(script)], cwd=tmp_path, capture_output=True, text=True, timeout=20)
    assert run.returncode != 0
    after = {str(p.relative_to(script_root)): p.read_bytes() for p in script_root.rglob("*") if p.is_file()}
    assert after == before
    assert "runtime ready:" not in run.stdout
    if not invalid_target:
        assert not target.exists()
