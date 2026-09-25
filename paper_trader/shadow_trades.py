"""
Shadow Trades Logger
-------------------
Persist "would-have-traded" candidates that were blocked only by inventory/policy
limits. This is used for post-hoc evaluation (resolution + hypothetical PnL)
without loosening any guardrails or placing real orders.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT / "data"
SHADOW_TRADES_FILE = DATA_DIR / "shadow_trades.jsonl"


@dataclass(frozen=True)
class ShadowTradeCandidate:
    timestamp: str
    run_id: Optional[str]
    proposal_id: str
    market_id: str
    allowed: bool
    reason_code: str
    reason_detail: str
    shadow_allowed_without_inventory: bool
    shadow_reason_code: str
    shadow_reason_detail: str
    side: str
    edge: float
    implied_probability: Optional[float]
    model_probability: Optional[float]
    confidence_level: Optional[str]
    city: Optional[str]
    market_type: Optional[str]
    entry_price: Optional[float]


def _safe_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        return float(value)
    except Exception:
        return None


def record_shadow_candidate(decision: Dict[str, Any]) -> None:
    """
    Append a shadow-candidate line to `data/shadow_trades.jsonl`.

    Expected input: the same dict written to guardrail_audit.jsonl.
    Only persists candidates that were blocked, but would pass without the
    inventory limit (shadow_allowed_without_inventory=True).
    """
    try:
        if not decision.get("shadow_allowed_without_inventory"):
            return
        if decision.get("allowed"):
            return

        side = "YES" if float(decision.get("edge") or 0.0) > 0 else "NO"

        candidate = ShadowTradeCandidate(
            timestamp=datetime.now(timezone.utc).isoformat(),
            run_id=decision.get("run_id"),
            proposal_id=str(decision.get("proposal_id") or ""),
            market_id=str(decision.get("market_id") or ""),
            allowed=bool(decision.get("allowed")),
            reason_code=str(decision.get("reason_code") or "unknown"),
            reason_detail=str(decision.get("reason_detail") or ""),
            shadow_allowed_without_inventory=bool(decision.get("shadow_allowed_without_inventory")),
            shadow_reason_code=str(decision.get("shadow_reason_code") or "unknown"),
            shadow_reason_detail=str(decision.get("shadow_reason_detail") or ""),
            side=side,
            edge=float(decision.get("edge") or 0.0),
            implied_probability=_safe_float(decision.get("implied_probability")),
            model_probability=_safe_float(decision.get("model_probability")),
            confidence_level=decision.get("confidence_level"),
            city=decision.get("city"),
            market_type=decision.get("market_type"),
            entry_price=_safe_float(decision.get("entry_price")),
        )

        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with open(SHADOW_TRADES_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(candidate), ensure_ascii=False) + "\n")

    except Exception as e:
        logger.warning("Failed to record shadow trade candidate: %s", e)

