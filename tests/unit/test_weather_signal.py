"""
UNIT TESTS - WEATHER OBSERVATION
================================
Tests for core/weather_signal.py (observer-only system)
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from typing import List, Tuple, Callable

from core.weather_signal import (
    WeatherObservation,
    ObservationAction,
    WeatherConfidence,
    create_observation,
    create_no_signal,
)


# =============================================================================
# TEST FUNCTIONS
# =============================================================================

def test_signal_creation_basic():
    """Test basic observation creation."""
    observation = WeatherObservation(
        observation_id="test-001",
        timestamp_utc="2026-01-24T12:00:00Z",
        market_id="market-001",
        city="New York",
        event_description="Temperature exceeds 100F",
        market_probability=0.05,
        model_probability=0.10,
        edge=1.0,
        confidence=WeatherConfidence.HIGH,
        action=ObservationAction.OBSERVE,
    )

    assert observation.observation_id == "test-001"
    assert observation.city == "New York"
    assert observation.market_probability == 0.05
    assert observation.model_probability == 0.10
    assert observation.edge == 1.0
    assert observation.confidence == WeatherConfidence.HIGH
    assert observation.action == ObservationAction.OBSERVE


def test_signal_is_actionable():
    """Test has_edge property."""
    observe_signal = WeatherObservation(
        observation_id="test-observe",
        timestamp_utc="2026-01-24T12:00:00Z",
        market_id="m1",
        city="NYC",
        event_description="Test",
        market_probability=0.05,
        model_probability=0.10,
        edge=1.0,
        confidence=WeatherConfidence.HIGH,
        action=ObservationAction.OBSERVE,
    )

    no_signal = WeatherObservation(
        observation_id="test-no",
        timestamp_utc="2026-01-24T12:00:00Z",
        market_id="m2",
        city="NYC",
        event_description="Test",
        market_probability=0.05,
        model_probability=0.10,
        edge=1.0,
        confidence=WeatherConfidence.HIGH,
        action=ObservationAction.NO_SIGNAL,
    )

    assert observe_signal.has_edge is True
    assert no_signal.has_edge is False


def test_signal_immutability():
    """Test that observations are immutable (frozen)."""
    observation = WeatherObservation(
        observation_id="test-immut",
        timestamp_utc="2026-01-24T12:00:00Z",
        market_id="m1",
        city="NYC",
        event_description="Test",
        market_probability=0.05,
        model_probability=0.10,
        edge=1.0,
        confidence=WeatherConfidence.HIGH,
        action=ObservationAction.OBSERVE,
    )

    # Trying to modify should raise AttributeError
    try:
        observation.market_probability = 0.99
        assert False, "Should have raised AttributeError"
    except AttributeError:
        pass  # Expected


def test_signal_validation_probability_range():
    """Test probability validation."""
    # Valid probabilities
    observation = WeatherObservation(
        observation_id="test",
        timestamp_utc="2026-01-24T12:00:00Z",
        market_id="m1",
        city="NYC",
        event_description="Test",
        market_probability=0.0,  # Boundary
        model_probability=1.0,    # Boundary
        edge=0.0,
        confidence=WeatherConfidence.HIGH,
        action=ObservationAction.OBSERVE,
    )
    assert observation.market_probability == 0.0
    assert observation.model_probability == 1.0

    # Invalid probabilities
    try:
        WeatherObservation(
            observation_id="test",
            timestamp_utc="2026-01-24T12:00:00Z",
            market_id="m1",
            city="NYC",
            event_description="Test",
            market_probability=1.5,  # Invalid
            model_probability=0.5,
            edge=0.0,
            confidence=WeatherConfidence.HIGH,
            action=ObservationAction.OBSERVE,
        )
        assert False, "Should have raised ValueError"
    except ValueError:
        pass  # Expected


def test_signal_to_dict():
    """Test observation serialization to dict."""
    observation = WeatherObservation(
        observation_id="test-dict",
        timestamp_utc="2026-01-24T12:00:00Z",
        market_id="market-123",
        city="London",
        event_description="Test event",
        market_probability=0.03,
        model_probability=0.08,
        edge=1.67,
        confidence=WeatherConfidence.MEDIUM,
        action=ObservationAction.OBSERVE,
        forecast_temperature_f=95.5,
    )

    d = observation.to_dict()

    assert d["observation_id"] == "test-dict"
    assert d["market_id"] == "market-123"
    assert d["city"] == "London"
    assert d["market_probability"] == 0.03
    assert d["model_probability"] == 0.08
    assert d["edge"] == 1.67
    assert d["confidence"] == "MEDIUM"
    assert d["action"] == "OBSERVE"
    assert d["forecast_temperature_f"] == 95.5


def test_signal_to_json():
    """Test observation serialization to JSON."""
    observation = WeatherObservation(
        observation_id="test-json",
        timestamp_utc="2026-01-24T12:00:00Z",
        market_id="m1",
        city="NYC",
        event_description="Test",
        market_probability=0.05,
        model_probability=0.10,
        edge=1.0,
        confidence=WeatherConfidence.HIGH,
        action=ObservationAction.OBSERVE,
    )

    json_str = observation.to_json()

    assert "test-json" in json_str
    assert "NYC" in json_str
    assert "HIGH" in json_str
    assert "OBSERVE" in json_str


def test_create_weather_signal_factory():
    """Test factory function creates observations correctly."""
    config = {"MIN_EDGE": 0.25, "SIGMA_F": 3.5}

    observation = create_observation(
        market_id="factory-test",
        city="Seoul",
        event_description="Temperature test",
        market_probability=0.04,
        model_probability=0.08,
        confidence=WeatherConfidence.HIGH,
        action=ObservationAction.OBSERVE,
        config_snapshot=config,
    )

    assert observation.market_id == "factory-test"
    assert observation.city == "Seoul"
    assert len(observation.observation_id) == 36  # UUID format
    assert observation.parameters_hash != ""
    # Edge should be calculated: (0.08 - 0.04) / 0.04 = 1.0
    assert abs(observation.edge - 1.0) < 0.001


def test_create_no_signal_factory():
    """Test NO_SIGNAL factory function."""
    config = {"MIN_EDGE": 0.25}

    observation = create_no_signal(
        market_id="no-signal-test",
        city="Tokyo",
        event_description="Some event",
        market_probability=0.05,
        reason="Insufficient edge",
        config_snapshot=config,
    )

    assert observation.market_id == "no-signal-test"
    assert observation.action == ObservationAction.NO_SIGNAL
    assert observation.confidence == WeatherConfidence.LOW
    assert "Insufficient edge" in observation.event_description


def test_confidence_enum_values():
    """Test confidence enum has correct values."""
    assert WeatherConfidence.LOW.value == "LOW"
    assert WeatherConfidence.MEDIUM.value == "MEDIUM"
    assert WeatherConfidence.HIGH.value == "HIGH"


def test_action_enum_values():
    """Test action enum has correct values (OBSERVE/NO_SIGNAL only)."""
    assert ObservationAction.OBSERVE.value == "OBSERVE"
    assert ObservationAction.NO_SIGNAL.value == "NO_SIGNAL"
    # BUY/SELL should NOT exist
    assert not hasattr(ObservationAction, "BUY")
    assert not hasattr(ObservationAction, "SELL")


def test_signal_with_optional_fields():
    """Test observation with all optional fields."""
    observation = WeatherObservation(
        observation_id="opt-test",
        timestamp_utc="2026-01-24T12:00:00Z",
        market_id="m1",
        city="NYC",
        event_description="Test",
        market_probability=0.05,
        model_probability=0.10,
        edge=1.0,
        confidence=WeatherConfidence.HIGH,
        action=ObservationAction.OBSERVE,
        forecast_source="tomorrow_io",
        forecast_temperature_f=98.5,
        forecast_sigma_f=3.5,
        threshold_temperature_f=100.0,
        hours_to_resolution=48.5,
    )

    assert observation.forecast_source == "tomorrow_io"
    assert observation.forecast_temperature_f == 98.5
    assert observation.forecast_sigma_f == 3.5
    assert observation.threshold_temperature_f == 100.0
    assert observation.hours_to_resolution == 48.5


def test_edge_calculation_zero_market_prob():
    """Test edge calculation when market probability is zero."""
    config = {}
    observation = create_observation(
        market_id="zero-test",
        city="NYC",
        event_description="Test",
        market_probability=0.0,
        model_probability=0.10,
        confidence=WeatherConfidence.HIGH,
        action=ObservationAction.NO_SIGNAL,
        config_snapshot=config,
    )

    # Edge should be 0 when market_probability is 0
    assert observation.edge == 0.0


def test_negative_probability_rejected():
    """Test that negative probabilities are rejected."""
    try:
        WeatherObservation(
            observation_id="neg-test",
            timestamp_utc="2026-01-24T12:00:00Z",
            market_id="m1",
            city="NYC",
            event_description="Test",
            market_probability=-0.1,  # Invalid
            model_probability=0.10,
            edge=1.0,
            confidence=WeatherConfidence.HIGH,
            action=ObservationAction.OBSERVE,
        )
        assert False, "Should have raised ValueError"
    except ValueError:
        pass


def test_parameters_hash_consistency():
    """Test that same config produces same hash."""
    config = {"MIN_EDGE": 0.25, "SIGMA_F": 3.5}

    obs1 = create_observation(
        market_id="m1", city="NYC", event_description="Test",
        market_probability=0.05, model_probability=0.10,
        confidence=WeatherConfidence.HIGH,
        action=ObservationAction.OBSERVE,
        config_snapshot=config,
    )

    obs2 = create_observation(
        market_id="m2", city="LA", event_description="Test2",
        market_probability=0.03, model_probability=0.08,
        confidence=WeatherConfidence.MEDIUM,
        action=ObservationAction.OBSERVE,
        config_snapshot=config,
    )

    # Same config should produce same hash
    assert obs1.parameters_hash == obs2.parameters_hash


def test_parameters_hash_differs_with_config():
    """Test that different config produces different hash."""
    config1 = {"MIN_EDGE": 0.25}
    config2 = {"MIN_EDGE": 0.30}

    obs1 = create_observation(
        market_id="m1", city="NYC", event_description="Test",
        market_probability=0.05, model_probability=0.10,
        confidence=WeatherConfidence.HIGH,
        action=ObservationAction.OBSERVE,
        config_snapshot=config1,
    )

    obs2 = create_observation(
        market_id="m1", city="NYC", event_description="Test",
        market_probability=0.05, model_probability=0.10,
        confidence=WeatherConfidence.HIGH,
        action=ObservationAction.OBSERVE,
        config_snapshot=config2,
    )

    # Different config should produce different hash
    assert obs1.parameters_hash != obs2.parameters_hash


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
