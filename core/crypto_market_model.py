# =============================================================================
# POLYMARKET BEOBACHTER - CRYPTO MARKET PROBABILITY MODEL
# =============================================================================
#
# Model for cryptocurrency price threshold markets.
# Uses log-normal distribution + historical volatility to estimate
# probability of price reaching a target by a given date.
#
# =============================================================================

import logging
import math
import re
from datetime import date, datetime
from typing import Dict, Any, Optional, Tuple

from .probability_models import (
    BaseProbabilityModel,
    HonestProbabilityEstimate,
    ModelType,
    ModelConfidence,
)

logger = logging.getLogger(__name__)


# =============================================================================
# KEYWORD DETECTION
# =============================================================================

CRYPTO_KEYWORDS = [
    "bitcoin", "btc", "ethereum", "eth", "solana", "sol",
    "crypto", "cryptocurrency",
]

PRICE_DIRECTION_KEYWORDS = [
    "price", "above", "below", "reach", "hit", "exceed",
    "worth", "trading at", "market cap",
]

# Approximate current prices (updated periodically)
# These serve as fallback when API data is unavailable
REFERENCE_PRICES: Dict[str, float] = {
    "bitcoin": 100000.0,
    "btc": 100000.0,
    "ethereum": 3200.0,
    "eth": 3200.0,
    "solana": 200.0,
    "sol": 200.0,
}

# Annualized volatility estimates (historical)
ANNUALIZED_VOLATILITY: Dict[str, float] = {
    "bitcoin": 0.60,
    "btc": 0.60,
    "ethereum": 0.75,
    "eth": 0.75,
    "solana": 0.90,
    "sol": 0.90,
}

# Price extraction pattern
PRICE_PATTERN = re.compile(
    r"\$\s*([\d,]+(?:\.\d+)?)\s*(?:k|K)?"
    r"|"
    r"([\d,]+(?:\.\d+)?)\s*(?:dollars|usd|USD)",
    re.IGNORECASE,
)

# Date extraction patterns
DATE_PATTERNS = [
    re.compile(r"by\s+(?:end\s+of\s+)?(\w+\s+\d{4})", re.IGNORECASE),
    re.compile(r"before\s+(\w+\s+\d{1,2},?\s+\d{4})", re.IGNORECASE),
    re.compile(r"by\s+(\w+\s+\d{1,2},?\s+\d{4})", re.IGNORECASE),
    re.compile(r"in\s+(\d{4})", re.IGNORECASE),
]


def _identify_crypto(text: str) -> Optional[str]:
    """Identify which cryptocurrency the market is about."""
    text_lower = text.lower()
    for kw in CRYPTO_KEYWORDS:
        if kw in text_lower:
            return kw
    return None


def _extract_target_price(text: str) -> Optional[float]:
    """Extract target price from market text."""
    for match in PRICE_PATTERN.finditer(text):
        raw = match.group(1) or match.group(2)
        if raw:
            raw = raw.replace(",", "")
            price = float(raw)
            # Handle "k" suffix
            if match.group(0).rstrip().lower().endswith("k"):
                price *= 1000
            if price > 0:
                return price
    # Try plain large numbers near crypto keywords
    numbers = re.findall(r"([\d,]+(?:\.\d+)?)", text)
    for n in numbers:
        val = float(n.replace(",", ""))
        if val >= 1000:  # likely a price
            return val
    return None


def _estimate_days_to_resolution(text: str) -> Optional[int]:
    """Estimate days until market resolution from text."""
    today = date.today()
    text_lower = text.lower()

    # "by end of 2026" / "in 2026"
    year_match = re.search(r"(?:by\s+end\s+of|in)\s+(20\d{2})", text_lower)
    if year_match:
        year = int(year_match.group(1))
        target = date(year, 12, 31)
        return max(1, (target - today).days)

    # Month + year: "by March 2026"
    month_year = re.search(
        r"(?:by|before)\s+(\w+)\s+(20\d{2})", text_lower
    )
    if month_year:
        try:
            dt = datetime.strptime(
                f"{month_year.group(1)} {month_year.group(2)}", "%B %Y"
            )
            target = date(dt.year, dt.month, 28)
            return max(1, (target - today).days)
        except ValueError:
            pass

    # Default: assume ~180 days if no date found
    return 180


def log_normal_probability(
    current_price: float,
    target_price: float,
    days: int,
    annual_vol: float,
) -> float:
    """
    Probability that price reaches target under geometric Brownian motion.

    Assumes zero drift (conservative — no directional bias).
    P(S_T >= K) = Phi(-d2) where d2 = (ln(K/S) - 0.5*sigma^2*T) / (sigma*sqrt(T))
    For "below" targets: P(S_T <= K) = 1 - P(S_T >= K)
    """
    if current_price <= 0 or target_price <= 0 or days <= 0:
        return 0.5

    T = days / 365.0
    sigma = annual_vol
    sigma_sqrt_T = sigma * math.sqrt(T)

    if sigma_sqrt_T < 1e-10:
        return 1.0 if current_price >= target_price else 0.0

    # d2 with zero drift
    d2 = (math.log(target_price / current_price) - 0.5 * sigma * sigma * T) / sigma_sqrt_T

    # Standard normal CDF approximation
    prob_above = _norm_cdf(-d2)
    return prob_above


def _norm_cdf(x: float) -> float:
    """Standard normal CDF approximation (Abramowitz & Stegun)."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


# =============================================================================
# MODEL
# =============================================================================


class CryptoMarketModel(BaseProbabilityModel):
    """
    Probability model for crypto price threshold markets.

    Uses log-normal distribution with historical volatility.
    Zero-drift assumption (conservative).
    """

    @property
    def model_type(self) -> ModelType:
        return ModelType.CRYPTO_MARKET

    def can_estimate(self, market_data: Dict[str, Any]) -> bool:
        title = market_data.get("title", "").lower()
        description = market_data.get("description", "").lower()
        combined = f"{title} {description}"

        has_crypto = any(kw in combined for kw in CRYPTO_KEYWORDS)
        has_price = any(kw in combined for kw in PRICE_DIRECTION_KEYWORDS)

        return has_crypto and has_price

    def estimate(self, market_data: Dict[str, Any]) -> HonestProbabilityEstimate:
        title = market_data.get("title", "")
        description = market_data.get("description", "")
        combined = f"{title} {description}"

        crypto = _identify_crypto(combined)
        if not crypto:
            return HonestProbabilityEstimate.invalid(
                reason="Could not identify cryptocurrency",
                model_type=ModelType.CRYPTO_MARKET,
            )

        target_price = _extract_target_price(combined)
        if not target_price:
            return HonestProbabilityEstimate.invalid(
                reason="Could not extract target price from market",
                model_type=ModelType.CRYPTO_MARKET,
            )

        current_price = REFERENCE_PRICES.get(crypto, None)
        if not current_price:
            return HonestProbabilityEstimate.invalid(
                reason=f"No reference price for {crypto}",
                model_type=ModelType.CRYPTO_MARKET,
            )

        days = _estimate_days_to_resolution(combined) or 180
        vol = ANNUALIZED_VOLATILITY.get(crypto, 0.70)

        # Determine direction
        is_below = any(w in combined.lower() for w in ["below", "under", "less than", "drop"])
        prob_above = log_normal_probability(current_price, target_price, days, vol)
        probability = (1.0 - prob_above) if is_below else prob_above

        # Clamp to reasonable range
        probability = max(0.02, min(0.98, probability))

        # Uncertainty band: wider for longer horizons
        band = min(0.20, 0.05 + (days / 365.0) * 0.10)

        return HonestProbabilityEstimate(
            probability=round(probability, 4),
            probability_low=round(max(0.01, probability - band), 4),
            probability_high=round(min(0.99, probability + band), 4),
            valid=True,
            confidence=ModelConfidence.MEDIUM,
            model_type=ModelType.CRYPTO_MARKET,
            assumption=(
                f"Log-normal model: {crypto.upper()} current ~${current_price:,.0f}, "
                f"target ${target_price:,.0f}, {days}d horizon, "
                f"annualized vol={vol:.0%}, zero drift"
            ),
            data_sources=[
                "Historical volatility estimates",
                "Reference price (periodically updated)",
                "Log-normal price distribution model",
            ],
            reasoning=(
                f"Crypto model: {crypto.upper()} ${current_price:,.0f} -> ${target_price:,.0f} "
                f"in {days}d, vol={vol:.0%}, P={'below' if is_below else 'above'}={probability:.3f}"
            ),
        )
