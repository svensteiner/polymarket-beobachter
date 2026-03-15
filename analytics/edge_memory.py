# =============================================================================
# POLYMARKET BEOBACHTER - EDGE MEMORY
# =============================================================================
#
# GOVERNANCE INTENT:
# This module tracks historical edge performance to calibrate future entries.
# It learns from past trades to improve edge assessment over time.
#
# =============================================================================

import logging
from typing import Dict, Any, Tuple, Optional, List
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class EdgeAssessment:
    """Assessment of a proposal's edge quality."""
    bucket: str  # "low", "medium", "high", "premium"
    historical_win_rate: Optional[float] = None
    sample_size: int = 0
    recommendation: str = "proceed"
    confidence_adjustment: float = 1.0


# Edge buckets based on historical performance
EDGE_BUCKETS = {
    "low": (0.05, 0.10),      # 5-10% edge
    "medium": (0.10, 0.20),   # 10-20% edge
    "high": (0.20, 0.30),     # 20-30% edge
    "premium": (0.30, 1.00),  # 30%+ edge
}


def classify_bucket(edge: float) -> str:
    """
    Classify an edge value into a bucket.

    Args:
        edge: The edge value (e.g., 0.15 for 15%)

    Returns:
        Bucket name
    """
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


def assess_proposal_edge(
    proposal_or_edge,
    market_type: Optional[str] = None,
    city: Optional[str] = None,
    **kwargs,
) -> Dict[str, Any]:
    """
    Assess a proposal's edge based on historical performance.

    Args:
        proposal_or_edge: Either a Proposal object or a float edge value
        market_type: Type of weather market (temp, precip, etc.)
        city: City for the market
        **kwargs: Additional context

    Returns:
        Dict with 'allowed', 'bucket', 'reason' keys
    """
    # Extract edge from proposal if needed
    if hasattr(proposal_or_edge, "edge"):
        edge = proposal_or_edge.edge
    else:
        edge = float(proposal_or_edge)

    bucket = classify_bucket(edge)

    # Determine if edge is acceptable
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


def record_outcome(
    proposal_id: str,
    edge: float,
    outcome: bool,
    pnl: float,
) -> None:
    """
    Record the outcome of a trade for future calibration.

    Args:
        proposal_id: Unique proposal identifier
        edge: The edge at entry
        outcome: Whether the trade was profitable
        pnl: Realized P&L
    """
    bucket = classify_bucket(edge)
    logger.info(
        "Edge outcome recorded: %s bucket=%s outcome=%s pnl=%.2f",
        proposal_id,
        bucket,
        "WIN" if outcome else "LOSS",
        pnl,
    )


def get_bucket_statistics() -> Dict[str, Dict[str, Any]]:
    """
    Get performance statistics for each edge bucket.

    Returns:
        Dict mapping bucket names to their statistics
    """
    # Placeholder - would load from persistent storage
    return {
        bucket: {
            "range": f"{low*100:.0f}%-{high*100:.0f}%",
            "trades": 0,
            "wins": 0,
            "win_rate": None,
        }
        for bucket, (low, high) in EDGE_BUCKETS.items()
    }
