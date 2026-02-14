# =============================================================================
# POLYMARKET BEOBACHTER - WEATHER PROBABILITY MODEL
# =============================================================================
#
# GOVERNANCE INTENT:
# This module computes fair probabilities for weather events.
# It uses external forecast data + statistical modeling.
# It does NOT learn or adapt - all parameters are static from config.
#
# MATHEMATICAL MODEL:
# - Assume forecast temperature follows Normal distribution
# - Mean = forecast value
# - Standard deviation = configurable sigma (adjusted by horizon)
# - P(event) = integral of PDF over event region
#
# EXAMPLE:
# Market: "Will NYC exceed 100°F on July 15?"
# Forecast: 95°F expected, sigma = 3.5°F
# P(T > 100) = 1 - CDF(100; mean=95, sigma=3.5) ≈ 0.077 (7.7%)
#
# If market prices this at 3%, edge = (7.7 - 3) / 3 = 1.57 (157% edge)
#
# CRITICAL ISOLATION:
# - NO imports from panic, execution, or learning modules
# - NO memory of past predictions
# - NO adaptive sigma
#
# =============================================================================

import logging
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional, Dict, Any, Tuple

from .weather_signal import WeatherConfidence

logger = logging.getLogger(__name__)


# =============================================================================
# DATA MODELS
# =============================================================================


@dataclass
class ForecastData:
    """
    External weather forecast data.

    This is READ-ONLY input.
    The model does not modify or store forecast data.
    """
    city: str
    forecast_time: datetime  # When forecast was made
    target_time: datetime    # Time the forecast is for
    temperature_f: float     # Expected temperature in Fahrenheit
    source: str             # Data source (e.g., "tomorrow_io")

    # Optional fields for advanced modeling
    temperature_min_f: Optional[float] = None
    temperature_max_f: Optional[float] = None
    humidity_percent: Optional[float] = None
    precipitation_probability: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for logging."""
        return {
            "city": self.city,
            "forecast_time": self.forecast_time.isoformat(),
            "target_time": self.target_time.isoformat(),
            "temperature_f": self.temperature_f,
            "source": self.source,
            "temperature_min_f": self.temperature_min_f,
            "temperature_max_f": self.temperature_max_f,
        }


@dataclass
class ProbabilityResult:
    """
    Result of probability computation.

    Contains:
    - fair_probability: computed probability
    - confidence: model confidence level
    - sigma_used: standard deviation used
    - computation_details: detailed breakdown
    """
    fair_probability: float
    confidence: WeatherConfidence
    sigma_used: float
    forecast_temperature_f: float
    threshold_temperature_f: float
    hours_to_resolution: float
    computation_details: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for logging."""
        return {
            "fair_probability": self.fair_probability,
            "confidence": self.confidence.value,
            "sigma_used": self.sigma_used,
            "forecast_temperature_f": self.forecast_temperature_f,
            "threshold_temperature_f": self.threshold_temperature_f,
            "hours_to_resolution": self.hours_to_resolution,
            "computation_details": self.computation_details,
        }


# =============================================================================
# MATHEMATICAL FUNCTIONS
# =============================================================================


def standard_normal_cdf(x: float) -> float:
    """
    Compute standard normal CDF using error function.

    This is the probability that a standard normal random variable
    is less than or equal to x.

    P(Z <= x) = 0.5 * (1 + erf(x / sqrt(2)))

    Args:
        x: Value to evaluate CDF at

    Returns:
        Probability P(Z <= x)
    """
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def normal_cdf(x: float, mean: float, sigma: float) -> float:
    """
    Compute CDF of normal distribution.

    P(X <= x) where X ~ Normal(mean, sigma)

    Args:
        x: Value to evaluate CDF at
        mean: Mean of the distribution
        sigma: Standard deviation

    Returns:
        Probability P(X <= x)
    """
    if sigma <= 0:
        raise ValueError(f"sigma must be positive, got {sigma}")

    z = (x - mean) / sigma
    return standard_normal_cdf(z)


def probability_exceeds(
    threshold: float, mean: float, sigma: float
) -> float:
    """
    Compute probability that value exceeds threshold.

    P(X > threshold) = 1 - P(X <= threshold)

    Args:
        threshold: Threshold value
        mean: Expected value
        sigma: Standard deviation

    Returns:
        Probability P(X > threshold)
    """
    return 1.0 - normal_cdf(threshold, mean, sigma)


def probability_below(
    threshold: float, mean: float, sigma: float
) -> float:
    """
    Compute probability that value is below threshold.

    P(X < threshold) = P(X <= threshold)

    Args:
        threshold: Threshold value
        mean: Expected value
        sigma: Standard deviation

    Returns:
        Probability P(X < threshold)
    """
    return normal_cdf(threshold, mean, sigma)


# =============================================================================
# WEATHER PROBABILITY MODEL
# =============================================================================


class WeatherProbabilityModel:
    """
    Computes fair probabilities for weather events.

    MODEL PHILOSOPHY:
    - This model does NOT predict the weather
    - It converts existing forecasts into probability distributions
    - It compares these distributions to market pricing
    - If the model is uncertain, it returns LOW confidence

    STATISTICAL ASSUMPTIONS:
    - Temperature follows Normal distribution around forecast
    - Standard deviation is configurable and horizon-dependent
    - No correlation modeling (each event is independent)

    GOVERNANCE:
    - All parameters from config (no hardcoded learning)
    - No memory of past predictions
    - No adaptive behavior
    """

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize probability model with configuration.

        Args:
            config: Configuration dictionary from weather.yaml
        """
        self.config = config

        # Base sigma (standard deviation in Fahrenheit)
        self.base_sigma_f = config.get("SIGMA_F", 3.5)

        # Horizon adjustments
        self.sigma_horizon_adjustments = config.get(
            "SIGMA_HORIZON_ADJUSTMENTS",
            {1: 0.8, 2: 0.9, 3: 1.0, 5: 1.2, 7: 1.5, 10: 2.0}
        )

        # Maximum forecast horizon
        self.max_horizon_days = config.get("MAX_FORECAST_HORIZON_DAYS", 10)

        # Confidence thresholds
        confidence_thresholds = config.get("CONFIDENCE_THRESHOLDS", {})
        self.high_confidence_max_hours = confidence_thresholds.get(
            "HIGH_CONFIDENCE_MAX_HOURS", 72
        )
        self.medium_confidence_max_hours = confidence_thresholds.get(
            "MEDIUM_CONFIDENCE_MAX_HOURS", 168
        )

        logger.info(
            f"WeatherProbabilityModel initialized | "
            f"base_sigma={self.base_sigma_f}°F | "
            f"max_horizon={self.max_horizon_days} days"
        )

    def compute_probability(
        self,
        forecast: ForecastData,
        threshold_f: float,
        event_type: str = "exceeds",
    ) -> ProbabilityResult:
        """
        Compute fair probability for a weather event.

        Args:
            forecast: External forecast data
            threshold_f: Temperature threshold in Fahrenheit
            event_type: "exceeds" or "below"

        Returns:
            ProbabilityResult with computed probability and confidence
        """
        # Calculate hours to resolution
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        hours_to_resolution = (forecast.target_time - now).total_seconds() / 3600
        days_to_resolution = hours_to_resolution / 24

        # Check if beyond maximum horizon
        if days_to_resolution > self.max_horizon_days:
            logger.warning(
                f"Forecast horizon {days_to_resolution:.1f} days exceeds "
                f"maximum {self.max_horizon_days} days"
            )
            return self._create_low_confidence_result(
                forecast, threshold_f, hours_to_resolution,
                reason="Forecast horizon too long"
            )

        # Calculate adjusted sigma based on horizon
        sigma = self._calculate_adjusted_sigma(days_to_resolution)

        # Compute probability based on event type
        if event_type == "exceeds":
            fair_prob = probability_exceeds(
                threshold_f, forecast.temperature_f, sigma
            )
        elif event_type == "below":
            fair_prob = probability_below(
                threshold_f, forecast.temperature_f, sigma
            )
        else:
            raise ValueError(f"Unknown event_type: {event_type}")

        # Determine confidence level
        confidence = self._determine_confidence(hours_to_resolution)

        # Build computation details
        details = {
            "event_type": event_type,
            "forecast_mean": forecast.temperature_f,
            "sigma_base": self.base_sigma_f,
            "sigma_adjusted": sigma,
            "days_to_resolution": days_to_resolution,
            "z_score": (threshold_f - forecast.temperature_f) / sigma,
            "data_source": forecast.source,
        }

        logger.info(
            f"Probability computed | city={forecast.city} | "
            f"forecast={forecast.temperature_f}°F | threshold={threshold_f}°F | "
            f"sigma={sigma:.2f} | P({event_type})={fair_prob:.4f} | "
            f"confidence={confidence.value}"
        )

        return ProbabilityResult(
            fair_probability=fair_prob,
            confidence=confidence,
            sigma_used=sigma,
            forecast_temperature_f=forecast.temperature_f,
            threshold_temperature_f=threshold_f,
            hours_to_resolution=hours_to_resolution,
            computation_details=details,
        )

    def _calculate_adjusted_sigma(self, days_to_resolution: float) -> float:
        """
        Calculate sigma adjusted for forecast horizon.

        Longer horizons → higher uncertainty → higher sigma.

        Args:
            days_to_resolution: Days until resolution

        Returns:
            Adjusted sigma value
        """
        # Find the appropriate adjustment factor
        adjustment = 1.0

        # Find the largest key that's <= days_to_resolution
        sorted_keys = sorted(self.sigma_horizon_adjustments.keys())
        for key in sorted_keys:
            if days_to_resolution >= key:
                adjustment = self.sigma_horizon_adjustments[key]
            else:
                break

        adjusted_sigma = self.base_sigma_f * adjustment

        logger.debug(
            f"Sigma adjustment | days={days_to_resolution:.1f} | "
            f"base={self.base_sigma_f} | multiplier={adjustment} | "
            f"adjusted={adjusted_sigma}"
        )

        return adjusted_sigma

    def _determine_confidence(self, hours_to_resolution: float) -> WeatherConfidence:
        """
        Determine confidence level based on forecast horizon.

        Args:
            hours_to_resolution: Hours until resolution

        Returns:
            WeatherConfidence level
        """
        if hours_to_resolution <= self.high_confidence_max_hours:
            return WeatherConfidence.HIGH
        elif hours_to_resolution <= self.medium_confidence_max_hours:
            return WeatherConfidence.MEDIUM
        else:
            return WeatherConfidence.LOW

    def _create_low_confidence_result(
        self,
        forecast: ForecastData,
        threshold_f: float,
        hours_to_resolution: float,
        reason: str,
    ) -> ProbabilityResult:
        """
        Create a result with LOW confidence when model cannot compute reliably.

        Args:
            forecast: Forecast data
            threshold_f: Threshold temperature
            hours_to_resolution: Hours to resolution
            reason: Reason for low confidence

        Returns:
            ProbabilityResult with LOW confidence
        """
        return ProbabilityResult(
            fair_probability=0.0,  # Unknown
            confidence=WeatherConfidence.LOW,
            sigma_used=0.0,
            forecast_temperature_f=forecast.temperature_f,
            threshold_temperature_f=threshold_f,
            hours_to_resolution=hours_to_resolution,
            computation_details={
                "low_confidence_reason": reason,
                "data_source": forecast.source,
            },
        )


# =============================================================================
# MODULE-LEVEL FUNCTIONS
# =============================================================================


def compute_probability_from_forecast_temp(
    temperature_f: float,
    threshold_f: float,
    sigma: float,
    event_type: str = "exceeds",
) -> float:
    """
    Compute event probability from a forecast temperature.

    Pure math extraction for use by EnsembleBuilder (no ForecastData needed).

    Args:
        temperature_f: Forecast temperature in Fahrenheit
        threshold_f: Threshold temperature in Fahrenheit
        sigma: Adjusted standard deviation
        event_type: "exceeds" or "below"

    Returns:
        Probability of the event
    """
    if sigma <= 0:
        raise ValueError(f"sigma must be positive, got {sigma}")

    if event_type == "exceeds":
        return probability_exceeds(threshold_f, temperature_f, sigma)
    elif event_type == "below":
        return probability_below(threshold_f, temperature_f, sigma)
    else:
        raise ValueError(f"Unknown event_type: {event_type}")


def compute_edge(
    fair_probability: float,
    market_probability: float,
) -> float:
    """
    Compute edge as percentage of market probability.

    edge = (fair - market) / market

    Args:
        fair_probability: Model-estimated fair probability
        market_probability: Market-implied probability

    Returns:
        Edge as decimal (0.25 = 25% edge)
    """
    if market_probability <= 0:
        return 0.0

    return (fair_probability - market_probability) / market_probability


def meets_edge_threshold(
    edge: float,
    min_edge: float,
    confidence: WeatherConfidence,
    medium_confidence_multiplier: float = 1.5,
) -> bool:
    """
    Check if edge meets threshold for given confidence level.

    For MEDIUM confidence, require higher edge (multiplier applied).
    For LOW confidence, always return False.

    Args:
        edge: Computed edge
        min_edge: Minimum required edge
        confidence: Model confidence level
        medium_confidence_multiplier: Multiplier for MEDIUM confidence

    Returns:
        True if edge meets threshold
    """
    if confidence == WeatherConfidence.LOW:
        return False

    required_edge = min_edge
    if confidence == WeatherConfidence.MEDIUM:
        required_edge = min_edge * medium_confidence_multiplier

    return edge >= required_edge
