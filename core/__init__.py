# =============================================================================
# WEATHER OBSERVER - CORE MODULE
# =============================================================================
#
# Weather-only observation system.
# No trading, no execution, no positions.
#
# MODULES:
# - weather_engine: Main observation orchestrator
# - weather_signal: Observation data model (OBSERVE/NO_SIGNAL)
# - weather_probability_model: Forecast to probability conversion
# - weather_market_filter: Market eligibility filtering
# - weather_validation: 6-point validation checklist
# - weather_analyzer: Structural validation
# - noaa_client: NOAA forecast API
# - outcome_tracker: Resolution tracking
# - calibration_engine: Analytics (read-only)
#
# =============================================================================

from .weather_signal import (
    WeatherObservation,
    ObservationAction,
    WeatherConfidence,
    create_observation,
    create_no_signal,
)
from .weather_engine import (
    WeatherEngine,
    EngineRunResult,
    create_engine,
    load_config,
)

__all__ = [
    "WeatherObservation",
    "ObservationAction",
    "WeatherConfidence",
    "create_observation",
    "create_no_signal",
    "WeatherEngine",
    "EngineRunResult",
    "create_engine",
    "load_config",
]
