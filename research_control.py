"""Bounded, read-only status and start control for research_supervisor."""
from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable

import research_health
from research_supervisor import AlreadyRunningError, LOCK_PATH, ROOT, single_instance

STATUS_PATH = ROOT / "output" / "research_supervisor.json"
SUPERVISOR_PATH = ROOT / "research_supervisor.py"


def _read(path: Path) -> dict[str, Any] | None:
    try:
        with path.open("rb") as handle: raw = handle.read(64 * 1024 + 1)
        if len(raw) > 64 * 1024: return None
        data = json.loads(raw.decode("utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None


def status(status_path: Path = STATUS_PATH, health_fn: Callable[..., dict[str, Any]] = research_health.evaluate) -> dict[str, Any]:
    result = health_fn(status_path)
    return {"action": "status", **result}


def start(*, status_path: Path = STATUS_PATH, lock_path: Path = LOCK_PATH,
          process_factory: Callable[..., Any] = subprocess.Popen,
          health_fn: Callable[..., dict[str, Any]] = research_health.evaluate,
          clock: Callable[[], float] = time.monotonic,
          sleep_fn: Callable[[float], None] = time.sleep,
          wait_timeout: float = 20.0) -> dict[str, Any]:
    if (not isinstance(wait_timeout, (int, float)) or isinstance(wait_timeout, bool) or
            not math.isfinite(wait_timeout) or wait_timeout <= 0 or wait_timeout > 60):
        raise ValueError("invalid wait timeout")
    before = _read(status_path) or {}
    prior_run = before.get("run_id")
    try:
        with single_instance(lock_path):
            pass
    except AlreadyRunningError:
        health = health_fn(status_path)
        return {"action": "start", **health, "state": "already_running",
                "exit_code": 0 if health.get("exit_code") == 0 else 2}
    kwargs = {"cwd": str(ROOT), "stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    if os.name == "nt": kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    try:
        child = process_factory([sys.executable, str(SUPERVISOR_PATH)], **kwargs)
    except (OSError, ValueError):
        return {"action": "start", "state": "failed", "exit_code": 1}
    deadline = clock() + wait_timeout
    while clock() < deadline:
        current = _read(status_path) or {}
        if current.get("run_id") and current.get("run_id") != prior_run:
            health = health_fn(status_path)
            if child.poll() is None and health.get("exit_code") == 0 and current.get("status") == "healthy":
                try:
                    with single_instance(lock_path):
                        return {"action": "start", **health, "state": "lock_lost", "pid": getattr(child, "pid", None), "exit_code": 2}
                except AlreadyRunningError:
                    return {"action": "start", **health, "state": "started", "pid": getattr(child, "pid", None), "exit_code": 0}
        if child.poll() is not None:
            return {"action": "start", "state": "failed", "exit_code": 1}
        sleep_fn(0.25)
    return {"action": "start", "state": "starting_unknown", "pid": getattr(child, "pid", None), "exit_code": 2}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--status-path", type=Path, default=STATUS_PATH)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status"); sub.add_parser("start")
    args = parser.parse_args(argv)
    try:
        if args.command == "start" and args.status_path != STATUS_PATH:
            raise ValueError("--status-path is only valid with status")
        result = status(args.status_path) if args.command == "status" else start()
        print(json.dumps(result, ensure_ascii=False)); return int(result.get("exit_code", 2))
    except (OSError, ValueError, TypeError):
        print(json.dumps({"error": "control operation failed"})); return 2


if __name__ == "__main__": raise SystemExit(main())
