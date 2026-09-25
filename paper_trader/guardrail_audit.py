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
DATA_DIR = PROJECT_ROOT / "data"
SHADOW_TRADES_FILE = DATA_DIR / "shadow_trades.jsonl"
OUTPUT_DIR = PROJECT_ROOT / "output"
EDGE_HUNTER_FILE = OUTPUT_DIR / "edge_hunter.json"


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
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **decision,
        }

        with open(AUDIT_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

        # Shadow trade log (for evaluating inventory-limit misses without executing trades).
        # Only log when the "shadow without inventory" gate is passed.
        if decision.get("shadow_allowed_without_inventory"):
            shadow_entry = {
                "timestamp": entry["timestamp"],
                "run_id": decision.get("run_id"),
                "proposal_id": decision.get("proposal_id"),
                "market_id": decision.get("market_id"),
                "allowed": bool(decision.get("allowed")),
                "reason_code": decision.get("reason_code"),
                "reason_detail": decision.get("reason_detail"),
                "shadow_reason_code": decision.get("shadow_reason_code"),
                "shadow_reason_detail": decision.get("shadow_reason_detail"),
                "city": decision.get("city"),
                "market_type": decision.get("market_type"),
                "price_band": decision.get("price_band"),
                "confidence_level": decision.get("confidence_level") or decision.get("confidence"),
                "implied_probability": decision.get("implied_probability"),
                "model_probability": decision.get("model_probability"),
                "edge": decision.get("edge"),
                "entry_price": decision.get("entry_price"),
                "market_question": decision.get("market_question"),
            }
            with open(SHADOW_TRADES_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(shadow_entry, ensure_ascii=False) + "\n")

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


def write_edge_hunter_report(run_id: str | None, limit: int = 25) -> Dict[str, Any]:
    """Write a compact 'edge hunter' report for the most recent run.

    This is intentionally READ-ONLY: it summarizes guardrail decisions only.
    """
    try:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        decisions = get_recent_decisions(1500)
        if run_id:
            decisions = [d for d in decisions if d.get("run_id") == run_id]

        def _edge_value(d: Dict[str, Any]) -> float:
            try:
                return float(d.get("edge") or 0.0)
            except Exception:
                return 0.0

        with_edge = [d for d in decisions if d.get("edge") is not None]
        top = sorted(with_edge, key=lambda d: abs(_edge_value(d)), reverse=True)[:limit]

        by_reason: Dict[str, int] = {}
        by_city: Dict[str, int] = {}
        for d in decisions:
            code = str(d.get("reason_code") or ("passed" if d.get("allowed") else "unknown"))
            by_reason[code] = by_reason.get(code, 0) + 1
            city = str(d.get("city") or "N/A")
            by_city[city] = by_city.get(city, 0) + 1

        report = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "run_id": run_id,
            "decisions_considered": len(decisions),
            "shadow_allowed_without_inventory": sum(1 for d in decisions if d.get("shadow_allowed_without_inventory")),
            "blocked_by_reason": dict(sorted(by_reason.items(), key=lambda kv: kv[1], reverse=True)[:15]),
            "blocked_by_city": dict(sorted(by_city.items(), key=lambda kv: kv[1], reverse=True)[:15]),
            "top_edges": [
                {
                    "timestamp": d.get("timestamp"),
                    "proposal_id": d.get("proposal_id"),
                    "market_id": d.get("market_id"),
                    "allowed": bool(d.get("allowed")),
                    "reason_code": d.get("reason_code"),
                    "reason_detail": d.get("reason_detail"),
                    "shadow_allowed_without_inventory": bool(d.get("shadow_allowed_without_inventory")),
                    "city": d.get("city"),
                    "market_type": d.get("market_type"),
                    "price_band": d.get("price_band"),
                    "confidence_level": d.get("confidence_level"),
                    "implied_probability": d.get("implied_probability"),
                    "model_probability": d.get("model_probability"),
                    "edge": d.get("edge"),
                    "entry_price": d.get("entry_price"),
                    "market_question": d.get("market_question"),
                }
                for d in top
            ],
        }
        EDGE_HUNTER_FILE.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return report
    except Exception as e:
        logger.warning("Edge hunter report konnte nicht geschrieben werden: %s", e)
        return {}


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
