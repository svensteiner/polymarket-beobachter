# =============================================================================
# POLYMARKET BEOBACHTER - CONSERVATIVE SLIPPAGE MODEL
# =============================================================================
#
# GOVERNANCE INTENT:
# This module calculates CONSERVATIVE slippage estimates for paper trading.
# The goal is to UNDERESTIMATE performance, not overestimate it.
#
# DESIGN PRINCIPLES:
# - Never use hindsight
# - Never pick best price
# - Always apply conservative slippage
# - When uncertain, use worst-case assumptions
#
# PAPER TRADING ONLY:
# This slippage model is used for simulation purposes.
# It does not affect any real trading.
#
# =============================================================================

from typing import Final, Optional
from paper_trader.models import LiquidityBucket, MarketSnapshot


# =============================================================================
# SLIPPAGE CONSTANTS (CONSERVATIVE)
# =============================================================================
#
# These values are intentionally PESSIMISTIC.
# We would rather underestimate paper profits than overestimate them.
#
# =============================================================================

# Base slippage percentages by liquidity bucket
# These are applied as a percentage of the price
SLIPPAGE_HIGH_LIQUIDITY: Final[float] = 0.005    # 0.5%
SLIPPAGE_MEDIUM_LIQUIDITY: Final[float] = 0.015  # 1.5%
SLIPPAGE_LOW_LIQUIDITY: Final[float] = 0.030     # 3.0%
SLIPPAGE_UNKNOWN_LIQUIDITY: Final[float] = 0.050  # 5.0% (worst case)

# Additional slippage for crossing the spread
# Applied when buying at ask or selling at bid
SPREAD_CROSSING_MULTIPLIER: Final[float] = 1.0  # Full spread impact

# Minimum slippage floor (always apply at least this much)
MINIMUM_SLIPPAGE: Final[float] = 0.002  # 0.2%

# Maximum slippage cap (sanity check)
MAXIMUM_SLIPPAGE: Final[float] = 0.10  # 10%


# =============================================================================
# SLIPPAGE CALCULATOR
# =============================================================================


class SlippageModel:
    """
    Conservative slippage calculator for paper trading.

    GOVERNANCE:
    This model applies PESSIMISTIC slippage estimates.
    - Buying: worst_fill_price = ask + slippage
    - Selling: worst_fill_price = bid - slippage

    The goal is to UNDERESTIMATE paper profits.
    """

    def __init__(self):
        """Initialize slippage model with conservative defaults."""
        self._slippage_rates = {
            LiquidityBucket.HIGH.value: SLIPPAGE_HIGH_LIQUIDITY,
            LiquidityBucket.MEDIUM.value: SLIPPAGE_MEDIUM_LIQUIDITY,
            LiquidityBucket.LOW.value: SLIPPAGE_LOW_LIQUIDITY,
            LiquidityBucket.UNKNOWN.value: SLIPPAGE_UNKNOWN_LIQUIDITY,
        }

    def get_slippage_rate(self, liquidity_bucket: str) -> float:
        """
        Get the slippage rate for a liquidity bucket.

        Args:
            liquidity_bucket: HIGH, MEDIUM, LOW, or UNKNOWN

        Returns:
            Slippage rate as a decimal (e.g., 0.015 for 1.5%)
        """
        return self._slippage_rates.get(
            liquidity_bucket,
            SLIPPAGE_UNKNOWN_LIQUIDITY  # Default to worst case
        )

    def calculate_entry_price(
        self,
        snapshot: MarketSnapshot,
        side: str  # "YES" or "NO"
    ) -> Optional[tuple]:
        """
        Calculate worst-case entry fill price.

        CONSERVATIVE LOGIC:
        - Buying YES: We pay at or above the ask
        - Buying NO: We pay at or above the ask (of the NO side)

        For simplicity in binary markets:
        - Buying YES at price P means paying P (want price to go up)
        - Buying NO at price P means paying (1-P) (want YES price to go down)

        Args:
            snapshot: Market snapshot with bid/ask data
            side: "YES" or "NO"

        Returns:
            Tuple of (entry_price, slippage_applied) or None if unavailable
        """
        if not snapshot.has_valid_prices():
            return None

        # Get base price
        if snapshot.best_ask is not None:
            base_price = snapshot.best_ask  # Start from ask (worst for buyer)
        elif snapshot.mid_price is not None:
            # If only mid_price, add half spread estimate
            base_price = snapshot.mid_price * 1.01  # 1% above mid
        else:
            return None

        # Get slippage rate
        slippage_rate = self.get_slippage_rate(snapshot.liquidity_bucket)

        # Apply slippage (always moves price against us)
        slippage_amount = base_price * slippage_rate

        # Ensure minimum slippage
        slippage_amount = max(slippage_amount, base_price * MINIMUM_SLIPPAGE)

        # Cap slippage
        slippage_amount = min(slippage_amount, base_price * MAXIMUM_SLIPPAGE)

        # Calculate entry price (price we pay)
        entry_price = base_price + slippage_amount

        # Clamp to valid range [0, 1] for prediction markets
        entry_price = max(0.01, min(0.99, entry_price))

        return (entry_price, slippage_amount)

    def calculate_exit_price(
        self,
        snapshot: MarketSnapshot,
        side: str,  # "YES" or "NO"
        is_resolution: bool = False
    ) -> Optional[tuple]:
        """
        Calculate worst-case exit fill price.

        CONSERVATIVE LOGIC:
        - Selling YES: We receive at or below the bid
        - If market resolved, use resolution price (1.0 or 0.0)

        Args:
            snapshot: Market snapshot with bid/ask data
            side: "YES" or "NO"
            is_resolution: True if exiting due to market resolution

        Returns:
            Tuple of (exit_price, slippage_applied) or None if unavailable
        """
        # Resolution exit - no slippage
        if is_resolution and snapshot.is_resolved:
            if snapshot.resolved_outcome == "YES":
                exit_price = 1.0 if side == "YES" else 0.0
            else:  # resolved to NO
                exit_price = 0.0 if side == "YES" else 1.0
            return (exit_price, 0.0)

        # Normal exit with slippage
        if not snapshot.has_valid_prices():
            return None

        # Get base price
        if snapshot.best_bid is not None:
            base_price = snapshot.best_bid  # Start from bid (worst for seller)
        elif snapshot.mid_price is not None:
            # If only mid_price, subtract half spread estimate
            base_price = snapshot.mid_price * 0.99  # 1% below mid
        else:
            return None

        # Get slippage rate
        slippage_rate = self.get_slippage_rate(snapshot.liquidity_bucket)

        # Apply slippage (always moves price against us)
        slippage_amount = base_price * slippage_rate

        # Ensure minimum slippage
        slippage_amount = max(slippage_amount, base_price * MINIMUM_SLIPPAGE)

        # Cap slippage
        slippage_amount = min(slippage_amount, base_price * MAXIMUM_SLIPPAGE)

        # Calculate exit price (price we receive)
        exit_price = base_price - slippage_amount

        # Clamp to valid range [0, 1]
        exit_price = max(0.01, min(0.99, exit_price))

        return (exit_price, slippage_amount)


# =============================================================================
# MODULE-LEVEL INSTANCE
# =============================================================================

_slippage_model: Optional[SlippageModel] = None


def get_slippage_model() -> SlippageModel:
    """Get the global slippage model instance."""
    global _slippage_model
    if _slippage_model is None:
        _slippage_model = SlippageModel()
    return _slippage_model


def calculate_entry_price(
    snapshot: MarketSnapshot,
    side: str
) -> Optional[tuple]:
    """Convenience function for calculating entry price."""
    return get_slippage_model().calculate_entry_price(snapshot, side)


def calculate_exit_price(
    snapshot: MarketSnapshot,
    side: str,
    is_resolution: bool = False
) -> Optional[tuple]:
    """Convenience function for calculating exit price."""
    return get_slippage_model().calculate_exit_price(snapshot, side, is_resolution)
