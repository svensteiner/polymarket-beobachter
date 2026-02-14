# =============================================================================
# POLYMARKET BEOBACHTER - KELLY CRITERION POSITION SIZING
# =============================================================================
#
# Kelly Fraction: f = (p * b - q) / b
# where p = win probability, b = odds (payout ratio), q = 1 - p
#
# We use Half-Kelly to balance growth rate with acceptable variance.
#
# CAPS:
# - Minimum: EUR 25 per trade
# - Maximum: EUR 500 per trade
# - Fallback: EUR 100 if edge/confidence not computable
#
# =============================================================================

import logging
from typing import Optional

logger = logging.getLogger(__name__)


# Position size caps
MIN_POSITION_EUR: float = 25.0
MAX_POSITION_EUR: float = 250.0    # Max 5% of 5000 EUR capital
FALLBACK_POSITION_EUR: float = 75.0

# Use Quarter-Kelly until model is calibrated
KELLY_FRACTION: float = 0.25


def kelly_size(
    win_probability: float,
    entry_price: float,
    bankroll: float = 10000.0,
    fraction: float = KELLY_FRACTION,
) -> float:
    """
    Compute Kelly-optimal position size in EUR.

    In prediction markets:
    - You pay `entry_price` per contract
    - You receive 1.0 if you win, 0.0 if you lose
    - Odds (b) = (1 - entry_price) / entry_price
    - Edge = win_probability - entry_price

    Kelly fraction: f = (p * b - q) / b
    Simplified for prediction markets: f = (p - entry_price) / (1 - entry_price)

    Args:
        win_probability: Estimated probability of winning (our model estimate)
        entry_price: Market price / entry cost per contract
        bankroll: Total available capital in EUR
        fraction: Kelly fraction (0.5 = Half-Kelly)

    Returns:
        Position size in EUR, capped to [MIN, MAX]
    """
    # Validate inputs
    if win_probability is None or entry_price is None:
        logger.debug("Kelly: missing inputs, using fallback")
        return FALLBACK_POSITION_EUR

    if not (0.01 <= win_probability <= 0.99):
        logger.debug(f"Kelly: win_probability {win_probability} out of range")
        return FALLBACK_POSITION_EUR

    if not (0.01 <= entry_price <= 0.99):
        logger.debug(f"Kelly: entry_price {entry_price} out of range")
        return FALLBACK_POSITION_EUR

    # Edge = our probability - market price
    edge = win_probability - entry_price

    if edge <= 0:
        # No positive edge - should not trade, but return minimum if forced
        logger.debug(f"Kelly: no positive edge ({edge:.4f}), using minimum")
        return MIN_POSITION_EUR

    # Kelly formula for prediction markets
    # f = (p - price) / (1 - price)
    denominator = 1.0 - entry_price
    if denominator <= 0:
        return FALLBACK_POSITION_EUR

    full_kelly = edge / denominator

    # Apply fraction (Half-Kelly)
    adjusted_kelly = full_kelly * fraction

    # Convert to EUR amount
    position_eur = adjusted_kelly * bankroll

    # Apply caps
    position_eur = max(MIN_POSITION_EUR, min(MAX_POSITION_EUR, position_eur))

    logger.debug(
        f"Kelly sizing: p={win_probability:.3f} price={entry_price:.3f} "
        f"edge={edge:.3f} f*={full_kelly:.3f} half_kelly={adjusted_kelly:.3f} "
        f"size={position_eur:.2f} EUR"
    )

    return round(position_eur, 2)
