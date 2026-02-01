# =============================================================================
# POLYMARKET BEOBACHTER - WEATHER TRADING ENGINE
# =============================================================================
#
# GOVERNANCE-FIRST WEATHER ENGINE
#
# This is the MAIN ORCHESTRATOR for weather-based signal generation.
# It coordinates filtering, forecasting, and probability computation.
#
# CRITICAL PROPERTIES:
# - ISOLATED: No imports from panic, execution, learning, or trading modules
# - READ-ONLY: Fetches data but does NOT modify anything
# - SIGNAL-ONLY: Output is WeatherSignal, not trades
# - STATIC: All parameters from config, no adaptive behavior
# - FAIL-CLOSED: Any uncertainty → NO_SIGNAL
#
# WHAT THIS ENGINE DOES:
# 1. Fetch eligible weather markets from data source (READ-ONLY)
# 2. Filter markets via strict criteria
# 3. Fetch external weather forecasts
# 4. Compute fair probability for each market
# 5. Compare to market odds
# 6. Emit signal ONLY if edge is significant
#
# WHAT THIS ENGINE DOES NOT DO:
# - Execute trades
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
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List, Callable

import yaml

from .weather_signal import (
    WeatherSignal,
    WeatherSignalAction,
    WeatherConfidence,
    create_weather_signal,
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
    - signals: All generated signals (including NO_SIGNAL)
    - actionable_signals: Only BUY signals
    - markets_processed: Number of markets evaluated
    - markets_filtered: Number passing filter
    - run_timestamp: When the run occurred
    - run_duration_seconds: How long the run took
    """
    signals: List[WeatherSignal]
    actionable_signals: List[WeatherSignal]
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
            "signals_total": len(self.signals),
            "signals_actionable": len(self.actionable_signals),
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
    4. Return List[WeatherSignal]

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

        # Extract config parameters
        self.min_edge = config.get("MIN_EDGE", 0.25)
        self.medium_confidence_multiplier = config.get(
            "MEDIUM_CONFIDENCE_EDGE_MULTIPLIER", 1.5
        )
        self.log_all_signals = config.get("LOG_ALL_SIGNALS", True)
        self.signal_log_path = config.get("SIGNAL_LOG_PATH", "logs/weather_signals.jsonl")

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
        Execute the weather engine pipeline.

        This is the MAIN ENTRY POINT.

        Returns:
            EngineRunResult with all generated signals
        """
        start_time = datetime.utcnow()
        run_timestamp = start_time.isoformat() + "Z"

        logger.info(f"WeatherEngine run started | timestamp={run_timestamp}")

        signals: List[WeatherSignal] = []

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
        for market in filtered_markets:
            signal = self._process_market(market)
            signals.append(signal)

            # Log signal if configured
            if self.log_all_signals or signal.is_actionable:
                self._log_signal(signal)

        # =====================================================================
        # STEP 4: Build result
        # =====================================================================
        end_time = datetime.utcnow()
        duration = (end_time - start_time).total_seconds()

        actionable_signals = [s for s in signals if s.is_actionable]

        result = EngineRunResult(
            signals=signals,
            actionable_signals=actionable_signals,
            markets_processed=markets_processed,
            markets_filtered=markets_filtered,
            run_timestamp=run_timestamp,
            run_duration_seconds=duration,
            config_hash=self._config_hash,
        )

        logger.info(
            f"WeatherEngine run complete | duration={duration:.2f}s | "
            f"signals={len(signals)} | actionable={len(actionable_signals)}"
        )

        return result

    def _process_market(self, market: WeatherMarket) -> WeatherSignal:
        """
        Process a single market through the probability pipeline.

        Args:
            market: Filtered weather market

        Returns:
            WeatherSignal (BUY or NO_SIGNAL)
        """
        logger.debug(f"Processing market: {market.market_id}")

        # -----------------------------------------------------------------
        # STEP A: Fetch forecast
        # -----------------------------------------------------------------
        if self._forecast_fetcher is None:
            logger.warning(
                f"No forecast fetcher for market {market.market_id}"
            )
            return create_no_signal(
                market_id=market.market_id,
                city=market.detected_city or "Unknown",
                event_description=market.question,
                market_probability=market.odds_yes,
                reason="No forecast fetcher configured",
                config_snapshot=self.config,
            )

        try:
            forecast = self._forecast_fetcher(
                market.detected_city, market.resolution_time
            )
        except Exception as e:
            logger.error(f"Forecast fetch failed for {market.market_id}: {e}")
            return create_no_signal(
                market_id=market.market_id,
                city=market.detected_city or "Unknown",
                event_description=market.question,
                market_probability=market.odds_yes,
                reason=f"Forecast fetch error: {e}",
                config_snapshot=self.config,
            )

        if forecast is None:
            return create_no_signal(
                market_id=market.market_id,
                city=market.detected_city or "Unknown",
                event_description=market.question,
                market_probability=market.odds_yes,
                reason="Forecast data unavailable",
                config_snapshot=self.config,
            )

        # -----------------------------------------------------------------
        # STEP B: Compute probability
        # -----------------------------------------------------------------
        if market.detected_threshold is None:
            return create_no_signal(
                market_id=market.market_id,
                city=market.detected_city or "Unknown",
                event_description=market.question,
                market_probability=market.odds_yes,
                reason="No temperature threshold detected",
                config_snapshot=self.config,
            )

        try:
            prob_result = self._model.compute_probability(
                forecast=forecast,
                threshold_f=market.detected_threshold,
                event_type="exceeds",  # Default to "exceeds" for temperature markets
            )
        except Exception as e:
            logger.error(f"Probability computation failed: {e}")
            return create_no_signal(
                market_id=market.market_id,
                city=market.detected_city or "Unknown",
                event_description=market.question,
                market_probability=market.odds_yes,
                reason=f"Probability computation error: {e}",
                config_snapshot=self.config,
            )

        # -----------------------------------------------------------------
        # STEP C: Check confidence
        # -----------------------------------------------------------------
        if prob_result.confidence == WeatherConfidence.LOW:
            return create_no_signal(
                market_id=market.market_id,
                city=market.detected_city or "Unknown",
                event_description=market.question,
                market_probability=market.odds_yes,
                reason="Model confidence is LOW",
                config_snapshot=self.config,
            )

        # -----------------------------------------------------------------
        # STEP D: Calculate edge
        # -----------------------------------------------------------------
        edge = compute_edge(
            fair_probability=prob_result.fair_probability,
            market_probability=market.odds_yes,
        )

        # -----------------------------------------------------------------
        # STEP E: Check edge threshold
        # -----------------------------------------------------------------
        edge_meets_threshold = meets_edge_threshold(
            edge=edge,
            min_edge=self.min_edge,
            confidence=prob_result.confidence,
            medium_confidence_multiplier=self.medium_confidence_multiplier,
        )

        if not edge_meets_threshold:
            return create_no_signal(
                market_id=market.market_id,
                city=market.detected_city or "Unknown",
                event_description=market.question,
                market_probability=market.odds_yes,
                reason=f"Insufficient edge: {edge:.2%} < required",
                config_snapshot=self.config,
            )

        # -----------------------------------------------------------------
        # STEP F: Generate BUY signal
        # -----------------------------------------------------------------
        return create_weather_signal(
            market_id=market.market_id,
            city=market.detected_city or "Unknown",
            event_description=market.question,
            market_probability=market.odds_yes,
            fair_probability=prob_result.fair_probability,
            confidence=prob_result.confidence,
            recommended_action=WeatherSignalAction.BUY,
            config_snapshot=self.config,
            forecast_source=forecast.source,
            forecast_temperature_f=forecast.temperature_f,
            forecast_sigma_f=prob_result.sigma_used,
            threshold_temperature_f=market.detected_threshold,
            hours_to_resolution=prob_result.hours_to_resolution,
        )

    def _log_signal(self, signal: WeatherSignal) -> None:
        """
        Log signal to JSONL file for audit.

        Args:
            signal: Signal to log
        """
        try:
            log_path = Path(self.signal_log_path)
            log_path.parent.mkdir(parents=True, exist_ok=True)

            with open(log_path, 'a') as f:
                f.write(signal.to_json() + "\n")

        except Exception as e:
            logger.error(f"Failed to log signal: {e}")

    def _create_empty_result(
        self,
        run_timestamp: str,
        start_time: datetime,
    ) -> EngineRunResult:
        """Create an empty result when engine cannot run."""
        end_time = datetime.utcnow()
        duration = (end_time - start_time).total_seconds()

        return EngineRunResult(
            signals=[],
            actionable_signals=[],
            markets_processed=0,
            markets_filtered=0,
            run_timestamp=run_timestamp,
            run_duration_seconds=duration,
            config_hash=self._config_hash,
        )


# =============================================================================
# FACTORY FUNCTIONS
# =============================================================================


def load_config(config_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Load weather engine configuration from YAML file.

    Args:
        config_path: Path to config file. If None, uses default.

    Returns:
        Configuration dictionary
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

    return config


def _default_forecast_fetcher(city: str, target_time: datetime) -> Optional[ForecastData]:
    """
    Default forecast fetcher using NOAA API.

    Args:
        city: City name
        target_time: Target datetime

    Returns:
        ForecastData or None
    """
    try:
        from .noaa_client import fetch_forecast_for_city
        return fetch_forecast_for_city(city, target_time)
    except Exception as e:
        logger.warning(f"NOAA forecast fetch failed for {city}: {e}")
        return None


def create_engine(
    config_path: Optional[str] = None,
    market_fetcher: Optional[MarketFetcher] = None,
    forecast_fetcher: Optional[ForecastFetcher] = None,
) -> WeatherEngine:
    """
    Create a configured WeatherEngine instance.

    This is the RECOMMENDED way to instantiate the engine.
    If no forecast_fetcher is provided, uses NOAA API as default.

    Args:
        config_path: Path to weather.yaml. If None, uses default.
        market_fetcher: Function to fetch markets
        forecast_fetcher: Function to fetch forecasts (default: NOAA API)

    Returns:
        Configured WeatherEngine
    """
    config = load_config(config_path)

    # Use NOAA as default forecast fetcher
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
