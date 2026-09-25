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
OUTPUT_DIR = PROJECT_ROOT / "output"
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


def get_decisions_for_run(
    run_id: str,
    max_scan_lines: int = 200_000,
    stop_after_misses: int = 3_000,
) -> List[Dict[str, Any]]:
    """
    Best-effort: load decisions for a specific run_id by scanning backwards.

    Rationale:
    - The audit file can grow large; loading everything is wasteful.
    - Run decisions are typically appended contiguously.
    """
    if not run_id or not AUDIT_FILE.exists():
        return []

    try:
        with open(AUDIT_FILE, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except Exception as e:
        logger.warning(f"Failed to read guardrail audit for run scan: {e}")
        return []

    collected: List[Dict[str, Any]] = []
    misses = 0
    scanned = 0
    started = False

    for raw in reversed(lines):
        scanned += 1
        if scanned > max_scan_lines:
            break
        raw = raw.strip()
        if not raw:
            continue
        try:
            obj = json.loads(raw)
        except Exception:
            continue

        if obj.get("run_id") == run_id:
            collected.append(obj)
            started = True
            misses = 0
            continue

        if started:
            misses += 1
            if misses >= stop_after_misses:
                break

    collected.reverse()
    return collected


def build_guardrail_summary(run_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Build a summary of guardrail decisions for a specific run or all recent runs.

    Args:
        run_id: Optional run ID to filter by

    Returns:
        Dict with summary statistics
    """
    if run_id:
        decisions = get_decisions_for_run(run_id)
    else:
        decisions = get_recent_decisions(500)

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

    return _build_rich_guardrail_summary(decisions=decisions, run_id=run_id)


def _build_rich_guardrail_summary(decisions: List[Dict[str, Any]], run_id: Optional[str]) -> Dict[str, Any]:
    total = len(decisions)
    allowed = sum(1 for d in decisions if d.get("allowed"))
    blocked = total - allowed

    blocked_by_reason: Dict[str, int] = {}
    blocked_by_city: Dict[str, int] = {}
    blocked_by_price_band: Dict[str, int] = {}
    blocked_by_market_type: Dict[str, int] = {}
    shadow_secondary_reasons: Dict[str, int] = {}

    shadow_allowed_without_inventory = 0
    for d in decisions:
        if d.get("shadow_allowed_without_inventory"):
            shadow_allowed_without_inventory += 1
            shadow_secondary_reasons[str(d.get("shadow_reason_code", "unknown"))] = (
                shadow_secondary_reasons.get(str(d.get("shadow_reason_code", "unknown")), 0) + 1
            )

        if d.get("allowed"):
            continue

        reason = str(d.get("reason_code", "unknown"))
        blocked_by_reason[reason] = blocked_by_reason.get(reason, 0) + 1

        city = str(d.get("city") or "").strip()
        if city:
            blocked_by_city[city] = blocked_by_city.get(city, 0) + 1

        price_band = str(d.get("price_band") or "").strip()
        if price_band:
            blocked_by_price_band[price_band] = blocked_by_price_band.get(price_band, 0) + 1

        market_type = str(d.get("market_type") or "").strip()
        if market_type:
            blocked_by_market_type[market_type] = blocked_by_market_type.get(market_type, 0) + 1

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "run_id": run_id,
        "entries_considered": total,
        "allowed_count": allowed,
        "blocked_count": blocked,
        "blocked_ratio": blocked / total if total > 0 else 0,
        "shadow_allowed_without_inventory": shadow_allowed_without_inventory,
        "shadow_allowed_ratio_without_inventory": shadow_allowed_without_inventory / total if total > 0 else 0,
        "shadow_secondary_reasons": shadow_secondary_reasons,
        "blocked_by_reason": blocked_by_reason,
        "blocked_by_city": blocked_by_city,
        "blocked_by_price_band": blocked_by_price_band,
        "blocked_by_market_type": blocked_by_market_type,
    }


def build_shadow_eligibility(run_id: Optional[str] = None, limit: int = 12) -> Dict[str, Any]:
    """
    Build the shadow-eligibility file used by the AgentPolicyEngine.

    We only list opportunities that were blocked by *inventory* while still passing
    all other guardrails (i.e. shadow_allowed_without_inventory == True).
    """
    if run_id:
        decisions = get_decisions_for_run(run_id)
    else:
        decisions = get_recent_decisions(2000)

    candidates: List[Dict[str, Any]] = []
    for d in decisions:
        if not d.get("shadow_allowed_without_inventory"):
            continue
        if d.get("allowed"):
            continue
        if str(d.get("reason_code", "")).strip() != "inventory_limit":
            continue
        candidates.append(d)

    def _edge_abs(item: Dict[str, Any]) -> float:
        try:
            return abs(float(item.get("edge", 0.0) or 0.0))
        except (TypeError, ValueError):
            return 0.0

    candidates.sort(key=_edge_abs, reverse=True)
    top = candidates[: max(0, int(limit))]

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "run_id": run_id,
        "shadow_allowed_without_inventory": len(candidates),
        "top_candidates": [
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
                "confidence": item.get("confidence_level") or item.get("confidence"),
                "implied_probability": item.get("implied_probability") or item.get("entry_price"),
                "edge": item.get("edge"),
            }
            for item in top
        ],
    }
    return payload


def write_guardrail_outputs(run_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Persist guardrail summary + shadow eligibility to output/ for downstream policy.

    Returns:
        Dict with the written payloads (guardrail_summary, shadow_eligibility).
    """
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    if run_id:
        decisions = get_decisions_for_run(run_id)
    else:
        decisions = get_recent_decisions(2000)

    guardrail_summary = _build_rich_guardrail_summary(decisions=decisions, run_id=run_id)
    shadow_eligibility = build_shadow_eligibility(run_id=run_id, limit=12)

    (OUTPUT_DIR / "guardrail_summary.json").write_text(
        json.dumps(guardrail_summary, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    (OUTPUT_DIR / "shadow_eligibility.json").write_text(
        json.dumps(shadow_eligibility, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    _append_shadow_trades(shadow_eligibility.get("top_candidates", []))
    return {"guardrail_summary": guardrail_summary, "shadow_eligibility": shadow_eligibility}


def _append_shadow_trades(candidates: List[Dict[str, Any]], max_existing_scan: int = 5000) -> None:
    """
    Append shadow candidates into data/shadow_trades.jsonl, idempotent by proposal_id.

    This file is intentionally small and run-scoped (top candidates only).
    It enables later resolution & segment analysis to answer: "what did we miss due to inventory?"
    """
    if not candidates:
        return

    existing: set[str] = set()
    if SHADOW_TRADES_FILE.exists():
        try:
            with open(SHADOW_TRADES_FILE, "r", encoding="utf-8") as f:
                lines = f.readlines()[-max_existing_scan:]
            for line in lines:
                try:
                    obj = json.loads(line)
                    pid = str(obj.get("proposal_id") or "")
                    if pid:
                        existing.add(pid)
                except Exception:
                    continue
        except Exception as exc:
            logger.debug("Shadow trades scan failed (%s): %s", SHADOW_TRADES_FILE, exc)

    to_write = []
    newly_seen: set[str] = set()
    for item in candidates:
        pid = str(item.get("proposal_id") or "")
        if not pid or pid in existing or pid in newly_seen:
            continue
        newly_seen.add(pid)
        to_write.append(
            {
                "logged_at": datetime.now(timezone.utc).isoformat(),
                "proposal_id": pid,
                "run_id": item.get("run_id"),
                "market_id": item.get("market_id"),
                "city": item.get("city"),
                "market_type": item.get("market_type"),
                "price_band": item.get("price_band"),
                "confidence": item.get("confidence"),
                "implied_probability": item.get("implied_probability"),
                "edge": item.get("edge"),
                "reason_code": item.get("reason_code"),
                "reason_detail": item.get("reason_detail"),
            }
        )

    if not to_write:
        return

    try:
        SHADOW_TRADES_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(SHADOW_TRADES_FILE, "a", encoding="utf-8") as f:
            for row in to_write:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception as exc:
        logger.warning("Failed to append shadow trades: %s", exc)


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
