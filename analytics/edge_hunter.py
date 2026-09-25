"""
EDGE HUNTER
==========

Intent: Brutal, auditierbar, deterministisch.
Aggregiert Guardrail-Entscheidungen und extrahiert "Shadow-Eligible" Kandidaten
(wären ohne Inventory-/Policy-Block handelbar) als Snapshot in output/edge_hunter.json.
"""

from __future__ import annotations

import json
import logging
from collections import Counter, defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent
LOGS_DIR = PROJECT_ROOT / "logs"
OUTPUT_DIR = PROJECT_ROOT / "output"
AUDIT_FILE = LOGS_DIR / "guardrail_audit.jsonl"
OUT_FILE = OUTPUT_DIR / "edge_hunter.json"


@dataclass(frozen=True)
class _Key:
    market_id: str
    proposal_id: str | None


def _safe_float(x: Any) -> Optional[float]:
    try:
        if x is None:
            return None
        return float(x)
    except Exception:
        return None


def _iter_recent_jsonl(path: Path, max_lines: int) -> Iterable[Dict[str, Any]]:
    if not path.exists():
        return []

    buf: deque[str] = deque(maxlen=max_lines)
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    buf.append(line)
    except Exception as e:
        logger.warning("edge_hunter: failed reading %s: %s", path, e)
        return []

    out: List[Dict[str, Any]] = []
    for line in buf:
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out


def build_edge_hunter_snapshot(
    *,
    run_id: str | None = None,
    max_lines: int = 5000,
    limit: int = 50,
) -> Dict[str, Any]:
    """
    Build an edge-hunter snapshot from guardrail audit.

    Rules:
    - We only care about candidates that were blocked in real mode, BUT were
      marked shadow-eligible (shadow_allowed_without_inventory == True).
    - Deterministic sorting: abs(edge) desc, occurrences desc, last_seen desc.
    """
    now = datetime.now(timezone.utc).isoformat()
    decisions = list(_iter_recent_jsonl(AUDIT_FILE, max_lines=max_lines))
    if run_id:
        decisions = [d for d in decisions if d.get("run_id") == run_id]

    shadow_candidates: List[Dict[str, Any]] = []
    reason_counter: Counter[str] = Counter()

    for d in decisions:
        allowed = bool(d.get("allowed"))
        shadow_ok = bool(d.get("shadow_allowed_without_inventory"))
        if allowed:
            continue
        if not shadow_ok:
            continue
        shadow_candidates.append(d)
        reason_counter[d.get("reason_code", "unknown")] += 1

    # Aggregate by market/proposal to find repeated "blocked but shadow-ok" patterns
    agg: Dict[_Key, Dict[str, Any]] = {}
    last_seen: Dict[_Key, str] = {}
    occurrences: Counter[_Key] = Counter()

    for d in shadow_candidates:
        market_id = str(d.get("market_id") or "")
        if not market_id:
            continue
        key = _Key(market_id=market_id, proposal_id=(d.get("proposal_id") or None))
        occurrences[key] += 1
        ts = str(d.get("timestamp") or "")
        if ts and ts > last_seen.get(key, ""):
            last_seen[key] = ts
        if key not in agg:
            agg[key] = d

    def sort_key(item: Tuple[_Key, Dict[str, Any]]) -> Tuple[float, int, str, str]:
        key, d = item
        edge = _safe_float(d.get("edge"))
        edge_abs = abs(edge) if edge is not None else 0.0
        return (
            edge_abs,
            int(occurrences.get(key, 0)),
            str(last_seen.get(key, "")),
            key.market_id,
        )

    ranked = sorted(agg.items(), key=sort_key, reverse=True)[:limit]

    top: List[Dict[str, Any]] = []
    for key, d in ranked:
        top.append(
            {
                "market_id": key.market_id,
                "proposal_id": key.proposal_id,
                "last_seen": last_seen.get(key),
                "occurrences_count": int(occurrences.get(key, 0)),
                "reason_code": d.get("reason_code"),
                "reason_detail": d.get("reason_detail"),
                "shadow_reason_code": d.get("shadow_reason_code"),
                "shadow_reason_detail": d.get("shadow_reason_detail"),
                "market_question": d.get("market_question"),
                "city": d.get("city"),
                "confidence_level": d.get("confidence_level"),
                "entry_price": _safe_float(d.get("entry_price")),
                "implied_probability": _safe_float(d.get("implied_probability")),
                "model_probability": _safe_float(d.get("model_probability")),
                "edge": _safe_float(d.get("edge")),
            }
        )

    return {
        "schema_version": 1,
        "generated_at": now,
        "run_id": run_id,
        "source": {
            "file": str(AUDIT_FILE),
            "max_lines": max_lines,
            "filtered_to_run_id": bool(run_id),
        },
        "counts": {
            "decisions_considered": len(decisions),
            "shadow_blocked_candidates": len(shadow_candidates),
        },
        "blocked_reasons_top": reason_counter.most_common(10),
        "top_shadow_candidates": top,
    }


def write_edge_hunter_snapshot(
    *,
    run_id: str | None = None,
    max_lines: int = 5000,
    limit: int = 50,
) -> Optional[Path]:
    """Write output/edge_hunter.json. Fail-closed: never raise."""
    try:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        snapshot = build_edge_hunter_snapshot(run_id=run_id, max_lines=max_lines, limit=limit)
        tmp = OUT_FILE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(OUT_FILE)
        return OUT_FILE
    except Exception as e:
        logger.warning("edge_hunter: failed writing snapshot: %s", e)
        return None

