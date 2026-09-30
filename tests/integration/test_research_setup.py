from __future__ import annotations

import hashlib
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "setup_research.ps1"


def run_setup(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(root / SCRIPT.name),
        ],
        cwd=root,
        text=True,
        capture_output=True,
        timeout=120,
    )


def stage_script(tmp_path: Path) -> Path:
    shutil.copy2(SCRIPT, tmp_path / SCRIPT.name)
    return tmp_path / ".venv-research"


def create_venv(target: Path) -> None:
    result = subprocess.run(["py", "-3.12", "-m", "venv", str(target)], text=True, capture_output=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr


def test_existing_non_venv_is_rejected_without_mutation(tmp_path: Path) -> None:
    target = stage_script(tmp_path)
    target.mkdir()
    marker = target / "keep.txt"
    marker.write_text("untouched", encoding="utf-8")
    before = hashlib.sha256(marker.read_bytes()).digest()

    result = run_setup(tmp_path)

    assert result.returncode != 0
    assert "refusing to modify" in " ".join((result.stdout + result.stderr).lower().split())
    assert marker.read_bytes() and hashlib.sha256(marker.read_bytes()).digest() == before


def test_existing_nonisolated_interpreter_is_rejected_without_mutation(tmp_path: Path) -> None:
    if shutil.which("py") is None:
        pytest.skip("Python launcher is unavailable")
    target = stage_script(tmp_path)
    create_venv(target)
    cfg = target / "pyvenv.cfg"
    cfg.write_text(cfg.read_text(encoding="utf-8").replace("include-system-site-packages = false", "include-system-site-packages = true"), encoding="utf-8")
    before = hashlib.sha256(cfg.read_bytes()).digest()

    result = run_setup(tmp_path)

    assert result.returncode != 0
    assert "include-system-site-packages" in (result.stdout + result.stderr).lower()
    assert hashlib.sha256(cfg.read_bytes()).digest() == before


@pytest.mark.parametrize("replacement", [
    "include-system-site-packages = false\ninclude-system-site-packages = true",
    "include-system-site-packages-extra = false",
])
def test_duplicate_or_lookalike_config_keys_are_rejected(tmp_path: Path, replacement: str) -> None:
    if shutil.which("py") is None:
        pytest.skip("Python launcher is unavailable")
    target = stage_script(tmp_path)
    create_venv(target)
    cfg = target / "pyvenv.cfg"
    cfg.write_text(cfg.read_text(encoding="utf-8").replace("include-system-site-packages = false", replacement), encoding="utf-8")

    result = run_setup(tmp_path)

    assert result.returncode != 0
    assert "include-system-site-packages" in (result.stdout + result.stderr).lower()


def test_unnamed_distribution_is_rejected_without_mutation(tmp_path: Path) -> None:
    if shutil.which("py") is None:
        pytest.skip("Python launcher is unavailable")
    target = stage_script(tmp_path)
    create_venv(target)
    metadata_dir = target / "Lib" / "site-packages" / "mystery-1.0.dist-info"
    metadata_dir.mkdir()
    metadata = metadata_dir / "METADATA"
    metadata.write_text("Version: 1.0\n", encoding="utf-8")
    before = hashlib.sha256(metadata.read_bytes()).digest()

    result = run_setup(tmp_path)

    assert result.returncode != 0
    assert "unnamed" in (result.stdout + result.stderr).lower()
    assert hashlib.sha256(metadata.read_bytes()).digest() == before


def test_reparse_point_target_is_rejected(tmp_path: Path) -> None:
    if shutil.which("py") is None:
        pytest.skip("Python launcher is unavailable")
    target = stage_script(tmp_path)
    real = tmp_path / "real-venv"
    real.mkdir()
    command = ["powershell", "-NoProfile", "-Command", "New-Item", "-ItemType", "Junction", "-Path", str(target), "-Target", str(real)]
    result = subprocess.run(command, text=True, capture_output=True, timeout=30)
    if result.returncode != 0:
        pytest.skip("junction creation is unavailable")

    result = run_setup(tmp_path)

    assert result.returncode != 0
    assert "reparse point" in (result.stdout + result.stderr).lower()


def test_missing_target_is_created_and_second_run_only_verifies(tmp_path: Path) -> None:
    if shutil.which("py") is None:
        pytest.skip("Python launcher is unavailable")
    target = stage_script(tmp_path)
    (tmp_path / "analytics").mkdir()
    (tmp_path / "analytics" / "__init__.py").write_text("", encoding="utf-8")
    for module in ("market_universe", "execution_scan", "implication_scan"):
        (tmp_path / "analytics" / f"{module}.py").write_text("", encoding="utf-8")
    (tmp_path / "research_runner.py").write_text("", encoding="utf-8")

    first = run_setup(tmp_path)
    assert first.returncode == 0, first.stdout + first.stderr
    python = target / "Scripts" / "python.exe"
    assert python.is_file()
    cfg_before = (target / "pyvenv.cfg").read_bytes()
    second = run_setup(tmp_path)
    assert second.returncode == 0, second.stdout + second.stderr
    assert (target / "pyvenv.cfg").read_bytes() == cfg_before
