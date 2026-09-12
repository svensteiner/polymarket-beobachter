"""Bounded supervisor for the read-only research runner."""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Callable

ROOT = Path(__file__).resolve().parent
STATUS_PATH = ROOT / "output" / "research_supervisor.json"
RUNNER_STATUS = ROOT / "output" / "research_status.json"
LOCK_PATH = ROOT / "output" / "research_supervisor.lock"
STOP_REQUEST = ROOT / "output" / "research_supervisor.stop"
DEFAULT_INTERVAL = 900.0
DEFAULT_TIMEOUT = 300.0
MAX_BACKOFF = 3600.0


class AlreadyRunningError(RuntimeError):
    pass


@contextmanager
def single_instance(path: Path = LOCK_PATH) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+b")
    try:
        if os.name == "nt":
            import msvcrt
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"0")
            handle.seek(0); handle.flush()
            try: msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc: raise AlreadyRunningError("research supervisor is already running") from exc
        else:
            import fcntl
            try: fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc: raise AlreadyRunningError("research supervisor is already running") from exc
        yield
    except ImportError as exc:
        raise RuntimeError("platform locking unavailable") from exc
    finally:
        try:
            if os.name == "nt":
                handle.seek(0); msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except (OSError, UnboundLocalError):
            pass
        handle.close()


def _write(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _fresh_child_status(started: float) -> bool:
    try:
        if RUNNER_STATUS.stat().st_mtime < started:
            return False
        payload = json.loads(RUNNER_STATUS.read_text(encoding="utf-8"))
        return payload.get("status") == "ok" and payload.get("research_only") is True
    except (OSError, ValueError, TypeError):
        return False


def _stop_child(child: Any) -> bool:
    if child.poll() is not None:
        return True
    try: child.terminate()
    except Exception: pass
    try: child.wait(timeout=5)
    except Exception: pass
    if child.poll() is None:
        try: child.kill()
        except Exception: pass
        try: child.wait(timeout=5)
        except Exception: pass
    return child.poll() is not None


def _stop_requested(path: Path, run_id: str) -> bool:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data.get("run_id") == run_id and data.get("action") == "stop"
    except (OSError, ValueError, TypeError):
        return False


def run_supervisor(*, interval: float = DEFAULT_INTERVAL, cycle_timeout: float = DEFAULT_TIMEOUT,
                   once: bool = False, status_path: Path = STATUS_PATH, lock_path: Path = LOCK_PATH,
                   process_factory: Callable[..., Any] = subprocess.Popen,
                   clock: Callable[[], float] = time.monotonic,
                   wall_clock: Callable[[], float] = time.time,
                   stop_path: Path = STOP_REQUEST,
                   sleep_fn: Callable[[float], None] = time.sleep) -> dict[str, Any]:
    if not all(isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0 and v < float("inf")
               for v in (interval, cycle_timeout)):
        raise ValueError("interval and cycle_timeout must be positive")
    failures = 0
    next_due = clock()
    last_success = None
    run_id = uuid.uuid4().hex
    supervisor_pid = os.getpid()
    with single_instance(lock_path):
        while True:
            now = clock()
            if now < next_due:
                while now < next_due:
                    if _stop_requested(stop_path, run_id):
                        state = {"status": "stopped", "child_pid": None, "supervisor_pid": supervisor_pid,
                                 "run_id": run_id, "started_at": None, "last_success": last_success,
                                 "consecutive_failures": failures, "next_due": wall_clock(), "updated_at": wall_clock()}
                        _write(status_path, state); return state
                    sleep_fn(min(1.0, next_due - now)); now = clock()
            started = clock(); started_wall = wall_clock()
            state: dict[str, Any] = {"status": "starting", "child_pid": None,
                "supervisor_pid": supervisor_pid, "run_id": run_id, "started_at": started_wall,
                "last_success": last_success, "consecutive_failures": failures,
                "next_due": wall_clock(), "updated_at": wall_clock()}
            _write(status_path, state)
            try:
                child = process_factory([sys.executable, str(ROOT / "research_runner.py"), "--once"], cwd=str(ROOT))
            except Exception as exc:
                failures += 1
                state.update(status="failed", error=f"spawn failed: {type(exc).__name__}: {exc}",
                             consecutive_failures=failures, next_due=wall_clock() + min(interval * (2 ** min(failures, 4)), MAX_BACKOFF))
                _write(status_path, state)
                if once: return state
                next_due = clock() + min(interval * (2 ** min(failures, 4)), MAX_BACKOFF); continue
            state.update(status="running", child_pid=getattr(child, "pid", None), updated_at=wall_clock())
            try:
                _write(status_path, state)
            except Exception as exc:
                _stop_child(child)
                state.update(status="failed", error=f"status write failed: {type(exc).__name__}: {exc}")
                _write(status_path, state)
                return state
            try:
                while child.poll() is None and clock() - started < cycle_timeout:
                    if _stop_requested(stop_path, run_id):
                        reaped = _stop_child(child)
                        state.update(status="stopped" if reaped else "failed",
                                     child_pid=None if reaped else getattr(child, "pid", None),
                                     updated_at=wall_clock())
                        if not reaped:
                            state["error"] = "stop requested but child was not reaped"
                        _write(status_path, state); return state
                    sleep_fn(min(1.0, max(0.0, cycle_timeout - (clock() - started))))
            except KeyboardInterrupt:
                _stop_child(child)
                raise
            if child.poll() is None:
                result_status = "degraded" if _stop_child(child) else "failed"; failures += 1
            else:
                code = child.returncode
                if code == 2:
                    result_status = "failed"; failures += 1
                elif code == 0 and _fresh_child_status(started_wall):
                    result_status = "healthy"; failures = 0
                else:
                    result_status = "degraded"; failures += 1
            next_due = clock() + min(interval * (2 ** min(failures, 4)), MAX_BACKOFF) if failures else clock() + interval
            state.update(status=result_status, child_pid=getattr(child, "pid", None) if child.poll() is None else None, consecutive_failures=failures,
                         next_due=next_due)
            if result_status == "healthy": last_success = wall_clock()
            state["last_success"] = last_success
            state["next_due"] = wall_clock() + (next_due - clock())
            state["updated_at"] = wall_clock()
            _write(status_path, state)
            if once or result_status == "failed":
                return state
            while clock() < next_due:
                if _stop_requested(stop_path, run_id):
                    state.update(status="stopped", child_pid=None, updated_at=wall_clock())
                    _write(status_path, state); return state
                sleep_fn(min(1.0, next_due - clock()))


def main(argv: list[str] | None = None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stop", action="store_true")
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args(argv)
    if args.stop:
        try:
            data = json.loads(STATUS_PATH.read_text(encoding="utf-8"))
            run_id = data.get("run_id")
            if not isinstance(run_id, str) or not run_id:
                return 1
            _write(STOP_REQUEST, {"action": "stop", "run_id": run_id, "requested_at": time.time()})
            return 0
        except (OSError, ValueError, TypeError):
            return 1
    try:
        result = run_supervisor(once=args.once)
        return 0 if result.get("status") == "healthy" else 1
    except KeyboardInterrupt:
        return 130
    except AlreadyRunningError:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
