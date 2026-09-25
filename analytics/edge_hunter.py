"""
Edge Hunter (READ-ONLY analytics)

Purpose
-------
Create a compact machine-readable summary of recent guardrail decisions and
paper-trader throughput to answer: "Is there edge and is it actionable?"

Governance:
- Read-only over strategy state (only reads logs/output/data)
- Writes ONLY to output/edge_hunter.json and optionally data/shadow_trades.jsonl (append-only)
- Does not change any trading thresholds or guardrails
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_read_jsonl(path: Path, tail_limit: int = 5000) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    rows: List[Dict[str, Any]] = []
    try:
        # tail read: keep memory bounded
        lines = path.read_text(encoding="utf-8").splitlines()[-tail_limit:]
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except Exception:
                continue
    except Exception:
        return []
    return rows


def _safe_read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _extract_last_run_id(guardrail_rows: List[Dict[str, Any]]) -> Optional[str]:
    for row in reversed(guardrail_rows):
        rid = row.get("run_id")
        if rid:
            return str(rid)
    return None


def _summarize_guardrails(rows: List[Dict[str, Any]], run_id: Optional[str]) -> Dict[str, Any]:
    if run_id:
        rows = [r for r in rows if r.get("run_id") == run_id]

    total = len(rows)
    allowed = [r for r in rows if r.get("allowed") is True]
    blocked = [r for r in rows if r.get("allowed") is False]

    blocked_reasons = Counter((r.get("reason_code") or "unknown") for r in blocked).most_common(12)

    def _edge_val(r: Dict[str, Any]) -> float:
        try:
            return float(r.get("edge") or 0.0)
        except Exception:
            return 0.0

    top_allowed = sorted(allowed, key=lambda r: abs(_edge_val(r)), reverse=True)[:10]

    # Normalize a compact view (avoid leaking huge questions)
    def _compact(r: Dict[str, Any]) -> Dict[str, Any]:
        q = (r.get("market_question") or "")[:140]
        return {
            "timestamp": r.get("timestamp"),
            "run_id": r.get("run_id"),
            "proposal_id": r.get("proposal_id"),
            "market_id": r.get("market_id"),
            "allowed": r.get("allowed"),
            "reason_code": r.get("reason_code"),
            "edge": r.get("edge"),
            "side": r.get("side"),
            "contract_price": r.get("contract_price"),
            "entry_price_yes": r.get("entry_price"),
            "implied_probability_yes": r.get("implied_probability"),
            "model_probability_yes": r.get("model_probability"),
            "confidence_level": r.get("confidence_level"),
            "city": r.get("city"),
            "market_type": r.get("market_type"),
            "market_question": q,
            "shadow_allowed_without_inventory": r.get("shadow_allowed_without_inventory"),
        }

    return {
        "run_id": run_id,
        "evaluated": total,
        "allowed": len(allowed),
        "blocked": len(blocked),
        "blocked_ratio": (len(blocked) / total) if total else 0.0,
        "blocked_top_reasons": blocked_reasons,
        "top_allowed_by_abs_edge": [_compact(r) for r in top_allowed],
    }


def _summarize_paper_trades(paper_trades_path: Path) -> Dict[str, Any]:
    rows = _safe_read_jsonl(paper_trades_path, tail_limit=15000)
    if not rows:
        return {"records_tail": 0}

    # skip header if present
    rows = [r for r in rows if r.get("_type") != "LOG_HEADER"]
    actions = Counter(r.get("action") or "UNKNOWN" for r in rows)
    skips = [r for r in rows if r.get("action") == "SKIP"]
    realized = [r for r in rows if r.get("pnl_eur") is not None]

    pnl_total = 0.0
    wins = 0
    losses = 0
    for r in realized:
        try:
            pnl = float(r.get("pnl_eur") or 0.0)
        except Exception:
            continue
        pnl_total += pnl
        if pnl > 0:
            wins += 1
        elif pnl < 0:
            losses += 1

    skip_reason_prefix = Counter((r.get("reason") or "unknown").split(":")[0] for r in skips).most_common(12)

    last_ts = None
    first_ts = None
    try:
        first_ts = rows[0].get("timestamp")
        last_ts = rows[-1].get("timestamp")
    except Exception:
        pass

    return {
        "records_tail": len(rows),
        "first_timestamp": first_ts,
        "last_timestamp": last_ts,
        "actions": dict(actions),
        "realized_trades": len(realized),
        "wins": wins,
        "losses": losses,
        "pnl_eur_total": round(pnl_total, 2),
        "skip_reason_prefix_top": skip_reason_prefix,
    }


def _append_shadow_trades(
    shadow_path: Path,
    guardrail_rows: List[Dict[str, Any]],
    run_id: Optional[str],
) -> Dict[str, Any]:
    """
    Export shadow-eligible trades (blocked by inventory but otherwise eligible)
    as an append-only JSONL stream for later resolution analysis.
    """
    if run_id:
        rows = [r for r in guardrail_rows if r.get("run_id") == run_id]
    else:
        rows = list(guardrail_rows)

    export_rows = [
        r
        for r in rows
        if (r.get("allowed") is False) and (r.get("shadow_allowed_without_inventory") is True)
    ]

    shadow_path.parent.mkdir(parents=True, exist_ok=True)
    created = False
    if not shadow_path.exists():
        header = {
            "_type": "LOG_HEADER",
            "created_at": _utc_now_iso(),
            "description": "Append-only SHADOW trades (hypothetical): blocked by inventory but guardrails otherwise passed",
            "format": "JSONL (one JSON object per line)",
            "governance_notice": "No real trades were executed. This file is analytics-only.",
        }
        shadow_path.write_text(json.dumps(header, ensure_ascii=False) + "\n", encoding="utf-8")
        created = True

    if export_rows:
        with open(shadow_path, "a", encoding="utf-8") as f:
            for r in export_rows:
                out = {
                    "timestamp": _utc_now_iso(),
                    "source_run_id": run_id,
                    "proposal_id": r.get("proposal_id"),
                    "market_id": r.get("market_id"),
                    "market_question": (r.get("market_question") or "")[:200],
                    "city": r.get("city"),
                    "market_type": r.get("market_type"),
                    "edge": r.get("edge"),
                    "side": r.get("side"),
                    "contract_price": r.get("contract_price"),
                    "entry_price_yes": r.get("entry_price"),
                    "implied_probability_yes": r.get("implied_probability"),
                    "model_probability_yes": r.get("model_probability"),
                    "confidence_level": r.get("confidence_level"),
                    "blocked_reason_code": r.get("reason_code"),
                    "blocked_reason_detail": r.get("reason_detail"),
                }
                f.write(json.dumps(out, ensure_ascii=False) + "\n")

    return {"created": created, "exported": len(export_rows)}


def generate_edge_hunter_outputs(project_root: Path, run_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Generate `output/edge_hunter.json` and append to `data/shadow_trades.jsonl`.
    Returns the report dict.
    """
    logs_dir = project_root / "logs"
    output_dir = project_root / "output"
    data_dir = project_root / "data"

    guardrail_rows = _safe_read_jsonl(logs_dir / "guardrail_audit.jsonl", tail_limit=20000)
    inferred_run_id = _extract_last_run_id(guardrail_rows)
    target_run_id = run_id or inferred_run_id

    report: Dict[str, Any] = {
        "generated_at": _utc_now_iso(),
        "target_run_id": target_run_id,
        "sources": {
            "guardrail_audit": str((logs_dir / "guardrail_audit.jsonl").as_posix()),
            "paper_trades": str((project_root / "paper_trader" / "logs" / "paper_trades.jsonl").as_posix()),
        },
        "guardrails": _summarize_guardrails(guardrail_rows, target_run_id),
        "paper_trader": _summarize_paper_trades(project_root / "paper_trader" / "logs" / "paper_trades.jsonl"),
        "missing_inputs": [],
    }

    # Missing file hints
    for expected in ("output/edge_hunter.json", "data/shadow_trades.jsonl"):
        # just informational; edge_hunter.json will be written below
        pass

    # Export shadow stream (best-effort)
    shadow_export = _append_shadow_trades(data_dir / "shadow_trades.jsonl", guardrail_rows, target_run_id)
    report["shadow_export"] = shadow_export

    # Also include some context snapshots if present (read-only)
    report["bot_health"] = _safe_read_json(project_root / "logs" / "bot_health.json", {})
    report["bot_status"] = _safe_read_json(project_root / "logs" / "bot_status.json", {})

    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "edge_hunter.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    return report

