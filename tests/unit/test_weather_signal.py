"""
UNIT TESTS - WEATHER SIGNAL
===========================
Intensive Tests fuer core/weather_signal.py
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from typing import List, Tuple, Callable

from core.weather_signal import (
    WeatherSignal,
    WeatherSignalAction,
    WeatherConfidence,
    create_weather_signal,
    create_no_signal,
)


# =============================================================================
# TEST FUNCTIONS
# =============================================================================

def test_signal_creation_basic():
    """Test basic signal creation."""
    signal = WeatherSignal(
        signal_id="test-001",
        timestamp_utc="2026-01-24T12:00:00Z",
        market_id="market-001",
        city="New York",
        event_description="Temperature exceeds 100F",
        market_probability=0.05,
        fair_probability=0.10,
        edge=1.0,
        confidence=WeatherConfidence.HIGH,
        recommended_action=WeatherSignalAction.BUY,
    )

    assert signal.signal_id == "test-001"
    assert signal.city == "New York"
    assert signal.market_probability == 0.05
    assert signal.fair_probability == 0.10
    assert signal.edge == 1.0
    assert signal.confidence == WeatherConfidence.HIGH
    assert signal.recommended_action == WeatherSignalAction.BUY


def test_signal_is_actionable():
    """Test is_actionable property."""
    buy_signal = WeatherSignal(
        signal_id="test-buy",
        timestamp_utc="2026-01-24T12:00:00Z",
        market_id="m1",
        city="NYC",
        event_description="Test",
        market_probability=0.05,
        fair_probability=0.10,
        edge=1.0,
        confidence=WeatherConfidence.HIGH,
        recommended_action=WeatherSignalAction.BUY,
    )

    no_signal = WeatherSignal(
        signal_id="test-no",
        timestamp_utc="2026-01-24T12:00:00Z",
        market_id="m2",
        city="NYC",
        event_description="Test",
        market_probability=0.05,
        fair_probability=0.10,
        edge=1.0,
        confidence=WeatherConfidence.HIGH,
        recommended_action=WeatherSignalAction.NO_SIGNAL,
    )

    assert buy_signal.is_actionable is True
    assert no_signal.is_actionable is False


def test_signal_immutability():
    """Test that signals are immutable (frozen)."""
    signal = WeatherSignal(
        signal_id="test-immut",
        timestamp_utc="2026-01-24T12:00:00Z",
        market_id="m1",
        city="NYC",
        event_description="Test",
        market_probability=0.05,
        fair_probability=0.10,
        edge=1.0,
        confidence=WeatherConfidence.HIGH,
        recommended_action=WeatherSignalAction.BUY,
    )

    # Trying to modify should raise AttributeError
    try:
        signal.market_probability = 0.99
        assert False, "Should have raised AttributeError"
    except AttributeError:
        pass  # Expected


def test_signal_validation_probability_range():
    """Test probability validation."""
    # Valid probabilities
    signal = WeatherSignal(
        signal_id="test",
        timestamp_utc="2026-01-24T12:00:00Z",
        market_id="m1",
        city="NYC",
        event_description="Test",
        market_probability=0.0,  # Boundary
        fair_probability=1.0,    # Boundary
        edge=0.0,
        confidence=WeatherConfidence.HIGH,
        recommended_action=WeatherSignalAction.BUY,
    )
    assert signal.market_probability == 0.0
    assert signal.fair_probability == 1.0

    # Invalid probabilities
    try:
        WeatherSignal(
            signal_id="test",
            timestamp_utc="2026-01-24T12:00:00Z",
            market_id="m1",
            city="NYC",
            event_description="Test",
            market_probability=1.5,  # Invalid
            fair_probability=0.5,
            edge=0.0,
            confidence=WeatherConfidence.HIGH,
            recommended_action=WeatherSignalAction.BUY,
        )
        assert False, "Should have raised ValueError"
    except ValueError:
        pass  # Expected


def test_signal_to_dict():
    """Test signal serialization to dict."""
    signal = WeatherSignal(
        signal_id="test-dict",
        timestamp_utc="2026-01-24T12:00:00Z",
        market_id="market-123",
        city="London",
        event_description="Test event",
        market_probability=0.03,
        fair_probability=0.08,
        edge=1.67,
        confidence=WeatherConfidence.MEDIUM,
        recommended_action=WeatherSignalAction.BUY,
        forecast_temperature_f=95.5,
    )

    d = signal.to_dict()

    assert d["signal_id"] == "test-dict"
    assert d["market_id"] == "market-123"
    assert d["city"] == "London"
    assert d["market_probability"] == 0.03
    assert d["fair_probability"] == 0.08
    assert d["edge"] == 1.67
    assert d["confidence"] == "MEDIUM"
    assert d["recommended_action"] == "BUY"
    assert d["forecast_temperature_f"] == 95.5


def test_signal_to_json():
    """Test signal serialization to JSON."""
    signal = WeatherSignal(
        signal_id="test-json",
        timestamp_utc="2026-01-24T12:00:00Z",
        market_id="m1",
        city="NYC",
        event_description="Test",
        market_probability=0.05,
        fair_probability=0.10,
        edge=1.0,
        confidence=WeatherConfidence.HIGH,
        recommended_action=WeatherSignalAction.BUY,
    )

    json_str = signal.to_json()

    assert "test-json" in json_str
    assert "NYC" in json_str
    assert "HIGH" in json_str
    assert "BUY" in json_str


def test_create_weather_signal_factory():
    """Test factory function creates signals correctly."""
    config = {"MIN_EDGE": 0.25, "SIGMA_F": 3.5}

    signal = create_weather_signal(
        market_id="factory-test",
        city="Seoul",
        event_description="Temperature test",
        market_probability=0.04,
        fair_probability=0.08,
        confidence=WeatherConfidence.HIGH,
        recommended_action=WeatherSignalAction.BUY,
        config_snapshot=config,
    )

    assert signal.market_id == "factory-test"
    assert signal.city == "Seoul"
    assert len(signal.signal_id) == 36  # UUID format
    assert signal.parameters_hash != ""
    # Edge should be calculated: (0.08 - 0.04) / 0.04 = 1.0
    assert abs(signal.edge - 1.0) < 0.001


def test_create_no_signal_factory():
    """Test NO_SIGNAL factory function."""
    config = {"MIN_EDGE": 0.25}

    signal = create_no_signal(
        market_id="no-signal-test",
        city="Tokyo",
        event_description="Some event",
        market_probability=0.05,
        reason="Insufficient edge",
        config_snapshot=config,
    )

    assert signal.market_id == "no-signal-test"
    assert signal.recommended_action == WeatherSignalAction.NO_SIGNAL
    assert signal.confidence == WeatherConfidence.LOW
    assert "Insufficient edge" in signal.event_description


def test_confidence_enum_values():
    """Test confidence enum has correct values."""
    assert WeatherConfidence.LOW.value == "LOW"
    assert WeatherConfidence.MEDIUM.value == "MEDIUM"
    assert WeatherConfidence.HIGH.value == "HIGH"


def test_action_enum_values():
    """Test action enum has correct values."""
    assert WeatherSignalAction.BUY.value == "BUY"
    assert WeatherSignalAction.NO_SIGNAL.value == "NO_SIGNAL"


def test_signal_with_optional_fields():
    """Test signal with all optional fields."""
    signal = WeatherSignal(
        signal_id="opt-test",
        timestamp_utc="2026-01-24T12:00:00Z",
        market_id="m1",
        city="NYC",
        event_description="Test",
        market_probability=0.05,
        fair_probability=0.10,
        edge=1.0,
        confidence=WeatherConfidence.HIGH,
        recommended_action=WeatherSignalAction.BUY,
        forecast_source="tomorrow_io",
        forecast_temperature_f=98.5,
        forecast_sigma_f=3.5,
        threshold_temperature_f=100.0,
        hours_to_resolution=48.5,
    )

    assert signal.forecast_source == "tomorrow_io"
    assert signal.forecast_temperature_f == 98.5
    assert signal.forecast_sigma_f == 3.5
    assert signal.threshold_temperature_f == 100.0
    assert signal.hours_to_resolution == 48.5


def test_edge_calculation_zero_market_prob():
    """Test edge calculation when market probability is zero."""
    config = {}
    signal = create_weather_signal(
        market_id="zero-test",
        city="NYC",
        event_description="Test",
        market_probability=0.0,
        fair_probability=0.10,
        confidence=WeatherConfidence.HIGH,
        recommended_action=WeatherSignalAction.NO_SIGNAL,
        config_snapshot=config,
    )

    # Edge should be 0 when market_probability is 0
    assert signal.edge == 0.0


def test_negative_probability_rejected():
    """Test that negative probabilities are rejected."""
    try:
        WeatherSignal(
            signal_id="neg-test",
            timestamp_utc="2026-01-24T12:00:00Z",
            market_id="m1",
            city="NYC",
            event_description="Test",
            market_probability=-0.1,  # Invalid
            fair_probability=0.10,
            edge=1.0,
            confidence=WeatherConfidence.HIGH,
            recommended_action=WeatherSignalAction.BUY,
        )
        assert False, "Should have raised ValueError"
    except ValueError:
        pass


def test_parameters_hash_consistency():
    """Test that same config produces same hash."""
    config = {"MIN_EDGE": 0.25, "SIGMA_F": 3.5}

    signal1 = create_weather_signal(
        market_id="m1", city="NYC", event_description="Test",
        market_probability=0.05, fair_probability=0.10,
        confidence=WeatherConfidence.HIGH,
        recommended_action=WeatherSignalAction.BUY,
        config_snapshot=config,
    )

    signal2 = create_weather_signal(
        market_id="m2", city="LA", event_description="Test2",
        market_probability=0.03, fair_probability=0.08,
        confidence=WeatherConfidence.MEDIUM,
        recommended_action=WeatherSignalAction.BUY,
        config_snapshot=config,
    )

    # Same config should produce same hash
    assert signal1.parameters_hash == signal2.parameters_hash


def test_parameters_hash_differs_with_config():
    """Test that different config produces different hash."""
    config1 = {"MIN_EDGE": 0.25}
    config2 = {"MIN_EDGE": 0.30}

    signal1 = create_weather_signal(
        market_id="m1", city="NYC", event_description="Test",
        market_probability=0.05, fair_probability=0.10,
        confidence=WeatherConfidence.HIGH,
        recommended_action=WeatherSignalAction.BUY,
        config_snapshot=config1,
    )

    signal2 = create_weather_signal(
        market_id="m1", city="NYC", event_description="Test",
        market_probability=0.05, fair_probability=0.10,
        confidence=WeatherConfidence.HIGH,
        recommended_action=WeatherSignalAction.BUY,
        config_snapshot=config2,
    )

    # Different config should produce different hash
    assert signal1.parameters_hash != signal2.parameters_hash


# =============================================================================
# TEST REGISTRY
# =============================================================================

def get_tests() -> List[Tuple[str, Callable]]:
    """Return list of all tests."""
    return [
        ("signal_creation_basic", test_signal_creation_basic),
        ("signal_is_actionable", test_signal_is_actionable),
        ("signal_immutability", test_signal_immutability),
        ("signal_validation_probability_range", test_signal_validation_probability_range),
        ("signal_to_dict", test_signal_to_dict),
        ("signal_to_json", test_signal_to_json),
        ("create_weather_signal_factory", test_create_weather_signal_factory),
        ("create_no_signal_factory", test_create_no_signal_factory),
        ("confidence_enum_values", test_confidence_enum_values),
        ("action_enum_values", test_action_enum_values),
        ("signal_with_optional_fields", test_signal_with_optional_fields),
        ("edge_calculation_zero_market_prob", test_edge_calculation_zero_market_prob),
        ("negative_probability_rejected", test_negative_probability_rejected),
        ("parameters_hash_consistency", test_parameters_hash_consistency),
        ("parameters_hash_differs_with_config", test_parameters_hash_differs_with_config),
    ]
