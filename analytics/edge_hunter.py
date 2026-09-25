"""
analytics/edge_hunter.py - Fail-closed, deterministische Edge-Run-Snapshots.

Ziel:
- Nach jedem Pipeline-Run einen kompakten, auditierbaren Snapshot schreiben:
  output/edge_hunter.json

Warum:
- Ohne reproduzierbare Artefakte ist jede "Edge" nur Behauptung.
- Guardrail-Audit enthaelt bereits die Rohdaten (edge/implied/model prob).

Dieses Modul macht KEINE Trades. Es schreibt nur Output.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from paper_trader.guardrail_audit import get_recent_decisions

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent
OUTPUT_FILE = PROJECT_ROOT / "output" / "edge_hunter.json"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _atomic_write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


@dataclass(frozen=True)
class EdgeRow:
    run_id: str
    proposal_id: str
    market_id: str
    allowed: bool
    shadow_allowed: bool
    entry_price: float | None
    implied_probability: float | None
    model_probability: float | None
    edge: float | None
    confidence_level: str | None
    city: str | None
    market_question: str | None
    timestamp: str | None


def _to_row(d: dict[str, Any]) -> EdgeRow | None:
    try:
        return EdgeRow(
            run_id=str(d.get("run_id") or ""),
            proposal_id=str(d.get("proposal_id") or ""),
            market_id=str(d.get("market_id") or ""),
            allowed=bool(d.get("allowed")),
            shadow_allowed=bool(d.get("shadow_allowed_without_inventory")),
            entry_price=(float(d["entry_price"]) if d.get("entry_price") is not None else None),
            implied_probability=(
                float(d["implied_probability"]) if d.get("implied_probability") is not None else None
            ),
            model_probability=(
                float(d["model_probability"]) if d.get("model_probability") is not None else None
            ),
            edge=(float(d["edge"]) if d.get("edge") is not None else None),
            confidence_level=(str(d.get("confidence_level")) if d.get("confidence_level") is not None else None),
            city=(str(d.get("city")) if d.get("city") is not None else None),
            market_question=(str(d.get("market_question")) if d.get("market_question") is not None else None),
            timestamp=(str(d.get("timestamp")) if d.get("timestamp") is not None else None),
        )
    except Exception:
        return None


def write_edge_hunter_snapshot(base_dir: Path, run_id: str, recent_limit: int = 800) -> dict[str, Any]:
    """
    Schreibt output/edge_hunter.json fuer einen Run (run_id).

    Deterministisch:
    - basiert auf guardrail_audit.jsonl (letzte N Eintraege)
    - sortiert/aggregiert stabil
    """
    _ = base_dir  # API-Konsistenz: base_dir wird vom Orchestrator uebergeben
    decisions = get_recent_decisions(limit=recent_limit)
    rows = [_to_row(d) for d in decisions if isinstance(d, dict) and d.get("run_id") == run_id]
    rows = [r for r in rows if r is not None]

    # Aggregation
    total = len(rows)
    allowed = sum(1 for r in rows if r.allowed)
    blocked = total - allowed
    shadow = sum(1 for r in rows if r.shadow_allowed)

    edges = [r.edge for r in rows if r.edge is not None]
    pos_edges = [e for e in edges if e > 0]
    neg_edges = [e for e in edges if e < 0]

    def _stats(vals: list[float]) -> dict[str, float] | None:
        if not vals:
            return None
        vals_sorted = sorted(vals)
        n = len(vals_sorted)
        return {
            "n": float(n),
            "min": float(vals_sorted[0]),
            "p50": float(vals_sorted[n // 2]),
            "max": float(vals_sorted[-1]),
            "mean": float(sum(vals_sorted) / n),
        }

    # Top absolute edges (diagnostisch; nicht "signale")
    top_abs = sorted(
        (r for r in rows if r.edge is not None),
        key=lambda r: abs(float(r.edge or 0.0)),
        reverse=True,
    )[:10]

    payload: dict[str, Any] = {
        "schema_version": 1,
        "generated_at": _utc_now().isoformat(),
        "run_id": run_id,
        "source": {
            "guardrail_audit_recent_limit": recent_limit,
        },
        "counts": {
            "total": total,
            "allowed": allowed,
            "blocked": blocked,
            "shadow_allowed_without_inventory": shadow,
            "blocked_ratio": (blocked / total) if total else 0.0,
            "shadow_ratio_without_inventory": (shadow / total) if total else 0.0,
        },
        "edge_stats": {
            "all": _stats([float(e) for e in edges]),
            "positive": _stats([float(e) for e in pos_edges]),
            "negative": _stats([float(e) for e in neg_edges]),
        },
        "top_abs_edges": [
            {
                "timestamp": r.timestamp,
                "proposal_id": r.proposal_id,
                "market_id": r.market_id,
                "city": r.city,
                "confidence_level": r.confidence_level,
                "entry_price": r.entry_price,
                "implied_probability": r.implied_probability,
                "model_probability": r.model_probability,
                "edge": r.edge,
                "allowed": r.allowed,
                "shadow_allowed_without_inventory": r.shadow_allowed,
                "market_question": r.market_question,
            }
            for r in top_abs
        ],
        "freshness": {
            "guardrail_audit_last_timestamp": (
                max((r.timestamp for r in rows if r.timestamp), default=None)
            ),
            "guardrail_audit_last_age_seconds": _age_seconds(
                max((_parse_iso(r.timestamp) for r in rows if _parse_iso(r.timestamp)), default=None)
            ),
        },
    }

    _atomic_write_json(OUTPUT_FILE, payload)
    return payload


def _age_seconds(dt: datetime | None) -> float | None:
    if dt is None:
        return None
    try:
        return float((_utc_now() - dt).total_seconds())
    except Exception:
        return None

