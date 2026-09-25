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
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent
LOGS_DIR = PROJECT_ROOT / "logs"
AUDIT_FILE = LOGS_DIR / "guardrail_audit.jsonl"
OUTPUT_DIR = PROJECT_ROOT / "output"
DATA_DIR = PROJECT_ROOT / "data"
EDGE_HUNTER_FILE = OUTPUT_DIR / "edge_hunter.json"
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


def _iter_audit_entries(limit: int = 5000) -> List[Dict[str, Any]]:
    """Read up to `limit` most recent audit entries (best-effort)."""
    if not AUDIT_FILE.exists():
        return []

    entries: List[Dict[str, Any]] = []
    try:
        with open(AUDIT_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except Exception:
                    continue
    except Exception as e:
        logger.warning(f"Failed to read guardrail audit: {e}")
        return []

    if limit <= 0:
        return entries
    return entries[-limit:]


def get_latest_run_id() -> Optional[str]:
    """Best-effort: infer the latest run_id present in the audit log."""
    for entry in reversed(_iter_audit_entries(limit=5000)):
        run_id = entry.get("run_id")
        if isinstance(run_id, str) and run_id.strip():
            return run_id
    return None


def build_edge_hunter_artifact(run_id: Optional[str] = None) -> Dict[str, Any]:
    """Build a compact 'edge_hunter' artifact from guardrail audit logs.

    Governance intent: observability only. No trading decisions are made here.
    """
    run_id = run_id or get_latest_run_id()
    entries = _iter_audit_entries(limit=20000)
    if run_id:
        entries = [e for e in entries if e.get("run_id") == run_id]

    edges = [e.get("edge") for e in entries if isinstance(e.get("edge"), (int, float))]
    allowed_edges = [e.get("edge") for e in entries if e.get("allowed") and isinstance(e.get("edge"), (int, float))]
    shadow_edges = [
        e.get("edge")
        for e in entries
        if e.get("shadow_allowed_without_inventory") and isinstance(e.get("edge"), (int, float))
    ]

    def _stats(vals: List[float]) -> Dict[str, Any]:
        if not vals:
            return {"count": 0}
        vs = sorted(float(v) for v in vals)
        n = len(vs)
        mean = sum(vs) / n
        median = vs[n // 2] if n % 2 == 1 else (vs[n // 2 - 1] + vs[n // 2]) / 2
        return {
            "count": n,
            "min": vs[0],
            "median": median,
            "mean": mean,
            "max": vs[-1],
            "pos_ratio": sum(1 for v in vs if v > 0) / n,
            "neg_ratio": sum(1 for v in vs if v < 0) / n,
        }

    # Top positive edges (if any)
    top_positive = [
        {
            "proposal_id": e.get("proposal_id"),
            "market_id": e.get("market_id"),
            "edge": e.get("edge"),
            "implied_probability": e.get("implied_probability"),
            "model_probability": e.get("model_probability"),
            "confidence_level": e.get("confidence_level"),
            "city": e.get("city"),
            "entry_price": e.get("entry_price"),
            "market_question": e.get("market_question"),
            "reason_code": e.get("reason_code"),
        }
        for e in entries
        if isinstance(e.get("edge"), (int, float)) and float(e.get("edge")) > 0
    ]
    top_positive.sort(key=lambda r: float(r.get("edge", 0.0)), reverse=True)
    top_positive = top_positive[:20]

    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "run_id": run_id,
        "sample_window_entries": len(entries),
        "edge_stats": _stats(edges),
        "allowed_edge_stats": _stats(allowed_edges),
        "shadow_edge_stats": _stats(shadow_edges),
        "top_positive_edges": top_positive,
    }


def write_edge_hunter_artifact(run_id: Optional[str] = None) -> bool:
    """Write `output/edge_hunter.json` (best-effort, non-blocking)."""
    try:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        artifact = build_edge_hunter_artifact(run_id=run_id)
        EDGE_HUNTER_FILE.write_text(json.dumps(artifact, ensure_ascii=False, indent=2), encoding="utf-8")
        return True
    except Exception as e:
        logger.warning(f"Failed to write edge_hunter artifact: {e}")
        return False


def _shadow_record_id(run_id: str, proposal_id: str, market_id: str) -> str:
    h = hashlib.sha1(f"{run_id}:{proposal_id}:{market_id}".encode("utf-8")).hexdigest()[:12]
    return f"SHADOW-{h}"


def append_shadow_trades_for_run(run_id: Optional[str] = None) -> int:
    """Append shadow-trade candidates to `data/shadow_trades.jsonl`.

    Shadow trades are *counterfactual* trades that would have been allowed
    without inventory constraints. This is for validation only.

    Returns:
        Number of newly appended records.
    """
    run_id = run_id or get_latest_run_id()
    if not run_id:
        return 0

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SHADOW_TRADES_FILE.touch(exist_ok=True)

    # Idempotence per run_id: avoid duplicates
    existing_ids: set[str] = set()
    try:
        with open(SHADOW_TRADES_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                if rec.get("run_id") == run_id and isinstance(rec.get("record_id"), str):
                    existing_ids.add(rec["record_id"])
    except Exception:
        # fail-closed: proceed without de-dupe (worst case: duplicates)
        existing_ids = set()

    appended = 0
    entries = _iter_audit_entries(limit=20000)
    entries = [e for e in entries if e.get("run_id") == run_id]

    shadow_candidates = [
        e for e in entries
        if not e.get("allowed")
        and e.get("reason_code") == "inventory_limit"
        and e.get("shadow_allowed_without_inventory")
    ]

    if not shadow_candidates:
        return 0

    try:
        with open(SHADOW_TRADES_FILE, "a", encoding="utf-8") as f:
            for e in shadow_candidates:
                proposal_id = str(e.get("proposal_id", ""))
                market_id = str(e.get("market_id", ""))
                rid = _shadow_record_id(run_id, proposal_id, market_id)
                if rid in existing_ids:
                    continue

                out = {
                    "record_id": rid,
                    "timestamp_logged": datetime.now(timezone.utc).isoformat(),
                    "run_id": run_id,
                    "proposal_id": proposal_id,
                    "market_id": market_id,
                    "edge": e.get("edge"),
                    "implied_probability": e.get("implied_probability"),
                    "model_probability": e.get("model_probability"),
                    "confidence_level": e.get("confidence_level"),
                    "city": e.get("city"),
                    "entry_price": e.get("entry_price"),
                    "market_question": e.get("market_question"),
                    "reason_code": e.get("reason_code"),
                    "reason_detail": e.get("reason_detail"),
                }
                f.write(json.dumps(out, ensure_ascii=False) + "\n")
                existing_ids.add(rid)
                appended += 1
    except Exception as e:
        logger.warning(f"Failed to append shadow trades: {e}")

    return appended
