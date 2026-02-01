# =============================================================================
# POLYMARKET EU AI REGULATION ANALYZER
# Module: core/market_sanity.py
# Purpose: Compare rule-based estimate to market-implied probability
# =============================================================================
#
# TRADING RATIONALE:
# We only consider trading when there is SIGNIFICANT divergence between:
# - Our conservative, rule-based probability estimate
# - The market-implied probability (from Polymarket prices)
#
# WHY 8 PERCENTAGE POINTS THRESHOLD:
# - Market noise and bid-ask spreads account for ~3pp
# - Our estimation uncertainty adds ~3-5pp
# - 8pp threshold balances signal frequency with edge quality
# - Strong signals at 15pp+ indicate high-conviction opportunities
#
# DIRECTION MATTERS:
# - MARKET_TOO_HIGH: Market overestimates probability → consider NO position
# - MARKET_TOO_LOW: Market underestimates probability → consider YES position
# - ALIGNED: No significant edge → NO TRADE
#
# IMPORTANT:
# This module does NOT recommend position direction.
# It only determines if there is structural mispricing.
# The Decision Engine makes the final call.
#
# =============================================================================

from models.data_models import (
    MarketInput,
    ProbabilityEstimate,
    MarketSanityAnalysis,
)
from shared.enums import MarketDirection


class MarketSanityChecker:
    """
    Compares rule-based estimate to market-implied probability.

    Determines if there is significant divergence worth trading.

    DESIGN PRINCIPLE:
    Only flag tradeable when delta exceeds threshold.
    Err on the side of NO TRADE.
    """

    # =========================================================================
    # THRESHOLD CONFIGURATION
    # =========================================================================

    # Minimum percentage point delta to consider trading
    # 8pp = 0.08 absolute difference
    MINIMUM_DELTA_THRESHOLD: float = 0.08

    # Strong signal threshold (high conviction)
    STRONG_DELTA_THRESHOLD: float = 0.15

    # =========================================================================
    # EDGE CASE THRESHOLDS
    # =========================================================================

    # Markets priced very close to 0 or 1 require special handling
    EXTREME_PRICE_LOW: float = 0.05  # Below 5%
    EXTREME_PRICE_HIGH: float = 0.95  # Above 95%

    def __init__(self):
        """Initialize the market sanity checker."""
        pass

    def analyze(
        self,
        market_input: MarketInput,
        probability_estimate: ProbabilityEstimate
    ) -> MarketSanityAnalysis:
        """
        Compare market price to rule-based estimate.

        PROCESS:
        1. Extract market-implied probability
        2. Calculate delta from our midpoint estimate
        3. Determine direction of mispricing
        4. Check if delta exceeds threshold
        5. Handle edge cases

        Args:
            market_input: Market input with implied probability
            probability_estimate: Our rule-based estimate

        Returns:
            MarketSanityAnalysis
        """
        market_prob = market_input.market_implied_probability
        rule_based_prob = probability_estimate.probability_midpoint

        # ---------------------------------------------------------------------
        # STEP 1: Calculate delta
        # ---------------------------------------------------------------------
        # Delta = Market - Our Estimate
        # Positive delta = Market thinks higher probability than we do
        # Negative delta = Market thinks lower probability than we do
        delta = market_prob - rule_based_prob
        delta_pp = abs(delta) * 100  # Convert to percentage points for display

        # ---------------------------------------------------------------------
        # STEP 2: Determine direction
        # ---------------------------------------------------------------------
        if delta > self.MINIMUM_DELTA_THRESHOLD:
            direction = MarketDirection.MARKET_TOO_HIGH.value
        elif delta < -self.MINIMUM_DELTA_THRESHOLD:
            direction = MarketDirection.MARKET_TOO_LOW.value
        else:
            direction = MarketDirection.ALIGNED.value

        # ---------------------------------------------------------------------
        # STEP 3: Check threshold
        # ---------------------------------------------------------------------
        meets_threshold = abs(delta) >= self.MINIMUM_DELTA_THRESHOLD

        # ---------------------------------------------------------------------
        # STEP 4: Handle edge cases
        # ---------------------------------------------------------------------
        edge_case_warning = self._check_edge_cases(market_prob, rule_based_prob)

        # ---------------------------------------------------------------------
        # STEP 5: Build reasoning
        # ---------------------------------------------------------------------
        reasoning = self._build_reasoning(
            market_prob,
            rule_based_prob,
            delta,
            delta_pp,
            direction,
            meets_threshold,
            edge_case_warning,
            probability_estimate.confidence_level
        )

        return MarketSanityAnalysis(
            market_implied_prob=market_prob,
            rule_based_prob=rule_based_prob,
            delta=delta,
            delta_percentage_points=delta_pp,
            direction=direction,
            meets_threshold=meets_threshold,
            reasoning=reasoning
        )

    def _check_edge_cases(
        self,
        market_prob: float,
        rule_based_prob: float
    ) -> str:
        """
        Check for edge cases that require special handling.

        Edge cases:
        - Market priced at extreme (< 5% or > 95%)
        - Our estimate is at extreme
        - Large range width in our estimate

        Args:
            market_prob: Market-implied probability
            rule_based_prob: Our midpoint estimate

        Returns:
            Warning string or empty string
        """
        warnings = []

        # Check for extreme market pricing
        if market_prob < self.EXTREME_PRICE_LOW:
            warnings.append(
                f"Market priced at extreme low ({market_prob:.1%}) - "
                "limited upside if wrong, high conviction in NO"
            )
        elif market_prob > self.EXTREME_PRICE_HIGH:
            warnings.append(
                f"Market priced at extreme high ({market_prob:.1%}) - "
                "limited upside if wrong, high conviction in YES"
            )

        # Check for extreme rule-based estimate
        if rule_based_prob < self.EXTREME_PRICE_LOW:
            warnings.append(
                f"Our estimate is extreme low ({rule_based_prob:.1%}) - "
                "high confidence in NO outcome"
            )
        elif rule_based_prob > self.EXTREME_PRICE_HIGH:
            warnings.append(
                f"Our estimate is extreme high ({rule_based_prob:.1%}) - "
                "high confidence in YES outcome"
            )

        return "; ".join(warnings) if warnings else ""

    def _build_reasoning(
        self,
        market_prob: float,
        rule_based_prob: float,
        delta: float,
        delta_pp: float,
        direction: str,
        meets_threshold: bool,
        edge_case_warning: str,
        confidence_level: str
    ) -> str:
        """
        Build human-readable reasoning for the analysis.

        Args:
            market_prob: Market-implied probability
            rule_based_prob: Our midpoint estimate
            delta: Raw delta (market - ours)
            delta_pp: Delta in percentage points
            direction: Direction of mispricing
            meets_threshold: Whether threshold is met
            edge_case_warning: Any edge case warnings
            confidence_level: Our estimate confidence level

        Returns:
            Reasoning string
        """
        parts = []

        parts.append(
            f"Market-implied probability: {market_prob:.1%}."
        )

        parts.append(
            f"Our rule-based estimate: {rule_based_prob:.1%} "
            f"(confidence: {confidence_level})."
        )

        parts.append(
            f"Delta: {delta:+.1%} ({delta_pp:.1f} percentage points)."
        )

        parts.append(
            f"Direction: {direction}."
        )

        if meets_threshold:
            parts.append(
                f"Threshold MET: Delta ({delta_pp:.1f}pp) >= "
                f"minimum required ({self.MINIMUM_DELTA_THRESHOLD * 100:.0f}pp)."
            )

            if abs(delta) >= self.STRONG_DELTA_THRESHOLD:
                parts.append(
                    "STRONG SIGNAL: Delta exceeds strong conviction threshold."
                )
        else:
            parts.append(
                f"Threshold NOT MET: Delta ({delta_pp:.1f}pp) < "
                f"minimum required ({self.MINIMUM_DELTA_THRESHOLD * 100:.0f}pp). "
                "Market pricing is within acceptable range of our estimate."
            )

        if edge_case_warning:
            parts.append(f"EDGE CASE WARNING: {edge_case_warning}")

        return " ".join(parts)
