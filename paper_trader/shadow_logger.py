"""
Shadow Trade Logger
===================

GOVERNANCE INTENT:
- READ-ONLY: Logs what *would* be eligible in SHADOW mode (ignoring inventory)
- Does NOT place orders and does NOT affect paper/live execution

Why this exists:
- Production readiness requires a stable artifact at `data/shadow_trades.jsonl`
  for later evaluation of "missed-but-actionable" opportunities and guardrail
  diagnosis.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class ShadowTradeRecord:
    timestamp: str
    run_id: Optional[str]
    proposal_id: str
    market_id: str
    shadow_allowed_without_inventory: bool
    shadow_reason_code: str
    shadow_reason_detail: str
    allowed_paper: bool
    paper_reason_code: str
    paper_reason_detail: str
    edge: float
    implied_probability: float
    model_probability: float
    confidence_level: str
    market_question: str
    city: Optional[str] = None
    entry_price: Optional[float] = None
    market_type: Optional[str] = None
    extra: Optional[Dict[str, Any]] = None


def append_shadow_trade_record(
    record: ShadowTradeRecord,
    *,
    base_dir: Path,
) -> None:
    """
    Append a single JSONL line to `data/shadow_trades.jsonl`.

    Best effort: failures must never break the pipeline.
    """
    try:
        out_file = base_dir / "data" / "shadow_trades.jsonl"
        out_file.parent.mkdir(parents=True, exist_ok=True)
        payload = asdict(record)
        with out_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception:
        # Logging is intentionally silent here to avoid noisy pipelines.
        return


def build_shadow_record(
    *,
    run_id: Optional[str],
    proposal_id: str,
    market_id: str,
    shadow_allowed_without_inventory: bool,
    shadow_reason_code: str,
    shadow_reason_detail: str,
    allowed_paper: bool,
    paper_reason_code: str,
    paper_reason_detail: str,
    proposal_meta: Dict[str, Any],
) -> ShadowTradeRecord:
    """
    Build a normalized record from proposal metadata used by guardrail audit.
    """
    now = datetime.now(timezone.utc).isoformat()
    edge = float(proposal_meta.get("edge") or 0.0)
    implied = float(proposal_meta.get("implied_probability") or 0.0)
    model = float(proposal_meta.get("model_probability") or 0.0)
    confidence = str(proposal_meta.get("confidence_level") or "UNKNOWN")
    question = str(proposal_meta.get("market_question") or "")

    return ShadowTradeRecord(
        timestamp=now,
        run_id=run_id,
        proposal_id=proposal_id,
        market_id=market_id,
        shadow_allowed_without_inventory=bool(shadow_allowed_without_inventory),
        shadow_reason_code=shadow_reason_code or "unknown",
        shadow_reason_detail=shadow_reason_detail or "",
        allowed_paper=bool(allowed_paper),
        paper_reason_code=paper_reason_code or "unknown",
        paper_reason_detail=paper_reason_detail or "",
        edge=edge,
        implied_probability=implied,
        model_probability=model,
        confidence_level=confidence,
        market_question=question,
        city=proposal_meta.get("city"),
        entry_price=proposal_meta.get("entry_price"),
        market_type=proposal_meta.get("market_type"),
        extra=None,
    )

