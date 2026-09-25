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
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent
LOGS_DIR = PROJECT_ROOT / "logs"
AUDIT_FILE = LOGS_DIR / "guardrail_audit.jsonl"
DEFAULT_EDGE_HUNTER_FILE = PROJECT_ROOT / "output" / "edge_hunter.json"
DEFAULT_SHADOW_TRADES_FILE = PROJECT_ROOT / "data" / "shadow_trades.jsonl"


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


def build_edge_hunter_snapshot(
    run_id: Optional[str] = None,
    limit: int = 20,
    include_shadow_only: bool = True,
) -> Dict[str, Any]:
    """
    Build an "edge hunter" snapshot from recent guardrail decisions.

    Governance intent:
    - Deterministic, audit-friendly artifact for automations/ops.
    - NOT a trading signal generator; only a ranking of observed edges.
    """
    decisions = get_recent_decisions(2000)
    if run_id:
        decisions = [d for d in decisions if d.get("run_id") == run_id]

    # Optionally focus on shadow-eligible (inventory-free) candidates.
    if include_shadow_only:
        decisions = [d for d in decisions if d.get("shadow_allowed_without_inventory")]

    def _edge_abs(d: Dict[str, Any]) -> float:
        try:
            return abs(float(d.get("edge") or 0.0))
        except Exception:
            return 0.0

    top = sorted(decisions, key=_edge_abs, reverse=True)[: max(0, int(limit))]

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "run_id": run_id,
        "source": "logs/guardrail_audit.jsonl",
        "filters": {
            "include_shadow_only": include_shadow_only,
            "limit": limit,
        },
        "counts": {
            "total_considered": len(decisions),
            "top_returned": len(top),
        },
        "top_candidates": top,
    }


def write_edge_hunter_artifact(
    run_id: Optional[str] = None,
    output_path: Path = DEFAULT_EDGE_HUNTER_FILE,
    limit: int = 20,
) -> Tuple[bool, str]:
    """Write output/edge_hunter.json for ops/automation compatibility."""
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        snapshot = build_edge_hunter_snapshot(run_id=run_id, limit=limit, include_shadow_only=True)
        tmp = output_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(output_path)
        return True, f"Wrote {output_path}"
    except Exception as e:
        return False, f"edge_hunter write failed: {e}"


def _shadow_file_has_run_id(filepath: Path, run_id: str) -> bool:
    if not filepath.exists():
        return False
    try:
        # Fast check: scan last ~10k lines at most (avoid full file reads).
        lines = filepath.read_text(encoding="utf-8", errors="replace").splitlines()
        for ln in reversed(lines[-10000:]):
            if run_id in ln:
                try:
                    obj = json.loads(ln)
                except Exception:
                    continue
                if obj.get("run_id") == run_id:
                    return True
        return False
    except Exception:
        return False


def append_shadow_trades(
    run_id: str,
    data_path: Path = DEFAULT_SHADOW_TRADES_FILE,
    limit: int = 50,
) -> Tuple[bool, str]:
    """
    Append shadow-eligible candidates for this run to data/shadow_trades.jsonl.

    This is NOT execution. It's a paper/shadow audit trail for later evaluation.
    Fail-closed: on any error, do not write partial data.
    """
    try:
        data_path.parent.mkdir(parents=True, exist_ok=True)
        if _shadow_file_has_run_id(data_path, run_id):
            return True, f"shadow_trades already has run_id={run_id}"

        snapshot = build_edge_hunter_snapshot(run_id=run_id, limit=limit, include_shadow_only=True)
        candidates = snapshot.get("top_candidates", []) or []

        # Build normalized shadow records (stable schema)
        now = datetime.now(timezone.utc).isoformat()
        out_lines: List[str] = []
        for c in candidates:
            out_lines.append(
                json.dumps(
                    {
                        "schema_version": 1,
                        "timestamp": now,
                        "run_id": c.get("run_id", run_id),
                        "proposal_id": c.get("proposal_id"),
                        "market_id": c.get("market_id"),
                        "shadow_allowed_without_inventory": bool(c.get("shadow_allowed_without_inventory")),
                        "shadow_reason_code": c.get("shadow_reason_code"),
                        "shadow_reason_detail": c.get("shadow_reason_detail"),
                        "allowed": bool(c.get("allowed")),
                        "reason_code": c.get("reason_code"),
                        "reason_detail": c.get("reason_detail"),
                        "edge": c.get("edge"),
                        "implied_probability": c.get("implied_probability"),
                        "model_probability": c.get("model_probability"),
                        "confidence_level": c.get("confidence_level"),
                        "market_question": c.get("market_question"),
                        "city": c.get("city"),
                        "entry_price": c.get("entry_price"),
                        "source": "guardrail_audit",
                    },
                    ensure_ascii=False,
                )
            )

        if not out_lines:
            # Ensure the file exists for automation compatibility, even if empty.
            if not data_path.exists():
                data_path.write_text("", encoding="utf-8")
            return True, f"No shadow candidates for run_id={run_id}"

        tmp = data_path.with_suffix(".tmp")
        prior = ""
        if data_path.exists():
            prior = data_path.read_text(encoding="utf-8", errors="replace")
        tmp.write_text(prior + ("\n" if prior and not prior.endswith("\n") else "") + "\n".join(out_lines) + "\n", encoding="utf-8")
        tmp.replace(data_path)
        return True, f"Appended {len(out_lines)} shadow records to {data_path}"
    except Exception as e:
        return False, f"shadow_trades append failed: {e}"
