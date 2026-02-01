# =============================================================================
# POLYMARKET BEOBACHTER - NUMERIC THRESHOLD PROBABILITY MODEL
# =============================================================================
#
# Broad model for markets with measurable numeric thresholds.
# "Will X reach/exceed/fall below Y by date Z?"
#
# Uses market price as consensus estimate + extremity analysis.
# When market price is near 50%, we have low edge.
# When market price is extreme (<15% or >85%), we check if it's justified.
#
# =============================================================================

import logging
import re
from typing import Dict, Any, Optional

from .probability_models import (
    BaseProbabilityModel,
    HonestProbabilityEstimate,
    ModelType,
    ModelConfidence,
)

logger = logging.getLogger(__name__)


# Keywords that indicate a numeric/threshold market
THRESHOLD_KEYWORDS = [
    "above", "below", "at least", "more than", "less than",
    "reach", "exceed", "over", "under", "higher than", "lower than",
    "surpass", "fall to", "rise to", "hit", "drop to",
]

# Keywords indicating measurable quantities
MEASURABLE_KEYWORDS = [
    "price", "rate", "gdp", "inflation", "unemployment",
    "temperature", "percent", "%", "million", "billion", "trillion",
    "index", "score", "rating", "approval", "yield", "spread",
    "revenue", "earnings", "subscribers", "users", "downloads",
    "market cap", "volume", "population",
]

# Number pattern
NUMBER_PATTERN = re.compile(
    r"[\$€£]?\s*\d[\d,]*(?:\.\d+)?\s*[%kKmMbBtT]?"
)


def _is_numeric_threshold_market(text: str) -> bool:
    """Check if market involves a numeric threshold."""
    text_lower = text.lower()
    has_threshold = any(kw in text_lower for kw in THRESHOLD_KEYWORDS)
    has_measurable = any(kw in text_lower for kw in MEASURABLE_KEYWORDS)
    has_number = bool(NUMBER_PATTERN.search(text))

    # Need at least threshold keyword + (measurable keyword OR number)
    return has_threshold and (has_measurable or has_number)


class NumericThresholdModel(BaseProbabilityModel):
    """
    Probability model for numeric threshold markets.

    Strategy: Use market consensus price as base, apply mean-reversion
    bias for extreme prices, and report with appropriate uncertainty.

    This is a "catch-all" for measurable markets not handled by
    more specific models (crypto, fed rate, etc.).
    """

    @property
    def model_type(self) -> ModelType:
        return ModelType.NUMERIC_THRESHOLD

    def can_estimate(self, market_data: Dict[str, Any]) -> bool:
        title = market_data.get("title", "").lower()
        description = market_data.get("description", "").lower()
        combined = f"{title} {description}"
        return _is_numeric_threshold_market(combined)

    def estimate(self, market_data: Dict[str, Any]) -> HonestProbabilityEstimate:
        title = market_data.get("title", "")
        description = market_data.get("description", "")
        combined = f"{title} {description}"

        # Get market-implied probability as baseline
        market_prob = market_data.get("market_implied_probability")
        if market_prob is None:
            # Try outcomePrices or other fields
            market_prob = market_data.get("yes_price") or market_data.get("price")

        if market_prob is None or not (0.01 <= market_prob <= 0.99):
            return HonestProbabilityEstimate.invalid(
                reason="No market probability available for threshold analysis",
                model_type=ModelType.NUMERIC_THRESHOLD,
            )

        # Mean-reversion adjustment for extreme prices
        # Markets at extremes tend to overstate certainty
        if market_prob < 0.10:
            # Very unlikely per market — nudge slightly up
            adjusted = market_prob * 1.3 + 0.02
            reasoning_note = "extreme low price, slight upward adjustment"
        elif market_prob > 0.90:
            # Very likely per market — nudge slightly down
            adjusted = market_prob * 0.95 + 0.03
            reasoning_note = "extreme high price, slight downward adjustment"
        elif market_prob < 0.20:
            adjusted = market_prob * 1.15 + 0.01
            reasoning_note = "low price, minor upward adjustment"
        elif market_prob > 0.80:
            adjusted = market_prob * 0.97 + 0.02
            reasoning_note = "high price, minor downward adjustment"
        else:
            # Mid-range: we have no meaningful edge over market
            adjusted = market_prob
            reasoning_note = "mid-range price, no significant edge"

        adjusted = max(0.02, min(0.98, adjusted))

        # Edge assessment
        edge = abs(adjusted - market_prob)
        if edge < 0.03:
            confidence = ModelConfidence.LOW
        else:
            confidence = ModelConfidence.MEDIUM

        # Wider bands for this general model
        band = 0.15

        return HonestProbabilityEstimate(
            probability=round(adjusted, 4),
            probability_low=round(max(0.01, adjusted - band), 4),
            probability_high=round(min(0.99, adjusted + band), 4),
            valid=True,
            confidence=confidence,
            model_type=ModelType.NUMERIC_THRESHOLD,
            assumption=(
                f"Market consensus {market_prob:.2%} as base, "
                f"mean-reversion adjustment: {reasoning_note}"
            ),
            data_sources=[
                "Polymarket consensus price",
                "Mean-reversion extremity analysis",
            ],
            reasoning=(
                f"Numeric threshold: market={market_prob:.3f}, "
                f"adjusted={adjusted:.3f}, edge={edge:.3f}, "
                f"{reasoning_note}"
            ),
        )
