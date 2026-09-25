"""
Edge Hunter (read-only analytics)
================================

Purpose:
- Provide a compact, actionable view of "what edge exists right now" and why it is
  not being traded (blocked reasons, shadow opportunities).
- Write `output/edge_hunter.json` as a stable artifact for automations/monitoring.

Governance:
- Reads only local logs and proposal metadata from guardrail audit.
- Does not modify trading behavior and does not loosen guardrails.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


PROJECT_ROOT = Path(__file__).parent.parent


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except Exception:
        return default


def _pick(d: Dict[str, Any], keys: Tuple[str, ...]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for k in keys:
        if k in d:
            out[k] = d.get(k)
    return out


@dataclass(frozen=True)
class EdgeHunterConfig:
    decisions_limit: int = 5000
    top_n: int = 12


def write_edge_hunter(
    *,
    run_id: Optional[str],
    output_dir: Path,
    config: EdgeHunterConfig | None = None,
) -> Path:
    from paper_trader.guardrail_audit import get_recent_decisions

    cfg = config or EdgeHunterConfig()
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / "edge_hunter.json"

    decisions = get_recent_decisions(cfg.decisions_limit)
    if run_id:
        decisions = [d for d in decisions if d.get("run_id") == run_id]

    total = len(decisions)
    allowed = [d for d in decisions if d.get("allowed")]
    blocked = [d for d in decisions if not d.get("allowed")]
    shadow_only = [d for d in decisions if (not d.get("allowed")) and d.get("shadow_allowed_without_inventory")]

    # Sort helpers
    def _edge(d: Dict[str, Any]) -> float:
        return _safe_float(d.get("edge"), 0.0)

    def _abs_edge(d: Dict[str, Any]) -> float:
        return abs(_edge(d))

    allowed_yes = [d for d in allowed if _edge(d) > 0]
    allowed_no = [d for d in allowed if _edge(d) < 0]
    blocked_yes = [d for d in blocked if _edge(d) > 0]

    allowed_yes.sort(key=_edge, reverse=True)
    allowed_no.sort(key=_abs_edge, reverse=True)
    shadow_only.sort(key=_abs_edge, reverse=True)
    blocked_yes.sort(key=_edge, reverse=True)

    # Block breakdown
    blocked_by_reason: Dict[str, int] = {}
    for d in blocked:
        code = str(d.get("reason_code", "unknown") or "unknown")
        blocked_by_reason[code] = blocked_by_reason.get(code, 0) + 1

    # Keep the payload compact and stable
    def _compact(d: Dict[str, Any]) -> Dict[str, Any]:
        base = _pick(
            d,
            (
                "timestamp",
                "run_id",
                "proposal_id",
                "market_id",
                "market_question",
                "city",
                "confidence_level",
                "entry_price",
                "implied_probability",
                "model_probability",
                "edge",
                "reason_code",
                "reason_detail",
                "shadow_reason_code",
                "shadow_reason_detail",
            ),
        )
        # Normalize numeric fields if present
        for k in ("entry_price", "implied_probability", "model_probability", "edge"):
            if k in base and base[k] is not None:
                base[k] = _safe_float(base[k], base[k])  # keep None as None
        return base

    payload = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "run_id": run_id,
        "counts": {
            "decisions_total": total,
            "allowed_total": len(allowed),
            "blocked_total": len(blocked),
            "shadow_only_total": len(shadow_only),
            "allowed_yes": len(allowed_yes),
            "allowed_no": len(allowed_no),
        },
        "blocked_by_reason": blocked_by_reason,
        "top_allowed_yes": [_compact(d) for d in allowed_yes[: cfg.top_n]],
        "top_allowed_no": [_compact(d) for d in allowed_no[: cfg.top_n]],
        "top_shadow_only": [_compact(d) for d in shadow_only[: cfg.top_n]],
        "top_blocked_positive_edge": [_compact(d) for d in blocked_yes[: cfg.top_n]],
        "notes": [
            "allowed_* reflects entry-guardrails only; simulator may still SKIP (e.g., LOW-liquidity, stale price drift, SQS).",
            "shadow_only are opportunities that would pass guardrails with inventory=0; useful for offline evaluation.",
        ],
    }

    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path

