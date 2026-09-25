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


def _append_jsonl(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")


def record_shadow_trade_candidate(candidate: Dict[str, Any]) -> None:
    """
    Record a SHADOW (missed) trade candidate.

    GOVERNANCE:
    - Observability only (no effect on trading decisions)
    - Append-only JSONL for later analysis (missed opportunities)

    Typical use-case:
    - Entry was blocked due to inventory_limit / policy, BUT would have passed
      without inventory constraint (shadow_allowed_without_inventory==True).
    """
    try:
        ensure_shadow_trades_file()
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **candidate,
        }
        _append_jsonl(SHADOW_TRADES_FILE, entry)
    except Exception as e:
        logger.warning(f"Failed to record shadow trade candidate: {e}")


def ensure_shadow_trades_file() -> None:
    """Create `data/shadow_trades.jsonl` with a header if missing."""
    try:
        if SHADOW_TRADES_FILE.exists():
            return
        header = {
            "_type": "LOG_HEADER",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "description": "Append-only shadow trade candidates (missed opportunities)",
            "format": "JSONL (one JSON object per line)",
            "governance_notice": (
                "This file contains SHADOW candidates only (observability). "
                "No real trade was executed and this file must not influence Layer 1 decisions."
            ),
        }
        _append_jsonl(SHADOW_TRADES_FILE, header)
    except Exception as e:
        logger.warning(f"Failed to init shadow trades file: {e}")


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
    blocked_by_city: Dict[str, int] = {}
    blocked_by_market_type: Dict[str, int] = {}
    blocked_by_price_band: Dict[str, int] = {}
    for d in decisions:
        if not d.get("allowed"):
            code = d.get("reason_code", "unknown")
            reason_counts[code] = reason_counts.get(code, 0) + 1
            city = d.get("city")
            if city:
                blocked_by_city[city] = blocked_by_city.get(city, 0) + 1
            mt = d.get("market_type")
            if mt:
                blocked_by_market_type[mt] = blocked_by_market_type.get(mt, 0) + 1
            pb = d.get("price_band")
            if pb:
                blocked_by_price_band[pb] = blocked_by_price_band.get(pb, 0) + 1

    # Shadow analysis (what would have been allowed without inventory limit)
    shadow_allowed = sum(1 for d in decisions if d.get("shadow_allowed_without_inventory"))
    shadow_secondary_reasons: Dict[str, int] = {}
    for d in decisions:
        if d.get("shadow_allowed_without_inventory"):
            code = d.get("shadow_reason_code", "passed") or "passed"
            shadow_secondary_reasons[code] = shadow_secondary_reasons.get(code, 0) + 1

    return {
        "run_id": run_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "entries_considered": total,
        "allowed_count": allowed,
        "blocked_count": blocked,
        "blocked_ratio": blocked / total if total > 0 else 0,
        "blocked_by_reason": reason_counts,
        "blocked_by_city": blocked_by_city,
        "blocked_by_market_type": blocked_by_market_type,
        "blocked_by_price_band": blocked_by_price_band,
        "shadow_allowed_without_inventory": shadow_allowed,
        "shadow_allowed_ratio_without_inventory": shadow_allowed / total if total > 0 else 0,
        "shadow_secondary_reasons": shadow_secondary_reasons,
    }


def build_shadow_eligibility(run_id: Optional[str] = None, top_n: int = 20) -> Dict[str, Any]:
    """
    Build a SHADOW eligibility snapshot for monitoring and agentic policy.

    This answers: "Welche Trades wären OHNE Inventory-Limit handelbar gewesen?"
    """
    decisions = get_recent_decisions(5000)
    if run_id:
        decisions = [d for d in decisions if d.get("run_id") == run_id]

    shadow = [d for d in decisions if d.get("shadow_allowed_without_inventory")]

    def _edge_key(d: Dict[str, Any]) -> float:
        try:
            return abs(float(d.get("edge") or 0.0))
        except Exception:
            return 0.0

    shadow.sort(key=_edge_key, reverse=True)

    fields = [
        "timestamp",
        "run_id",
        "proposal_id",
        "market_id",
        "allowed",
        "reason_code",
        "reason_detail",
        "policy_open_positions_count",
        "shadow_allowed_without_inventory",
        "shadow_reason_code",
        "shadow_reason_detail",
        "market_question",
        "edge",
        "implied_probability",
        "model_probability",
        "confidence_level",
        "city",
        "market_type",
        "price_band",
        "entry_price",
    ]
    top = [{k: d.get(k) for k in fields} for d in shadow[:top_n]]

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "run_id": run_id,
        "shadow_allowed_without_inventory": len(shadow),
        "top_candidates": top,
    }


def build_edge_hunter(run_id: Optional[str] = None, top_n: int = 25) -> Dict[str, Any]:
    """
    Build a compact "edge hunter" view:
    - strongest positive edges
    - what got blocked (and why)
    - what would have been allowed in shadow mode
    """
    decisions = get_recent_decisions(5000)
    if run_id:
        decisions = [d for d in decisions if d.get("run_id") == run_id]

    # Attach paper SKIP reasons (best-effort) by proposal_id
    paper_skip_reason_by_proposal: Dict[str, str] = {}
    try:
        paper_trades_path = PROJECT_ROOT / "paper_trader" / "logs" / "paper_trades.jsonl"
        if paper_trades_path.exists():
            with open(paper_trades_path, "r", encoding="utf-8") as f:
                for line in f.readlines()[-5000:]:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except Exception:
                        continue
                    if rec.get("_type") == "LOG_HEADER":
                        continue
                    if rec.get("action") != "SKIP":
                        continue
                    pid = rec.get("proposal_id")
                    if pid and rec.get("reason"):
                        paper_skip_reason_by_proposal[pid] = str(rec.get("reason"))
    except Exception:
        pass

    def _edge(d: Dict[str, Any]) -> float:
        try:
            return float(d.get("edge") or 0.0)
        except Exception:
            return 0.0

    positive = [d for d in decisions if _edge(d) > 0]
    positive.sort(key=lambda d: _edge(d), reverse=True)

    def _pack(d: Dict[str, Any]) -> Dict[str, Any]:
        packed = {
            "timestamp": d.get("timestamp"),
            "run_id": d.get("run_id"),
            "proposal_id": d.get("proposal_id"),
            "market_id": d.get("market_id"),
            "market_question": d.get("market_question"),
            "edge": d.get("edge"),
            "implied_probability": d.get("implied_probability"),
            "model_probability": d.get("model_probability"),
            "confidence_level": d.get("confidence_level"),
            "city": d.get("city"),
            "market_type": d.get("market_type"),
            "price_band": d.get("price_band"),
            "entry_price": d.get("entry_price"),
            "allowed": d.get("allowed"),
            "reason_code": d.get("reason_code"),
            "reason_detail": d.get("reason_detail"),
            "shadow_allowed_without_inventory": d.get("shadow_allowed_without_inventory"),
            "shadow_reason_code": d.get("shadow_reason_code"),
            "shadow_reason_detail": d.get("shadow_reason_detail"),
        }
        pid = d.get("proposal_id")
        if pid and pid in paper_skip_reason_by_proposal:
            packed["paper_skip_reason"] = paper_skip_reason_by_proposal[pid]
        return packed

    top_allowed = [_pack(d) for d in positive if d.get("allowed")][:top_n]
    top_blocked = [_pack(d) for d in positive if not d.get("allowed")][:top_n]
    top_missed_inventory = [
        _pack(d)
        for d in positive
        if (not d.get("allowed")) and d.get("reason_code") == "inventory_limit" and d.get("shadow_allowed_without_inventory")
    ][:top_n]

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "run_id": run_id,
        "counts": {
            "decisions_total": len(decisions),
            "positive_edge_total": len(positive),
            "positive_edge_allowed": len([d for d in positive if d.get("allowed")]),
            "positive_edge_blocked": len([d for d in positive if not d.get("allowed")]),
            "missed_due_to_inventory_limit": len(
                [
                    d
                    for d in positive
                    if (not d.get("allowed")) and d.get("reason_code") == "inventory_limit" and d.get("shadow_allowed_without_inventory")
                ]
            ),
        },
        "top_allowed_positive": top_allowed,
        "top_blocked_positive": top_blocked,
        "top_missed_inventory_limit": top_missed_inventory,
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
