"""
analytics/shadow_trades.py - Shadow-Trade Export (READ-ONLY).

Ziel:
- Aus `logs/guardrail_audit.jsonl` alle Setups extrahieren, die *ohne* Inventory-Limit
  erlaubt waeren (shadow_allowed_without_inventory == True), aber policy-seitig geblockt wurden.
- Persistentes Append-Log: `data/shadow_trades.jsonl`
- Checkpoint fuer Idempotenz: `data/shadow_trades_state.json` (byte offset)

Wichtig:
- Kein Trading, keine Orders.
- Nur Telemetrie fuer Divergenz-/Opportunity-Analyse.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent
GUARDRAIL_AUDIT = PROJECT_ROOT / "logs" / "guardrail_audit.jsonl"
OUT_JSONL = PROJECT_ROOT / "data" / "shadow_trades.jsonl"
STATE_FILE = PROJECT_ROOT / "data" / "shadow_trades_state.json"


def _load_state() -> dict[str, Any]:
    try:
        if STATE_FILE.exists():
            data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except Exception as exc:
        logger.debug("shadow_trades state load fehlgeschlagen: %s", exc)
    return {}


def _save_state(state: dict[str, Any]) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")


def export_shadow_trades() -> dict[str, Any]:
    """
    Exportiere neue Shadow-Eligible Entscheidungen.

    Returns:
        dict mit Countern/Status; niemals Exception nach aussen.
    """
    result = {
        "ok": False,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": str(GUARDRAIL_AUDIT),
        "out": str(OUT_JSONL),
        "appended": 0,
        "skipped": 0,
        "errors": 0,
        "state_reset": False,
    }

    if not GUARDRAIL_AUDIT.exists():
        result["ok"] = True
        return result

    state = _load_state()
    offset = int(state.get("byte_offset") or 0)

    try:
        with open(GUARDRAIL_AUDIT, "rb") as src:
            src.seek(0, 2)
            size = src.tell()
            if offset > size:
                offset = 0
                result["state_reset"] = True
            src.seek(offset)

            OUT_JSONL.parent.mkdir(parents=True, exist_ok=True)
            with open(OUT_JSONL, "a", encoding="utf-8") as out:
                while True:
                    line = src.readline()
                    if not line:
                        break
                    offset = src.tell()
                    try:
                        raw = line.decode("utf-8", errors="replace").strip()
                        if not raw:
                            continue
                        data = json.loads(raw)
                        if not isinstance(data, dict):
                            result["skipped"] += 1
                            continue
                    except Exception:
                        result["errors"] += 1
                        continue

                    shadow_ok = bool(data.get("shadow_allowed_without_inventory"))
                    policy_allowed = bool(data.get("allowed"))
                    if shadow_ok and (not policy_allowed):
                        payload = {
                            "type": "SHADOW_ELIGIBLE_BUT_BLOCKED",
                            "exported_at": result["generated_at"],
                            "timestamp": data.get("timestamp"),
                            "run_id": data.get("run_id"),
                            "proposal_id": data.get("proposal_id"),
                            "market_id": data.get("market_id"),
                            "city": data.get("city"),
                            "confidence_level": data.get("confidence_level"),
                            "edge": data.get("edge"),
                            "entry_price": data.get("entry_price"),
                            "implied_probability": data.get("implied_probability"),
                            "model_probability": data.get("model_probability"),
                            "reason_code": data.get("reason_code"),
                            "reason_detail": data.get("reason_detail"),
                            "shadow_reason_code": data.get("shadow_reason_code"),
                            "shadow_reason_detail": data.get("shadow_reason_detail"),
                            "market_question": data.get("market_question"),
                        }
                        out.write(json.dumps(payload, ensure_ascii=False) + "\n")
                        result["appended"] += 1
                    else:
                        result["skipped"] += 1

        _save_state({"byte_offset": offset})
        result["ok"] = True
        return result
    except OSError as exc:
        logger.debug("shadow_trades export fehlgeschlagen (unkritisch): %s", exc)
        return result

