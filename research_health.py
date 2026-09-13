"""Read-only health check for the research supervisor."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parent
STATUS_PATH = ROOT / "output" / "research_supervisor.json"
MAX_STATUS_BYTES = 64 * 1024
RUNNING_LIMIT = 300.0
OVERDUE_GRACE = 30.0
FUTURE_TOLERANCE = 5.0


def _read(path: Path) -> dict[str, Any] | None:
    try:
        with path.open("rb") as handle:
            raw = handle.read(MAX_STATUS_BYTES + 1)
        if len(raw) > MAX_STATUS_BYTES:
            return None
        value = json.loads(raw.decode("utf-8"))
        return value if isinstance(value, dict) else None
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None


def _probe(pid: int) -> dict[str, Any] | None:
    if pid <= 0:
        return None
    if os.name == "nt":
        # PID is validated as an integer before interpolation; no user text enters this command.
        command = f"$p=Get-CimInstance Win32_Process -Filter 'ProcessId = {pid}'; if ($p) {{ [Console]::Write(($p | Select-Object -First 1 ExecutablePath,CommandLine | ConvertTo-Json -Compress)) }}"
        try:
            completed = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
                capture_output=True, text=True, timeout=3, check=False)
            if completed.returncode or not completed.stdout.strip():
                return {"alive": False}
            value = json.loads(completed.stdout)
            if not isinstance(value, dict):
                return None
            return {"alive": True, "executable": value.get("ExecutablePath"),
                    "commandline": value.get("CommandLine")}
        except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
            return None
    try:
        commandline = Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode()
        return {"alive": True, "commandline": commandline}
    except (OSError, UnicodeDecodeError):
        return {"alive": False}


def _identity_ok(info: dict[str, Any] | None, script: str) -> bool | None:
    if not isinstance(info, dict):
        return None
    if info.get("alive") is not True:
        return False
    command = str(info.get("commandline") or "").lower()
    if script.lower() not in command:
        return False
    if script == "research_runner.py" and "--once" not in command:
        return False
    return True


def evaluate(path: Path = STATUS_PATH, *, now: float | None = None,
             process_probe: Callable[[int], dict[str, Any] | None] = _probe) -> dict[str, Any]:
    current = time.time() if now is None else now
    data = _read(path)
    if data is None:
        return {"state": "unknown", "reason": "missing_or_corrupt_status", "exit_code": 2}
    for field in ("updated_at", "next_due"):
        value = data.get(field)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value != value or value == float("inf") or value == float("-inf"):
            return {"state": "unknown", "reason": f"invalid_{field}", "exit_code": 2}
        if field == "updated_at" and value > current + FUTURE_TOLERANCE:
            return {"state": "unknown", "reason": f"future_{field}", "exit_code": 2}
    status = data.get("status")
    if not isinstance(status, str):
        return {"state": "unknown", "reason": "invalid_status", "exit_code": 2}
    if status in {"failed", "degraded", "stopped"}:
        return {"state": status, "reason": "supervisor_not_healthy", "exit_code": 1}
    supervisor_pid = data.get("supervisor_pid")
    if isinstance(supervisor_pid, bool) or not isinstance(supervisor_pid, int) or supervisor_pid <= 0:
        return {"state": "unknown", "reason": "invalid_supervisor_pid", "exit_code": 2}
    supervisor_identity = _identity_ok(process_probe(supervisor_pid), "research_supervisor.py")
    if supervisor_identity is None:
        return {"state": "unknown", "reason": "supervisor_probe_failed", "exit_code": 2}
    if not supervisor_identity:
        return {"state": "unknown", "reason": "supervisor_identity_mismatch", "exit_code": 2}
    if status == "healthy":
        if current > data["next_due"] + OVERDUE_GRACE:
            return {"state": "stale", "reason": "next_due_overdue", "exit_code": 1}
        return {"state": "healthy", "reason": "within_schedule", "exit_code": 0}
    if status != "running":
        return {"state": "unknown", "reason": "invalid_status", "exit_code": 2}
    started = data.get("started_at")
    pid = data.get("child_pid")
    if (isinstance(started, bool) or not isinstance(started, (int, float)) or
            started != started or started in (float("inf"), float("-inf")) or
            started > current + FUTURE_TOLERANCE):
        return {"state": "unknown", "reason": "invalid_started_at", "exit_code": 2}
    if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
        return {"state": "unknown", "reason": "invalid_child_pid", "exit_code": 2}
    identity = _identity_ok(process_probe(pid), "research_runner.py")
    if identity is None:
        return {"state": "unknown", "reason": "process_probe_failed", "exit_code": 2}
    if not identity:
        return {"state": "unknown", "reason": "child_identity_mismatch", "exit_code": 2}
    if current - started > RUNNING_LIMIT:
        return {"state": "stale", "reason": "child_runtime_overdue", "exit_code": 1}
    return {"state": "running", "reason": "child_within_runtime", "exit_code": 0}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--status-path", type=Path, default=STATUS_PATH)
    args = parser.parse_args(argv)
    result = evaluate(args.status_path)
    print(json.dumps(result, indent=2))
    return int(result["exit_code"])


if __name__ == "__main__":
    raise SystemExit(main())
