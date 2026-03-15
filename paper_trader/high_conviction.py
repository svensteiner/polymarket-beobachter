# =============================================================================
# POLYMARKET BEOBACHTER - HIGH CONVICTION EVALUATOR
# =============================================================================
#
# GOVERNANCE INTENT:
# This module evaluates whether a trade qualifies for high-conviction
# exception handling, allowing it to bypass certain guardrails.
#
# =============================================================================

import logging
from typing import Dict, Any, Tuple, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from proposals.models import Proposal

logger = logging.getLogger(__name__)


# High conviction thresholds
MIN_EDGE_HIGH_CONVICTION = 0.25  # 25% edge required
MIN_CONFIDENCE_HIGH_CONVICTION = "HIGH"  # HIGH confidence required


def evaluate_high_conviction_exception(
    proposal: "Proposal",
    entry_price: Optional[float] = None,
) -> Tuple[bool, str]:
    """
    Evaluate if a trade qualifies for high-conviction exception.

    High-conviction trades can bypass certain temporary guardrails
    like bot health restrictions, but NOT core risk limits.

    Args:
        proposal: The Proposal object to evaluate
        entry_price: Optional entry price for additional checks

    Returns:
        Tuple of (is_high_conviction, reason)
    """
    reasons = []

    # Extract fields from proposal
    edge = getattr(proposal, "edge", None)
    confidence_level = getattr(proposal, "confidence_level", None)

    # Check edge threshold
    if edge is not None and edge >= MIN_EDGE_HIGH_CONVICTION:
        reasons.append(f"edge={edge:.1%}")

    # Check confidence threshold (HIGH = high conviction)
    if confidence_level == MIN_CONFIDENCE_HIGH_CONVICTION:
        reasons.append(f"confidence={confidence_level}")

    # Need both edge AND confidence for high conviction
    is_high_conviction = len(reasons) >= 2

    if is_high_conviction:
        reason = f"High conviction: {', '.join(reasons)}"
        logger.info(reason)
        return (True, reason)
    else:
        return (False, "Does not meet high conviction criteria")


def get_high_conviction_thresholds() -> Dict[str, Any]:
    """Return current high conviction thresholds for transparency."""
    return {
        "min_edge": MIN_EDGE_HIGH_CONVICTION,
        "min_confidence": MIN_CONFIDENCE_HIGH_CONVICTION,
        "factors_required": 2,
    }
