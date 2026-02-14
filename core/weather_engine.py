# =============================================================================
# WEATHER OBSERVER ENGINE
# =============================================================================
#
# OBSERVER-ONLY WEATHER ENGINE
#
# This is the MAIN ORCHESTRATOR for weather market observation.
# It coordinates filtering, forecasting, and probability computation.
#
# CRITICAL PROPERTIES:
# - OBSERVER-ONLY: No trading, no execution, no positions
# - READ-ONLY: Fetches data but does NOT modify anything
# - STATIC: All parameters from config, no adaptive behavior
# - FAIL-CLOSED: Any uncertainty → NO_SIGNAL
#
# WHAT THIS ENGINE DOES:
# 1. Fetch eligible weather markets from data source (READ-ONLY)
# 2. Filter markets via strict criteria
# 3. Fetch external weather forecasts
# 4. Compute probability for each market
# 5. Compare model probability to market odds
# 6. Emit OBSERVE if edge detected, NO_SIGNAL otherwise
#
# WHAT THIS ENGINE DOES NOT DO:
# - Execute trades
# - Recommend positions
# - Modify parameters
# - Learn from outcomes
# - Interface with execution systems
# - Make decisions about position sizing
#
# =============================================================================

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any, List, Callable

import yaml

from .weather_signal import (
    WeatherObservation,
    ObservationAction,
    WeatherConfidence,
    create_observation,
    create_no_signal,
)
from .weather_market_filter import (
    WeatherMarket,
    WeatherMarketFilter,
    FilterResult,
)
from .weather_probability_model import (
    WeatherProbabilityModel,
    ForecastData,
    ProbabilityResult,
    compute_edge,
    meets_edge_threshold,
)
from .ensemble_builder import EnsembleBuilder, EnsembleForecast, degrade_confidence

logger = logging.getLogger(__name__)


# =============================================================================
# TYPE DEFINITIONS
# =============================================================================

# Type alias for market fetcher function
MarketFetcher = Callable[[], List[WeatherMarket]]

# Type alias for forecast fetcher function
ForecastFetcher = Callable[[str, datetime], Optional[ForecastData]]


# =============================================================================
# ENGINE RESULT
# =============================================================================


@dataclass
class EngineRunResult:
    """
    Result of a single engine run.

    Contains:
    - observations: All generated observations (including NO_SIGNAL)
    - edge_observations: Only OBSERVE observations (detected edge)
    - markets_processed: Number of markets evaluated
    - markets_filtered: Number passing filter
    - run_timestamp: When the run occurred
    - run_duration_seconds: How long the run took
    """
    observations: List[WeatherObservation]
    edge_observations: List[WeatherObservation]
    markets_processed: int
    markets_filtered: int
    run_timestamp: str
    run_duration_seconds: float
    config_hash: str

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for logging."""
        return {
            "run_timestamp": self.run_timestamp,
            "run_duration_seconds": self.run_duration_seconds,
            "markets_processed": self.markets_processed,
            "markets_filtered": self.markets_filtered,
            "observations_total": len(self.observations),
            "edge_observations": len(self.edge_observations),
            "config_hash": self.config_hash,
        }


# =============================================================================
# WEATHER ENGINE
# =============================================================================


class WeatherEngine:
    """
    Weather Trading Engine - Main Orchestrator.

    GOVERNANCE PROPERTIES:
    - This engine is ISOLATED from all trading/execution code
    - It produces SIGNALS only, not trades
    - All parameters are STATIC from configuration
    - It has NO MEMORY of past runs
    - Uncertainty → NO_SIGNAL

    PIPELINE:
    1. Fetch markets → List[WeatherMarket]
    2. Filter markets → List[WeatherMarket] (subset)
    3. For each filtered market:
       a. Fetch forecast
       b. Compute probability
       c. Calculate edge
       d. Generate signal
    4. Return List[WeatherObservation]

    NO SIDE EFFECTS (except optional logging).
    """

    VERSION = "1.0.0"

    def __init__(
        self,
        config: Dict[str, Any],
        market_fetcher: Optional[MarketFetcher] = None,
        forecast_fetcher: Optional[ForecastFetcher] = None,
    ):
        """
        Initialize the Weather Engine.

        Args:
            config: Configuration dictionary from weather.yaml
            market_fetcher: Function to fetch weather markets (injectable for testing)
            forecast_fetcher: Function to fetch forecasts (injectable for testing)
        """
        self.config = config
        self._market_fetcher = market_fetcher
        self._forecast_fetcher = forecast_fetcher

        # Initialize components
        self._filter = WeatherMarketFilter(config)
        self._model = WeatherProbabilityModel(config)

        # Initialize ensemble builder
        ensemble_cfg = config.get("ENSEMBLE", {})
        self._ensemble_enabled = ensemble_cfg.get("ENABLED", False)
        self._ensemble_builder = EnsembleBuilder(config) if self._ensemble_enabled else None

        # Extract config parameters
        self.min_edge = config.get("MIN_EDGE", 0.25)
        self.min_edge_absolute = config.get("MIN_EDGE_ABSOLUTE", 0.05)
        self.medium_confidence_multiplier = config.get(
            "MEDIUM_CONFIDENCE_EDGE_MULTIPLIER", 1.5
        )
        self.log_all_observations = config.get("LOG_ALL_OBSERVATIONS", True)
        self.observation_log_path = config.get("OBSERVATION_LOG_PATH", "logs/weather_observations.jsonl")

        # Compute config hash for audit
        config_json = json.dumps(config, sort_keys=True)
        import hashlib
        self._config_hash = hashlib.sha256(config_json.encode()).hexdigest()[:16]

        logger.info(
            f"WeatherEngine initialized | version={self.VERSION} | "
            f"config_hash={self._config_hash}"
        )

    def run(self) -> EngineRunResult:
        """
        Execute the weather observer pipeline.

        This is the MAIN ENTRY POINT.

        Returns:
            EngineRunResult with all observations
        """
        start_time = datetime.now(timezone.utc)
        run_timestamp = start_time.strftime("%Y-%m-%dT%H:%M:%S") + "Z"

        logger.info(f"WeatherObserver run started | timestamp={run_timestamp}")

        observations: List[WeatherObservation] = []

        # =====================================================================
        # STEP 1: Fetch markets
        # =====================================================================
        if self._market_fetcher is None:
            logger.warning("No market fetcher configured - returning empty result")
            return self._create_empty_result(run_timestamp, start_time)

        try:
            markets = self._market_fetcher()
            logger.info(f"Fetched {len(markets)} weather markets")
        except Exception as e:
            logger.error(f"Failed to fetch markets: {e}")
            return self._create_empty_result(run_timestamp, start_time)

        markets_processed = len(markets)

        # =====================================================================
        # STEP 2: Filter markets
        # =====================================================================
        filtered_markets, filter_results = self._filter.filter_markets(markets)
        markets_filtered = len(filtered_markets)

        logger.info(
            f"Filtered markets: {markets_filtered}/{markets_processed} passed"
        )

        # =====================================================================
        # STEP 3: Process each filtered market
        # =====================================================================
        # Reset global forecast timer before processing markets
        try:
            from .multi_forecast import reset_forecast_timer
            reset_forecast_timer()
        except ImportError:
            pass

        for market in filtered_markets:
            observation = self._process_market(market)
            observations.append(observation)

            # Log observation if configured
            if self.log_all_observations or observation.has_edge:
                self._log_observation(observation)

        # =====================================================================
        # STEP 4: Build result
        # =====================================================================
        end_time = datetime.now(timezone.utc)
        duration = (end_time - start_time).total_seconds()

        edge_observations = [o for o in observations if o.has_edge]

        result = EngineRunResult(
            observations=observations,
            edge_observations=edge_observations,
            markets_processed=markets_processed,
            markets_filtered=markets_filtered,
            run_timestamp=run_timestamp,
            run_duration_seconds=duration,
            config_hash=self._config_hash,
        )

        logger.info(
            f"WeatherObserver run complete | duration={duration:.2f}s | "
            f"observations={len(observations)} | with_edge={len(edge_observations)}"
        )

        return result

    def _process_market(self, market: WeatherMarket) -> WeatherObservation:
        """
        Process a single market through the probability pipeline.

        Uses ensemble path when enabled, falls back to single-source.

        Args:
            market: Filtered weather market

        Returns:
            WeatherObservation (OBSERVE or NO_SIGNAL)
        """
        logger.debug(f"Processing market: {market.market_id}")

        city = market.detected_city or "Unknown"

        # Check threshold early (needed for both paths)
        if market.detected_threshold is None:
            return create_no_signal(
                market_id=market.market_id, city=city,
                event_description=market.question,
                market_probability=market.odds_yes,
                reason="No temperature threshold detected",
                config_snapshot=self.config,
            )

        # -----------------------------------------------------------------
        # ENSEMBLE PATH (preferred when enabled)
        # -----------------------------------------------------------------
        if self._ensemble_enabled and self._ensemble_builder is not None:
            ensemble_result = self._try_ensemble(market, city)
            if ensemble_result is not None:
                return ensemble_result
            # Ensemble returned None (0 sources) -> fall through to single-source

        # -----------------------------------------------------------------
        # SINGLE-SOURCE FALLBACK PATH
        # -----------------------------------------------------------------
        return self._process_market_single_source(market, city)

    def _try_ensemble(self, market: WeatherMarket, city: str) -> Optional[WeatherObservation]:
        """
        Try to process market via ensemble. Returns None if ensemble has no data.
        """
        try:
            ensemble = self._ensemble_builder.build(
                city=city,
                target_time=market.resolution_time,
                threshold_f=market.detected_threshold,
                event_type="exceeds",
            )
        except Exception as e:
            logger.warning(f"Ensemble build failed for {market.market_id}: {e}")
            return None

        if ensemble is None:
            return None

        # Use ensemble probability
        fair_prob = ensemble.ensemble_mean_probability

        # Get horizon-based confidence from the probability model
        from datetime import timezone as _tz
        now = datetime.now(_tz.utc).replace(tzinfo=None)
        target_naive = market.resolution_time.replace(tzinfo=None) if market.resolution_time.tzinfo else market.resolution_time
        hours_to_res = max(0, (target_naive - now).total_seconds() / 3600)

        horizon_confidence = self._model._determine_confidence(hours_to_res)

        # Apply ensemble confidence degradation
        confidence = degrade_confidence(horizon_confidence, ensemble.confidence_adjustment)

        if confidence == WeatherConfidence.LOW:
            return create_no_signal(
                market_id=market.market_id, city=city,
                event_description=market.question,
                market_probability=market.odds_yes,
                reason=f"Confidence LOW (ensemble: {ensemble.confidence_adjustment}, "
                       f"sources={ensemble.source_count}, independent={ensemble.independent_model_count})",
                config_snapshot=self.config,
            )

        # Calculate edge
        edge = compute_edge(fair_prob, market.odds_yes)

        edge_ok = meets_edge_threshold(
            edge=edge, min_edge=self.min_edge,
            confidence=confidence,
            medium_confidence_multiplier=self.medium_confidence_multiplier,
        )
        if not edge_ok:
            return create_no_signal(
                market_id=market.market_id, city=city,
                event_description=market.question,
                market_probability=market.odds_yes,
                reason=f"Insufficient edge: {edge:.2%} < required (ensemble, {ensemble.source_count} sources)",
                config_snapshot=self.config,
            )

        absolute_edge = abs(fair_prob - market.odds_yes)
        if absolute_edge < self.min_edge_absolute:
            return create_no_signal(
                market_id=market.market_id, city=city,
                event_description=market.question,
                market_probability=market.odds_yes,
                reason=f"Absolute edge too small: {absolute_edge:.2%} < {self.min_edge_absolute:.0%} (ensemble)",
                config_snapshot=self.config,
            )

        # Compute sigma for logging
        sigma = self._ensemble_builder._calculate_sigma(hours_to_res / 24)

        source_names = ",".join(sf.source_name for sf in ensemble.source_forecasts)

        logger.info(
            f"Ensemble OBSERVE | {city} | sources={ensemble.source_count} "
            f"({source_names}) | P_ensemble={fair_prob:.4f} | "
            f"var={ensemble.ensemble_variance:.4f} | edge={edge:.2%}"
        )

        return create_observation(
            market_id=market.market_id, city=city,
            event_description=market.question,
            market_probability=market.odds_yes,
            model_probability=fair_prob,
            confidence=confidence,
            action=ObservationAction.OBSERVE,
            config_snapshot=self.config,
            forecast_source=f"ensemble({source_names})",
            forecast_temperature_f=ensemble.ensemble_temperature_f,
            forecast_sigma_f=sigma,
            threshold_temperature_f=market.detected_threshold,
            hours_to_resolution=hours_to_res,
            ensemble_source_count=ensemble.source_count,
            ensemble_source_names=source_names,
            ensemble_variance=ensemble.ensemble_variance,
            ensemble_max_deviation=ensemble.max_source_deviation,
        )

    def _process_market_single_source(self, market: WeatherMarket, city: str) -> WeatherObservation:
        """Original single-source processing path (fallback)."""
        if self._forecast_fetcher is None:
            return create_no_signal(
                market_id=market.market_id, city=city,
                event_description=market.question,
                market_probability=market.odds_yes,
                reason="No forecast fetcher configured",
                config_snapshot=self.config,
            )

        try:
            forecast = self._forecast_fetcher(city, market.resolution_time)
        except Exception as e:
            logger.error(f"Forecast fetch failed for {market.market_id}: {e}")
            return create_no_signal(
                market_id=market.market_id, city=city,
                event_description=market.question,
                market_probability=market.odds_yes,
                reason=f"Forecast fetch error: {e}",
                config_snapshot=self.config,
            )

        if forecast is None:
            return create_no_signal(
                market_id=market.market_id, city=city,
                event_description=market.question,
                market_probability=market.odds_yes,
                reason="Forecast data unavailable",
                config_snapshot=self.config,
            )

        try:
            prob_result = self._model.compute_probability(
                forecast=forecast,
                threshold_f=market.detected_threshold,
                event_type="exceeds",
            )
        except Exception as e:
            logger.error(f"Probability computation failed: {e}")
            return create_no_signal(
                market_id=market.market_id, city=city,
                event_description=market.question,
                market_probability=market.odds_yes,
                reason=f"Probability computation error: {e}",
                config_snapshot=self.config,
            )

        if prob_result.confidence == WeatherConfidence.LOW:
            return create_no_signal(
                market_id=market.market_id, city=city,
                event_description=market.question,
                market_probability=market.odds_yes,
                reason="Model confidence is LOW",
                config_snapshot=self.config,
            )

        edge = compute_edge(prob_result.fair_probability, market.odds_yes)

        edge_ok = meets_edge_threshold(
            edge=edge, min_edge=self.min_edge,
            confidence=prob_result.confidence,
            medium_confidence_multiplier=self.medium_confidence_multiplier,
        )
        if not edge_ok:
            return create_no_signal(
                market_id=market.market_id, city=city,
                event_description=market.question,
                market_probability=market.odds_yes,
                reason=f"Insufficient edge: {edge:.2%} < required",
                config_snapshot=self.config,
            )

        absolute_edge = abs(prob_result.fair_probability - market.odds_yes)
        if absolute_edge < self.min_edge_absolute:
            return create_no_signal(
                market_id=market.market_id, city=city,
                event_description=market.question,
                market_probability=market.odds_yes,
                reason=f"Absolute edge too small: {absolute_edge:.2%} < {self.min_edge_absolute:.0%}",
                config_snapshot=self.config,
            )

        return create_observation(
            market_id=market.market_id, city=city,
            event_description=market.question,
            market_probability=market.odds_yes,
            model_probability=prob_result.fair_probability,
            confidence=prob_result.confidence,
            action=ObservationAction.OBSERVE,
            config_snapshot=self.config,
            forecast_source=forecast.source,
            forecast_temperature_f=forecast.temperature_f,
            forecast_sigma_f=prob_result.sigma_used,
            threshold_temperature_f=market.detected_threshold,
            hours_to_resolution=prob_result.hours_to_resolution,
        )

    @staticmethod
    def _rotate_if_needed(filepath, max_size_mb=10):
        """Rotate log file if it exceeds max_size_mb."""
        try:
            filepath = str(filepath)
            if os.path.exists(filepath) and os.path.getsize(filepath) > max_size_mb * 1024 * 1024:
                date_str = datetime.now().strftime("%Y%m%d_%H%M%S")
                base, ext = os.path.splitext(filepath)
                rotated = f"{base}_{date_str}{ext}"
                os.rename(filepath, rotated)
                logger.info(f"Log rotiert: {filepath} -> {rotated}")
        except OSError as e:
            logger.warning(f"Log-Rotation fehlgeschlagen fuer {filepath}: {e}")

    def _log_observation(self, observation: WeatherObservation) -> None:
        """
        Log observation to JSONL file for audit.

        Args:
            observation: Observation to log
        """
        try:
            log_path = Path(self.observation_log_path)
            log_path.parent.mkdir(parents=True, exist_ok=True)

            # Rotate if file exceeds 10 MB
            self._rotate_if_needed(log_path, max_size_mb=10)

            with open(log_path, 'a') as f:
                f.write(observation.to_json() + "\n")

        except Exception as e:
            logger.error(f"Failed to log observation: {e}")

    def _create_empty_result(
        self,
        run_timestamp: str,
        start_time: datetime,
    ) -> EngineRunResult:
        """Create an empty result when engine cannot run."""
        end_time = datetime.now(timezone.utc)
        duration = (end_time - start_time).total_seconds()

        return EngineRunResult(
            observations=[],
            edge_observations=[],
            markets_processed=0,
            markets_filtered=0,
            run_timestamp=run_timestamp,
            run_duration_seconds=duration,
            config_hash=self._config_hash,
        )


# =============================================================================
# FACTORY FUNCTIONS
# =============================================================================


REQUIRED_CONFIG_KEYS = [
    "MIN_EDGE", "MIN_EDGE_ABSOLUTE", "MAX_ODDS", "MIN_ODDS",
    "SIGMA_F", "ALLOWED_CITIES",
]


def validate_config(config: Any) -> None:
    """
    Validate that weather.yaml contains all required keys.

    Raises:
        ValueError: If config is None or missing required keys.
    """
    if config is None:
        raise ValueError("weather.yaml ist leer oder ungueltig")
    errors = []
    for key in REQUIRED_CONFIG_KEYS:
        if key not in config:
            errors.append(f"Fehlender Key: {key}")
    if errors:
        raise ValueError(f"weather.yaml Validierung fehlgeschlagen: {', '.join(errors)}")


def load_config(config_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Load weather engine configuration from YAML file.

    Args:
        config_path: Path to config file. If None, uses default.

    Returns:
        Configuration dictionary

    Raises:
        ValueError: If config is invalid or missing required keys.
    """
    if config_path is None:
        # Default path relative to project root
        config_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "config",
            "weather.yaml"
        )

    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)

    validate_config(config)

    return config


def _default_forecast_fetcher(city: str, target_time: datetime) -> Optional[ForecastData]:
    """
    Default forecast fetcher using multi-source chain.

    Priority: Tomorrow.io -> OpenWeather -> WeatherAPI -> NOAA (US-only).

    Args:
        city: City name
        target_time: Target datetime

    Returns:
        ForecastData or None
    """
    if not city:
        logger.debug("No city provided, skipping forecast fetch")
        return None
    try:
        from .multi_forecast import fetch_forecast_multi
        return fetch_forecast_multi(city, target_time)
    except Exception as e:
        logger.warning(f"Forecast fetch failed for {city}: {e}")
        return None


def create_engine(
    config_path: Optional[str] = None,
    market_fetcher: Optional[MarketFetcher] = None,
    forecast_fetcher: Optional[ForecastFetcher] = None,
) -> WeatherEngine:
    """
    Create a configured WeatherEngine instance.

    This is the RECOMMENDED way to instantiate the engine.
    If no forecast_fetcher is provided, uses multi-source chain as default.

    Args:
        config_path: Path to weather.yaml. If None, uses default.
        market_fetcher: Function to fetch markets
        forecast_fetcher: Function to fetch forecasts (default: multi-source)

    Returns:
        Configured WeatherEngine
    """
    config = load_config(config_path)

    # Use multi-source chain as default forecast fetcher
    if forecast_fetcher is None:
        forecast_fetcher = _default_forecast_fetcher

    return WeatherEngine(
        config=config,
        market_fetcher=market_fetcher,
        forecast_fetcher=forecast_fetcher,
    )


# =============================================================================
# ISOLATION VERIFICATION
# =============================================================================
#
# This section explicitly documents what this module does NOT import.
# If any of these imports exist, it's a governance violation.
#
# FORBIDDEN IMPORTS:
# - core.panic_contrarian_engine
# - core.execution_engine
# - core.decision_engine
# - paper_trader.*
# - Any learning/ML modules
#
# VERIFICATION:
# Run: grep -n "import.*panic\|import.*execution\|import.*decision\|import.*trader" core/weather_engine.py
# Expected: No results
#
# =============================================================================
