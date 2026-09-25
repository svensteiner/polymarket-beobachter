# =============================================================================
# POLYMARKET BEOBACHTER - EDGE HUNTER (READ-ONLY)
# =============================================================================
#
# GOVERNANCE INTENT:
# - Produces a compact, actionable "top edges" view for operators.
# - Uses existing audit artifacts only (no guardrail changes, no trading actions).
#
# Output:
# - output/edge_hunter.json
#
# =============================================================================

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def _safe_float(x: Any, default: float = 0.0) -> float:
    try:
        return float(x)
    except Exception:
        return default


def _load_recent_jsonl(path: Path, limit: int = 2500) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    try:
        # Simple, robust approach: read all lines and slice tail.
        # guardrail_audit.jsonl is expected to be manageable; limit keeps it bounded.
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        out: List[Dict[str, Any]] = []
        for line in lines[-limit:]:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except Exception:
                continue
        return out
    except Exception as e:
        logger.debug("edge_hunter: failed reading %s: %s", path, e)
        return []


def _normalize_candidate(d: Dict[str, Any]) -> Dict[str, Any]:
    edge = _safe_float(d.get("edge"))
    implied = _safe_float(d.get("implied_probability"))
    model = _safe_float(d.get("model_probability"))
    entry_price = _safe_float(d.get("entry_price"))
    side = "YES" if edge >= 0 else "NO"
    edge_abs = abs(edge)
    return {
        "timestamp": d.get("timestamp"),
        "run_id": d.get("run_id"),
        "proposal_id": d.get("proposal_id"),
        "market_id": d.get("market_id"),
        "market_question": d.get("market_question"),
        "city": d.get("city"),
        "confidence_level": d.get("confidence_level"),
        "allowed": bool(d.get("allowed", False)),
        "reason_code": d.get("reason_code"),
        "reason_detail": d.get("reason_detail"),
        "shadow_allowed_without_inventory": bool(d.get("shadow_allowed_without_inventory", False)),
        "shadow_reason_code": d.get("shadow_reason_code"),
        "shadow_reason_detail": d.get("shadow_reason_detail"),
        "side": side,
        "edge": edge,
        "edge_abs": edge_abs,
        "implied_probability": implied,
        "model_probability": model,
        "entry_price": entry_price,
        "delta_pp": (model - implied) * 100.0,
    }


def run_edge_hunter(base_dir: Optional[Path] = None, top_n: int = 20) -> Dict[str, Any]:
    """
    Build a compact edge report from the guardrail audit log.

    Categories:
    - actionable_now: passed all guardrails (allowed=True)
    - shadow_candidates: would pass without inventory constraint (shadow_allowed_without_inventory=True)
    """
    base = base_dir or Path(__file__).parent.parent
    audit_file = base / "logs" / "guardrail_audit.jsonl"
    out_file = base / "output" / "edge_hunter.json"
    shadow_file = base / "data" / "shadow_trades.jsonl"

    decisions = _load_recent_jsonl(audit_file, limit=5000)

    normalized = [_normalize_candidate(d) for d in decisions]

    actionable = [c for c in normalized if c.get("allowed") is True]
    shadow = [
        c for c in normalized
        if c.get("allowed") is False and c.get("shadow_allowed_without_inventory") is True
    ]

    # Sort by absolute edge descending; prefer fresher timestamps implicitly by stable sort key second
    actionable.sort(key=lambda c: (c.get("edge_abs", 0.0), str(c.get("timestamp") or "")), reverse=True)
    shadow.sort(key=lambda c: (c.get("edge_abs", 0.0), str(c.get("timestamp") or "")), reverse=True)

    payload: Dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": str(audit_file),
        "decision_rows_considered": len(decisions),
        "actionable_now_count": len(actionable),
        "shadow_candidates_count": len(shadow),
        "actionable_now": actionable[:top_n],
        "shadow_candidates": shadow[:top_n],
    }

    try:
        out_file.parent.mkdir(parents=True, exist_ok=True)
        out_file.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        logger.debug("edge_hunter: failed writing %s: %s", out_file, e)

    # Ensure shadow trades file exists (append-only log is written by guardrail_audit).
    # This avoids "file missing" confusion during ops checks.
    try:
        shadow_file.parent.mkdir(parents=True, exist_ok=True)
        if not shadow_file.exists():
            shadow_file.write_text("", encoding="utf-8")
    except Exception:
        pass

    return payload
