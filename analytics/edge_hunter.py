"""
analytics/edge_hunter.py

Ziel: Reproduzierbarer Snapshot, welche "guten" Kandidaten durch Guardrails geblockt werden.

Design-Prinzipien:
- read-only auf vorhandenen Logs (guardrail_audit.jsonl)
- fail-closed (bei Fehlern kein Pipeline-Crash)
- deterministisch (nur File-Inhalt + Parameter)
"""

from __future__ import annotations

import json
import logging
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


def _iter_jsonl(path: Path) -> Iterable[Dict[str, Any]]:
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except Exception:
                continue


def _as_float(x: Any) -> Optional[float]:
    if isinstance(x, (int, float)):
        return float(x)
    return None


@dataclass(frozen=True)
class EdgeCandidate:
    score: float
    record: Dict[str, Any]


def _top_n_by_score(cands: List[EdgeCandidate], n: int) -> List[Dict[str, Any]]:
    if n <= 0:
        return []
    cands_sorted = sorted(cands, key=lambda c: c.score, reverse=True)[:n]
    return [c.record for c in cands_sorted]


def run_edge_hunter(
    *,
    max_records: int = 200_000,
    top_n: int = 50,
    out_file: Path = OUT_FILE,
    audit_file: Path = AUDIT_FILE,
) -> Dict[str, Any]:
    """
    Erzeuge edge_hunter.json aus guardrail_audit.jsonl.

    Heuristik:
    - Fokus auf geblockte Decisions
    - "Shadow-ready" Kandidaten = allowed==False & shadow_allowed_without_inventory==True
    - Score = abs(edge) (grobe Priorisierung, keine PnL-Behauptung)
    """
    generated_at = datetime.now(timezone.utc).isoformat()

    if not audit_file.exists():
        payload = {
            "generated_at": generated_at,
            "source_file": str(audit_file),
            "status": "missing_audit_file",
            "candidates": [],
            "stats": {},
        }
        try:
            OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
            out_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass
        return payload

    blocked_code_counts: Dict[str, int] = {}
    blocked_detail_counts: Dict[str, int] = {}
    shadow_block_code_counts: Dict[str, int] = {}

    total = 0
    allowed = 0
    blocked = 0
    shadow_allowed = 0

    shadow_candidates: List[EdgeCandidate] = []
    low_price_traps: List[EdgeCandidate] = []

    for rec in _iter_jsonl(audit_file):
        total += 1
        if total > max_records:
            break

        is_allowed = rec.get("allowed") is True
        if is_allowed:
            allowed += 1
        else:
            blocked += 1
            code = rec.get("reason_code") or "unknown"
            detail = rec.get("reason_detail") or ""
            blocked_code_counts[code] = blocked_code_counts.get(code, 0) + 1
            if detail:
                blocked_detail_counts[detail] = blocked_detail_counts.get(detail, 0) + 1

        if rec.get("shadow_allowed_without_inventory") is True:
            shadow_allowed += 1
        else:
            sc = rec.get("shadow_reason_code") or None
            if sc:
                shadow_block_code_counts[sc] = shadow_block_code_counts.get(sc, 0) + 1

        # Candidate extraction
        edge = _as_float(rec.get("edge"))
        if edge is None:
            continue

        score = abs(edge)
        base = {
            "timestamp": rec.get("timestamp"),
            "run_id": rec.get("run_id"),
            "proposal_id": rec.get("proposal_id"),
            "market_id": rec.get("market_id"),
            "city": rec.get("city"),
            "market_question": rec.get("market_question"),
            "entry_price": rec.get("entry_price"),
            "implied_probability": rec.get("implied_probability"),
            "model_probability": rec.get("model_probability"),
            "edge": edge,
            "confidence_level": rec.get("confidence_level"),
            "allowed": rec.get("allowed"),
            "reason_code": rec.get("reason_code"),
            "reason_detail": rec.get("reason_detail"),
            "shadow_allowed_without_inventory": rec.get("shadow_allowed_without_inventory"),
            "shadow_reason_code": rec.get("shadow_reason_code"),
            "shadow_reason_detail": rec.get("shadow_reason_detail"),
        }

        if base["allowed"] is False and base["shadow_allowed_without_inventory"] is True:
            shadow_candidates.append(EdgeCandidate(score=score, record=base))

        if base.get("reason_code") == "price_too_low":
            low_price_traps.append(EdgeCandidate(score=score, record=base))

    def _top(counter: Dict[str, int], n: int) -> List[Tuple[str, int]]:
        return sorted(counter.items(), key=lambda kv: kv[1], reverse=True)[:n]

    payload = {
        "generated_at": generated_at,
        "source_file": str(audit_file),
        "max_records": max_records,
        "stats": {
            "total_records_scanned": total,
            "allowed": allowed,
            "blocked": blocked,
            "allowed_pct": round((allowed / total) * 100, 2) if total else 0.0,
            "shadow_allowed_without_inventory": shadow_allowed,
            "shadow_allowed_pct": round((shadow_allowed / total) * 100, 2) if total else 0.0,
            "blocked_reason_codes_top": _top(blocked_code_counts, 10),
            "blocked_reason_details_top": _top(blocked_detail_counts, 10),
            "shadow_block_reason_codes_top": _top(shadow_block_code_counts, 10),
        },
        "candidates": _top_n_by_score(shadow_candidates, top_n),
        "low_price_traps": _top_n_by_score(low_price_traps, min(25, top_n)),
        "governance_notice": "Edge-Hunter ist ein Diagnose-Snapshot. Keine Edge-Behauptung ohne Out-of-sample Evidenz.",
    }

    try:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        out_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        logger.debug("edge_hunter write failed (ignored): %s", e)

    return payload


def main() -> int:
    try:
        run_edge_hunter()
        return 0
    except Exception as e:
        logger.error("edge_hunter failed: %s", e)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

