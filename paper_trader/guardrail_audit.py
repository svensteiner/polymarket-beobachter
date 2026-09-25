# =============================================================================
# POLYMARKET BEOBACHTER - GUARDRAIL AUDIT
# =============================================================================
#
# GOVERNANCE INTENT:
# Logs all guardrail decisions for audit and analysis.
# Helps understand why proposals were blocked or allowed.
#
# =============================================================================

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent
LOGS_DIR = PROJECT_ROOT / "logs"
DATA_DIR = PROJECT_ROOT / "data"
AUDIT_FILE = LOGS_DIR / "guardrail_audit.jsonl"
SHADOW_TRADES_FILE = DATA_DIR / "shadow_trades.jsonl"


def record_guardrail_decision(decision: Dict[str, Any]) -> None:
    """
    Record a guardrail decision to the audit log.

    Args:
        decision: Dict containing:
            - run_id: Pipeline run ID
            - proposal_id: Proposal ID
            - market_id: Market ID
            - allowed: Whether entry was allowed
            - reason_code: Short reason code (e.g., "inventory_limit")
            - reason_detail: Detailed reason
            - Additional metadata
    """
    try:
        LOGS_DIR.mkdir(parents=True, exist_ok=True)

        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **decision,
        }

        with open(AUDIT_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    except Exception as e:
        logger.warning(f"Failed to record guardrail decision: {e}")


def get_recent_decisions(limit: int = 100) -> List[Dict[str, Any]]:
    """
    Get recent guardrail decisions.

    Args:
        limit: Maximum number of decisions to return

    Returns:
        List of decision dicts
    """
    if not AUDIT_FILE.exists():
        return []

    decisions = []
    try:
        with open(AUDIT_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        decisions.append(json.loads(line))
                    except Exception:
                        pass
    except Exception as e:
        logger.warning(f"Failed to read guardrail audit: {e}")

    return decisions[-limit:]


def build_guardrail_summary(run_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Build a summary of guardrail decisions for a specific run or all recent runs.

    Args:
        run_id: Optional run ID to filter by

    Returns:
        Dict with summary statistics
    """
    decisions = get_recent_decisions(500)

    if run_id:
        decisions = [d for d in decisions if d.get("run_id") == run_id]

    total = len(decisions)
    allowed = sum(1 for d in decisions if d.get("allowed"))
    blocked = total - allowed

    # Group by reason code
    reason_counts: Dict[str, int] = {}
    for d in decisions:
        if not d.get("allowed"):
            code = d.get("reason_code", "unknown")
            reason_counts[code] = reason_counts.get(code, 0) + 1

    # Shadow analysis (what would have been allowed without inventory limit)
    shadow_allowed = sum(1 for d in decisions if d.get("shadow_allowed_without_inventory"))

    return {
        "run_id": run_id,
        "total_evaluated": total,
        "allowed_count": allowed,
        "blocked_count": blocked,
        "blocked_ratio": blocked / total if total > 0 else 0,
        "blocked_by_reason": reason_counts,
        "shadow_allowed_without_inventory": shadow_allowed,
        "shadow_allowed_ratio_without_inventory": shadow_allowed / total if total > 0 else 0,
    }


def export_shadow_trades(run_id: str, *, limit: int = 500) -> Dict[str, Any]:
    """
    Export "shadow-eligible" proposals into data/shadow_trades.jsonl.

    Purpose:
    - create an append-only ledger of what *would* have passed without inventory limits
    - enables post-run divergence analysis vs paper/live fills

    Contract:
    - deterministic + append-only
    - de-duplicate by (run_id, proposal_id) using a stable record_id
    - never throws (best-effort); returns counts for status/audit
    """
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)

        decisions = get_recent_decisions(limit)
        run_decisions = [d for d in decisions if d.get("run_id") == run_id]
        shadow = [d for d in run_decisions if d.get("shadow_allowed_without_inventory")]

        # Ensure file exists for downstream consumers even if empty for this run
        if not SHADOW_TRADES_FILE.exists():
            SHADOW_TRADES_FILE.touch()

        if not shadow:
            return {"run_id": run_id, "exported": 0, "skipped_existing": 0}

        existing_ids: set[str] = set()
        if SHADOW_TRADES_FILE.exists():
            try:
                with open(SHADOW_TRADES_FILE, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            existing_ids.add(json.loads(line).get("record_id", ""))
                        except Exception:
                            continue
            except Exception:
                pass

        exported = 0
        skipped = 0
        with open(SHADOW_TRADES_FILE, "a", encoding="utf-8") as f:
            for d in shadow:
                proposal_id = str(d.get("proposal_id") or "")
                record_id = f"SHADOW-{run_id}-{proposal_id}"
                if record_id in existing_ids:
                    skipped += 1
                    continue

                entry = {
                    "record_id": record_id,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "run_id": run_id,
                    "proposal_id": d.get("proposal_id"),
                    "market_id": d.get("market_id"),
                    "city": d.get("city"),
                    "market_question": d.get("market_question"),
                    "edge": d.get("edge"),
                    "implied_probability": d.get("implied_probability"),
                    "model_probability": d.get("model_probability"),
                    "confidence_level": d.get("confidence_level"),
                    "entry_price": d.get("entry_price"),
                    "reason_code": d.get("reason_code"),
                    "reason_detail": d.get("reason_detail"),
                    "source_audit_timestamp": d.get("timestamp"),
                }
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
                exported += 1

        return {"run_id": run_id, "exported": exported, "skipped_existing": skipped}
    except Exception as e:
        logger.warning("Failed to export shadow trades: %s", e)
        return {"run_id": run_id, "exported": 0, "skipped_existing": 0, "error": str(e)[:200]}


def get_block_rate_by_reason() -> Dict[str, float]:
    """
    Calculate block rates by reason code.

    Returns:
        Dict mapping reason codes to their percentages
    """
    decisions = get_recent_decisions(500)
    blocked = [d for d in decisions if not d.get("allowed")]

    if not blocked:
        return {}

    reason_counts: Dict[str, int] = {}
    for d in blocked:
        code = d.get("reason_code", "unknown")
        reason_counts[code] = reason_counts.get(code, 0) + 1

    total_blocked = len(blocked)
    return {
        code: count / total_blocked
        for code, count in reason_counts.items()
    }
