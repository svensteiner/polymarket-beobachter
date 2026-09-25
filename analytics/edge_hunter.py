"""
Edge Hunter
===========

Goal:
- Produce a compact, machine-readable snapshot of *actionable* edge and the
  dominant blockers (liquidity, guardrails, etc.) for production monitoring.

Artifact:
- output/edge_hunter.json

GOVERNANCE:
- READ-ONLY: consumes existing logs; never modifies proposals or trading state.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


def _read_tail_bytes(path: Path, max_bytes: int) -> str:
    if not path.exists() or max_bytes <= 0:
        return ""
    try:
        with path.open("rb") as f:
            try:
                f.seek(-max_bytes, 2)
            except OSError:
                f.seek(0)
            data = f.read()
        return data.decode("utf-8", errors="replace")
    except Exception:
        return ""


def _parse_jsonl_lines(text: str) -> Iterable[Dict[str, Any]]:
    for line in text.splitlines():
        line = line.strip()
        if not line or not line.startswith("{"):
            continue
        try:
            yield json.loads(line)
        except Exception:
            continue


def _parse_ts(value: Any) -> Optional[datetime]:
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not isinstance(value, str):
        return None
    v = value.strip()
    # Support "...Z"
    if v.endswith("Z"):
        v = v[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(v)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


@dataclass(frozen=True)
class EdgeHunterSnapshot:
    generated_at: str
    lookback_hours: int
    guardrail_decisions_seen: int
    shadow_allowed_seen: int
    paper_skips_seen: int
    low_liquidity_market_ids: List[str]
    top_shadow_eligible: List[Dict[str, Any]]
    blocker_breakdown: Dict[str, int]


def generate_edge_hunter_snapshot(
    *,
    base_dir: Path,
    lookback_hours: int = 24,
    max_items: int = 25,
    max_tail_bytes: int = 2_000_000,
) -> EdgeHunterSnapshot:
    logs_dir = base_dir / "logs"
    paper_dir = base_dir / "paper_trader" / "logs"

    guardrail_audit = logs_dir / "guardrail_audit.jsonl"
    paper_trades = paper_dir / "paper_trades.jsonl"

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=lookback_hours)

    # 1) Low-liquidity market ids from recent paper skips (best signal for "not actionable")
    low_liq_ids: set[str] = set()
    paper_skips = 0
    paper_tail = _read_tail_bytes(paper_trades, max_tail_bytes)
    for rec in _parse_jsonl_lines(paper_tail):
        ts = _parse_ts(rec.get("timestamp"))
        if ts is None or ts < cutoff:
            continue
        if rec.get("action") == "SKIP":
            paper_skips += 1
            reason = str(rec.get("reason") or "")
            if "LOW-liquidity" in reason or "LOW-liq" in reason:
                mid = rec.get("market_id")
                if mid:
                    low_liq_ids.add(str(mid))

    # 2) Guardrail decisions: keep only shadow-eligible (ignoring inventory)
    blocker_breakdown: Dict[str, int] = {}
    shadow_eligible: List[Tuple[float, Dict[str, Any]]] = []
    decisions_seen = 0
    shadow_allowed_seen = 0

    audit_tail = _read_tail_bytes(guardrail_audit, max_tail_bytes)
    for rec in _parse_jsonl_lines(audit_tail):
        ts = _parse_ts(rec.get("timestamp"))
        if ts is None or ts < cutoff:
            continue

        decisions_seen += 1
        reason_code = str(rec.get("reason_code") or "unknown")
        blocker_breakdown[reason_code] = blocker_breakdown.get(reason_code, 0) + 1

        if rec.get("shadow_allowed_without_inventory"):
            shadow_allowed_seen += 1
            edge = float(rec.get("edge") or 0.0)
            shadow_eligible.append((abs(edge), rec))

    shadow_eligible.sort(key=lambda t: t[0], reverse=True)
    top: List[Dict[str, Any]] = []
    for _, rec in shadow_eligible[:max_items]:
        mid = str(rec.get("market_id") or "")
        top.append(
            {
                "timestamp": rec.get("timestamp"),
                "run_id": rec.get("run_id"),
                "proposal_id": rec.get("proposal_id"),
                "market_id": mid,
                "market_question": rec.get("market_question"),
                "edge": rec.get("edge"),
                "implied_probability": rec.get("implied_probability"),
                "model_probability": rec.get("model_probability"),
                "confidence_level": rec.get("confidence_level"),
                "city": rec.get("city"),
                "entry_price": rec.get("entry_price"),
                "paper_allowed": rec.get("allowed"),
                "paper_reason_code": rec.get("reason_code"),
                "paper_reason_detail": rec.get("reason_detail"),
                "shadow_reason_code": rec.get("shadow_reason_code"),
                "shadow_reason_detail": rec.get("shadow_reason_detail"),
                "blocked_by_low_liquidity": mid in low_liq_ids if mid else False,
            }
        )

    return EdgeHunterSnapshot(
        generated_at=now.isoformat(),
        lookback_hours=lookback_hours,
        guardrail_decisions_seen=decisions_seen,
        shadow_allowed_seen=shadow_allowed_seen,
        paper_skips_seen=paper_skips,
        low_liquidity_market_ids=sorted(low_liq_ids),
        top_shadow_eligible=top,
        blocker_breakdown=blocker_breakdown,
    )


def write_edge_hunter_snapshot(
    *,
    base_dir: Path,
    lookback_hours: int = 24,
    max_items: int = 25,
) -> Optional[Path]:
    """
    Writes `output/edge_hunter.json` using atomic .tmp + rename.

    Returns output path if written, else None.
    """
    try:
        snapshot = generate_edge_hunter_snapshot(
            base_dir=base_dir,
            lookback_hours=lookback_hours,
            max_items=max_items,
        )
        out_dir = base_dir / "output"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_file = out_dir / "edge_hunter.json"
        tmp = out_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(snapshot.__dict__, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(out_file)
        return out_file
    except Exception:
        return None

