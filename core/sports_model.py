# =============================================================================
# POLYMARKET BEOBACHTER - SPORTS BETTING PROBABILITY MODEL
# =============================================================================
#
# Model for sports markets: championships, MVPs, game outcomes.
# Uses market consensus + extremity/arbitrage analysis.
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


SPORTS_KEYWORDS = [
    "nba", "nfl", "mlb", "nhl", "mls", "ufc", "pga",
    "soccer", "football", "basketball", "baseball", "hockey",
    "championship", "world cup", "olympics", "super bowl",
    "world series", "stanley cup", "final", "playoff",
    "mvp", "rookie of the year", "scoring title",
    "win", "beat", "defeat", "seed", "standings",
]


class SportsBettingModel(BaseProbabilityModel):
    """
    Probability model for sports markets.

    Uses market consensus as base, adjusts for extremity.
    Sports markets are generally efficient, so edge is small.
    Confidence: LOW-MEDIUM.
    """

    @property
    def model_type(self) -> ModelType:
        return ModelType.SPORTS

    def can_estimate(self, market_data: Dict[str, Any]) -> bool:
        title = market_data.get("title", "").lower()
        description = market_data.get("description", "").lower()
        category = market_data.get("category", "").lower()
        combined = f"{title} {description} {category}"

        match_count = sum(1 for kw in SPORTS_KEYWORDS if kw in combined)
        return match_count >= 2

    def estimate(self, market_data: Dict[str, Any]) -> HonestProbabilityEstimate:
        title = market_data.get("title", "")

        market_prob = market_data.get("market_implied_probability")
        if market_prob is None:
            market_prob = market_data.get("yes_price") or market_data.get("price")

        if market_prob is None or not (0.01 <= market_prob <= 0.99):
            return HonestProbabilityEstimate.invalid(
                reason="No market probability for sports analysis",
                model_type=ModelType.SPORTS,
            )

        # Sports markets are efficient but longshots are slightly overbet
        # and heavy favorites slightly underbet (favorite-longshot bias)
        if market_prob < 0.10:
            # Longshot — historically overpriced
            adjusted = market_prob * 0.70
            note = "longshot bias correction — historically overpriced"
        elif market_prob > 0.90:
            # Heavy favorite — historically slightly underpriced
            adjusted = market_prob * 0.98 + 0.02
            note = "favorite bias correction — slight upward"
        elif market_prob < 0.25:
            adjusted = market_prob * 0.85 + 0.01
            note = "mild longshot adjustment"
        elif market_prob > 0.75:
            adjusted = market_prob * 0.97 + 0.02
            note = "mild favorite adjustment"
        else:
            adjusted = market_prob
            note = "mid-range, no meaningful edge"

        adjusted = max(0.02, min(0.98, adjusted))
        edge = abs(adjusted - market_prob)

        return HonestProbabilityEstimate(
            probability=round(adjusted, 4),
            probability_low=round(max(0.01, adjusted - 0.12), 4),
            probability_high=round(min(0.99, adjusted + 0.12), 4),
            valid=True,
            confidence=ModelConfidence.LOW if edge < 0.03 else ModelConfidence.MEDIUM,
            model_type=ModelType.SPORTS,
            assumption=(
                f"Market consensus {market_prob:.2%} as base, "
                f"favorite-longshot bias adjustment: {note}"
            ),
            data_sources=[
                "Polymarket consensus price",
                "Favorite-longshot bias model",
            ],
            reasoning=(
                f"Sports model: '{title[:40]}' market={market_prob:.3f}, "
                f"adjusted={adjusted:.3f}, {note}"
            ),
        )
