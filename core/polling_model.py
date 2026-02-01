# =============================================================================
# POLYMARKET BEOBACHTER - POLLING-BASED PROBABILITY MODEL
# =============================================================================
#
# Model for markets with polling/survey data: elections, approval ratings, MVPs.
# Uses market price as consensus + extremity analysis.
#
# =============================================================================

import logging
from typing import Dict, Any

from .probability_models import (
    BaseProbabilityModel,
    HonestProbabilityEstimate,
    ModelType,
    ModelConfidence,
)

logger = logging.getLogger(__name__)


POLLING_KEYWORDS = [
    "election", "win", "nominee", "approval", "approval rating",
    "president", "governor", "senate", "congress", "democrat",
    "republican", "vote", "ballot", "primary", "caucus",
    "poll", "polling", "mvp", "award",
    "trump", "biden",
]


class PollingModel(BaseProbabilityModel):
    """
    Probability model for polling-based markets.

    Uses market consensus as base estimate with extremity adjustment.
    Confidence is LOW-MEDIUM since we don't ingest live polling data yet.
    """

    @property
    def model_type(self) -> ModelType:
        return ModelType.POLLING

    def can_estimate(self, market_data: Dict[str, Any]) -> bool:
        title = market_data.get("title", "").lower()
        description = market_data.get("description", "").lower()
        category = market_data.get("category", "").lower()
        combined = f"{title} {description} {category}"

        match_count = sum(1 for kw in POLLING_KEYWORDS if kw in combined)
        return match_count >= 2  # Need at least 2 keyword matches

    def estimate(self, market_data: Dict[str, Any]) -> HonestProbabilityEstimate:
        title = market_data.get("title", "")

        market_prob = market_data.get("market_implied_probability")
        if market_prob is None:
            market_prob = market_data.get("yes_price") or market_data.get("price")

        if market_prob is None or not (0.01 <= market_prob <= 0.99):
            return HonestProbabilityEstimate.invalid(
                reason="No market probability for polling analysis",
                model_type=ModelType.POLLING,
            )

        # Extremity adjustment — polls-based markets at extremes often
        # overstate certainty (upsets happen)
        if market_prob < 0.08:
            adjusted = market_prob * 1.5 + 0.02
            note = "very low — polling upsets possible"
        elif market_prob > 0.92:
            adjusted = market_prob * 0.92 + 0.05
            note = "very high — polling uncertainty suggests slight regression"
        elif market_prob < 0.20:
            adjusted = market_prob * 1.2 + 0.01
            note = "low price, slight upward adjustment for upset probability"
        elif market_prob > 0.80:
            adjusted = market_prob * 0.95 + 0.03
            note = "high price, slight downward adjustment for uncertainty"
        else:
            adjusted = market_prob
            note = "mid-range, no meaningful edge over market consensus"

        adjusted = max(0.02, min(0.98, adjusted))
        edge = abs(adjusted - market_prob)

        return HonestProbabilityEstimate(
            probability=round(adjusted, 4),
            probability_low=round(max(0.01, adjusted - 0.15), 4),
            probability_high=round(min(0.99, adjusted + 0.15), 4),
            valid=True,
            confidence=ModelConfidence.LOW if edge < 0.03 else ModelConfidence.MEDIUM,
            model_type=ModelType.POLLING,
            assumption=(
                f"Market consensus {market_prob:.2%} as base, "
                f"polling extremity adjustment: {note}"
            ),
            data_sources=[
                "Polymarket consensus price",
                "Historical polling accuracy patterns",
            ],
            reasoning=(
                f"Polling model: '{title[:40]}' market={market_prob:.3f}, "
                f"adjusted={adjusted:.3f}, {note}"
            ),
        )
