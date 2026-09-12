import json
from pathlib import Path

import pytest

import research_supervisor as sup


class FakeProcess:
    def __init__(self, code=0, poll_after=0):
        self.returncode = None
        self.code = code
        self.poll_after = poll_after
        self.polls = 0
        self.terminated = False

    def poll(self):
        self.polls += 1
        if self.polls > self.poll_after and self.code is not None:
            self.returncode = self.code
        return self.returncode

    def wait(self, timeout=None):
        if not self.terminated:
            self.returncode = self.code
        return self.code

    def terminate(self):
        self.terminated = True
        self.returncode = -15


def test_success_writes_healthy_status_and_next_due(tmp_path: Path):
    clock = iter([100.0, 100.0, 101.0, 101.0, 1001.0, 1001.0]).__next__
    proc = FakeProcess(0)
    runner_status = tmp_path / "runner.json"
    runner_status.write_text(json.dumps({"status": "ok", "research_only": True}))
    sup.RUNNER_STATUS = runner_status
    result = sup.run_supervisor(
        interval=900, cycle_timeout=300, once=True, status_path=tmp_path / "s.json",
        lock_path=tmp_path / "l", process_factory=lambda *a, **k: proc,
        clock=clock, wall_clock=lambda: 0.0, sleep_fn=lambda _: None,
    )
    assert result["status"] == "healthy"
    assert result["last_success"] is not None
    assert json.loads((tmp_path / "s.json").read_text())["child_pid"] is None


def test_duplicate_runner_is_failed_without_restart(tmp_path: Path):
    calls = []
    proc = FakeProcess(2)
    sup.RUNNER_STATUS = tmp_path / "missing-runner.json"
    result = sup.run_supervisor(
        interval=900, cycle_timeout=300, once=True, status_path=tmp_path / "s.json",
        lock_path=tmp_path / "l", process_factory=lambda *a, **k: calls.append(1) or proc,
        clock=lambda: 1.0, sleep_fn=lambda _: None,
    )
    assert result["status"] == "failed"
    assert len(calls) == 1


def test_timeout_terminates_only_child_and_backoff_is_capped(tmp_path: Path):
    proc = FakeProcess(None, poll_after=100)
    sleeps = []
    times = iter([0.0, 0.0, 0.0, 2.0, 2.0, 2.0])
    result = sup.run_supervisor(
        interval=900, cycle_timeout=1, once=True, status_path=tmp_path / "s.json",
        lock_path=tmp_path / "l", process_factory=lambda *a, **k: proc,
        clock=lambda: next(times, 2.0), sleep_fn=sleeps.append,
    )
    assert result["status"] == "degraded"
    assert proc.terminated
    assert result["consecutive_failures"] == 1


def test_duplicate_supervisor_lock_fails_closed(tmp_path: Path):
    lock = tmp_path / "l"
    with sup.single_instance(lock):
        with pytest.raises(sup.AlreadyRunningError):
            with sup.single_instance(lock):
                pass


def test_keyboard_interrupt_terminates_child(tmp_path: Path):
    proc = FakeProcess(None, poll_after=100)
    def interrupt(_):
        raise KeyboardInterrupt
    with pytest.raises(KeyboardInterrupt):
        sup.run_supervisor(interval=900, cycle_timeout=300, once=True,
            status_path=tmp_path / "s.json", lock_path=tmp_path / "l",
            process_factory=lambda *a, **k: proc, clock=lambda: 1.0,
            sleep_fn=interrupt)
    assert proc.terminated


def test_status_freshness_uses_wall_epoch_not_monotonic(tmp_path: Path, monkeypatch):
    status = tmp_path / "runner.json"
    status.write_text(json.dumps({"status": "ok", "research_only": True}))
    monkeypatch.setattr(sup, "RUNNER_STATUS", status)
    assert sup._fresh_child_status(1.0)
    assert not sup._fresh_child_status(10**12)


def test_spawn_failure_is_durable(tmp_path: Path):
    def spawn(*args, **kwargs):
        raise OSError("missing python")
    result = sup.run_supervisor(once=True, status_path=tmp_path / "s.json",
        lock_path=tmp_path / "l", process_factory=spawn, clock=lambda: 1.0,
        wall_clock=lambda: 2.0, sleep_fn=lambda _: None)
    assert result["status"] == "failed"
    assert "spawn failed" in result["error"]
    assert json.loads((tmp_path / "s.json").read_text())["status"] == "failed"


def test_terminate_ignored_escalates_to_kill():
    class Stubborn:
        returncode = None
        terminated = False
        killed = False
        def poll(self): return self.returncode
        def terminate(self): self.terminated = True
        def kill(self): self.killed = True; self.returncode = -9
        def wait(self, timeout=None): return self.returncode
    child = Stubborn()
    assert sup._stop_child(child)
    assert child.terminated and child.killed


def test_lock_body_error_is_not_reported_as_contention(tmp_path: Path):
    with pytest.raises(OSError, match="body failure"):
        with sup.single_instance(tmp_path / "l"):
            raise OSError("body failure")


def test_main_returns_failure_for_degraded_supervisor(monkeypatch):
    monkeypatch.setattr(sup, "run_supervisor", lambda **kwargs: {"status": "degraded"})
    assert sup.main([]) == 1


def test_stop_request_wrong_run_is_ignored(tmp_path: Path):
    request = tmp_path / "stop"
    request.write_text(json.dumps({"action": "stop", "run_id": "old"}))
    assert not sup._stop_requested(request, "current")


def test_targeted_stop_during_active_child(tmp_path: Path, monkeypatch):
    proc = FakeProcess(None, poll_after=100)
    stop = tmp_path / "stop"
    monkeypatch.setattr(sup, "_fresh_child_status", lambda _: True)
    def spawn(*args, **kwargs):
        run_id = json.loads((tmp_path / "s.json").read_text())["run_id"]
        stop.write_text(json.dumps({"action": "stop", "run_id": run_id}))
        return proc
    result = sup.run_supervisor(once=True, status_path=tmp_path / "s.json",
        lock_path=tmp_path / "l", stop_path=stop, process_factory=spawn,
        clock=lambda: 1.0, wall_clock=lambda: 2.0, sleep_fn=lambda _: None)
    assert result["status"] == "stopped"
    assert proc.terminated


def test_unreaped_timeout_is_failed_and_not_restarted(tmp_path: Path):
    class Unreaped:
        pid = 4242
        returncode = None
        def poll(self): return None
        def terminate(self): pass
        def kill(self): pass
        def wait(self, timeout=None): pass
    calls = []
    ticks = iter([0.0, 0.0, 0.0, 2.0, 2.0, 2.0])
    result = sup.run_supervisor(interval=1, cycle_timeout=1, status_path=tmp_path / "s.json",
        lock_path=tmp_path / "l", process_factory=lambda *a, **k: calls.append(1) or Unreaped(),
        clock=lambda: next(ticks, 2.0), wall_clock=lambda: 3.0, sleep_fn=lambda _: None)
    assert result["status"] == "failed"
    assert result["child_pid"] == 4242
    assert calls == [1]
