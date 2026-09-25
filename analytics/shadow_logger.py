"""
analytics/shadow_logger.py - Shadow-Trade Journal (read-only, auditierbar).

Ziel:
- data/shadow_trades.jsonl als deterministisches Journal befuellen.
- Eine Shadow-Trade-Zeile ist ein "wuerde-eingegangen" Record auf Basis der
  Guardrail-Audit-Daten, wenn Inventory/Execution nicht limitiert haette.

Wichtig:
- Keine Orders. Keine Side-Effects ausser Append.
- Dedupe pro (run_id, proposal_id) um Doppel-Append zu verhindern.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from paper_trader.guardrail_audit import get_recent_decisions

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent
SHADOW_FILE = PROJECT_ROOT / "data" / "shadow_trades.jsonl"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _read_existing_keys(limit: int = 5000) -> set[str]:
    if not SHADOW_FILE.exists():
        return set()
    keys: set[str] = set()
    try:
        # Tail-read: grob, aber ausreichend (wir dedupen nur gegen letzte N)
        lines = SHADOW_FILE.read_text(encoding="utf-8").splitlines()
        for line in lines[-limit:]:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                k = str(obj.get("key") or "")
                if k:
                    keys.add(k)
            except Exception:
                continue
    except Exception:
        return keys
    return keys


def append_shadow_trades_for_run(base_dir: Path, run_id: str, recent_limit: int = 1200) -> dict[str, Any]:
    """
    Appendet Shadow-Trades fuer einen bestimmten run_id.

    Shadow-Kriterium:
    - shadow_allowed_without_inventory == True

    Schreibweise:
    - JSONL (1 object / line)
    - Stabiler "key" = f\"{run_id}:{proposal_id}\"
    """
    _ = base_dir
    decisions = get_recent_decisions(limit=recent_limit)
    candidates = [
        d for d in decisions
        if isinstance(d, dict)
        and d.get("run_id") == run_id
        and bool(d.get("shadow_allowed_without_inventory"))
    ]

    existing = _read_existing_keys()
    appended = 0
    skipped = 0

    SHADOW_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(SHADOW_FILE, "a", encoding="utf-8") as f:
        for d in candidates:
            proposal_id = str(d.get("proposal_id") or "")
            if not proposal_id:
                continue
            key = f"{run_id}:{proposal_id}"
            if key in existing:
                skipped += 1
                continue

            record = {
                "schema_version": 1,
                "recorded_at": _utc_now().isoformat(),
                "key": key,
                "run_id": run_id,
                "proposal_id": proposal_id,
                "market_id": str(d.get("market_id") or ""),
                "market_question": d.get("market_question"),
                "city": d.get("city"),
                "confidence_level": d.get("confidence_level"),
                "entry_price": d.get("entry_price"),
                "implied_probability": d.get("implied_probability"),
                "model_probability": d.get("model_probability"),
                "edge": d.get("edge"),
                "guardrail_allowed": bool(d.get("allowed")),
                "shadow_allowed_without_inventory": True,
                "reason_code": d.get("reason_code"),
                "reason_detail": d.get("reason_detail"),
            }

            f.write(json.dumps(record, ensure_ascii=False) + "\n")
            existing.add(key)
            appended += 1

    return {
        "run_id": run_id,
        "candidates": len(candidates),
        "appended": appended,
        "skipped_existing": skipped,
        "file": str(SHADOW_FILE),
    }

