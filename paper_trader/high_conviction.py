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

# Absolute entry-price floor for high-conviction trades.
# Why: Trades 2026-05-31 entered at 0.020 / 0.037 via HighConvictionException
# bypass, both exited as "below 5% floor" guardrail with -2.51 / -3.66 EUR.
# At entry-prices <10%, the model-vs-market divergence is so extreme that the
# model is almost certainly miscalibrated (companion markets at 90%+ already
# established the consensus). No edge claim survives this prior.
HIGH_CONVICTION_MIN_ENTRY_PRICE = 0.10

# Brier-skill-score gate: if the forecast is worse than the naive baseline,
# do not allow any high-conviction bypass — edge claims are not trustworthy.
HIGH_CONVICTION_MIN_BRIER_SKILL = -0.30


def _read_brier_skill_score() -> Optional[float]:
    """Read latest BSS from self_diagnostic snapshot. Returns None if unavailable."""
    try:
        from pathlib import Path
        import json
        diag_path = Path(__file__).resolve().parent.parent / "data" / "agent_memory" / "self_diagnostic.json"
        if not diag_path.exists():
            return None
        data = json.loads(diag_path.read_text(encoding="utf-8"))
        bss = data.get("brier_skill_score")
        return float(bss) if isinstance(bss, (int, float)) else None
    except (OSError, ValueError, KeyError, json.JSONDecodeError):
        return None


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

    if not is_high_conviction:
        return (False, "Does not meet high conviction criteria")

    # Entry-price floor: even with strong edge+confidence, refuse bypass when
    # the real-time entry price suggests extreme tail-market mispricing.
    # Compare against the most up-to-date price available (caller passes
    # snapshot.mid_price as entry_price; fall back to proposal.implied_probability).
    effective_price = entry_price
    if effective_price is None:
        effective_price = getattr(proposal, "implied_probability", None)
    is_no_bet = (edge or 0.0) < 0
    if not is_no_bet and effective_price is not None:
        try:
            ep = float(effective_price)
        except (TypeError, ValueError):
            ep = 0.0
        if 0.0 < ep < HIGH_CONVICTION_MIN_ENTRY_PRICE:
            reason = (
                f"High-conviction blocked: YES entry {ep:.1%} < floor "
                f"{HIGH_CONVICTION_MIN_ENTRY_PRICE:.0%} (tail-market trap)"
            )
            logger.info(reason)
            return (False, reason)

    # Brier-skill-score gate: forecaster must beat naive baseline before any
    # bypass. If the system is actively miscalibrated (BSS < -0.30), all edge
    # claims are unreliable and high-conviction must remain disabled.
    bss = _read_brier_skill_score()
    if bss is not None and bss < HIGH_CONVICTION_MIN_BRIER_SKILL:
        reason = (
            f"High-conviction blocked: Brier-Skill {bss:+.2f} < "
            f"{HIGH_CONVICTION_MIN_BRIER_SKILL:+.2f} — forecaster worse than baseline"
        )
        logger.info(reason)
        return (False, reason)

    reason = f"High conviction: {', '.join(reasons)}"
    logger.info(reason)
    return (True, reason)


def get_high_conviction_thresholds() -> Dict[str, Any]:
    """Return current high conviction thresholds for transparency."""
    return {
        "min_edge": MIN_EDGE_HIGH_CONVICTION,
        "min_confidence": MIN_CONFIDENCE_HIGH_CONVICTION,
        "min_entry_price": HIGH_CONVICTION_MIN_ENTRY_PRICE,
        "min_brier_skill": HIGH_CONVICTION_MIN_BRIER_SKILL,
        "factors_required": 2,
    }
