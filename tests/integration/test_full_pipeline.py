"""
INTEGRATION TESTS - FULL PIPELINE
==================================
End-to-end Tests fuer das Weather Engine System.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import tempfile
import os
from datetime import datetime, timedelta
from typing import List, Tuple, Callable, Optional

from core.weather_engine import WeatherEngine, EngineRunResult
from core.weather_market_filter import WeatherMarket, WeatherMarketFilter
from core.weather_probability_model import WeatherProbabilityModel, ForecastData
from core.weather_signal import (
    WeatherSignal,
    WeatherSignalAction,
    WeatherConfidence,
    create_weather_signal,
)
from shared.module_loader import ModuleConfig


# =============================================================================
# TEST CONFIGURATION
# =============================================================================

FULL_CONFIG = {
    "MIN_LIQUIDITY": 50,
    "MIN_ODDS": 0.01,
    "MAX_ODDS": 0.10,
    "MIN_TIME_TO_RESOLUTION_HOURS": 48,
    "SAFETY_BUFFER_HOURS": 48,
    "ALLOWED_CITIES": ["New York", "London", "Seoul", "Tokyo", "Chicago", "Miami"],
    "SIGMA_F": 3.5,
    "MAX_FORECAST_HORIZON_DAYS": 10,
    "MIN_EDGE": 0.25,
    "MEDIUM_CONFIDENCE_EDGE_MULTIPLIER": 1.5,
    "LOG_ALL_SIGNALS": False,
    "CONFIDENCE_THRESHOLDS": {
        "HIGH_CONFIDENCE_MAX_HOURS": 72,
        "MEDIUM_CONFIDENCE_MAX_HOURS": 168,
    },
    "SIGMA_HORIZON_ADJUSTMENTS": {1: 0.8, 2: 0.9, 3: 1.0, 5: 1.2, 7: 1.5, 10: 2.0},
}


# =============================================================================
# TEST FUNCTIONS
# =============================================================================

def test_filter_to_model_pipeline():
    """Test pipeline from filter output to probability model."""
    # Create filter
    filter_instance = WeatherMarketFilter(FULL_CONFIG)

    # Create market that passes filter
    market = WeatherMarket(
        market_id="pipe-001",
        question="Will New York temperature exceed 100°F on Jan 30?",
        resolution_text="Resolves YES if temperature in New York exceeds 100°F",
        description="Weather prediction market for New York",
        category="WEATHER",
        is_binary=True,
        liquidity_usd=150.0,
        odds_yes=0.04,
        resolution_time=datetime.utcnow() + timedelta(hours=72),
    )

    # Run through filter
    result = filter_instance.filter_market(market)

    assert result.passed is True
    assert result.market.detected_city == "New York"
    assert result.market.detected_threshold is not None

    # Create model and compute probability
    model = WeatherProbabilityModel(FULL_CONFIG)

    forecast = ForecastData(
        city=result.market.detected_city,
        forecast_time=datetime.utcnow(),
        target_time=market.resolution_time,
        temperature_f=105.0,  # Higher than threshold
        source="integration_test",
    )

    prob_result = model.compute_probability(
        forecast=forecast,
        threshold_f=result.market.detected_threshold,
        event_type="exceeds",
    )

    assert prob_result.fair_probability > 0
    assert prob_result.confidence in [WeatherConfidence.HIGH, WeatherConfidence.MEDIUM]


def test_full_engine_pipeline():
    """Test complete engine pipeline end-to-end."""
    markets = [
        WeatherMarket(
            market_id="full-001",
            question="Will New York temperature exceed 100°F?",
            resolution_text="Resolves YES if temperature exceeds 100°F in NYC",
            description="NYC weather market",
            category="WEATHER",
            is_binary=True,
            liquidity_usd=200.0,
            odds_yes=0.03,  # Low market probability
            resolution_time=datetime.utcnow() + timedelta(hours=60),
        ),
        WeatherMarket(
            market_id="full-002",
            question="Will London temperature exceed 30°C?",
            resolution_text="Resolves YES if temperature exceeds 30°C in London",
            description="London weather market",
            category="WEATHER",
            is_binary=True,
            liquidity_usd=150.0,
            odds_yes=0.05,
            resolution_time=datetime.utcnow() + timedelta(hours=72),
        ),
    ]

    def market_fetcher():
        return markets

    def forecast_fetcher(city: str, res_time: datetime) -> Optional[ForecastData]:
        # Return high temperature forecasts for strong signal
        return ForecastData(
            city=city,
            forecast_time=datetime.utcnow(),
            target_time=res_time,
            temperature_f=110.0,  # Much higher than thresholds
            source="integration_test",
        )

    engine = WeatherEngine(
        config=FULL_CONFIG,
        market_fetcher=market_fetcher,
        forecast_fetcher=forecast_fetcher,
    )

    result = engine.run()

    assert isinstance(result, EngineRunResult)
    assert result.markets_processed == 2
    assert result.run_duration_seconds >= 0
    assert len(result.signals) > 0


def test_signal_generation_consistency():
    """Test that signal generation is consistent."""
    config = FULL_CONFIG.copy()

    # Create identical markets
    market1 = WeatherMarket(
        market_id="consist-001",
        question="Will New York temperature exceed 100°F?",
        resolution_text="Resolves YES if > 100°F",
        description="Weather market",
        category="WEATHER",
        is_binary=True,
        liquidity_usd=100.0,
        odds_yes=0.03,
        resolution_time=datetime.utcnow() + timedelta(hours=72),
    )

    market2 = WeatherMarket(
        market_id="consist-002",
        question="Will New York temperature exceed 100°F?",
        resolution_text="Resolves YES if > 100°F",
        description="Weather market",
        category="WEATHER",
        is_binary=True,
        liquidity_usd=100.0,
        odds_yes=0.03,
        resolution_time=datetime.utcnow() + timedelta(hours=72),
    )

    # Filter should produce same results
    filter_instance = WeatherMarketFilter(config)

    result1 = filter_instance.filter_market(market1)
    result2 = filter_instance.filter_market(market2)

    assert result1.passed == result2.passed
    if result1.passed:
        assert result1.market.detected_city == result2.market.detected_city
        assert result1.market.detected_threshold == result2.market.detected_threshold


def test_edge_calculation_integration():
    """Test edge calculation through the full pipeline."""
    # Setup market with known probabilities
    market_prob = 0.03  # 3%

    markets = [
        WeatherMarket(
            market_id="edge-001",
            question="Will Miami temperature exceed 95°F?",
            resolution_text="Resolves YES if > 95°F in Miami",
            description="Miami weather",
            category="WEATHER",
            is_binary=True,
            liquidity_usd=100.0,
            odds_yes=market_prob,
            resolution_time=datetime.utcnow() + timedelta(hours=60),
        ),
    ]

    def market_fetcher():
        return markets

    # Forecast that gives high probability of exceeding threshold
    def forecast_fetcher(city: str, res_time: datetime) -> Optional[ForecastData]:
        return ForecastData(
            city=city,
            forecast_time=datetime.utcnow(),
            target_time=res_time,
            temperature_f=100.0,  # 5°F above threshold
            source="integration_test",
        )

    engine = WeatherEngine(
        config=FULL_CONFIG,
        market_fetcher=market_fetcher,
        forecast_fetcher=forecast_fetcher,
    )

    result = engine.run()

    # Should process the market
    assert result.markets_processed == 1

    # If there are actionable signals, check edge
    for signal in result.actionable_signals:
        assert signal.edge > 0
        assert signal.market_probability == market_prob


def test_multi_city_integration():
    """Test handling markets from multiple cities."""
    cities = ["New York", "London", "Tokyo", "Chicago"]

    markets = []
    for i, city in enumerate(cities):
        markets.append(WeatherMarket(
            market_id=f"multi-{i:03d}",
            question=f"Will {city} temperature exceed 90°F?",
            resolution_text=f"Resolves YES if > 90°F in {city}",
            description=f"{city} weather market",
            category="WEATHER",
            is_binary=True,
            liquidity_usd=100.0,
            odds_yes=0.04,
            resolution_time=datetime.utcnow() + timedelta(hours=72),
        ))

    def market_fetcher():
        return markets

    def forecast_fetcher(city: str, res_time: datetime) -> Optional[ForecastData]:
        return ForecastData(
            city=city,
            forecast_time=datetime.utcnow(),
            target_time=res_time,
            temperature_f=95.0,
            source="integration_test",
        )

    engine = WeatherEngine(
        config=FULL_CONFIG,
        market_fetcher=market_fetcher,
        forecast_fetcher=forecast_fetcher,
    )

    result = engine.run()

    assert result.markets_processed == 4
    assert result.markets_filtered >= 0


def test_module_config_integration():
    """Test module config integration with engine."""
    config_yaml = """
global:
  master_enabled: true
  pipeline_interval: 900

weather_engine:
  enabled: true
  description: "Weather Engine"
  interval_seconds: 3600
  priority: 10
  category: "ENGINE"
"""

    # Create temp config file
    fd, path = tempfile.mkstemp(suffix=".yaml")
    with os.fdopen(fd, 'w') as f:
        f.write(config_yaml)

    try:
        config = ModuleConfig(Path(path))

        assert config.is_enabled("weather_engine") is True

        module = config.get_module("weather_engine")
        assert module.category == "ENGINE"
    finally:
        os.unlink(path)


def test_signal_serialization_roundtrip():
    """Test signal can be serialized and contains all data."""
    signal = create_weather_signal(
        market_id="serial-001",
        city="New York",
        event_description="Temperature test",
        market_probability=0.04,
        fair_probability=0.10,
        confidence=WeatherConfidence.HIGH,
        recommended_action=WeatherSignalAction.BUY,
        config_snapshot=FULL_CONFIG,
        forecast_source="test",
        forecast_temperature_f=105.0,
        forecast_sigma_f=3.5,
        threshold_temperature_f=100.0,
        hours_to_resolution=48.0,
    )

    # Serialize to dict
    d = signal.to_dict()

    # Check all important fields are present
    assert d["market_id"] == "serial-001"
    assert d["city"] == "New York"
    assert d["market_probability"] == 0.04
    assert d["fair_probability"] == 0.10
    assert d["edge"] > 0
    assert d["confidence"] == "HIGH"
    assert d["recommended_action"] == "BUY"

    # Serialize to JSON
    json_str = signal.to_json()
    assert "serial-001" in json_str
    assert "New York" in json_str


def test_filter_rejection_cascade():
    """Test that multiple filter rejections are tracked."""
    filter_instance = WeatherMarketFilter(FULL_CONFIG)

    # Create market that fails multiple criteria
    bad_market = WeatherMarket(
        market_id="bad-001",
        question="Will it be hot?",  # No city, no threshold
        resolution_text="Maybe",     # Vague
        description="General market",
        category="SPORTS",           # Wrong category
        is_binary=False,             # Not binary
        liquidity_usd=10.0,          # Too low
        odds_yes=0.50,               # Too high
        resolution_time=datetime.utcnow() + timedelta(hours=12),  # Too soon
    )

    result = filter_instance.filter_market(bad_market)

    assert result.passed is False
    assert len(result.rejection_reasons) >= 3


def test_probability_model_edge_cases():
    """Test probability model with edge case inputs."""
    model = WeatherProbabilityModel(FULL_CONFIG)

    # Test with temperature exactly at threshold
    forecast = ForecastData(
        city="New York",
        forecast_time=datetime.utcnow(),
        target_time=datetime.utcnow() + timedelta(hours=48),
        temperature_f=100.0,
        source="test",
    )

    result = model.compute_probability(forecast, threshold_f=100.0, event_type="exceeds")

    # P(X > 100 | mean=100) should be ~0.5
    assert 0.4 < result.fair_probability < 0.6


def test_concurrent_engine_runs():
    """Test multiple engine instances don't interfere."""
    config1 = FULL_CONFIG.copy()
    config1["MIN_EDGE"] = 0.20

    config2 = FULL_CONFIG.copy()
    config2["MIN_EDGE"] = 0.50

    engine1 = WeatherEngine(config1)
    engine2 = WeatherEngine(config2)

    # Different configs should produce different hashes
    assert engine1._config_hash != engine2._config_hash

    # Both should run without error
    result1 = engine1.run()
    result2 = engine2.run()

    assert result1.config_hash != result2.config_hash


# =============================================================================
# TEST REGISTRY
# =============================================================================

def get_tests() -> List[Tuple[str, Callable]]:
    """Return list of all tests."""
    return [
        ("filter_to_model_pipeline", test_filter_to_model_pipeline),
        ("full_engine_pipeline", test_full_engine_pipeline),
        ("signal_generation_consistency", test_signal_generation_consistency),
        ("edge_calculation_integration", test_edge_calculation_integration),
        ("multi_city_integration", test_multi_city_integration),
        ("module_config_integration", test_module_config_integration),
        ("signal_serialization_roundtrip", test_signal_serialization_roundtrip),
        ("filter_rejection_cascade", test_filter_rejection_cascade),
        ("probability_model_edge_cases", test_probability_model_edge_cases),
        ("concurrent_engine_runs", test_concurrent_engine_runs),
    ]
