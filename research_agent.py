"""Offline lifecycle CLI for prepared research-agent runs."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from analytics.agent_run_store import RunStore, RunStoreError, validate_key
from analytics.research_coordinator import MODEL_ALLOWLIST, PROMPT, CoordinatorError, reconcile, request_plan

ROOT = Path(__file__).resolve().parent
STATUS_PATH = ROOT / "output" / "research_status.json"
STORE_PATH = ROOT / "output" / "agent_runs.json"


def _key(model: str, value: str) -> str:
    material = json.dumps({"model": model, "input": value, "prompt": PROMPT}, sort_keys=True)
    return hashlib.sha256(material.encode()).hexdigest()


def prepare(model: str, status_path: Path = STATUS_PATH, store_path: Path = STORE_PATH) -> dict[str, Any]:
    if model not in MODEL_ALLOWLIST:
        raise CoordinatorError("model is not allowlisted")
    plan = request_plan(model, status_path)
    key = _key(model, plan["session"]["input"])
    record = {"state": "prepared", "model": model,
              "prompt_hash": hashlib.sha256(PROMPT.encode()).hexdigest(),
              "input": plan["session"]["input"]}
    store = RunStore(store_path)
    with store.operation():
        existing = store.load(key)
        immutable = ("model", "prompt_hash", "input")
        if existing is not None and any(existing.get(k) != record[k] for k in immutable):
            raise CoordinatorError("run key input conflict")
        if not existing:
            store.save(key, record)
    return {"state": "prepared_offline", "run_key": key,
            "model": model, "input": plan["session"]["input"], "live_enabled": False,
            "dispatch_available": False, "admission_budget": None, "store_path": str(store_path)}


def show(run_key: str, store_path: Path = STORE_PATH) -> dict[str, Any]:
    try:
        key = validate_key(run_key)
        record = RunStore(store_path).load(key)
    except RunStoreError as exc:
        raise CoordinatorError(str(exc)) from exc
    if record is None:
        raise CoordinatorError("run not found")
    return {"state": "stored", "run_key": key, "record": record}


def reconcile_known(run_key: str, store_path: Path = STORE_PATH, timeout: float = 30.0) -> dict[str, Any]:
    if timeout <= 0 or timeout != timeout or timeout in (float("inf"), float("-inf")) or timeout > 60:
        raise CoordinatorError("invalid timeout")
    store = RunStore(store_path)
    try:
        key = validate_key(run_key)
        record = store.load(key)
    except RunStoreError as exc:
        raise CoordinatorError(str(exc)) from exc
    if not record or not record.get("session_id"):
        raise CoordinatorError("known session required")
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise CoordinatorError("optional OpenAI SDK is unavailable") from exc
    holder: dict[str, Any] = {}
    def factory(**kwargs: Any) -> Any:
        holder["client"] = OpenAI(timeout=timeout, **kwargs)
        return holder["client"]
    try:
        result = reconcile(store, factory, key)
    finally:
        client = holder.get("client")
        if client is not None and hasattr(client, "close"):
            client.close()
    result["exit_code"] = 0 if result.get("state") == "completed" else (3 if result.get("state") == "in_progress" else 1)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", type=Path, default=STORE_PATH)
    parser.add_argument("--status", type=Path, default=STATUS_PATH)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("prepare"); p.add_argument("--model", required=True)
    s = sub.add_parser("show"); s.add_argument("--run-key", required=True)
    r = sub.add_parser("reconcile"); r.add_argument("--run-key", required=True); r.add_argument("--timeout", type=float, default=30.0)
    sub.add_parser("costs")
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare": result = prepare(args.model, args.status, args.store)
        elif args.command == "show": result = show(args.run_key, args.store)
        elif args.command == "costs":
            from analytics.agent_cost_report import report
            result = report(args.store)
        else: result = reconcile_known(args.run_key, args.store, args.timeout)
        print(json.dumps(result, indent=2, ensure_ascii=False)); return int(result.get("exit_code", 0))
    except CoordinatorError as exc:
        message = str(exc)
        safe = message if message in {"run not found", "known session required", "model is not allowlisted",
                                      "optional OpenAI SDK is unavailable", "invalid timeout"} else "operation failed"
        print(json.dumps({"error": safe}, ensure_ascii=False)); return 2 if safe == "run not found" else 1
    except (OSError, ValueError, TypeError):
        print(json.dumps({"error": "invalid input or local store"}, ensure_ascii=False)); return 2


if __name__ == "__main__":
    raise SystemExit(main())
