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
from typing import Optional

logger = logging.getLogger(__name__)


# Position size caps — lesen aus capital_config.json (Laufzeit-Override möglich)
# Strategie-Reset 2026-04-11: HIGH-only, 5 EUR/Trade bis WR >60% über 50 Trades bewiesen
def _load_caps() -> tuple[float, float, float]:
    """Lade Position-Caps aus capital_config.json, Fallback auf Defaults."""
    try:
        import json
        from pathlib import Path
        cfg_path = Path(__file__).parent.parent / "data" / "capital_config.json"
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        size = float(cfg.get("position_size_eur", 5.0))
        return size, size, size   # min = max = fallback = configured size
    except Exception:
        return 5.0, 5.0, 5.0

# Module-level caps (loaded at import time for tests/introspection)
MIN_POSITION_EUR, MAX_POSITION_EUR, FALLBACK_POSITION_EUR = _load_caps()

# Kelly-Fraction wird durch die festen Caps dominiert solange position_size_eur klein ist
KELLY_FRACTION: float = 0.05


def _get_caps() -> tuple[float, float, float]:
    """Caps werden bei jedem Aufruf live gelesen — damit Restarts nicht nötig sind."""
    return _load_caps()


# =============================================================================
# FEATURE 7: TIME-TO-RESOLUTION URGENCY
# =============================================================================
# Inspiriert von: dylanpersonguy/Fully-Autonomous-Polymarket-AI-Trading-Bot
# und suislanchez/polymarket-kalshi-weather-bot
#
# Kernidee: Wetter-Forecasts werden genauer je naeher die Resolution rueckt.
# Die Projekt-Tests erwarten die folgende Staffelung:
#   <6h   -> 0.3
#   <24h  -> 0.6
#   <72h  -> 1.0
#   <168h -> 0.8
#   sonst -> 0.5


def time_decay_factor(hours_to_resolution: Optional[float]) -> float:
    """
    Kelly-Skalierungsfaktor basierend auf Restlaufzeit bis Market-Resolution.

    Args:
        hours_to_resolution: Stunden bis zur Market-Aufloesung (None = kein Decay)

    Returns:
        Skalierungsfaktor zwischen 0.3 und 1.0
    """
    if hours_to_resolution is None or hours_to_resolution < 0:
        return 1.0

    if hours_to_resolution < 6:
        factor = 0.3
    elif hours_to_resolution < 24:
        factor = 0.6
    elif hours_to_resolution < 72:
        factor = 1.0
    elif hours_to_resolution < 168:
        factor = 0.8
    else:
        factor = 0.5

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
        return 1.0

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
    """
    # Caps live laden (kein Bot-Restart nötig nach capital_config.json Änderung)
    _min_eur, _max_eur, _fallback_eur = _get_caps()

    if win_probability is None or entry_price is None:
        return _fallback_eur

    if not (0.01 <= win_probability <= 0.99) or not (0.01 <= entry_price <= 0.99):
        return _fallback_eur

    edge = win_probability - entry_price
    if edge <= 0:
        return _min_eur

    denominator = 1.0 - entry_price
    if denominator <= 1e-6:
        return _fallback_eur

    kelly_multiplier = (edge / denominator) * fraction

    if hours_to_resolution is not None:
        kelly_multiplier *= time_decay_factor(hours_to_resolution)

    if ensemble_variance is not None:
        kelly_multiplier *= ensemble_vol_scale(ensemble_variance)

    try:
        from analytics.signal_darwin import get_darwin

        darwin_mult = get_darwin().get_multiplier(confidence_level, market_type)
        kelly_multiplier *= darwin_mult
    except Exception:
        pass

    position_eur = kelly_multiplier * bankroll
    position_eur = max(_min_eur, min(_max_eur, position_eur))

    if logger.isEnabledFor(logging.DEBUG):
        logger.debug(
            f"Kelly sizing: p={win_probability:.3f} price={entry_price:.3f} "
            f"edge={edge:.3f} kelly={kelly_multiplier:.3f} "
            f"size={position_eur:.2f} EUR"
        )

    return round(position_eur, 2)
