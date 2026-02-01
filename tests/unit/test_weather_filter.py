"""
UNIT TESTS - WEATHER MARKET FILTER
===================================
Intensive Tests fuer core/weather_market_filter.py
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from datetime import datetime, timedelta
from typing import List, Tuple, Callable

from core.weather_market_filter import (
    WeatherMarket,
    FilterResult,
    WeatherMarketFilter,
)


# =============================================================================
# TEST FIXTURES
# =============================================================================

def create_test_config():
    """Create standard test configuration."""
    return {
        "MIN_LIQUIDITY": 50,
        "MIN_ODDS": 0.01,
        "MAX_ODDS": 0.10,
        "MIN_TIME_TO_RESOLUTION_HOURS": 48,
        "SAFETY_BUFFER_HOURS": 48,
        "ALLOWED_CITIES": ["New York", "London", "Seoul", "Tokyo", "Chicago"],
    }


def create_valid_market(
    market_id: str = "test-market-001",
    city: str = "New York",
    threshold: str = "100°F",
):
    """Create a market that should pass all filters."""
    return WeatherMarket(
        market_id=market_id,
        question=f"Will {city} temperature exceed {threshold} tomorrow?",
        resolution_text=f"Resolves YES if temperature in {city} exceeds {threshold}",
        description=f"Weather prediction market for {city}",
        category="WEATHER",
        is_binary=True,
        liquidity_usd=100.0,
        odds_yes=0.05,
        resolution_time=datetime.utcnow() + timedelta(hours=72),
    )


# =============================================================================
# TEST FUNCTIONS
# =============================================================================

def test_filter_initialization():
    """Test filter initializes with correct config values."""
    config = create_test_config()
    f = WeatherMarketFilter(config)

    assert f.min_liquidity == 50
    assert f.min_odds == 0.01
    assert f.max_odds == 0.10
    assert f.min_time_to_resolution_hours == 48
    assert "New York" in f.allowed_cities


def test_valid_market_passes():
    """Test that a valid market passes all filters."""
    config = create_test_config()
    f = WeatherMarketFilter(config)
    market = create_valid_market()

    result = f.filter_market(market)

    assert result.passed is True
    assert len(result.rejection_reasons) == 0
    assert result.market is not None
    assert result.market.detected_city == "New York"


def test_filter_rejects_non_weather():
    """Test rejection of non-weather markets."""
    config = create_test_config()
    f = WeatherMarketFilter(config)

    market = WeatherMarket(
        market_id="non-weather-001",
        question="Will Bitcoin reach $100k?",
        resolution_text="Resolves YES if BTC/USD >= 100000",
        description="Crypto prediction market",
        category="CRYPTO",
        is_binary=True,
        liquidity_usd=100.0,
        odds_yes=0.05,
        resolution_time=datetime.utcnow() + timedelta(hours=72),
    )

    result = f.filter_market(market)

    assert result.passed is False
    assert any("CATEGORY" in r for r in result.rejection_reasons)


def test_filter_rejects_non_binary():
    """Test rejection of non-binary markets."""
    config = create_test_config()
    f = WeatherMarketFilter(config)

    market = create_valid_market()
    market = WeatherMarket(
        market_id=market.market_id,
        question=market.question,
        resolution_text=market.resolution_text,
        description=market.description,
        category=market.category,
        is_binary=False,  # Non-binary!
        liquidity_usd=market.liquidity_usd,
        odds_yes=market.odds_yes,
        resolution_time=market.resolution_time,
    )

    result = f.filter_market(market)

    assert result.passed is False
    assert any("BINARY" in r for r in result.rejection_reasons)


def test_filter_rejects_low_liquidity():
    """Test rejection of low liquidity markets."""
    config = create_test_config()
    f = WeatherMarketFilter(config)

    market = WeatherMarket(
        market_id="low-liq-001",
        question="Will New York temperature exceed 100°F?",
        resolution_text="Resolves YES if temperature exceeds 100°F",
        description="Weather market",
        category="WEATHER",
        is_binary=True,
        liquidity_usd=10.0,  # Below minimum of 50
        odds_yes=0.05,
        resolution_time=datetime.utcnow() + timedelta(hours=72),
    )

    result = f.filter_market(market)

    assert result.passed is False
    assert any("LIQUIDITY" in r for r in result.rejection_reasons)


def test_filter_rejects_odds_too_low():
    """Test rejection when odds are below minimum."""
    config = create_test_config()
    f = WeatherMarketFilter(config)

    market = WeatherMarket(
        market_id="low-odds-001",
        question="Will New York temperature exceed 100°F?",
        resolution_text="Resolves YES if temperature exceeds 100°F",
        description="Weather market",
        category="WEATHER",
        is_binary=True,
        liquidity_usd=100.0,
        odds_yes=0.005,  # Below minimum of 0.01
        resolution_time=datetime.utcnow() + timedelta(hours=72),
    )

    result = f.filter_market(market)

    assert result.passed is False
    assert any("ODDS" in r for r in result.rejection_reasons)


def test_filter_rejects_odds_too_high():
    """Test rejection when odds are above maximum."""
    config = create_test_config()
    f = WeatherMarketFilter(config)

    market = WeatherMarket(
        market_id="high-odds-001",
        question="Will New York temperature exceed 100°F?",
        resolution_text="Resolves YES if temperature exceeds 100°F",
        description="Weather market",
        category="WEATHER",
        is_binary=True,
        liquidity_usd=100.0,
        odds_yes=0.50,  # Above maximum of 0.10
        resolution_time=datetime.utcnow() + timedelta(hours=72),
    )

    result = f.filter_market(market)

    assert result.passed is False
    assert any("ODDS" in r for r in result.rejection_reasons)


def test_filter_rejects_too_soon():
    """Test rejection when resolution is too soon."""
    config = create_test_config()
    f = WeatherMarketFilter(config)

    market = WeatherMarket(
        market_id="soon-001",
        question="Will New York temperature exceed 100°F?",
        resolution_text="Resolves YES if temperature exceeds 100°F",
        description="Weather market",
        category="WEATHER",
        is_binary=True,
        liquidity_usd=100.0,
        odds_yes=0.05,
        resolution_time=datetime.utcnow() + timedelta(hours=12),  # Only 12h, needs 48h
    )

    result = f.filter_market(market)

    assert result.passed is False
    assert any("TIME" in r for r in result.rejection_reasons)


def test_filter_rejects_unknown_city():
    """Test rejection when city is not in allowed list."""
    config = create_test_config()
    f = WeatherMarketFilter(config)

    market = WeatherMarket(
        market_id="unknown-city-001",
        question="Will Berlin temperature exceed 35°C?",
        resolution_text="Resolves YES if temperature exceeds 35°C",
        description="Weather market for Berlin",
        category="WEATHER",
        is_binary=True,
        liquidity_usd=100.0,
        odds_yes=0.05,
        resolution_time=datetime.utcnow() + timedelta(hours=72),
    )

    result = f.filter_market(market)

    assert result.passed is False
    assert any("CITY" in r for r in result.rejection_reasons)


def test_filter_rejects_no_city():
    """Test rejection when no city can be detected."""
    config = create_test_config()
    f = WeatherMarketFilter(config)

    market = WeatherMarket(
        market_id="no-city-001",
        question="Will temperature exceed 100°F somewhere?",
        resolution_text="Resolves YES if temperature exceeds 100°F",
        description="Weather market",
        category="WEATHER",
        is_binary=True,
        liquidity_usd=100.0,
        odds_yes=0.05,
        resolution_time=datetime.utcnow() + timedelta(hours=72),
    )

    result = f.filter_market(market)

    assert result.passed is False
    assert any("CITY" in r for r in result.rejection_reasons)


def test_filter_rejects_vague_resolution():
    """Test rejection when resolution contains vague terms."""
    config = create_test_config()
    f = WeatherMarketFilter(config)

    market = WeatherMarket(
        market_id="vague-001",
        question="Will New York have extreme heat?",
        resolution_text="Resolves YES if there is significant heat in New York",
        description="Weather market with vague terms",
        category="WEATHER",
        is_binary=True,
        liquidity_usd=100.0,
        odds_yes=0.05,
        resolution_time=datetime.utcnow() + timedelta(hours=72),
    )

    result = f.filter_market(market)

    assert result.passed is False
    assert any("RESOLUTION" in r for r in result.rejection_reasons)


def test_filter_rejects_no_threshold():
    """Test rejection when no numeric threshold is found."""
    config = create_test_config()
    f = WeatherMarketFilter(config)

    market = WeatherMarket(
        market_id="no-thresh-001",
        question="Will New York be hot tomorrow?",
        resolution_text="Resolves YES if it's hot in New York",
        description="Weather market without threshold",
        category="WEATHER",
        is_binary=True,
        liquidity_usd=100.0,
        odds_yes=0.05,
        resolution_time=datetime.utcnow() + timedelta(hours=72),
    )

    result = f.filter_market(market)

    assert result.passed is False
    assert any("RESOLUTION" in r for r in result.rejection_reasons)


def test_city_detection_aliases():
    """Test city detection with various aliases."""
    config = create_test_config()
    f = WeatherMarketFilter(config)

    # NYC alias
    market1 = WeatherMarket(
        market_id="alias-001",
        question="Will NYC temperature exceed 100°F?",
        resolution_text="Resolves YES if temperature exceeds 100°F",
        description="Weather market",
        category="WEATHER",
        is_binary=True,
        liquidity_usd=100.0,
        odds_yes=0.05,
        resolution_time=datetime.utcnow() + timedelta(hours=72),
    )

    result1 = f.filter_market(market1)
    assert result1.passed is True
    assert result1.market.detected_city == "New York"


def test_temperature_celsius_conversion():
    """Test temperature threshold detection in Celsius."""
    config = create_test_config()
    f = WeatherMarketFilter(config)

    market = WeatherMarket(
        market_id="celsius-001",
        question="Will London temperature exceed 30°C?",
        resolution_text="Resolves YES if temperature exceeds 30°C",
        description="Weather market",
        category="WEATHER",
        is_binary=True,
        liquidity_usd=100.0,
        odds_yes=0.05,
        resolution_time=datetime.utcnow() + timedelta(hours=72),
    )

    result = f.filter_market(market)

    assert result.passed is True
    # 30°C = 86°F
    assert result.market.detected_threshold is not None
    assert abs(result.market.detected_threshold - 86.0) < 1.0


def test_filter_markets_batch():
    """Test filtering multiple markets at once."""
    config = create_test_config()
    f = WeatherMarketFilter(config)

    markets = [
        create_valid_market("m1", "New York", "100°F"),
        create_valid_market("m2", "London", "30°C"),
        WeatherMarket(  # Invalid - low liquidity
            market_id="m3",
            question="Will Tokyo temperature exceed 35°C?",
            resolution_text="Resolves YES if > 35°C",
            description="Weather market",
            category="WEATHER",
            is_binary=True,
            liquidity_usd=10.0,
            odds_yes=0.05,
            resolution_time=datetime.utcnow() + timedelta(hours=72),
        ),
    ]

    passed, all_results = f.filter_markets(markets)

    assert len(passed) == 2
    assert len(all_results) == 3
    assert all_results[0].passed is True
    assert all_results[1].passed is True
    assert all_results[2].passed is False


def test_weather_category_keyword_detection():
    """Test weather category detection via keywords."""
    config = create_test_config()
    f = WeatherMarketFilter(config)

    # Market with no explicit WEATHER category but has weather keywords
    market = WeatherMarket(
        market_id="keyword-001",
        question="Will New York temperature hit 100°F?",
        resolution_text="Resolves YES if temperature hits 100°F",
        description="Prediction about heat wave",
        category="OTHER",  # Not WEATHER but has keywords
        is_binary=True,
        liquidity_usd=100.0,
        odds_yes=0.05,
        resolution_time=datetime.utcnow() + timedelta(hours=72),
    )

    result = f.filter_market(market)

    assert result.filter_details["is_weather_category"] is True


def test_filter_result_to_dict():
    """Test FilterResult serialization."""
    config = create_test_config()
    f = WeatherMarketFilter(config)
    market = create_valid_market()

    result = f.filter_market(market)
    d = result.to_dict()

    assert "passed" in d
    assert "market_id" in d
    assert "rejection_reasons" in d
    assert "filter_details" in d


def test_weather_market_to_dict():
    """Test WeatherMarket serialization."""
    market = create_valid_market()
    d = market.to_dict()

    assert d["market_id"] == "test-market-001"
    assert "question" in d
    assert "category" in d
    assert "is_binary" in d


def test_boundary_liquidity():
    """Test liquidity exactly at boundary."""
    config = create_test_config()  # MIN_LIQUIDITY = 50
    f = WeatherMarketFilter(config)

    market = WeatherMarket(
        market_id="boundary-001",
        question="Will New York temperature exceed 100°F?",
        resolution_text="Resolves YES if temperature exceeds 100°F",
        description="Weather market",
        category="WEATHER",
        is_binary=True,
        liquidity_usd=50.0,  # Exactly at boundary
        odds_yes=0.05,
        resolution_time=datetime.utcnow() + timedelta(hours=72),
    )

    result = f.filter_market(market)

    assert result.passed is True


def test_boundary_odds():
    """Test odds exactly at boundaries."""
    config = create_test_config()  # MIN_ODDS = 0.01, MAX_ODDS = 0.10
    f = WeatherMarketFilter(config)

    # At minimum
    market1 = create_valid_market()
    market1 = WeatherMarket(
        market_id="bound-min",
        question="Will New York temperature exceed 100°F?",
        resolution_text="Resolves YES if temperature exceeds 100°F",
        description="Weather market",
        category="WEATHER",
        is_binary=True,
        liquidity_usd=100.0,
        odds_yes=0.01,  # At minimum
        resolution_time=datetime.utcnow() + timedelta(hours=72),
    )

    result1 = f.filter_market(market1)
    assert result1.passed is True

    # At maximum
    market2 = WeatherMarket(
        market_id="bound-max",
        question="Will New York temperature exceed 100°F?",
        resolution_text="Resolves YES if temperature exceeds 100°F",
        description="Weather market",
        category="WEATHER",
        is_binary=True,
        liquidity_usd=100.0,
        odds_yes=0.10,  # At maximum
        resolution_time=datetime.utcnow() + timedelta(hours=72),
    )

    result2 = f.filter_market(market2)
    assert result2.passed is True


def test_multiple_rejection_reasons():
    """Test that multiple failures are all reported."""
    config = create_test_config()
    f = WeatherMarketFilter(config)

    market = WeatherMarket(
        market_id="multi-fail-001",
        question="Will it rain?",  # No city, no threshold
        resolution_text="Significant precipitation expected",  # Vague
        description="General market",
        category="SPORTS",  # Wrong category
        is_binary=False,  # Not binary
        liquidity_usd=1.0,  # Too low
        odds_yes=0.50,  # Too high
        resolution_time=datetime.utcnow() + timedelta(hours=12),  # Too soon
    )

    result = f.filter_market(market)

    assert result.passed is False
    assert len(result.rejection_reasons) >= 5  # Multiple failures


def test_create_filter_from_config():
    """Test create_filter_from_config factory function."""
    import tempfile
    import os
    import yaml
    from core.weather_market_filter import create_filter_from_config

    config_content = {
        "MIN_LIQUIDITY": 75,
        "MIN_ODDS": 0.02,
        "MAX_ODDS": 0.15,
        "MIN_TIME_TO_RESOLUTION_HOURS": 24,
        "ALLOWED_CITIES": ["Paris", "Berlin"],
    }

    # Create temp config file
    fd, path = tempfile.mkstemp(suffix=".yaml")
    with os.fdopen(fd, 'w') as f:
        yaml.dump(config_content, f)

    try:
        filter_instance = create_filter_from_config(path)

        assert filter_instance.min_liquidity == 75
        assert filter_instance.min_odds == 0.02
        assert filter_instance.max_odds == 0.15
        assert "Paris" in filter_instance.allowed_cities
        assert "Berlin" in filter_instance.allowed_cities
    finally:
        os.unlink(path)


def test_all_city_patterns():
    """Test all city pattern aliases are detected correctly."""
    config = create_test_config()
    config["ALLOWED_CITIES"] = [
        "New York", "London", "Seoul", "Los Angeles", "Chicago",
        "Miami", "Denver", "Phoenix", "Seattle", "Boston",
        "Tokyo", "Paris", "Berlin", "Sydney", "Toronto"
    ]
    f = WeatherMarketFilter(config)

    # Test various aliases
    test_cases = [
        ("nyc", "New York"),
        ("manhattan", "New York"),
        ("la", "Los Angeles"),
        ("london", "London"),
        ("seoul", "Seoul"),
        ("tokyo", "Tokyo"),
        ("paris", "Paris"),
        ("berlin", "Berlin"),
    ]

    for alias, expected_city in test_cases:
        market = WeatherMarket(
            market_id=f"alias-{alias}",
            question=f"Will {alias} temperature exceed 100°F?",
            resolution_text="Resolves YES if > 100°F",
            description="Weather market",
            category="WEATHER",
            is_binary=True,
            liquidity_usd=100.0,
            odds_yes=0.05,
            resolution_time=datetime.utcnow() + timedelta(hours=72),
        )
        result = f.filter_market(market)
        assert result.filter_details["detected_city"] == expected_city, f"Failed for alias: {alias}"


# =============================================================================
# TEST REGISTRY
# =============================================================================

def get_tests() -> List[Tuple[str, Callable]]:
    """Return list of all tests."""
    return [
        ("filter_initialization", test_filter_initialization),
        ("valid_market_passes", test_valid_market_passes),
        ("filter_rejects_non_weather", test_filter_rejects_non_weather),
        ("filter_rejects_non_binary", test_filter_rejects_non_binary),
        ("filter_rejects_low_liquidity", test_filter_rejects_low_liquidity),
        ("filter_rejects_odds_too_low", test_filter_rejects_odds_too_low),
        ("filter_rejects_odds_too_high", test_filter_rejects_odds_too_high),
        ("filter_rejects_too_soon", test_filter_rejects_too_soon),
        ("filter_rejects_unknown_city", test_filter_rejects_unknown_city),
        ("filter_rejects_no_city", test_filter_rejects_no_city),
        ("filter_rejects_vague_resolution", test_filter_rejects_vague_resolution),
        ("filter_rejects_no_threshold", test_filter_rejects_no_threshold),
        ("city_detection_aliases", test_city_detection_aliases),
        ("temperature_celsius_conversion", test_temperature_celsius_conversion),
        ("filter_markets_batch", test_filter_markets_batch),
        ("weather_category_keyword_detection", test_weather_category_keyword_detection),
        ("filter_result_to_dict", test_filter_result_to_dict),
        ("weather_market_to_dict", test_weather_market_to_dict),
        ("boundary_liquidity", test_boundary_liquidity),
        ("boundary_odds", test_boundary_odds),
        ("multiple_rejection_reasons", test_multiple_rejection_reasons),
        ("create_filter_from_config", test_create_filter_from_config),
        ("all_city_patterns", test_all_city_patterns),
    ]
