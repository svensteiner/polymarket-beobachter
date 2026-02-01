# =============================================================================
# POLYMARKET BEOBACHTER - WEATHER SIGNAL DATA MODEL
# =============================================================================
#
# GOVERNANCE INTENT:
# This module defines the WeatherSignal data structure - the ONLY output
# of the Weather Trading Engine.
#
# CRITICAL ISOLATION:
# - This module has NO imports from panic, trader, execution, or learning modules
# - WeatherSignal is an IMMUTABLE FACT - once created, it cannot be modified
# - The signal does NOT execute trades - it only provides information
#
# SIGNAL PHILOSOPHY:
# A WeatherSignal represents a potential mispricing opportunity.
# It compares physical reality (weather forecasts) to market pricing.
# If the model is uncertain, the correct output is NO_SIGNAL.
#
# =============================================================================

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional, Dict, Any
from uuid import uuid4


# =============================================================================
# ENUMS
# =============================================================================


class WeatherSignalAction(Enum):
    """
    Recommended action from the weather engine.

    BUY: Model estimates fair probability > market probability by MIN_EDGE.
         This suggests the market is underpricing the event.

    NO_SIGNAL: Either:
               - Edge is insufficient (below MIN_EDGE)
               - Model confidence is LOW
               - Market fails filter criteria
               - Any uncertainty exists

    NOTE: There is NO SELL action. The weather engine is long-only.
    We identify underpriced events, not overpriced ones.
    """
    BUY = "BUY"
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
            Action: Require higher MIN_EDGE

    HIGH: Model has high confidence.
          - Forecast horizon < 3 days
          - Strong data agreement
          - Clear event definition
          Action: Standard MIN_EDGE applies
    """
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


# =============================================================================
# WEATHER SIGNAL DATA MODEL
# =============================================================================


@dataclass(frozen=True)
class WeatherSignal:
    """
    Immutable signal from the Weather Trading Engine.

    This is the ONLY output type of the engine.
    A signal is a fact - it represents the engine's assessment at a point in time.

    GOVERNANCE:
    - Signals do NOT execute trades
    - Signals are logged for audit
    - Signals can be ignored by downstream systems
    - The engine emits signals; humans/systems decide what to do with them

    IMMUTABILITY:
    This dataclass is frozen. Once created, it cannot be modified.
    To "update" a signal, create a new one.
    """
    # Unique identifier for this signal
    signal_id: str

    # Timestamp when signal was generated (ISO8601 UTC)
    timestamp_utc: str

    # Market identification
    market_id: str
    city: str
    event_description: str

    # Probabilities
    market_probability: float  # Current market-implied probability
    fair_probability: float    # Model-estimated fair probability

    # Edge calculation
    edge: float  # (fair - market) / market

    # Model assessment
    confidence: WeatherConfidence

    # Final recommendation
    recommended_action: WeatherSignalAction

    # Engine metadata
    engine: str = "weather_engine_v1"
    parameters_hash: str = ""  # SHA256 of config snapshot

    # Optional additional context
    forecast_source: Optional[str] = None
    forecast_temperature_f: Optional[float] = None
    forecast_sigma_f: Optional[float] = None
    threshold_temperature_f: Optional[float] = None
    hours_to_resolution: Optional[float] = None

    def __post_init__(self):
        """Validate signal fields."""
        # Validate probabilities are in valid range
        if not (0.0 <= self.market_probability <= 1.0):
            raise ValueError(
                f"market_probability must be in [0, 1], got {self.market_probability}"
            )
        if not (0.0 <= self.fair_probability <= 1.0):
            raise ValueError(
                f"fair_probability must be in [0, 1], got {self.fair_probability}"
            )

        # Validate confidence is correct type
        if not isinstance(self.confidence, WeatherConfidence):
            raise TypeError(
                f"confidence must be WeatherConfidence, got {type(self.confidence)}"
            )

        # Validate action is correct type
        if not isinstance(self.recommended_action, WeatherSignalAction):
            raise TypeError(
                f"recommended_action must be WeatherSignalAction, "
                f"got {type(self.recommended_action)}"
            )

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert signal to JSON-serializable dictionary.

        Used for:
        - Audit logging
        - Signal registry storage
        - Human review
        """
        return {
            "signal_id": self.signal_id,
            "timestamp_utc": self.timestamp_utc,
            "market_id": self.market_id,
            "city": self.city,
            "event_description": self.event_description,
            "market_probability": self.market_probability,
            "fair_probability": self.fair_probability,
            "edge": self.edge,
            "confidence": self.confidence.value,
            "recommended_action": self.recommended_action.value,
            "engine": self.engine,
            "parameters_hash": self.parameters_hash,
            "forecast_source": self.forecast_source,
            "forecast_temperature_f": self.forecast_temperature_f,
            "forecast_sigma_f": self.forecast_sigma_f,
            "threshold_temperature_f": self.threshold_temperature_f,
            "hours_to_resolution": self.hours_to_resolution,
        }

    def to_json(self) -> str:
        """Convert signal to JSON string."""
        return json.dumps(self.to_dict(), indent=2)

    @property
    def is_actionable(self) -> bool:
        """
        Check if this signal suggests action.

        Returns True only if recommended_action is BUY.
        NO_SIGNAL means no action should be taken.
        """
        return self.recommended_action == WeatherSignalAction.BUY


# =============================================================================
# FACTORY FUNCTIONS
# =============================================================================


def create_weather_signal(
    market_id: str,
    city: str,
    event_description: str,
    market_probability: float,
    fair_probability: float,
    confidence: WeatherConfidence,
    recommended_action: WeatherSignalAction,
    config_snapshot: Dict[str, Any],
    forecast_source: Optional[str] = None,
    forecast_temperature_f: Optional[float] = None,
    forecast_sigma_f: Optional[float] = None,
    threshold_temperature_f: Optional[float] = None,
    hours_to_resolution: Optional[float] = None,
) -> WeatherSignal:
    """
    Factory function to create a WeatherSignal with computed fields.

    This is the RECOMMENDED way to create signals.
    It handles:
    - UUID generation
    - Timestamp generation
    - Edge calculation
    - Config hash computation

    Args:
        market_id: Polymarket market identifier
        city: City for the weather event
        event_description: Human-readable event description
        market_probability: Current market-implied probability
        fair_probability: Model-estimated fair probability
        confidence: Model confidence level
        recommended_action: BUY or NO_SIGNAL
        config_snapshot: Current configuration dictionary (for hash)
        forecast_source: Optional source of forecast data
        forecast_temperature_f: Optional forecasted temperature in Fahrenheit
        forecast_sigma_f: Optional standard deviation of forecast
        threshold_temperature_f: Optional threshold temperature for the event
        hours_to_resolution: Optional hours until market resolution

    Returns:
        WeatherSignal instance
    """
    # Generate unique signal ID
    signal_id = str(uuid4())

    # Generate timestamp
    timestamp_utc = datetime.utcnow().isoformat() + "Z"

    # Calculate edge
    if market_probability > 0:
        edge = (fair_probability - market_probability) / market_probability
    else:
        edge = 0.0

    # Compute config hash
    config_json = json.dumps(config_snapshot, sort_keys=True)
    parameters_hash = hashlib.sha256(config_json.encode()).hexdigest()

    return WeatherSignal(
        signal_id=signal_id,
        timestamp_utc=timestamp_utc,
        market_id=market_id,
        city=city,
        event_description=event_description,
        market_probability=market_probability,
        fair_probability=fair_probability,
        edge=edge,
        confidence=confidence,
        recommended_action=recommended_action,
        parameters_hash=parameters_hash,
        forecast_source=forecast_source,
        forecast_temperature_f=forecast_temperature_f,
        forecast_sigma_f=forecast_sigma_f,
        threshold_temperature_f=threshold_temperature_f,
        hours_to_resolution=hours_to_resolution,
    )


def create_no_signal(
    market_id: str,
    city: str,
    event_description: str,
    market_probability: float,
    reason: str,
    config_snapshot: Dict[str, Any],
) -> WeatherSignal:
    """
    Factory function to create a NO_SIGNAL response.

    Use this when:
    - Market fails filter criteria
    - Model confidence is too low
    - Edge is insufficient
    - Any uncertainty exists

    The reason is embedded in event_description for audit trail.

    Args:
        market_id: Polymarket market identifier
        city: City for the weather event
        event_description: Original event description
        market_probability: Current market-implied probability
        reason: Reason for NO_SIGNAL (for audit)
        config_snapshot: Current configuration dictionary

    Returns:
        WeatherSignal with NO_SIGNAL action
    """
    return create_weather_signal(
        market_id=market_id,
        city=city,
        event_description=f"{event_description} [NO_SIGNAL: {reason}]",
        market_probability=market_probability,
        fair_probability=0.0,  # Unknown/invalid
        confidence=WeatherConfidence.LOW,
        recommended_action=WeatherSignalAction.NO_SIGNAL,
        config_snapshot=config_snapshot,
    )
