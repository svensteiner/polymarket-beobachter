import json
import subprocess
import sys
import math
from contextlib import contextmanager
from pathlib import Path

import research_control as control
from research_supervisor import single_instance, AlreadyRunningError


class Proc:
    pid = 123
    def __init__(self): self.code = None
    def poll(self): return self.code


def test_timeout_does_not_retry_or_terminate(tmp_path):
    now = [0.0]
    calls = []
    proc = Proc()
    def spawn(*args, **kwargs):
        calls.append(args)
        return proc
    def sleep(seconds):
        now[0] += seconds
    result = control.start(status_path=tmp_path / "missing", lock_path=tmp_path / "lock",
        process_factory=spawn, clock=lambda: now[0], sleep_fn=sleep, wait_timeout=0.5)
    assert result["state"] == "starting_unknown"
    assert len(calls) == 1 and proc.poll() is None


def test_early_exit_is_not_success(tmp_path):
    proc = Proc()
    proc.code = 2
    result = control.start(status_path=tmp_path / "missing", lock_path=tmp_path / "lock",
        process_factory=lambda *a, **kw: proc)
    assert result["state"] == "failed" and result["exit_code"] == 1


def test_healthy_file_without_lock_is_not_success(tmp_path):
    path = tmp_path / "status.json"
    def spawn(*args, **kwargs):
        path.write_text(json.dumps({"run_id": "new", "status": "healthy"}))
        return Proc()
    result = control.start(status_path=path, lock_path=tmp_path / "lock",
        process_factory=spawn, health_fn=lambda _: {"state": "healthy", "exit_code": 0})
    assert result["state"] == "lock_lost" and result["exit_code"] == 2


def test_status_delegates_health(tmp_path: Path):
    seen = []
    result = control.status(tmp_path / "s", health_fn=lambda p: seen.append(p) or {"state": "healthy", "exit_code": 0})
    assert result["action"] == "status" and result["state"] == "healthy" and seen


def test_start_launches_exact_supervisor_and_accepts_fresh_status(tmp_path: Path):
    status = tmp_path / "status.json"; status.write_text(json.dumps({"run_id": "old"}))
    proc = Proc(); calls = []
    checks = [0]
    @contextmanager
    def fake_lock(_):
        checks[0] += 1
        if checks[0] > 1: raise AlreadyRunningError("held")
        yield
    original = control.single_instance
    control.single_instance = fake_lock
    def spawn(command, **kwargs):
        calls.append((command, kwargs))
        status.write_text(json.dumps({"run_id": "new", "status": "healthy"}))
        return proc
    try:
        result = control.start(status_path=status, lock_path=tmp_path / "lock", process_factory=spawn,
            health_fn=lambda _: {"state": "healthy", "exit_code": 0}, clock=lambda: 0.0,
            sleep_fn=lambda _: None)
    finally:
        control.single_instance = original
    assert result["state"] == "started"
    assert calls[0][0] == [sys.executable, str(control.SUPERVISOR_PATH)]
    assert calls[0][1]["cwd"] == str(control.ROOT)


def test_start_duplicate_lock_does_not_spawn(tmp_path: Path):
    with single_instance(tmp_path / "lock"):
        result = control.start(status_path=tmp_path / "status", lock_path=tmp_path / "lock",
            process_factory=lambda *a, **k: (_ for _ in ()).throw(AssertionError()))
    assert result["state"] == "already_running"


def test_cli_status_from_foreign_cwd_is_json(tmp_path: Path):
    command = [sys.executable, str(control.ROOT / "research_control.py"),
               "--status-path", str(tmp_path / "missing.json"), "status"]
    result = subprocess.run(command, cwd=tmp_path, capture_output=True, text=True, check=False)
    assert result.returncode == 2 and json.loads(result.stdout)["state"] == "unknown"


def test_start_rejects_nonfinite_wait_timeout(tmp_path: Path):
    for value in (math.nan, math.inf):
        try: control.start(lock_path=tmp_path / "l", wait_timeout=value)
        except ValueError: pass
        else: raise AssertionError("nonfinite timeout accepted")


def test_start_spawn_failure_is_structured(tmp_path: Path):
    def spawn(*args, **kwargs): raise OSError("no runtime")
    result = control.start(status_path=tmp_path / "s", lock_path=tmp_path / "l", process_factory=spawn)
    assert result["state"] == "failed" and result["exit_code"] == 1
