from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent
SHADOW_TRADES_FILE = PROJECT_ROOT / "data" / "shadow_trades.jsonl"
SHADOW_INDEX_FILE = PROJECT_ROOT / "data" / "shadow_trades_index.json"


def _load_index() -> set[str]:
    try:
        if SHADOW_INDEX_FILE.exists():
            data = json.loads(SHADOW_INDEX_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("proposal_ids"), list):
                return {str(x) for x in data["proposal_ids"] if str(x)}
    except Exception:
        pass
    return set()


def _save_index(ids: set[str]) -> None:
    SHADOW_INDEX_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = SHADOW_INDEX_FILE.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps({"proposal_ids": sorted(ids)}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    tmp.replace(SHADOW_INDEX_FILE)


def record_shadow_candidate(entry: Dict[str, Any]) -> bool:
    """
    Append a shadow candidate entry to `data/shadow_trades.jsonl` (idempotent by proposal_id).

    Governance:
    - Records scouting candidates only.
    - Does not execute any trades and does not touch capital/positions.
    """
    proposal_id = str(entry.get("proposal_id") or "").strip()
    if not proposal_id:
        return False

    ids = _load_index()
    if proposal_id in ids:
        return False

    try:
        SHADOW_TRADES_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(SHADOW_TRADES_FILE, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
        ids.add(proposal_id)
        _save_index(ids)
        return True
    except Exception as exc:
        logger.debug("Shadow candidate write failed: %s", exc)
        return False

