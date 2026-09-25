from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from proposals.storage import get_storage

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EdgeCandidate:
    proposal_id: str
    market_id: str
    timestamp: str
    market_question: str
    confidence_level: str
    edge: float
    implied_probability: Optional[float]
    model_probability: Optional[float]
    side: str


def _parse_ts(raw: str) -> Optional[datetime]:
    try:
        cleaned = (raw or "").strip()
        if cleaned.endswith("Z"):
            cleaned = cleaned[:-1] + "+00:00"
        dt = datetime.fromisoformat(cleaned)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _to_candidate(p) -> Optional[EdgeCandidate]:
    try:
        edge = float(getattr(p, "edge", 0) or 0)
        return EdgeCandidate(
            proposal_id=str(getattr(p, "proposal_id", "")),
            market_id=str(getattr(p, "market_id", "")),
            timestamp=str(getattr(p, "timestamp", "")),
            market_question=str(getattr(p, "market_question", "") or ""),
            confidence_level=str(getattr(p, "confidence_level", "UNKNOWN") or "UNKNOWN"),
            edge=edge,
            implied_probability=(
                float(getattr(p, "implied_probability"))
                if getattr(p, "implied_probability", None) is not None
                else None
            ),
            model_probability=(
                float(getattr(p, "model_probability"))
                if getattr(p, "model_probability", None) is not None
                else None
            ),
            side="YES" if edge > 0 else "NO",
        )
    except Exception:
        return None


def build_edge_hunter_snapshot(
    *,
    max_age_hours: float = 24.0,
    per_bucket_limit: int = 15,
) -> Dict[str, Any]:
    """
    Build a lightweight "where is the edge?" snapshot from recent proposals.

    GOVERNANCE:
    - READ-ONLY: only reads proposals storage.
    - No strategy changes. No trading actions.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)

    proposals = get_storage().load_proposals(limit=2000)
    recent_trade = []
    for p in proposals:
        if getattr(p, "decision", None) != "TRADE":
            continue
        ts = _parse_ts(getattr(p, "timestamp", "") or "")
        if ts is None or ts < cutoff:
            continue
        cand = _to_candidate(p)
        if cand is not None:
            recent_trade.append(cand)

    by_abs_edge = sorted(recent_trade, key=lambda c: abs(c.edge), reverse=True)[:per_bucket_limit]
    by_yes_edge = sorted((c for c in recent_trade if c.side == "YES"), key=lambda c: c.edge, reverse=True)[
        :per_bucket_limit
    ]
    by_no_edge = sorted((c for c in recent_trade if c.side == "NO"), key=lambda c: abs(c.edge), reverse=True)[
        :per_bucket_limit
    ]

    newest_ts = None
    if recent_trade:
        newest_ts = max((_parse_ts(c.timestamp) for c in recent_trade), default=None)

    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window": {"max_age_hours": max_age_hours, "cutoff_utc": cutoff.isoformat()},
        "counts": {
            "recent_trade_proposals": len(recent_trade),
            "recent_yes": sum(1 for c in recent_trade if c.side == "YES"),
            "recent_no": sum(1 for c in recent_trade if c.side == "NO"),
        },
        "newest_proposal_ts_utc": newest_ts.isoformat() if newest_ts else None,
        "top": {
            "by_abs_edge": [asdict(c) for c in by_abs_edge],
            "by_yes_edge": [asdict(c) for c in by_yes_edge],
            "by_no_abs_edge": [asdict(c) for c in by_no_edge],
        },
    }


def write_edge_hunter_snapshot(
    output_path: Path,
    *,
    max_age_hours: float = 24.0,
    per_bucket_limit: int = 15,
) -> bool:
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        snapshot = build_edge_hunter_snapshot(
            max_age_hours=max_age_hours,
            per_bucket_limit=per_bucket_limit,
        )
        output_path.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False), encoding="utf-8")
        return True
    except Exception as e:
        logger.warning("edge_hunter write failed: %s", e)
        return False

