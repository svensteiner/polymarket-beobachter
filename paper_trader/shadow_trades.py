"""
Shadow-Trades (Beobachtung) - Append-only Logging.

GOVERNANCE:
- Keine Orders, kein Trading, keine Wallet-Aktionen.
- Dient nur dazu, verpasste/gebockte Entry-Setups zu protokollieren,
  damit sie spaeter gegen Resolutions ausgewertet werden koennen.

Output:
  data/shadow_trades.jsonl
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT / "data"
SHADOW_TRADES_FILE = DATA_DIR / "shadow_trades.jsonl"


def record_shadow_trade_candidate(
    *,
    run_id: Optional[str],
    proposal_id: str,
    market_id: str,
    market_question: str,
    implied_probability: float,
    model_probability: float,
    edge: float,
    confidence_level: str,
    blocked_reason_code: str,
    blocked_reason_detail: str,
    extra: Dict[str, Any] | None = None,
) -> None:
    """
    Append a single shadow-trade candidate record.

    Intended usage: when the trade is blocked in real paper mode,
    but would have passed without inventory limit (shadow eligible).
    """
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)

        side = "YES" if float(edge or 0.0) >= 0 else "NO"

        entry = {
            "schema_version": 1,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "run_id": run_id,
            "proposal_id": proposal_id,
            "market_id": market_id,
            "market_question": market_question,
            "side": side,
            "implied_probability": implied_probability,
            "model_probability": model_probability,
            "edge": edge,
            "confidence_level": confidence_level,
            "blocked_reason_code": blocked_reason_code,
            "blocked_reason_detail": blocked_reason_detail,
            "extra": extra or {},
            "governance_notice": "SHADOW TRADE ONLY - No trade executed (paper/live).",
        }

        with open(SHADOW_TRADES_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    except Exception as e:
        logger.warning("Failed to record shadow trade candidate: %s", e)

