from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT / "data"
SHADOW_TRADES_FILE = DATA_DIR / "shadow_trades.jsonl"


def record_shadow_trade(entry: Dict[str, Any]) -> None:
    """
    Append a shadow-trade entry to data/shadow_trades.jsonl.

    Definition:
    - Shadow trade = would pass entry guardrails if inventory limits were ignored,
      but is blocked in the current run due to inventory/open-position limits.

    GOVERNANCE:
    - Append-only
    - No trading / no orders
    """
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "schema_version": 1,
            "type": "SHADOW_ELIGIBLE_BLOCKED",
            **entry,
        }
        with open(SHADOW_TRADES_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as e:
        logger.warning("Failed to record shadow trade: %s", e)

