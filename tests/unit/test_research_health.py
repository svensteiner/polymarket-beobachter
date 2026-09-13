import json
import math
from pathlib import Path

import research_health as health


def write_status(path: Path, **overrides):
    data = {"status": "healthy", "updated_at": 1000.0, "next_due": 1900.0,
            "started_at": 1000.0, "run_id": "run-1", "supervisor_pid": 10,
            "child_pid": None}
    data.update(overrides)
    path.write_text(json.dumps(data), encoding="utf-8")


def test_healthy_waiting_until_next_due(tmp_path: Path):
    path = tmp_path / "s.json"
    write_status(path)
    result = health.evaluate(path, now=1800.0,
        process_probe=lambda pid: {"alive": True, "commandline": "python research_supervisor.py"})
    assert result["state"] == "healthy" and result["exit_code"] == 0


def test_healthy_overdue_is_stale(tmp_path: Path):
    path = tmp_path / "s.json"
    write_status(path, next_due=1900.0)
    result = health.evaluate(path, now=1931.0,
        process_probe=lambda pid: {"alive": True, "commandline": "python research_supervisor.py"})
    assert result["state"] == "stale" and result["exit_code"] == 1


def test_running_child_requires_identity_and_deadline(tmp_path: Path):
    path = tmp_path / "s.json"
    write_status(path, status="running", updated_at=1100.0, started_at=1000.0, child_pid=44)
    result = health.evaluate(path, now=1200.0,
        process_probe=lambda pid: {"alive": True, "commandline": "python research_supervisor.py" if pid == 10 else "python research_runner.py --once"})
    assert result["state"] == "running" and result["exit_code"] == 0
    result = health.evaluate(path, now=1301.0,
        process_probe=lambda pid: {"alive": True, "commandline": "python research_supervisor.py" if pid == 10 else "python research_runner.py --once"})
    assert result["state"] == "stale" and result["exit_code"] == 1


def test_dead_or_wrong_process_is_unknown(tmp_path: Path):
    path = tmp_path / "s.json"
    write_status(path, status="running", child_pid=44)
    result = health.evaluate(path, now=1100.0, process_probe=lambda _: {"alive": True, "commandline": "python research_supervisor.py"})
    assert result["state"] == "unknown" and result["exit_code"] == 2
    result = health.evaluate(path, now=1100.0,
        process_probe=lambda _: {"alive": True, "commandline": "python other.py"})
    assert result["state"] == "unknown" and result["exit_code"] == 2


def test_corrupt_and_future_status_are_unknown(tmp_path: Path):
    path = tmp_path / "s.json"
    path.write_text("{", encoding="utf-8")
    assert health.evaluate(path, now=1000.0)["exit_code"] == 2
    write_status(path, updated_at=2000.0)
    assert health.evaluate(path, now=1000.0)["state"] == "unknown"


def test_failed_stopped_and_missing_are_unhealthy_or_unknown(tmp_path: Path):
    path = tmp_path / "s.json"
    write_status(path, status="failed")
    assert health.evaluate(path, now=1100.0,
        process_probe=lambda _: {"alive": True, "commandline": "python research_supervisor.py"})["exit_code"] == 1
    write_status(path, status="stopped")
    assert health.evaluate(path, now=1100.0,
        process_probe=lambda _: {"alive": True, "commandline": "python research_supervisor.py"})["exit_code"] == 1
    assert health.evaluate(tmp_path / "missing.json", now=1100.0)["exit_code"] == 2


def test_oversized_status_is_unknown_without_unbounded_read(tmp_path: Path):
    path = tmp_path / "s.json"
    path.write_bytes(b"x" * (health.MAX_STATUS_BYTES + 1))
    result = health.evaluate(path, now=1100.0)
    assert result["reason"] == "missing_or_corrupt_status"
    assert result["exit_code"] == 2


def test_healthy_with_dead_supervisor_is_unknown(tmp_path: Path):
    path = tmp_path / "s.json"
    write_status(path)
    result = health.evaluate(path, now=1100.0, process_probe=lambda _: {"alive": False})
    assert result["state"] == "unknown"
    assert result["reason"] == "supervisor_identity_mismatch"


def test_windows_probe_normalizes_cim_field_names(monkeypatch):
    class Completed:
        returncode = 0
        stdout = '{"ExecutablePath":"C:/Python/python.exe","CommandLine":"python research_supervisor.py"}'
    monkeypatch.setattr(health.os, "name", "nt")
    monkeypatch.setattr(health.subprocess, "run", lambda *args, **kwargs: Completed())
    result = health._probe(42)
    assert result["alive"] is True
    assert result["commandline"].endswith("research_supervisor.py")
    assert result["executable"].endswith("python.exe")


def test_nonfinite_started_at_is_unknown(tmp_path: Path):
    path = tmp_path / "s.json"
    for value in (math.nan, math.inf, -math.inf):
        write_status(path, status="running", child_pid=44, started_at=value)
        result = health.evaluate(path, now=1100.0,
            process_probe=lambda pid: {"alive": True, "commandline": "python research_supervisor.py"})
        assert result["reason"] == "invalid_started_at"
        assert result["exit_code"] == 2


def test_non_string_status_is_unknown(tmp_path: Path):
    path = tmp_path / "s.json"
    for value in ([], {}):
        write_status(path, status=value)
        result = health.evaluate(path, now=1100.0)
        assert result == {"state": "unknown", "reason": "invalid_status", "exit_code": 2}
