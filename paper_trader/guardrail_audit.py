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
AUDIT_FILE = LOGS_DIR / "guardrail_audit.jsonl"


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


def build_shadow_eligibility(run_id: Optional[str] = None, limit: int = 20) -> Dict[str, Any]:
    """
    Build a small report of top shadow-eligible candidates.

    "Shadow-eligible" means: the entry would pass all guardrails if the
    inventory limit is ignored (used for opportunity scouting only).
    """
    decisions = get_recent_decisions(1000)
    if run_id:
        decisions = [d for d in decisions if d.get("run_id") == run_id]

    candidates = [d for d in decisions if d.get("shadow_allowed_without_inventory")]

    def _edge_abs(item: Dict[str, Any]) -> float:
        try:
            return abs(float(item.get("edge", 0.0) or 0.0))
        except Exception:
            return 0.0

    candidates.sort(key=_edge_abs, reverse=True)

    trimmed: list[Dict[str, Any]] = []
    for item in candidates[:limit]:
        # Keep only a stable subset to avoid schema churn.
        trimmed.append(
            {
                "timestamp": item.get("timestamp"),
                "run_id": item.get("run_id"),
                "proposal_id": item.get("proposal_id"),
                "market_id": item.get("market_id"),
                "allowed": item.get("allowed"),
                "reason_code": item.get("reason_code"),
                "reason_detail": item.get("reason_detail"),
                "policy_open_positions_count": item.get("policy_open_positions_count"),
                "shadow_allowed_without_inventory": item.get("shadow_allowed_without_inventory"),
                "shadow_reason_code": item.get("shadow_reason_code"),
                "shadow_reason_detail": item.get("shadow_reason_detail"),
                "city": item.get("city"),
                "market_type": item.get("market_type"),
                "price_band": item.get("price_band"),
                "confidence": item.get("confidence"),
                "implied_probability": item.get("implied_probability"),
                "edge": item.get("edge"),
            }
        )

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "run_id": run_id,
        "shadow_allowed_without_inventory": len(candidates),
        "top_candidates": trimmed,
    }


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
