# =============================================================================
# EDGE HUNTER (READ-ONLY)
# =============================================================================
#
# Ziel:
# - Aus den Guardrail-Audit-Logs + Shadow-Candidates eine kompakte,
#   "actionable" Opportunity-Liste bauen.
#
# Governance:
# - Keine Trades, keine Orders, nur Reporting.
# - Guardrails werden NICHT gelockert.
#
# Output:
# - output/edge_hunter.json
#
# =============================================================================

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CandidateKey:
    proposal_id: Optional[str]
    market_id: Optional[str]


def _read_jsonl(path: Path, limit: int = 5000) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    items: List[Dict[str, Any]] = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    items.append(json.loads(line))
                except Exception:
                    continue
    except Exception as e:
        logger.debug(f"edge_hunter: failed reading {path}: {e}")
        return []
    if limit and len(items) > limit:
        return items[-limit:]
    return items


def _candidate_key(row: Dict[str, Any]) -> CandidateKey:
    return CandidateKey(
        proposal_id=row.get("proposal_id"),
        market_id=row.get("market_id"),
    )


def _score(row: Dict[str, Any]) -> Tuple[int, float, float]:
    """
    Sortierung: Confidence (HIGH zuerst), |edge| absteigend, guenstigerer Entry-Preis (niedriger).
    """
    conf = (row.get("confidence_level") or "").upper()
    conf_rank = {"HIGH": 3, "MEDIUM": 2, "LOW": 1}.get(conf, 0)
    edge = row.get("edge")
    try:
        edge_abs = abs(float(edge)) if edge is not None else 0.0
    except Exception:
        edge_abs = 0.0
    entry_price = row.get("entry_price")
    try:
        price = float(entry_price) if entry_price is not None else 1.0
    except Exception:
        price = 1.0
    return (conf_rank, edge_abs, -price)


def build_edge_hunter_report(
    root: Path,
    max_candidates: int = 50,
    audit_limit: int = 8000,
    shadow_limit: int = 8000,
) -> Dict[str, Any]:
    logs_dir = root / "logs"
    data_dir = root / "data"
    output_dir = root / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)

    audit_file = logs_dir / "guardrail_audit.jsonl"
    shadow_file = data_dir / "shadow_trades.jsonl"

    audit_rows = _read_jsonl(audit_file, limit=audit_limit)
    shadow_rows = _read_jsonl(shadow_file, limit=shadow_limit)

    # Backfill: wenn shadow_trades.jsonl noch fehlt, zumindest anlegen,
    # damit Automations/Reports nicht scheitern.
    if not shadow_file.exists():
        try:
            shadow_file.write_text("", encoding="utf-8")
        except Exception:
            pass

    candidates: List[Dict[str, Any]] = []
    by_key: Dict[CandidateKey, Dict[str, Any]] = {}
    occurrences: Dict[CandidateKey, int] = {}

    # 1) Primär aus shadow_trades.jsonl (gezielt: blocked aber shadow-eligible)
    for row in shadow_rows:
        key = _candidate_key(row)
        occurrences[key] = occurrences.get(key, 0) + 1
        existing = by_key.get(key)
        if existing is None or _score(row) > _score(existing):
            by_key[key] = row

    # 2) Fallback/Ergaenzung aus guardrail_audit.jsonl
    for row in audit_rows:
        if row.get("allowed") is True:
            continue
        if not row.get("shadow_allowed_without_inventory"):
            continue
        key = _candidate_key(row)
        occurrences[key] = occurrences.get(key, 0) + 1
        candidate = (
            {
                "timestamp": row.get("timestamp"),
                "run_id": row.get("run_id"),
                "proposal_id": row.get("proposal_id"),
                "market_id": row.get("market_id"),
                "allowed": row.get("allowed"),
                "reason_code": row.get("reason_code"),
                "reason_detail": row.get("reason_detail"),
                "shadow_allowed_without_inventory": row.get("shadow_allowed_without_inventory"),
                "shadow_reason_code": row.get("shadow_reason_code"),
                "shadow_reason_detail": row.get("shadow_reason_detail"),
                "market_question": row.get("market_question"),
                "edge": row.get("edge"),
                "implied_probability": row.get("implied_probability"),
                "model_probability": row.get("model_probability"),
                "confidence_level": row.get("confidence_level"),
                "city": row.get("city"),
                "entry_price": row.get("entry_price"),
                "source": "guardrail_audit_backfill",
            }
        )
        existing = by_key.get(key)
        if existing is None or _score(candidate) > _score(existing):
            by_key[key] = candidate

    for key, row in by_key.items():
        row = dict(row)
        row["occurrences_count"] = occurrences.get(key, 1)
        candidates.append(row)

    candidates_sorted = sorted(candidates, key=_score, reverse=True)[:max_candidates]

    blocked_by_reason: Dict[str, int] = {}
    for row in candidates_sorted:
        code = row.get("reason_code") or "unknown"
        blocked_by_reason[code] = blocked_by_reason.get(code, 0) + 1

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "shadow_file_present": shadow_file.exists(),
        "audit_rows_considered": len(audit_rows),
        "shadow_rows_considered": len(shadow_rows),
        "candidates_count": len(candidates_sorted),
        "blocked_by_reason_top": dict(sorted(blocked_by_reason.items(), key=lambda kv: kv[1], reverse=True)[:10]),
        "candidates": candidates_sorted,
    }


def run_edge_hunter(root: Optional[Path] = None) -> Dict[str, Any]:
    root = root or Path(__file__).parent.parent
    report = build_edge_hunter_report(root=root)
    out = root / "output" / "edge_hunter.json"
    try:
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        logger.debug(f"edge_hunter: failed writing {out}: {e}")
    return report
