from __future__ import annotations

import json
import os
from dataclasses import asdict, is_dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional


def _load_json(path: Path) -> Optional[Dict[str, Any]]:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _atomic_write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def _failed_steps_from_result(result: Any) -> list[str]:
    steps = getattr(result, "steps", None)
    if not steps:
        return []
    failed: list[str] = []
    for s in steps:
        try:
            name = getattr(s, "name", None) or (s.get("name") if isinstance(s, dict) else None)
            success = getattr(s, "success", None)
            if success is None and isinstance(s, dict):
                success = s.get("success")
            if name and success is False:
                failed.append(str(name))
        except Exception:
            continue
    return failed


def write_bot_status_from_pipeline_result(
    *,
    bot_status_file: Path,
    process_started_at: datetime,
    run_result: Any,
) -> None:
    """
    Write `logs/bot_status.json` in a cockpit-compatible schema.

    Motivation:
    - Pipeline runs can be triggered without `cockpit.py` (daemon, tests, direct orchestrator).
    - Without this, `bot_status.json`/`heartbeat.txt` go stale while outputs advance -> false health signal.
    """
    now = datetime.now()

    prev = _load_json(bot_status_file) or {}
    prev_run_count = int(prev.get("run_count") or 0)
    prev_consecutive_errors = int(prev.get("consecutive_errors") or 0)

    state_value = getattr(getattr(run_result, "state", None), "value", None) or str(getattr(run_result, "state", "UNKNOWN"))
    summary = getattr(run_result, "summary", None)
    if summary is None:
        summary = {}
    if is_dataclass(summary):
        summary = asdict(summary)
    if not isinstance(summary, dict):
        summary = {}

    run_count = prev_run_count + 1
    consecutive_errors = 0 if state_value == "OK" else (prev_consecutive_errors + 1)

    last_run = {
        "state": state_value,
        "duration_seconds": summary.get("duration_seconds", 0),
        "markets_fetched": summary.get("markets_fetched", 0),
        "edge_observations": summary.get("edge_observations", 0),
        "paper_positions_entered": summary.get("paper_positions_entered", 0),
        "bot_health_status": summary.get("bot_health_status", "UNKNOWN"),
        "bot_health_guardrails_active": summary.get("bot_health_guardrails_active", False),
        "failed_steps": _failed_steps_from_result(run_result),
    }

    payload = {
        "schema_version": 1,
        "timestamp": now.isoformat(),
        "pid": os.getpid(),
        "uptime_seconds": round((now - process_started_at).total_seconds(), 1),
        "started_at": process_started_at.isoformat(),
        "run_count": run_count,
        "consecutive_errors": consecutive_errors,
        "run_id": summary.get("run_id"),
        "last_run": last_run,
        "last_crash": prev.get("last_crash"),
    }

    _atomic_write_json(bot_status_file, payload)

