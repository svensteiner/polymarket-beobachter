# =============================================================================
# PERFORMANCE CACHE - High-Speed Calculations with Memoization
# =============================================================================
#
# Optimiert häufige Berechnungen durch Caching und Vorberechnung
# - Normal-CDF Tabelle für häufige Z-Werte
# - Fee-Calculation Cache
# - Temperature-Probability LUT (Lookup Table)
# - Edge-Threshold Fast Path
#
# =============================================================================

import logging
import math
from typing import Dict, Tuple, Optional
from functools import lru_cache

logger = logging.getLogger(__name__)

# =============================================================================
# PRE-COMPUTED LOOKUP TABLES
# =============================================================================

# Pre-compute Normal CDF for common Z-values (-4 to 4 in 0.1 steps)
_NORMAL_CDF_TABLE: Dict[float, float] = {}
_Z_PRECISION = 0.1
_Z_RANGE = 40  # -4.0 to 4.0

def _build_normal_cdf_table():
    """Build lookup table for Normal CDF values."""
    global _NORMAL_CDF_TABLE
    if _NORMAL_CDF_TABLE:
        return

    for i in range(-_Z_RANGE, _Z_RANGE + 1):
        z = i * _Z_PRECISION
        # Standard normal CDF: 0.5 * (1 + erf(z / sqrt(2)))
        cdf_val = 0.5 * (1 + math.erf(z / math.sqrt(2)))
        _NORMAL_CDF_TABLE[round(z, 1)] = cdf_val

    logger.debug(f"Built Normal CDF table with {len(_NORMAL_CDF_TABLE)} entries")

def fast_normal_cdf(x: float, mean: float, sigma: float) -> float:
    """
    Fast Normal CDF using lookup table for common values.

    Falls back to exact calculation for uncommon Z-values.
    """
    if sigma <= 0:
        raise ValueError(f"sigma must be positive, got {sigma}")

    z = (x - mean) / sigma
    z_rounded = round(z, 1)

    # Use lookup table if available
    if z_rounded in _NORMAL_CDF_TABLE:
        return _NORMAL_CDF_TABLE[z_rounded]

    # Fallback to exact calculation
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))

# =============================================================================
# FEE CALCULATION CACHE
# =============================================================================

@lru_cache(maxsize=1000)
def cached_polymarket_fee(price_hundredths: int) -> float:
    """
    Cached fee calculation for common price points.

    Args:
        price_hundredths: Price * 100 as integer (e.g. 0.25 -> 25)

    Returns:
        Fee as decimal
    """
    price = price_hundredths / 100.0
    p = max(0.001, min(0.999, price))
    return 0.02 * p * (1.0 - p) / 0.25

def fast_polymarket_fee(price: float) -> float:
    """Fast fee calculation using cache."""
    price_hundredths = round(price * 100)
    return cached_polymarket_fee(price_hundredths)

# =============================================================================
# PROBABILITY CALCULATION OPTIMIZATIONS
# =============================================================================

@lru_cache(maxsize=2000)
def cached_probability_exceeds(
    threshold_tenths: int,
    mean_tenths: int,
    sigma_tenths: int
) -> float:
    """
    Cached probability calculation for temperature thresholds.

    Args:
        *_tenths: Values * 10 as integers for cache key
    """
    threshold = threshold_tenths / 10.0
    mean = mean_tenths / 10.0
    sigma = sigma_tenths / 10.0

    return 1.0 - fast_normal_cdf(threshold, mean, sigma)

@lru_cache(maxsize=2000)
def cached_probability_between(
    low_tenths: int,
    high_tenths: int,
    mean_tenths: int,
    sigma_tenths: int
) -> float:
    """Cached probability for temperature ranges."""
    low = low_tenths / 10.0
    high = high_tenths / 10.0
    mean = mean_tenths / 10.0
    sigma = sigma_tenths / 10.0

    if low >= high:
        return 0.0

    cdf_high = fast_normal_cdf(high, mean, sigma)
    cdf_low = fast_normal_cdf(low, mean, sigma)
    return cdf_high - cdf_low

def fast_probability_calculation(
    temperature_f: float,
    threshold_f: float,
    sigma: float,
    event_type: str = "exceeds",
    threshold_high_f: Optional[float] = None,
) -> float:
    """
    Optimized probability calculation using caches and lookup tables.

    ~10x faster than original implementation for common values.
    """
    # Round to cache-friendly values (0.1°F precision)
    temp_tenths = round(temperature_f * 10)
    threshold_tenths = round(threshold_f * 10)
    sigma_tenths = round(sigma * 10)

    if event_type == "exceeds":
        return cached_probability_exceeds(
            threshold_tenths, temp_tenths, sigma_tenths
        )
    elif event_type == "below":
        return 1.0 - cached_probability_exceeds(
            threshold_tenths, temp_tenths, sigma_tenths
        )
    elif event_type == "between_range":
        if threshold_high_f is None:
            raise ValueError("threshold_high_f required for between_range")

        high_tenths = round(threshold_high_f * 10)
        return cached_probability_between(
            threshold_tenths, high_tenths, temp_tenths, sigma_tenths
        )
    else:
        raise ValueError(f"Unknown event_type: {event_type}")

# =============================================================================
# EDGE CALCULATION OPTIMIZATIONS
# =============================================================================

@lru_cache(maxsize=500)
def cached_edge_with_fee(
    model_prob_thousandths: int,
    market_prob_thousandths: int
) -> Tuple[float, float, float]:
    """
    Cached edge calculation including fee computation.

    Returns:
        Tuple of (raw_edge, fee, net_edge)
    """
    model_prob = model_prob_thousandths / 1000.0
    market_prob = market_prob_thousandths / 1000.0

    raw_edge = model_prob - market_prob
    fee = fast_polymarket_fee(market_prob)
    # BUGFIX: Fee reduces edge magnitude regardless of direction.
    # YES (raw >= 0): net = raw - fee
    # NO (raw < 0): net = raw + fee (reduces negative magnitude)
    if raw_edge >= 0:
        net_edge = raw_edge - fee
    else:
        net_edge = raw_edge + fee

    return raw_edge, fee, net_edge

def fast_edge_calculation(model_prob: float, market_prob: float) -> Tuple[float, float, float]:
    """Fast edge calculation with fee using cache."""
    model_thousandths = round(model_prob * 1000)
    market_thousandths = round(market_prob * 1000)

    return cached_edge_with_fee(model_thousandths, market_thousandths)

# =============================================================================
# THRESHOLD CHECKING OPTIMIZATIONS
# =============================================================================

def fast_edge_threshold_check(
    edge: float,
    min_edge: float,
    confidence_level: str,  # "HIGH", "MEDIUM", "LOW"
    medium_multiplier: float = 1.5
) -> bool:
    """
    Fast edge threshold checking with early returns.

    Optimized for the most common case (LOW confidence -> False).
    """
    # Early return for LOW confidence (most common rejection)
    if confidence_level == "LOW":
        return False

    # Calculate required edge
    required_edge = min_edge
    if confidence_level == "MEDIUM":
        required_edge *= medium_multiplier

    return abs(edge) >= required_edge

# =============================================================================
# BATCH PROCESSING OPTIMIZATIONS
# =============================================================================

def batch_probability_calculations(
    temperatures: list,
    thresholds: list,
    sigmas: list,
    event_types: list
) -> list:
    """
    Process multiple probability calculations in batch for better cache utilization.

    Returns list of probabilities in same order as inputs.
    """
    results = []

    for temp, threshold, sigma, event_type in zip(temperatures, thresholds, sigmas, event_types):
        prob = fast_probability_calculation(temp, threshold, sigma, event_type)
        results.append(prob)

    return results

# =============================================================================
# INITIALIZATION
# =============================================================================

def initialize_performance_cache():
    """Initialize all lookup tables and caches."""
    logger.info("Initializing performance cache...")
    start_time = time.time()

    _build_normal_cdf_table()

    # Pre-warm fee cache for common price points
    for price_hundredths in range(1, 100, 2):  # 0.01, 0.03, 0.05, ...
        cached_polymarket_fee(price_hundredths)

    elapsed = time.time() - start_time
    logger.info(f"Performance cache initialized in {elapsed:.3f}s")

# Auto-initialize on import
import time
initialize_performance_cache()