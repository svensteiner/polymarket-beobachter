# =============================================================================
# POLYMARKET BEOBACHTER - EDGE MEMORY
# =============================================================================
#
# GOVERNANCE INTENT:
# This module tracks historical edge performance to calibrate future entries.
# It learns from past trades to improve edge assessment over time.
#
# =============================================================================

import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent
POSITIONS_FILE = PROJECT_ROOT / "paper_trader" / "logs" / "paper_positions.jsonl"

# Minimum trades required to act on historical data
MIN_TRADES_DEFAULT = 2

# Edge buckets based on historical performance
EDGE_BUCKETS = {
    "low": (0.05, 0.10),      # 5-10% edge
    "medium": (0.10, 0.20),   # 10-20% edge
    "high": (0.20, 0.30),     # 20-30% edge
    "premium": (0.30, 1.00),  # 30%+ edge
}


def classify_bucket(edge: float) -> str:
    if edge < 0.05:
        return "insufficient"
    elif edge < 0.10:
        return "low"
    elif edge < 0.20:
        return "medium"
    elif edge < 0.30:
        return "high"
    else:
        return "premium"


def _edge_range_label(edge: float) -> str:
    abs_edge = abs(edge)
    if abs_edge < 0.10:
        return "edge5p"
    elif abs_edge < 0.20:
        return "edge10p"
    elif abs_edge < 0.30:
        return "edge20p"
    else:
        return "edge30p"


def _detect_market_type_from_question(question: str) -> str:
    q = (question or "").lower()
    if re.search(r"between\s+\d", q):
        return "between"
    if re.search(r"or\s+below|or\s+less|or\s+under|or\s+lower|\bbelow\b", q):
        return "at_or_below"
    if re.search(r"above|or\s+above|exceed|or\s+higher|or\s+more|or\s+over", q):
        return "at_or_above"
    if re.search(r"\bexactly\s+\d+|\bbe\s+\d+", q):
        return "exact"
    return "unknown"


def _load_closed_positions(path: Optional[Path] = None) -> List[Dict[str, Any]]:
    target = path if path is not None else POSITIONS_FILE
    if not Path(target).exists():
        return []
    positions = []
    try:
        with open(target, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    pos = json.loads(line)
                    if pos.get("status") == "CLOSED":
                        positions.append(pos)
                except json.JSONDecodeError:
                    continue
    except OSError:
        logger.warning("Could not read positions file: %s", target)
    return positions


def get_edge_summary(min_trades: int = MIN_TRADES_DEFAULT, limit: int = 10) -> List[Dict[str, Any]]:
    """
    Liefere eine Edge-Bucket-Zusammenfassung basierend auf geschlossenen Positionen.

    Returns list of dicts with keys:
        bucket, trade_count, win_count, win_rate, avg_pnl_eur
    """
    positions = _load_closed_positions()
    if not positions:
        return []

    buckets: Dict[str, Dict[str, Any]] = {}
    for pos in positions:
        key = pos.get("edge_bucket")
        if not key:
            continue
        pnl = pos.get("realized_pnl_eur", 0.0)
        try:
            pnl = float(pnl)
        except (TypeError, ValueError):
            pnl = 0.0

        if key not in buckets:
            buckets[key] = {"bucket": key, "trade_count": 0, "win_count": 0, "total_pnl": 0.0}
        buckets[key]["trade_count"] += 1
        buckets[key]["total_pnl"] += pnl
        if pnl > 0:
            buckets[key]["win_count"] += 1

    results = []
    for key, stats in buckets.items():
        if stats["trade_count"] < min_trades:
            continue
        n = stats["trade_count"]
        results.append({
            "bucket": key,
            "trade_count": n,
            "win_count": stats["win_count"],
            "win_rate": stats["win_count"] / n,
            "avg_pnl_eur": stats["total_pnl"] / n,
        })

    results.sort(key=lambda r: r["avg_pnl_eur"], reverse=True)
    return results[:limit]


def assess_proposal_edge(
    proposal_or_edge,
    market_type: Optional[str] = None,
    city: Optional[str] = None,
    **kwargs,
) -> Dict[str, Any]:
    """
    Assess a proposal's edge based on historical performance.

    Returns dict with keys: allowed, bucket, edge, reason, confidence_adjustment,
    and optionally position_scale.
    """
    # Extract edge and metadata from proposal if needed
    if hasattr(proposal_or_edge, "edge"):
        edge = proposal_or_edge.edge
        confidence = getattr(proposal_or_edge, "confidence_level", "MEDIUM")
        question = getattr(proposal_or_edge, "market_question", "")
        if market_type is None:
            market_type = _detect_market_type_from_question(question)
    else:
        edge = float(proposal_or_edge)
        confidence = "MEDIUM"
        if market_type is None:
            market_type = "unknown"

    bucket = classify_bucket(abs(edge))
    side = "YES" if edge >= 0 else "NO"
    edge_label = _edge_range_label(edge)

    # Build partial bucket key to match against historical positions
    partial_key = f"{confidence}|{market_type}|{side}|{edge_label}"

    # Load historical positions matching this partial key
    positions = _load_closed_positions()
    matching = [
        p for p in positions
        if p.get("edge_bucket", "").startswith(partial_key)
    ]

    if len(matching) >= MIN_TRADES_DEFAULT:
        pnls = [float(p.get("realized_pnl_eur", 0.0)) for p in matching]
        avg_pnl = sum(pnls) / len(pnls)
        win_rate = sum(1 for p in pnls if p > 0) / len(pnls)

        if avg_pnl < 0:
            return {
                "allowed": False,
                "bucket": bucket,
                "edge": edge,
                "reason": "negative_edge_memory",
                "confidence_adjustment": 0.0,
                "historical_avg_pnl": avg_pnl,
                "historical_win_rate": win_rate,
                "sample_size": len(matching),
            }

        if avg_pnl > 0:
            scale = max(1.1, 1.0 + win_rate * 0.5)
            return {
                "allowed": True,
                "bucket": bucket,
                "edge": edge,
                "reason": "positive_edge_memory",
                "confidence_adjustment": 1.0,
                "position_scale": scale,
                "historical_avg_pnl": avg_pnl,
                "historical_win_rate": win_rate,
                "sample_size": len(matching),
            }

    # No sufficient history — default assessment
    allowed = bucket not in ("insufficient",)
    reason = f"Edge {edge:.1%} in bucket '{bucket}'"
    if not allowed:
        reason = f"Edge {edge:.1%} insufficient (< 5%)"

    logger.debug(
        "Edge assessment: edge=%.1f%% bucket=%s allowed=%s",
        edge * 100,
        bucket,
        allowed,
    )

    return {
        "allowed": allowed,
        "bucket": bucket,
        "edge": edge,
        "reason": reason,
        "confidence_adjustment": 1.0 if allowed else 0.0,
    }


def detect_market_type(market_question: str) -> str:
    if not market_question:
        return "unknown"

    question_lower = market_question.lower()

    temp_keywords = [
        "temperature", "degrees", "celsius", "fahrenheit",
        "hot", "cold", "warm", "cool", "heat", "°f", "°c",
        "high of", "low of", "reach", "exceed", "above", "below",
    ]
    for keyword in temp_keywords:
        if keyword in question_lower:
            return "temperature"

    precip_keywords = [
        "rain", "precipitation", "rainfall", "inch", "inches",
        "mm of", "wet", "shower", "storm", "thunderstorm",
    ]
    for keyword in precip_keywords:
        if keyword in question_lower:
            return "precipitation"

    snow_keywords = ["snow", "snowfall", "blizzard", "flurries", "accumulation"]
    for keyword in snow_keywords:
        if keyword in question_lower:
            return "snow"

    wind_keywords = ["wind", "mph", "gust", "breeze", "hurricane", "tornado"]
    for keyword in wind_keywords:
        if keyword in question_lower:
            return "wind"

    return "unknown"
