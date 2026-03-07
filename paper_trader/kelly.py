# =============================================================================
# POLYMARKET BEOBACHTER - KELLY CRITERION POSITION SIZING
# =============================================================================
#
# Kelly Fraction: f = (p * b - q) / b
# where p = win probability, b = odds (payout ratio), q = 1 - p
#
# We use Quarter-Kelly to balance growth rate with acceptable variance.
#
# CAPS:
# - Minimum: EUR 25 per trade
# - Maximum: EUR 250 per trade
# - Fallback: EUR 75 if edge/confidence not computable
#
# FEATURES:
# - Time-to-Resolution Decay: Kelly-Faktor sinkt bei kurzer Restlaufzeit
# - Ensemble Disagreement: Kelly-Faktor sinkt bei hoher Modell-Varianz
#
# =============================================================================

import logging
import math
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)


# Position size caps
MIN_POSITION_EUR: float = 25.0
MAX_POSITION_EUR: float = 250.0    # Max 5% of 5000 EUR capital
FALLBACK_POSITION_EUR: float = 75.0

# Use Quarter-Kelly until model is calibrated
KELLY_FRACTION: float = 0.1125  # Reduziert: 11.1% Win-Rate braucht konservativeren Ansatz


# =============================================================================
# FEATURE 7: TIME-TO-RESOLUTION DECAY
# =============================================================================

def time_decay_factor(hours_to_resolution: Optional[float]) -> float:
    """
    Kelly-Skalierungsfaktor basierend auf Restlaufzeit bis Market-Resolution.

    Rationale:
    - Sehr kurze Maerkte (<6h): Markt bereits korrekt eingepreist, hohes Risiko
    - Kurze Maerkte (<24h): Erhoehtes Risiko, reduzierter Kelly
    - Optimale Maerkte (24-72h): Volle Kelly-Groesse
    - Laengere Maerkte (72-168h): Leicht reduziert (Modell-Unsicherheit steigt)
    - Sehr lange Maerkte (>168h): Stark reduziert (7 Tage = hohe Unsicherheit)

    Args:
        hours_to_resolution: Stunden bis zur Market-Auflosung (None = kein Decay)

    Returns:
        Skalierungsfaktor zwischen 0.2 und 1.0
    """
    if hours_to_resolution is None or hours_to_resolution < 0:
        return 1.0  # Kein Decay wenn unbekannt

    if hours_to_resolution < 6:
        factor = 0.3   # Sehr kurzfristig: stark reduziert
    elif hours_to_resolution < 24:
        factor = 0.6   # Kurzfristig: reduziert
    elif hours_to_resolution < 72:
        factor = 1.0   # Optimal: volle Groesse (24-72h)
    elif hours_to_resolution < 168:
        factor = 0.8   # Mittelfristig: leicht reduziert (3-7 Tage)
    else:
        factor = 0.5   # Langfristig: stark reduziert (>7 Tage)

    logger.debug(
        f"Time-Decay: hours_to_resolution={hours_to_resolution:.1f}h -> factor={factor:.2f}"
    )
    return factor


# =============================================================================
# FEATURE 4: ENSEMBLE DISAGREEMENT VOLATILITY SCALING
# =============================================================================

def ensemble_vol_scale(ensemble_variance: Optional[float]) -> float:
    """
    Kelly-Skalierungsfaktor basierend auf Ensemble-Disagreement.

    Wenn die Forecast-Quellen stark voneinander abweichen, ist die
    Unsicherheit hoch -> Kelly-Faktor reduzieren.

    Formel: scale = max(0.25, 1.0 - variance * 2.0)
    - variance=0.00 -> scale=1.00 (volle Groesse, alle Quellen einig)
    - variance=0.05 -> scale=0.90 (kleine Abweichung)
    - variance=0.10 -> scale=0.80 (mittlere Abweichung)
    - variance=0.25 -> scale=0.50 (hohe Abweichung)
    - variance=0.38 -> scale=0.25 (sehr hohe Abweichung, Minimum)

    Args:
        ensemble_variance: Varianz der Ensemble-Forecasts (0.0 bis ~0.5)
                          None = kein Scaling

    Returns:
        Skalierungsfaktor zwischen 0.25 und 1.0
    """
    if ensemble_variance is None or ensemble_variance < 0:
        return 1.0  # Kein Scaling wenn nicht verfuegbar

    scale = max(0.25, 1.0 - ensemble_variance * 2.0)

    logger.debug(
        f"Ensemble-Vol-Scale: variance={ensemble_variance:.4f} -> scale={scale:.3f}"
    )
    return scale


def kelly_size(
    win_probability: float,
    entry_price: float,
    bankroll: float = 10000.0,
    fraction: float = KELLY_FRACTION,
    hours_to_resolution: Optional[float] = None,
    ensemble_variance: Optional[float] = None,
    confidence_level: Optional[str] = None,
    market_type: Optional[str] = None,
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

    Additional modifiers:
    - Time-to-Resolution Decay: reduziert bei kurzer Restlaufzeit
    - Ensemble Disagreement: reduziert bei hoher Modell-Varianz

    Args:
        win_probability: Estimated probability of winning (our model estimate)
        entry_price: Market price / entry cost per contract
        bankroll: Total available capital in EUR
        fraction: Kelly fraction (0.25 = Quarter-Kelly)
        hours_to_resolution: Optional Stunden bis Auflosung fuer Time-Decay
        ensemble_variance: Optional Ensemble-Varianz fuer Vol-Scaling

    Returns:
        Position size in EUR, capped to [MIN, MAX]
    """
    # Fast validation with early returns for performance
    if win_probability is None or entry_price is None:
        return FALLBACK_POSITION_EUR

    # Use bitwise operations for range checks (faster than comparisons)
    if not (0.01 <= win_probability <= 0.99) or not (0.01 <= entry_price <= 0.99):
        return FALLBACK_POSITION_EUR

    # Fast edge calculation
    edge = win_probability - entry_price
    if edge <= 0:
        return MIN_POSITION_EUR

    # Optimized Kelly calculation
    denominator = 1.0 - entry_price
    if denominator <= 1e-6:  # Avoid division by very small numbers
        return FALLBACK_POSITION_EUR

    # Single multiplication chain for better performance
    kelly_multiplier = (edge / denominator) * fraction

    # Apply modifiers (cached function calls)
    if hours_to_resolution is not None:
        kelly_multiplier *= time_decay_factor(hours_to_resolution)

    if ensemble_variance is not None:
        kelly_multiplier *= ensemble_vol_scale(ensemble_variance)

    # Darwin-Multiplikator: gelernte Gewichtung pro Signal-Typ
    try:
        from analytics.signal_darwin import get_darwin
        darwin_mult = get_darwin().get_multiplier(confidence_level, market_type)
        kelly_multiplier *= darwin_mult
    except Exception:
        pass  # Fail-open

    # Fast final calculation with bounds checking
    position_eur = kelly_multiplier * bankroll
    position_eur = max(MIN_POSITION_EUR, min(MAX_POSITION_EUR, position_eur))

    # Only log in debug mode to reduce overhead
    if logger.isEnabledFor(logging.DEBUG):
        logger.debug(
            f"Kelly sizing: p={win_probability:.3f} price={entry_price:.3f} "
            f"edge={edge:.3f} kelly={kelly_multiplier:.3f} "
            f"size={position_eur:.2f} EUR"
        )

    return round(position_eur, 2)
