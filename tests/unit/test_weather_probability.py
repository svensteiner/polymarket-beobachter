"""
UNIT TESTS - WEATHER PROBABILITY MODEL
=======================================
Intensive Tests fuer core/weather_probability_model.py
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import math
from datetime import datetime, timedelta
from typing import List, Tuple, Callable

from core.weather_probability_model import (
    ForecastData,
    ProbabilityResult,
    WeatherProbabilityModel,
    standard_normal_cdf,
    normal_cdf,
    probability_exceeds,
    probability_below,
    compute_edge,
    meets_edge_threshold,
)
from core.weather_signal import WeatherConfidence


# =============================================================================
# TEST FIXTURES
# =============================================================================

def create_test_config():
    """Create standard test configuration."""
    return {
        "SIGMA_F": 3.5,
        "MAX_FORECAST_HORIZON_DAYS": 10,
        "SIGMA_HORIZON_ADJUSTMENTS": {1: 0.8, 2: 0.9, 3: 1.0, 5: 1.2, 7: 1.5, 10: 2.0},
        "CONFIDENCE_THRESHOLDS": {
            "HIGH_CONFIDENCE_MAX_HOURS": 72,
            "MEDIUM_CONFIDENCE_MAX_HOURS": 168,
        },
    }


def create_forecast(
    temperature_f: float = 95.0,
    hours_ahead: float = 48.0,
    city: str = "New York",
):
    """Create test forecast data."""
    now = datetime.utcnow()
    return ForecastData(
        city=city,
        forecast_time=now,
        target_time=now + timedelta(hours=hours_ahead),
        temperature_f=temperature_f,
        source="test_source",
    )


# =============================================================================
# MATHEMATICAL FUNCTION TESTS
# =============================================================================

def test_standard_normal_cdf_zero():
    """Test standard normal CDF at x=0."""
    result = standard_normal_cdf(0)
    assert abs(result - 0.5) < 0.0001


def test_standard_normal_cdf_extreme_positive():
    """Test standard normal CDF at extreme positive."""
    result = standard_normal_cdf(10)
    assert result > 0.9999


def test_standard_normal_cdf_extreme_negative():
    """Test standard normal CDF at extreme negative."""
    result = standard_normal_cdf(-10)
    assert result < 0.0001


def test_standard_normal_cdf_symmetry():
    """Test symmetry: CDF(x) + CDF(-x) = 1."""
    for x in [0.5, 1.0, 1.5, 2.0, 2.5]:
        result = standard_normal_cdf(x) + standard_normal_cdf(-x)
        assert abs(result - 1.0) < 0.0001


def test_standard_normal_cdf_known_values():
    """Test against known CDF values."""
    # z = 1.96 → ~0.975
    result = standard_normal_cdf(1.96)
    assert abs(result - 0.975) < 0.001

    # z = 1.0 → ~0.8413
    result = standard_normal_cdf(1.0)
    assert abs(result - 0.8413) < 0.001

    # z = -1.0 → ~0.1587
    result = standard_normal_cdf(-1.0)
    assert abs(result - 0.1587) < 0.001


def test_normal_cdf_basic():
    """Test normal CDF with mean and sigma."""
    # Standard normal: mean=0, sigma=1
    result = normal_cdf(0, 0, 1)
    assert abs(result - 0.5) < 0.0001


def test_normal_cdf_shifted():
    """Test normal CDF with shifted mean."""
    # P(X <= 100) where X ~ N(100, 1) should be 0.5
    result = normal_cdf(100, 100, 1)
    assert abs(result - 0.5) < 0.0001


def test_normal_cdf_sigma_effect():
    """Test sigma affects spread correctly."""
    mean = 95
    threshold = 100

    # When threshold > mean:
    # Smaller sigma = tighter distribution around mean = MORE probability of X <= threshold
    # Larger sigma = wider spread = LESS probability of X <= threshold (more mass above)
    result_small = normal_cdf(threshold, mean, 2)
    result_large = normal_cdf(threshold, mean, 5)

    # With smaller sigma, higher probability of X <= 100 (more concentrated around 95)
    assert result_small > result_large


def test_normal_cdf_invalid_sigma():
    """Test normal CDF rejects non-positive sigma."""
    try:
        normal_cdf(0, 0, 0)
        assert False, "Should raise ValueError"
    except ValueError:
        pass

    try:
        normal_cdf(0, 0, -1)
        assert False, "Should raise ValueError"
    except ValueError:
        pass


def test_probability_exceeds_basic():
    """Test probability_exceeds function."""
    # P(X > 100) where X ~ N(95, 3.5)
    # z = (100-95)/3.5 = 1.43
    # P(Z > 1.43) ≈ 0.077
    result = probability_exceeds(100, 95, 3.5)
    assert 0.05 < result < 0.15  # Roughly 7.7%


def test_probability_exceeds_threshold_below_mean():
    """Test when threshold is below mean."""
    # P(X > 90) where X ~ N(95, 3.5) should be > 0.5
    result = probability_exceeds(90, 95, 3.5)
    assert result > 0.5


def test_probability_exceeds_threshold_above_mean():
    """Test when threshold is above mean."""
    # P(X > 100) where X ~ N(95, 3.5) should be < 0.5
    result = probability_exceeds(100, 95, 3.5)
    assert result < 0.5


def test_probability_below_basic():
    """Test probability_below function."""
    # P(X < 100) = 1 - P(X > 100)
    result_below = probability_below(100, 95, 3.5)
    result_exceeds = probability_exceeds(100, 95, 3.5)
    assert abs(result_below + result_exceeds - 1.0) < 0.0001


def test_probability_exceeds_extreme():
    """Test extreme threshold values."""
    # P(X > 200) where X ~ N(95, 3.5) should be ~0
    result = probability_exceeds(200, 95, 3.5)
    assert result < 0.0001

    # P(X > 0) where X ~ N(95, 3.5) should be ~1
    result = probability_exceeds(0, 95, 3.5)
    assert result > 0.9999


# =============================================================================
# EDGE CALCULATION TESTS
# =============================================================================

def test_compute_edge_basic():
    """Test basic edge calculation."""
    # fair=0.10, market=0.05 → edge = (0.10-0.05)/0.05 = 1.0
    edge = compute_edge(0.10, 0.05)
    assert abs(edge - 1.0) < 0.0001


def test_compute_edge_negative():
    """Test negative edge (market overpriced)."""
    # fair=0.05, market=0.10 → edge = (0.05-0.10)/0.10 = -0.5
    edge = compute_edge(0.05, 0.10)
    assert abs(edge - (-0.5)) < 0.0001


def test_compute_edge_zero_market():
    """Test edge when market probability is zero."""
    edge = compute_edge(0.10, 0.0)
    assert edge == 0.0


def test_compute_edge_equal_probabilities():
    """Test edge when probabilities are equal."""
    edge = compute_edge(0.05, 0.05)
    assert abs(edge) < 0.0001


def test_meets_edge_threshold_high_confidence():
    """Test edge threshold for HIGH confidence."""
    # HIGH confidence uses base threshold
    assert meets_edge_threshold(0.30, 0.25, WeatherConfidence.HIGH) is True
    assert meets_edge_threshold(0.20, 0.25, WeatherConfidence.HIGH) is False


def test_meets_edge_threshold_medium_confidence():
    """Test edge threshold for MEDIUM confidence."""
    # MEDIUM uses multiplier (default 1.5x)
    # Required = 0.25 * 1.5 = 0.375
    assert meets_edge_threshold(0.40, 0.25, WeatherConfidence.MEDIUM) is True
    assert meets_edge_threshold(0.30, 0.25, WeatherConfidence.MEDIUM) is False


def test_meets_edge_threshold_low_confidence():
    """Test edge threshold for LOW confidence (always false)."""
    assert meets_edge_threshold(1.0, 0.25, WeatherConfidence.LOW) is False
    assert meets_edge_threshold(10.0, 0.25, WeatherConfidence.LOW) is False


def test_meets_edge_threshold_custom_multiplier():
    """Test custom multiplier for MEDIUM confidence."""
    # Required = 0.25 * 2.0 = 0.50
    assert meets_edge_threshold(0.55, 0.25, WeatherConfidence.MEDIUM, 2.0) is True
    assert meets_edge_threshold(0.45, 0.25, WeatherConfidence.MEDIUM, 2.0) is False


# =============================================================================
# PROBABILITY MODEL TESTS
# =============================================================================

def test_model_initialization():
    """Test model initializes with correct config."""
    config = create_test_config()
    model = WeatherProbabilityModel(config)

    assert model.base_sigma_f == 3.5
    assert model.max_horizon_days == 10


def test_model_compute_probability_exceeds():
    """Test probability computation for exceeds event."""
    config = create_test_config()
    model = WeatherProbabilityModel(config)
    forecast = create_forecast(temperature_f=95.0, hours_ahead=48.0)

    result = model.compute_probability(forecast, threshold_f=100.0, event_type="exceeds")

    assert isinstance(result, ProbabilityResult)
    assert 0 < result.fair_probability < 0.5
    assert result.forecast_temperature_f == 95.0
    assert result.threshold_temperature_f == 100.0


def test_model_compute_probability_below():
    """Test probability computation for below event."""
    config = create_test_config()
    model = WeatherProbabilityModel(config)
    forecast = create_forecast(temperature_f=40.0, hours_ahead=48.0)

    result = model.compute_probability(forecast, threshold_f=32.0, event_type="below")

    assert isinstance(result, ProbabilityResult)
    assert 0 < result.fair_probability < 0.5


def test_model_confidence_high():
    """Test HIGH confidence for short horizon."""
    config = create_test_config()
    model = WeatherProbabilityModel(config)
    forecast = create_forecast(hours_ahead=48.0)  # 2 days

    result = model.compute_probability(forecast, 100.0)

    assert result.confidence == WeatherConfidence.HIGH


def test_model_confidence_medium():
    """Test MEDIUM confidence for medium horizon."""
    config = create_test_config()
    model = WeatherProbabilityModel(config)
    forecast = create_forecast(hours_ahead=120.0)  # 5 days

    result = model.compute_probability(forecast, 100.0)

    assert result.confidence == WeatherConfidence.MEDIUM


def test_model_confidence_low():
    """Test LOW confidence for long horizon."""
    config = create_test_config()
    model = WeatherProbabilityModel(config)
    forecast = create_forecast(hours_ahead=200.0)  # 8+ days

    result = model.compute_probability(forecast, 100.0)

    assert result.confidence == WeatherConfidence.LOW


def test_model_horizon_too_long():
    """Test handling of horizon beyond maximum."""
    config = create_test_config()  # MAX = 10 days
    model = WeatherProbabilityModel(config)
    forecast = create_forecast(hours_ahead=300.0)  # 12+ days

    result = model.compute_probability(forecast, 100.0)

    assert result.confidence == WeatherConfidence.LOW
    assert result.fair_probability == 0.0  # Unknown


def test_model_sigma_adjustment():
    """Test sigma is adjusted based on horizon."""
    config = create_test_config()
    model = WeatherProbabilityModel(config)

    # 2-day forecast should use lower sigma
    forecast_short = create_forecast(hours_ahead=48.0)
    result_short = model.compute_probability(forecast_short, 100.0)

    # 7-day forecast should use higher sigma
    forecast_long = create_forecast(hours_ahead=168.0)
    result_long = model.compute_probability(forecast_long, 100.0)

    assert result_short.sigma_used < result_long.sigma_used


def test_model_invalid_event_type():
    """Test rejection of invalid event type."""
    config = create_test_config()
    model = WeatherProbabilityModel(config)
    forecast = create_forecast()

    try:
        model.compute_probability(forecast, 100.0, event_type="invalid")
        assert False, "Should raise ValueError"
    except ValueError:
        pass


def test_probability_result_to_dict():
    """Test ProbabilityResult serialization."""
    config = create_test_config()
    model = WeatherProbabilityModel(config)
    forecast = create_forecast()

    result = model.compute_probability(forecast, 100.0)
    d = result.to_dict()

    assert "fair_probability" in d
    assert "confidence" in d
    assert "sigma_used" in d
    assert "computation_details" in d


def test_forecast_data_to_dict():
    """Test ForecastData serialization."""
    forecast = create_forecast()
    d = forecast.to_dict()

    assert d["city"] == "New York"
    assert "forecast_time" in d
    assert "target_time" in d
    assert d["temperature_f"] == 95.0


def test_model_computation_details():
    """Test that computation details are populated."""
    config = create_test_config()
    model = WeatherProbabilityModel(config)
    forecast = create_forecast()

    result = model.compute_probability(forecast, 100.0)

    details = result.computation_details
    assert "event_type" in details
    assert "forecast_mean" in details
    assert "sigma_base" in details
    assert "sigma_adjusted" in details
    assert "z_score" in details
    assert "data_source" in details


def test_model_z_score_calculation():
    """Test z-score is calculated correctly."""
    config = create_test_config()
    model = WeatherProbabilityModel(config)
    forecast = create_forecast(temperature_f=95.0)

    result = model.compute_probability(forecast, 100.0)

    # z = (100 - 95) / sigma
    expected_z = (100.0 - 95.0) / result.sigma_used
    assert abs(result.computation_details["z_score"] - expected_z) < 0.001


def test_probability_range():
    """Test probabilities are always in [0, 1]."""
    config = create_test_config()
    model = WeatherProbabilityModel(config)

    # Various scenarios
    scenarios = [
        (95, 100),  # Threshold above mean
        (105, 100),  # Threshold below mean
        (100, 100),  # Threshold at mean
        (50, 100),   # Very high threshold
        (150, 100),  # Very low threshold
    ]

    for mean_temp, threshold in scenarios:
        forecast = create_forecast(temperature_f=mean_temp)
        result = model.compute_probability(forecast, threshold)
        assert 0.0 <= result.fair_probability <= 1.0


def test_forecast_optional_fields():
    """Test ForecastData with all optional fields."""
    now = datetime.utcnow()
    forecast = ForecastData(
        city="New York",
        forecast_time=now,
        target_time=now + timedelta(hours=48),
        temperature_f=95.0,
        source="tomorrow_io",
        temperature_min_f=88.0,
        temperature_max_f=102.0,
        humidity_percent=65.5,
        precipitation_probability=0.15,
    )

    assert forecast.temperature_min_f == 88.0
    assert forecast.temperature_max_f == 102.0
    assert forecast.humidity_percent == 65.5
    assert forecast.precipitation_probability == 0.15

    # Check serialization includes optional fields
    d = forecast.to_dict()
    assert d["temperature_min_f"] == 88.0
    assert d["temperature_max_f"] == 102.0


def test_forecast_optional_fields_none():
    """Test ForecastData with None optional fields."""
    forecast = create_forecast()

    assert forecast.temperature_min_f is None
    assert forecast.temperature_max_f is None
    assert forecast.humidity_percent is None
    assert forecast.precipitation_probability is None


def test_create_low_confidence_result():
    """Test _create_low_confidence_result method directly."""
    config = create_test_config()
    model = WeatherProbabilityModel(config)

    forecast = ForecastData(
        city="New York",
        forecast_time=datetime.utcnow(),
        target_time=datetime.utcnow() + timedelta(hours=48),
        temperature_f=95.0,
        source="test_source",
    )

    result = model._create_low_confidence_result(
        forecast=forecast,
        threshold_f=100.0,
        hours_to_resolution=48.0,
        reason="Test reason",
    )

    assert result.fair_probability == 0.0
    assert result.confidence == WeatherConfidence.LOW
    assert result.sigma_used == 0.0
    assert result.forecast_temperature_f == 95.0
    assert result.threshold_temperature_f == 100.0
    assert result.hours_to_resolution == 48.0
    assert "low_confidence_reason" in result.computation_details
    assert result.computation_details["low_confidence_reason"] == "Test reason"


def test_calculate_adjusted_sigma_direct():
    """Test _calculate_adjusted_sigma method directly."""
    config = create_test_config()
    model = WeatherProbabilityModel(config)

    # Test different horizons
    sigma_1d = model._calculate_adjusted_sigma(1.0)
    sigma_3d = model._calculate_adjusted_sigma(3.0)
    sigma_7d = model._calculate_adjusted_sigma(7.0)
    sigma_10d = model._calculate_adjusted_sigma(10.0)

    # Longer horizons should have higher sigma
    assert sigma_1d < sigma_3d
    assert sigma_3d < sigma_7d
    assert sigma_7d <= sigma_10d


def test_determine_confidence_direct():
    """Test _determine_confidence method directly."""
    config = create_test_config()
    model = WeatherProbabilityModel(config)

    # HIGH confidence: <= 72 hours
    assert model._determine_confidence(24.0) == WeatherConfidence.HIGH
    assert model._determine_confidence(72.0) == WeatherConfidence.HIGH

    # MEDIUM confidence: 72 < hours <= 168
    assert model._determine_confidence(100.0) == WeatherConfidence.MEDIUM
    assert model._determine_confidence(168.0) == WeatherConfidence.MEDIUM

    # LOW confidence: > 168 hours
    assert model._determine_confidence(200.0) == WeatherConfidence.LOW
    assert model._determine_confidence(500.0) == WeatherConfidence.LOW


# =============================================================================
# TEST REGISTRY
# =============================================================================

def get_tests() -> List[Tuple[str, Callable]]:
    """Return list of all tests."""
    return [
        ("standard_normal_cdf_zero", test_standard_normal_cdf_zero),
        ("standard_normal_cdf_extreme_positive", test_standard_normal_cdf_extreme_positive),
        ("standard_normal_cdf_extreme_negative", test_standard_normal_cdf_extreme_negative),
        ("standard_normal_cdf_symmetry", test_standard_normal_cdf_symmetry),
        ("standard_normal_cdf_known_values", test_standard_normal_cdf_known_values),
        ("normal_cdf_basic", test_normal_cdf_basic),
        ("normal_cdf_shifted", test_normal_cdf_shifted),
        ("normal_cdf_sigma_effect", test_normal_cdf_sigma_effect),
        ("normal_cdf_invalid_sigma", test_normal_cdf_invalid_sigma),
        ("probability_exceeds_basic", test_probability_exceeds_basic),
        ("probability_exceeds_threshold_below_mean", test_probability_exceeds_threshold_below_mean),
        ("probability_exceeds_threshold_above_mean", test_probability_exceeds_threshold_above_mean),
        ("probability_below_basic", test_probability_below_basic),
        ("probability_exceeds_extreme", test_probability_exceeds_extreme),
        ("compute_edge_basic", test_compute_edge_basic),
        ("compute_edge_negative", test_compute_edge_negative),
        ("compute_edge_zero_market", test_compute_edge_zero_market),
        ("compute_edge_equal_probabilities", test_compute_edge_equal_probabilities),
        ("meets_edge_threshold_high_confidence", test_meets_edge_threshold_high_confidence),
        ("meets_edge_threshold_medium_confidence", test_meets_edge_threshold_medium_confidence),
        ("meets_edge_threshold_low_confidence", test_meets_edge_threshold_low_confidence),
        ("meets_edge_threshold_custom_multiplier", test_meets_edge_threshold_custom_multiplier),
        ("model_initialization", test_model_initialization),
        ("model_compute_probability_exceeds", test_model_compute_probability_exceeds),
        ("model_compute_probability_below", test_model_compute_probability_below),
        ("model_confidence_high", test_model_confidence_high),
        ("model_confidence_medium", test_model_confidence_medium),
        ("model_confidence_low", test_model_confidence_low),
        ("model_horizon_too_long", test_model_horizon_too_long),
        ("model_sigma_adjustment", test_model_sigma_adjustment),
        ("model_invalid_event_type", test_model_invalid_event_type),
        ("probability_result_to_dict", test_probability_result_to_dict),
        ("forecast_data_to_dict", test_forecast_data_to_dict),
        ("model_computation_details", test_model_computation_details),
        ("model_z_score_calculation", test_model_z_score_calculation),
        ("probability_range", test_probability_range),
        ("forecast_optional_fields", test_forecast_optional_fields),
        ("forecast_optional_fields_none", test_forecast_optional_fields_none),
        ("create_low_confidence_result", test_create_low_confidence_result),
        ("calculate_adjusted_sigma_direct", test_calculate_adjusted_sigma_direct),
        ("determine_confidence_direct", test_determine_confidence_direct),
    ]
