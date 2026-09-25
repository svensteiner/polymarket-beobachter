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
from typing import Any, Dict, Iterable, List, Optional, Tuple

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent
LOGS_DIR = PROJECT_ROOT / "logs"
AUDIT_FILE = LOGS_DIR / "guardrail_audit.jsonl"

_DEFAULT_TAIL_BYTES = 8 * 1024 * 1024  # 8MB tail-read to avoid loading huge logs


def _tail_lines(path: Path, *, max_lines: int, max_bytes: int) -> List[str]:
    """
    Read up to max_lines from the end of a file without loading the full file.

    Best-effort: falls back to full read if tail-reading fails.
    """
    if max_lines <= 0:
        return []
    if max_bytes <= 0:
        max_bytes = _DEFAULT_TAIL_BYTES

    try:
        size = path.stat().st_size
        start = max(0, size - max_bytes)
        with open(path, "rb") as f:
            f.seek(start)
            chunk = f.read()

        # Ensure we start at a line boundary (unless we started at 0)
        if start > 0:
            nl = chunk.find(b"\n")
            if nl >= 0:
                chunk = chunk[nl + 1 :]

        text = chunk.decode("utf-8", errors="replace")
        lines = [ln for ln in text.splitlines() if ln.strip()]
        return lines[-max_lines:]
    except Exception as e:
        logger.debug(f"Tail read failed for {path}: {e}")
        try:
            return [
                ln
                for ln in path.read_text(encoding="utf-8", errors="replace").splitlines()
                if ln.strip()
            ][-max_lines:]
        except Exception:
            return []


def _parse_json_lines(lines: Iterable[str]) -> List[Dict[str, Any]]:
    parsed: List[Dict[str, Any]] = []
    for line in lines:
        try:
            parsed.append(json.loads(line))
        except Exception:
            continue
    return parsed

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


def get_recent_decisions(limit: int = 100, *, max_tail_bytes: int = _DEFAULT_TAIL_BYTES) -> List[Dict[str, Any]]:
    """
    Get recent guardrail decisions.

    Args:
        limit: Maximum number of decisions to return

    Returns:
        List of decision dicts
    """
    if not AUDIT_FILE.exists():
        return []

    try:
        # Read more than limit to compensate for parse failures.
        raw_lines = _tail_lines(AUDIT_FILE, max_lines=max(limit * 6, 200), max_bytes=max_tail_bytes)
        decisions = _parse_json_lines(raw_lines)
    except Exception as e:
        logger.warning(f"Failed to read guardrail audit tail: {e}")
        return []

    return decisions[-limit:]


def _infer_market_type_from_question(question: str) -> str:
    q = (question or "").lower()
    if "between" in q:
        return "between"
    if "exactly" in q:
        return "exact"
    if "at or above" in q or "or above" in q or "above" in q or "exceed" in q:
        return "at_or_above"
    if "at or below" in q or "or below" in q or "below" in q or "under" in q or "less" in q:
        return "at_or_below"
    return "unknown"


def _price_band(entry_price: Any) -> str:
    try:
        p = float(entry_price)
    except Exception:
        return "unknown"
    if p < 0.20:
        return "0.00-0.20"
    if p < 0.35:
        return "0.20-0.35"
    if p < 0.50:
        return "0.35-0.50"
    if p < 0.65:
        return "0.50-0.65"
    if p < 0.80:
        return "0.65-0.80"
    return "0.80-1.00"


def _summarize_decisions(
    decisions: List[Dict[str, Any]],
) -> Tuple[Dict[str, int], Dict[str, int], Dict[str, int], Dict[str, int]]:
    blocked_by_reason: Dict[str, int] = {}
    blocked_by_city: Dict[str, int] = {}
    blocked_by_market_type: Dict[str, int] = {}
    blocked_by_price_band: Dict[str, int] = {}

    for d in decisions:
        if d.get("allowed"):
            continue

        reason = str(d.get("reason_code", "unknown") or "unknown")
        blocked_by_reason[reason] = blocked_by_reason.get(reason, 0) + 1

        city = d.get("city")
        if city:
            city_s = str(city)
            blocked_by_city[city_s] = blocked_by_city.get(city_s, 0) + 1

        market_type = d.get("market_type") or _infer_market_type_from_question(str(d.get("market_question", "") or ""))
        blocked_by_market_type[market_type] = blocked_by_market_type.get(market_type, 0) + 1

        band = d.get("price_band") or _price_band(d.get("entry_price"))
        blocked_by_price_band[band] = blocked_by_price_band.get(band, 0) + 1

    return blocked_by_reason, blocked_by_city, blocked_by_market_type, blocked_by_price_band


def build_guardrail_summary(run_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Build a summary of guardrail decisions for a specific run or all recent runs.

    Args:
        run_id: Optional run ID to filter by

    Returns:
        Dict with summary statistics
    """
    decisions = get_recent_decisions(800)

    if run_id:
        decisions = [d for d in decisions if d.get("run_id") == run_id]

    total = len(decisions)
    allowed = sum(1 for d in decisions if d.get("allowed"))
    blocked = total - allowed

    # Shadow analysis (what would have been allowed without inventory limit)
    shadow_allowed = sum(1 for d in decisions if d.get("shadow_allowed_without_inventory"))

    blocked_by_reason, blocked_by_city, blocked_by_market_type, blocked_by_price_band = _summarize_decisions(decisions)

    shadow_candidates = [
        d
        for d in decisions
        if (not d.get("allowed")) and d.get("shadow_allowed_without_inventory")
    ]
    shadow_candidates.sort(key=lambda d: abs(float(d.get("edge", 0.0) or 0.0)), reverse=True)

    shadow_secondary_reasons: Dict[str, int] = {}
    for d in shadow_candidates:
        code = str(d.get("shadow_reason_code", "unknown") or "unknown")
        shadow_secondary_reasons[code] = shadow_secondary_reasons.get(code, 0) + 1

    return {
        "run_id": run_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_evaluated": total,
        "allowed_count": allowed,
        "blocked_count": blocked,
        "blocked_ratio": blocked / total if total > 0 else 0,
        "blocked_by_reason": blocked_by_reason,
        "blocked_by_city": blocked_by_city,
        "blocked_by_price_band": blocked_by_price_band,
        "blocked_by_market_type": blocked_by_market_type,
        "shadow_allowed_without_inventory": shadow_allowed,
        "shadow_allowed_ratio_without_inventory": shadow_allowed / total if total > 0 else 0,
        "shadow_secondary_reasons": shadow_secondary_reasons,
        "top_candidates": shadow_candidates[:10],
    }


def export_shadow_trades_jsonl(
    *,
    run_id: Optional[str] = None,
    out_file: Optional[Path] = None,
    limit: int = 500,
) -> Path:
    """
    Export a compact shadow-trade stream from the guardrail audit.

    Shadow trade = (shadow_allowed_without_inventory == True) AND (allowed == False).
    This captures opportunities blocked by policy/inventory constraints so they can be
    evaluated offline without loosening guardrails.
    """
    out_path = out_file or (PROJECT_ROOT / "data" / "shadow_trades.jsonl")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    decisions = get_recent_decisions(max(limit * 6, 800))
    if run_id:
        decisions = [d for d in decisions if d.get("run_id") == run_id]

    shadow = [
        d
        for d in decisions
        if (not d.get("allowed")) and d.get("shadow_allowed_without_inventory")
    ]
    shadow.sort(key=lambda d: abs(float(d.get("edge", 0.0) or 0.0)), reverse=True)
    shadow = shadow[:limit]

    now = datetime.now(timezone.utc).isoformat()
    with open(out_path, "w", encoding="utf-8") as f:
        for d in shadow:
            row = {
                "exported_at": now,
                "run_id": d.get("run_id"),
                "proposal_id": d.get("proposal_id"),
                "market_id": d.get("market_id"),
                "market_question": d.get("market_question"),
                "city": d.get("city"),
                "entry_price": d.get("entry_price"),
                "implied_probability": d.get("implied_probability"),
                "model_probability": d.get("model_probability"),
                "edge": d.get("edge"),
                "reason_code": d.get("reason_code"),
                "reason_detail": d.get("reason_detail"),
                "shadow_reason_code": d.get("shadow_reason_code"),
                "shadow_reason_detail": d.get("shadow_reason_detail"),
            }
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    return out_path


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
