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
# Stark reduziert: Erst bei nachgewiesener Kalibrierung erhoehen
MIN_POSITION_EUR: float = 15.0
MAX_POSITION_EUR: float = 75.0     # Max 1.5% of 5000 EUR capital
FALLBACK_POSITION_EUR: float = 40.0

# 5% Kelly bis Ensemble-Kalibrierung bewiesen ist
# (Profitable Bots nutzen 15% Kelly ABER mit besser kalibriertem Modell)
KELLY_FRACTION: float = 0.05


# =============================================================================
# FEATURE 7: TIME-TO-RESOLUTION URGENCY
# =============================================================================
# Inspiriert von: dylanpersonguy/Fully-Autonomous-Polymarket-AI-Trading-Bot
# und suislanchez/polymarket-kalshi-weather-bot
#
# Kernidee: Wetter-Forecasts werden genauer je naeher die Resolution rueckt.
# 1-2 Tage vor Resolution sind Forecasts 85-90% akkurat (NOAA-Daten).
# Deshalb: MEHR traden kurz vor Resolution, WENIGER bei langer Laufzeit.

def time_decay_factor(hours_to_resolution: Optional[float]) -> float:
    """
    Kelly-Skalierungsfaktor basierend auf Restlaufzeit bis Market-Resolution.

    NEUE Logik (umgedreht gegenueber altem Ansatz):
    - Forecasts werden genauer je naeher die Resolution rueckt
    - 6-24h: Forecast sehr genau → Kelly ERHOEHEN (1.4x)
    - 24-48h: Sweet Spot → volle Groesse (1.2x)
    - 48-72h: Gut → Standard (1.0x)
    - 72-168h: Mehr Unsicherheit → reduziert (0.7x)
    - >168h: Zu unsicher → stark reduziert (0.4x)
    - <6h: Markt oft schon eingepreist → leicht reduziert (0.8x)

    Args:
        hours_to_resolution: Stunden bis zur Market-Auflosung (None = kein Decay)

    Returns:
        Skalierungsfaktor zwischen 0.4 und 1.4
    """
    if hours_to_resolution is None or hours_to_resolution < 0:
        return 1.0  # Kein Decay wenn unbekannt

    if hours_to_resolution < 6:
        factor = 0.8   # Sehr kurzfristig: Markt oft korrekt, aber Forecast ist top
    elif hours_to_resolution < 24:
        factor = 1.4   # PRIME TIME: Forecast extrem genau, Markt hinkt hinterher
    elif hours_to_resolution < 48:
        factor = 1.2   # Sweet Spot: sehr gute Forecasts
    elif hours_to_resolution < 72:
        factor = 1.0   # Standard: solide Forecasts
    elif hours_to_resolution < 168:
        factor = 0.7   # Mittelfristig: zunehmende Unsicherheit
    else:
        factor = 0.4   # Langfristig: Forecast zu unsicher fuer grosse Positionen

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
