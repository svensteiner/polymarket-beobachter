# =============================================================================
# POLYMARKET BEOBACHTER - FED RATE PROBABILITY MODEL
# =============================================================================
#
# Model for Federal Reserve interest rate markets.
#
# APPROACH:
# - Hardcoded FOMC schedule for the current year
# - Current target rate as baseline
# - Simple model: compare market pricing to base rate expectations
# - Keywords: "fed", "interest rate", "fomc", "rate cut", "rate hike"
#
# HONEST PRINCIPLE:
# This model only returns valid=True when it can identify a Fed rate market
# AND has a defensible probability based on the FOMC schedule and current rate.
#
# =============================================================================

import logging
import re
from datetime import date, datetime
from typing import Dict, Any, List, Optional

from .probability_models import (
    BaseProbabilityModel,
    HonestProbabilityEstimate,
    ModelType,
    ModelConfidence,
)

logger = logging.getLogger(__name__)


# =============================================================================
# FOMC SCHEDULE & RATE DATA
# =============================================================================

# FOMC meeting dates for 2026 (announcement days)
FOMC_DATES_2026: List[date] = [
    date(2026, 1, 28),
    date(2026, 3, 18),
    date(2026, 5, 6),
    date(2026, 6, 17),
    date(2026, 7, 29),
    date(2026, 9, 16),
    date(2026, 10, 28),
    date(2026, 12, 16),
]

# Current Fed Funds target range (update as needed)
CURRENT_TARGET_RATE_LOW: float = 4.25
CURRENT_TARGET_RATE_HIGH: float = 4.50

# Standard rate move increment
RATE_STEP_BPS: int = 25  # 25 basis points


# =============================================================================
# KEYWORD DETECTION
# =============================================================================

FED_RATE_KEYWORDS = [
    "federal reserve", "fed funds", "federal funds",
    "fomc", "interest rate", "rate cut", "rate hike",
    "rate hold", "rate decision", "fed rate",
    "basis points", "bps", "monetary policy",
    "rate unchanged",
]

# Patterns for extracting rate targets from market questions
RATE_PATTERN = re.compile(
    r"(\d+(?:\.\d+)?)\s*%|"
    r"(\d+)\s*(?:basis\s*points|bps)|"
    r"(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)\s*%",
    re.IGNORECASE,
)


def is_fed_rate_market(market_data: Dict[str, Any]) -> bool:
    """Check if a market is about Fed interest rates."""
    title = market_data.get("title", "").lower()
    description = market_data.get("description", "").lower()
    combined = f"{title} {description}"

    return any(kw in combined for kw in FED_RATE_KEYWORDS)


def extract_rate_target(text: str) -> Optional[float]:
    """
    Extract a target rate from market text.

    Examples:
    - "Will the Fed cut rates to 4.00-4.25%?" -> 4.125
    - "Will rates be above 4.5%?" -> 4.5
    - "Will the Fed cut by 25 basis points?" -> returns delta

    Returns:
        Target rate as float, or None if not extractable
    """
    text_lower = text.lower()

    # Try range pattern first: "4.00-4.25%"
    range_match = re.search(r"(\d+\.\d+)\s*-\s*(\d+\.\d+)\s*%", text)
    if range_match:
        low = float(range_match.group(1))
        high = float(range_match.group(2))
        return (low + high) / 2.0

    # Try single rate: "4.5%"
    single_match = re.search(r"(\d+(?:\.\d+)?)\s*%", text)
    if single_match:
        rate = float(single_match.group(1))
        if 0.0 <= rate <= 20.0:  # Sanity check
            return rate

    return None


def next_fomc_date() -> Optional[date]:
    """Get the next upcoming FOMC meeting date."""
    today = date.today()
    for d in FOMC_DATES_2026:
        if d >= today:
            return d
    return None


def meetings_remaining() -> int:
    """Count remaining FOMC meetings this year."""
    today = date.today()
    return sum(1 for d in FOMC_DATES_2026 if d >= today)


# =============================================================================
# PROBABILITY MODEL
# =============================================================================


class FedRateModel(BaseProbabilityModel):
    """
    Probability model for Fed rate markets.

    Uses FOMC schedule and current rate to estimate probabilities
    for rate decisions (cut, hold, hike).

    HONEST PRINCIPLES:
    - Only estimates for clearly identifiable Fed rate markets
    - Returns INVALID if target rate cannot be extracted
    - Confidence is MEDIUM at best (we don't have CME FedWatch data)
    """

    @property
    def model_type(self) -> ModelType:
        return ModelType.FED_RATE

    def can_estimate(self, market_data: Dict[str, Any]) -> bool:
        """Check if this model can handle the market."""
        return is_fed_rate_market(market_data)

    def estimate(self, market_data: Dict[str, Any]) -> HonestProbabilityEstimate:
        """
        Estimate probability for a Fed rate market.

        Logic:
        - Extract target rate from market question
        - Compare to current rate
        - Use FOMC schedule to estimate likelihood

        The model is conservative:
        - "hold" bias: rates staying the same is the base case
        - Each 25bps move gets assigned diminishing probability
        - More meetings remaining = higher probability of cumulative moves
        """
        title = market_data.get("title", "")
        description = market_data.get("description", "")
        combined = f"{title} {description}"

        # Extract target rate
        target_rate = extract_rate_target(combined)

        if target_rate is None:
            return HonestProbabilityEstimate.invalid(
                reason="Cannot extract target rate from market question",
                model_type=ModelType.FED_RATE,
                warnings=["Market appears to be about Fed rates but no rate target found"],
            )

        current_mid = (CURRENT_TARGET_RATE_LOW + CURRENT_TARGET_RATE_HIGH) / 2.0
        rate_delta = target_rate - current_mid
        cuts_needed = int(abs(rate_delta) / 0.25) if rate_delta != 0 else 0

        remaining = meetings_remaining()

        if remaining == 0:
            # No more FOMC meetings this year
            if abs(rate_delta) < 0.01:
                # Rate already at target
                probability = 0.95
            else:
                probability = 0.02
        elif cuts_needed == 0:
            # Market asking about hold — high base probability
            probability = 0.55
        elif cuts_needed <= remaining:
            # Achievable within remaining meetings
            # Each cut has ~40% base probability, compounds
            if rate_delta < 0:
                # Rate cuts
                per_cut_prob = 0.40
            else:
                # Rate hikes (less likely in current environment)
                per_cut_prob = 0.15

            probability = per_cut_prob ** cuts_needed
            # But more meetings give more chances
            meeting_factor = min(remaining / max(cuts_needed, 1), 2.0)
            probability = min(0.85, probability * meeting_factor)
        else:
            # More cuts needed than meetings available
            probability = 0.03

        # Determine direction from keywords
        is_cut_market = any(w in combined.lower() for w in ["cut", "lower", "decrease", "below"])
        is_hike_market = any(w in combined.lower() for w in ["hike", "raise", "increase", "above"])

        assumption = (
            f"Based on current rate {CURRENT_TARGET_RATE_LOW}-{CURRENT_TARGET_RATE_HIGH}%, "
            f"target {target_rate}%, {cuts_needed} moves needed, "
            f"{remaining} FOMC meetings remaining"
        )

        return HonestProbabilityEstimate(
            probability=round(probability, 4),
            probability_low=round(max(0.01, probability - 0.15), 4),
            probability_high=round(min(0.99, probability + 0.15), 4),
            valid=True,
            confidence=ModelConfidence.MEDIUM,
            model_type=ModelType.FED_RATE,
            assumption=assumption,
            data_sources=["FOMC schedule 2026", "Current Fed Funds rate"],
            reasoning=(
                f"Fed rate model: target={target_rate}%, current_mid={current_mid}%, "
                f"delta={rate_delta:+.2f}%, cuts_needed={cuts_needed}, "
                f"meetings_remaining={remaining}, P={probability:.3f}"
            ),
        )
