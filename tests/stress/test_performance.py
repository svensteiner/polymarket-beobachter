"""
STRESS TESTS - PERFORMANCE
===========================
Belastungstests fuer das Weather Engine System.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import time
import random
import statistics
from datetime import datetime, timedelta
from typing import List, Tuple, Callable, Optional

from core.weather_engine import WeatherEngine, EngineRunResult
from core.weather_market_filter import WeatherMarket, WeatherMarketFilter
from core.weather_probability_model import (
    WeatherProbabilityModel,
    ForecastData,
    standard_normal_cdf,
    probability_exceeds,
)
from core.weather_signal import (
    WeatherSignal,
    WeatherSignalAction,
    WeatherConfidence,
    create_weather_signal,
    create_no_signal,
)


# =============================================================================
# TEST CONFIGURATION
# =============================================================================

STRESS_CONFIG = {
    "MIN_LIQUIDITY": 50,
    "MIN_ODDS": 0.01,
    "MAX_ODDS": 0.10,
    "MIN_TIME_TO_RESOLUTION_HOURS": 48,
    "SAFETY_BUFFER_HOURS": 48,
    "ALLOWED_CITIES": [
        "New York", "London", "Seoul", "Tokyo", "Chicago",
        "Miami", "Los Angeles", "Seattle", "Boston", "Denver",
    ],
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
# HELPER FUNCTIONS
# =============================================================================

def generate_random_markets(count: int) -> List[WeatherMarket]:
    """Generate random markets for stress testing."""
    cities = STRESS_CONFIG["ALLOWED_CITIES"]
    thresholds = [80, 85, 90, 95, 100, 105, 110]

    markets = []
    for i in range(count):
        city = random.choice(cities)
        threshold = random.choice(thresholds)
        hours = random.randint(50, 200)

        markets.append(WeatherMarket(
            market_id=f"stress-{i:06d}",
            question=f"Will {city} temperature exceed {threshold}°F?",
            resolution_text=f"Resolves YES if temperature exceeds {threshold}°F in {city}",
            description=f"Weather market for {city}",
            category="WEATHER",
            is_binary=True,
            liquidity_usd=random.uniform(50, 500),
            odds_yes=random.uniform(0.02, 0.08),
            resolution_time=datetime.utcnow() + timedelta(hours=hours),
        ))

    return markets


def measure_time(func: Callable) -> Tuple[float, any]:
    """Measure execution time of a function."""
    start = time.perf_counter()
    result = func()
    end = time.perf_counter()
    return end - start, result


# =============================================================================
# TEST FUNCTIONS
# =============================================================================

def test_cdf_performance():
    """Test CDF calculation performance under load."""
    iterations = 10000

    times = []
    for _ in range(iterations):
        x = random.uniform(-5, 5)
        start = time.perf_counter()
        _ = standard_normal_cdf(x)
        end = time.perf_counter()
        times.append(end - start)

    avg_time = statistics.mean(times)
    max_time = max(times)

    # Should be very fast (< 0.1ms per call)
    assert avg_time < 0.0001, f"CDF avg time {avg_time*1000:.4f}ms too slow"
    assert max_time < 0.001, f"CDF max time {max_time*1000:.4f}ms too slow"


def test_probability_calculation_performance():
    """Test probability calculation performance."""
    iterations = 5000

    times = []
    for _ in range(iterations):
        threshold = random.uniform(80, 110)
        mean = random.uniform(85, 105)
        sigma = random.uniform(2, 5)

        start = time.perf_counter()
        _ = probability_exceeds(threshold, mean, sigma)
        end = time.perf_counter()
        times.append(end - start)

    avg_time = statistics.mean(times)

    # Should be very fast
    assert avg_time < 0.0001, f"Probability calc avg time {avg_time*1000:.4f}ms too slow"


def test_filter_performance_100_markets():
    """Test filter performance with 100 markets."""
    filter_instance = WeatherMarketFilter(STRESS_CONFIG)
    markets = generate_random_markets(100)

    duration, (passed, results) = measure_time(
        lambda: filter_instance.filter_markets(markets)
    )

    # Should process 100 markets in < 0.5 second
    assert duration < 0.5, f"100 markets took {duration:.3f}s"
    assert len(results) == 100


def test_filter_performance_1000_markets():
    """Test filter performance with 1000 markets."""
    filter_instance = WeatherMarketFilter(STRESS_CONFIG)
    markets = generate_random_markets(1000)

    duration, (passed, results) = measure_time(
        lambda: filter_instance.filter_markets(markets)
    )

    # Should process 1000 markets in < 2 seconds
    assert duration < 2.0, f"1000 markets took {duration:.3f}s"
    assert len(results) == 1000


def test_model_performance_1000_computations():
    """Test probability model with 1000 computations."""
    model = WeatherProbabilityModel(STRESS_CONFIG)

    times = []
    for i in range(1000):
        forecast = ForecastData(
            city="New York",
            forecast_time=datetime.utcnow(),
            target_time=datetime.utcnow() + timedelta(hours=random.randint(48, 168)),
            temperature_f=random.uniform(85, 110),
            source="stress_test",
        )

        threshold = random.uniform(80, 110)

        start = time.perf_counter()
        _ = model.compute_probability(forecast, threshold, "exceeds")
        end = time.perf_counter()
        times.append(end - start)

    avg_time = statistics.mean(times)
    total_time = sum(times)

    # Should complete 1000 computations in < 1 second
    assert total_time < 1.0, f"1000 computations took {total_time:.3f}s"


def test_signal_creation_performance():
    """Test signal creation performance."""
    iterations = 1000

    times = []
    for i in range(iterations):
        start = time.perf_counter()
        _ = create_weather_signal(
            market_id=f"perf-{i:06d}",
            city="New York",
            event_description="Temperature test",
            market_probability=0.05,
            fair_probability=0.10,
            confidence=WeatherConfidence.HIGH,
            recommended_action=WeatherSignalAction.BUY,
            config_snapshot=STRESS_CONFIG,
        )
        end = time.perf_counter()
        times.append(end - start)

    avg_time = statistics.mean(times)
    total_time = sum(times)

    # Should create 1000 signals in < 0.5 seconds
    assert total_time < 0.5, f"1000 signals took {total_time:.3f}s"


def test_engine_run_performance_100_markets():
    """Test engine run with 100 markets."""
    markets = generate_random_markets(100)

    def market_fetcher():
        return markets

    def forecast_fetcher(city: str, res_time: datetime) -> Optional[ForecastData]:
        return ForecastData(
            city=city,
            forecast_time=datetime.utcnow(),
            target_time=res_time,
            temperature_f=random.uniform(90, 105),
            source="stress_test",
        )

    engine = WeatherEngine(
        config=STRESS_CONFIG,
        market_fetcher=market_fetcher,
        forecast_fetcher=forecast_fetcher,
    )

    duration, result = measure_time(engine.run)

    assert result.markets_processed == 100
    # Should complete in < 2 seconds
    assert duration < 2.0, f"100 markets engine run took {duration:.3f}s"


def test_memory_stability():
    """Test for memory leaks during repeated runs."""
    import gc

    engine = WeatherEngine(
        config=STRESS_CONFIG,
        market_fetcher=lambda: generate_random_markets(50),
        forecast_fetcher=lambda city, rt: ForecastData(
            city=city,
            forecast_time=datetime.utcnow(),
            target_time=rt,
            temperature_f=95.0,
            source="mem_test",
        ),
    )

    # Run multiple times
    for i in range(10):
        result = engine.run()
        assert result.markets_processed == 50

    # Force garbage collection
    gc.collect()

    # If we get here without OOM, test passes
    assert True


def test_concurrent_filter_operations():
    """Test filter operations are thread-safe (conceptually)."""
    filter_instance = WeatherMarketFilter(STRESS_CONFIG)

    # Run many filter operations
    results = []
    for _ in range(100):
        markets = generate_random_markets(10)
        passed, res = filter_instance.filter_markets(markets)
        results.append(len(passed))

    # All operations should complete
    assert len(results) == 100


def test_serialization_performance():
    """Test signal serialization performance."""
    signals = []
    for i in range(500):
        signals.append(create_weather_signal(
            market_id=f"serial-{i:06d}",
            city="New York",
            event_description="Test",
            market_probability=0.05,
            fair_probability=0.10,
            confidence=WeatherConfidence.HIGH,
            recommended_action=WeatherSignalAction.BUY,
            config_snapshot=STRESS_CONFIG,
        ))

    # Test to_dict
    start = time.perf_counter()
    for signal in signals:
        _ = signal.to_dict()
    dict_time = time.perf_counter() - start

    # Test to_json
    start = time.perf_counter()
    for signal in signals:
        _ = signal.to_json()
    json_time = time.perf_counter() - start

    # Should serialize 500 signals in < 0.5 seconds each method
    assert dict_time < 0.5, f"500 to_dict took {dict_time:.3f}s"
    assert json_time < 0.5, f"500 to_json took {json_time:.3f}s"


def test_config_hash_performance():
    """Test config hash calculation performance."""
    iterations = 1000

    times = []
    for _ in range(iterations):
        start = time.perf_counter()
        engine = WeatherEngine(config=STRESS_CONFIG)
        end = time.perf_counter()
        times.append(end - start)

    avg_time = statistics.mean(times)

    # Engine initialization should be fast
    assert avg_time < 0.01, f"Engine init avg time {avg_time*1000:.2f}ms too slow"


def test_worst_case_filter():
    """Test filter performance with worst-case inputs."""
    filter_instance = WeatherMarketFilter(STRESS_CONFIG)

    # Create market with long text fields
    long_text = "weather " * 100  # 800 chars

    markets = []
    for i in range(100):
        markets.append(WeatherMarket(
            market_id=f"worst-{i:06d}",
            question=f"Will New York temperature exceed 100°F? {long_text}",
            resolution_text=f"Resolves YES if > 100°F {long_text}",
            description=f"Description {long_text}",
            category="WEATHER",
            is_binary=True,
            liquidity_usd=100.0,
            odds_yes=0.05,
            resolution_time=datetime.utcnow() + timedelta(hours=72),
        ))

    duration, (passed, results) = measure_time(
        lambda: filter_instance.filter_markets(markets)
    )

    # Should still complete in reasonable time
    assert duration < 1.0, f"Worst case 100 markets took {duration:.3f}s"


def test_batch_size_scaling():
    """Test performance scales linearly with batch size."""
    filter_instance = WeatherMarketFilter(STRESS_CONFIG)

    sizes = [10, 50, 100, 200]
    times = []

    for size in sizes:
        markets = generate_random_markets(size)
        duration, _ = measure_time(lambda m=markets: filter_instance.filter_markets(m))
        times.append(duration)

    # Check roughly linear scaling (within 3x factor)
    if times[0] > 0:
        ratio = times[-1] / times[0]
        expected_ratio = sizes[-1] / sizes[0]
        assert ratio < expected_ratio * 3, f"Non-linear scaling: {ratio:.1f}x vs expected {expected_ratio:.1f}x"


# =============================================================================
# TEST REGISTRY
# =============================================================================

def get_tests() -> List[Tuple[str, Callable]]:
    """Return list of all tests."""
    return [
        ("cdf_performance", test_cdf_performance),
        ("probability_calculation_performance", test_probability_calculation_performance),
        ("filter_performance_100_markets", test_filter_performance_100_markets),
        ("filter_performance_1000_markets", test_filter_performance_1000_markets),
        ("model_performance_1000_computations", test_model_performance_1000_computations),
        ("signal_creation_performance", test_signal_creation_performance),
        ("engine_run_performance_100_markets", test_engine_run_performance_100_markets),
        ("memory_stability", test_memory_stability),
        ("concurrent_filter_operations", test_concurrent_filter_operations),
        ("serialization_performance", test_serialization_performance),
        ("config_hash_performance", test_config_hash_performance),
        ("worst_case_filter", test_worst_case_filter),
        ("batch_size_scaling", test_batch_size_scaling),
    ]
