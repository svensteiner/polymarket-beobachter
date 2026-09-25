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


def write_edge_hunter_report(run_id: Optional[str] = None, top_n: int = 25) -> Dict[str, Any]:
    """
    Write a compact report of the strongest candidates.

    Output: `output/edge_hunter.json`
    Purpose: quick diagnostics whether there is actionable edge and why trades
    are blocked, without changing any guardrails.
    """
    try:
        output_dir = PROJECT_ROOT / "output"
        output_dir.mkdir(parents=True, exist_ok=True)
        out_path = output_dir / "edge_hunter.json"

        decisions = get_recent_decisions(2000)
        if run_id:
            decisions = [d for d in decisions if d.get("run_id") == run_id]

        def _edge_abs(d: Dict[str, Any]) -> float:
            try:
                return abs(float(d.get("edge") or 0.0))
            except Exception:
                return 0.0

        def _side(d: Dict[str, Any]) -> str:
            try:
                return "YES" if float(d.get("edge") or 0.0) > 0 else "NO"
            except Exception:
                return "NO"

        total = len(decisions)
        allowed = [d for d in decisions if d.get("allowed")]
        blocked = [d for d in decisions if not d.get("allowed")]

        allowed_sorted = sorted(allowed, key=_edge_abs, reverse=True)[:top_n]
        blocked_sorted = sorted(blocked, key=_edge_abs, reverse=True)[:top_n]

        def _project(d: Dict[str, Any]) -> Dict[str, Any]:
            return {
                "proposal_id": d.get("proposal_id"),
                "market_id": d.get("market_id"),
                "city": d.get("city"),
                "market_type": d.get("market_type"),
                "side": _side(d),
                "edge": d.get("edge"),
                "implied_probability": d.get("implied_probability"),
                "model_probability": d.get("model_probability"),
                "confidence_level": d.get("confidence_level"),
                "entry_price": d.get("entry_price"),
                "allowed": d.get("allowed"),
                "reason_code": d.get("reason_code"),
                "reason_detail": d.get("reason_detail"),
                "shadow_allowed_without_inventory": d.get("shadow_allowed_without_inventory"),
            }

        summary = build_guardrail_summary(run_id=run_id)
        payload = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "run_id": run_id,
            "total_evaluated": total,
            "summary": summary,
            "top_allowed": [_project(d) for d in allowed_sorted],
            "top_blocked": [_project(d) for d in blocked_sorted],
        }

        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

        return payload

    except Exception as e:
        logger.warning("Failed to write edge_hunter report: %s", e)
        return {"error": str(e), "run_id": run_id}


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
