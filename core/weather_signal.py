# =============================================================================
# WEATHER OBSERVER - SIGNAL DATA MODEL
# =============================================================================
#
# OBSERVER-ONLY SYSTEM - NO TRADING
#
# This module defines the WeatherObservation data structure.
# The ONLY output of the Weather Observer Engine.
#
# CRITICAL PROPERTIES:
# - This is an OBSERVER system, not a trading system
# - Output is OBSERVE or NO_SIGNAL, never BUY/SELL
# - Observations are immutable facts
# - No execution, no trading, no position sizing
#
# =============================================================================

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Optional, Dict, Any
from uuid import uuid4


# =============================================================================
# ENUMS
# =============================================================================


class ObservationAction(Enum):
    """
    Observation classification from the weather engine.

    OBSERVE: Model detects potential edge (fair prob differs from market).
             This is an OBSERVATION, not a trade recommendation.
             Action: Log for calibration and analysis.

    NO_SIGNAL: Either:
               - Edge is insufficient
               - Model confidence is LOW
               - Market fails filter criteria
               - Data is missing or ambiguous
               Action: Do nothing.

    NOTE: There is NO BUY, SELL, or TRADE action.
    This is a read-only observation system.
    """
    OBSERVE = "OBSERVE"
    NO_SIGNAL = "NO_SIGNAL"


class WeatherConfidence(Enum):
    """
    Confidence level of the probability model.

    LOW: Model has significant uncertainty.
         - Forecast horizon > 7 days
         - Multiple conflicting data sources
         - Event definition is edge-case
         Action: NO_SIGNAL regardless of edge

    MEDIUM: Model has moderate confidence.
            - Forecast horizon 3-7 days
            - Consistent data sources
            Action: Require higher edge threshold for OBSERVE

    HIGH: Model has high confidence.
          - Forecast horizon < 3 days
          - Strong data agreement
          - Clear event definition
          Action: Standard edge threshold applies
    """
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


# =============================================================================
# WEATHER OBSERVATION DATA MODEL
# =============================================================================


@dataclass(frozen=True)
class WeatherObservation:
    """
    Immutable observation from the Weather Observer Engine.

    This is the ONLY output type of the engine.
    An observation is a fact - it represents the engine's assessment at a point in time.

    OBSERVER-ONLY GUARANTEES:
    - Observations do NOT execute trades
    - Observations do NOT recommend positions
    - Observations are logged for calibration analysis
    - The engine observes; humans decide what to do
    """
    # Unique identifier
    observation_id: str

    # Timestamp (ISO8601 UTC)
    timestamp_utc: str

    # Market identification
    market_id: str
    city: str
    event_description: str

    # Probabilities
    market_probability: float  # Current market-implied probability
    model_probability: float   # Model-estimated probability

    # Edge calculation
    edge: float  # (model - market) / market

    # Model assessment
    confidence: WeatherConfidence

    # Classification
    action: ObservationAction

    # Engine metadata
    engine: str = "weather_observer_v1"
    parameters_hash: str = ""

    # Forecast context
    forecast_source: Optional[str] = None
    forecast_temperature_f: Optional[float] = None
    forecast_sigma_f: Optional[float] = None
    threshold_temperature_f: Optional[float] = None
    hours_to_resolution: Optional[float] = None

    # Ensemble metadata (optional, populated when ensemble is used)
    ensemble_source_count: Optional[int] = None
    ensemble_source_names: Optional[str] = None  # comma-separated
    ensemble_variance: Optional[float] = None
    ensemble_max_deviation: Optional[float] = None

    def __post_init__(self):
        """Validate observation fields."""
        if not (0.0 <= self.market_probability <= 1.0):
            raise ValueError(
                f"market_probability must be in [0, 1], got {self.market_probability}"
            )
        if not (0.0 <= self.model_probability <= 1.0):
            raise ValueError(
                f"model_probability must be in [0, 1], got {self.model_probability}"
            )
        if not isinstance(self.confidence, WeatherConfidence):
            raise TypeError(
                f"confidence must be WeatherConfidence, got {type(self.confidence)}"
            )
        if not isinstance(self.action, ObservationAction):
            raise TypeError(
                f"action must be ObservationAction, got {type(self.action)}"
            )

    def to_dict(self) -> Dict[str, Any]:
        """Convert observation to JSON-serializable dictionary."""
        return {
            "observation_id": self.observation_id,
            "timestamp_utc": self.timestamp_utc,
            "market_id": self.market_id,
            "city": self.city,
            "event_description": self.event_description,
            "market_probability": self.market_probability,
            "model_probability": self.model_probability,
            "edge": self.edge,
            "confidence": self.confidence.value,
            "action": self.action.value,
            "engine": self.engine,
            "parameters_hash": self.parameters_hash,
            "forecast_source": self.forecast_source,
            "forecast_temperature_f": self.forecast_temperature_f,
            "forecast_sigma_f": self.forecast_sigma_f,
            "threshold_temperature_f": self.threshold_temperature_f,
            "hours_to_resolution": self.hours_to_resolution,
            "ensemble_source_count": self.ensemble_source_count,
            "ensemble_source_names": self.ensemble_source_names,
            "ensemble_variance": self.ensemble_variance,
            "ensemble_max_deviation": self.ensemble_max_deviation,
        }

    def to_json(self) -> str:
        """Convert observation to JSON string."""
        return json.dumps(self.to_dict(), indent=2)

    @property
    def has_edge(self) -> bool:
        """Check if this observation detected edge."""
        return self.action == ObservationAction.OBSERVE


# =============================================================================
# FACTORY FUNCTIONS
# =============================================================================


def create_observation(
    market_id: str,
    city: str,
    event_description: str,
    market_probability: float,
    model_probability: float,
    confidence: WeatherConfidence,
    action: ObservationAction,
    config_snapshot: Dict[str, Any],
    forecast_source: Optional[str] = None,
    forecast_temperature_f: Optional[float] = None,
    forecast_sigma_f: Optional[float] = None,
    threshold_temperature_f: Optional[float] = None,
    hours_to_resolution: Optional[float] = None,
    ensemble_source_count: Optional[int] = None,
    ensemble_source_names: Optional[str] = None,
    ensemble_variance: Optional[float] = None,
    ensemble_max_deviation: Optional[float] = None,
) -> WeatherObservation:
    """
    Factory function to create a WeatherObservation with computed fields.

    Args:
        market_id: Polymarket market identifier
        city: City for the weather event
        event_description: Human-readable event description
        market_probability: Current market-implied probability
        model_probability: Model-estimated probability
        confidence: Model confidence level
        action: OBSERVE or NO_SIGNAL
        config_snapshot: Current configuration dictionary (for hash)
        forecast_source: Optional source of forecast data
        forecast_temperature_f: Optional forecasted temperature
        forecast_sigma_f: Optional standard deviation of forecast
        threshold_temperature_f: Optional threshold temperature
        hours_to_resolution: Optional hours until resolution

    Returns:
        WeatherObservation instance
    """
    observation_id = str(uuid4())
    timestamp_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S") + "Z"

    if market_probability > 0:
        edge = (model_probability - market_probability) / market_probability
    else:
        edge = 0.0

    config_json = json.dumps(config_snapshot, sort_keys=True)
    parameters_hash = hashlib.sha256(config_json.encode()).hexdigest()

    return WeatherObservation(
        observation_id=observation_id,
        timestamp_utc=timestamp_utc,
        market_id=market_id,
        city=city,
        event_description=event_description,
        market_probability=market_probability,
        model_probability=model_probability,
        edge=edge,
        confidence=confidence,
        action=action,
        parameters_hash=parameters_hash,
        forecast_source=forecast_source,
        forecast_temperature_f=forecast_temperature_f,
        forecast_sigma_f=forecast_sigma_f,
        threshold_temperature_f=threshold_temperature_f,
        hours_to_resolution=hours_to_resolution,
        ensemble_source_count=ensemble_source_count,
        ensemble_source_names=ensemble_source_names,
        ensemble_variance=ensemble_variance,
        ensemble_max_deviation=ensemble_max_deviation,
    )


def create_no_signal(
    market_id: str,
    city: str,
    event_description: str,
    market_probability: float,
    reason: str,
    config_snapshot: Dict[str, Any],
) -> WeatherObservation:
    """
    Factory function to create a NO_SIGNAL observation.

    Use this when:
    - Market fails filter criteria
    - Model confidence is too low
    - Edge is insufficient
    - Data is missing or ambiguous

    Args:
        market_id: Polymarket market identifier
        city: City for the weather event
        event_description: Original event description
        market_probability: Current market-implied probability
        reason: Reason for NO_SIGNAL (for audit)
        config_snapshot: Current configuration dictionary

    Returns:
        WeatherObservation with NO_SIGNAL action
    """
    return create_observation(
        market_id=market_id,
        city=city,
        event_description=f"{event_description} [NO_SIGNAL: {reason}]",
        market_probability=market_probability,
        model_probability=0.0,
        confidence=WeatherConfidence.LOW,
        action=ObservationAction.NO_SIGNAL,
        config_snapshot=config_snapshot,
    )


# =============================================================================
# LEGACY COMPATIBILITY (for existing tests)
# =============================================================================

# Aliases for backward compatibility during transition
WeatherSignal = WeatherObservation
WeatherSignalAction = ObservationAction
create_weather_signal = create_observation
