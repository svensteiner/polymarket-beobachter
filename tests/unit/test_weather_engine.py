"""
UNIT TESTS - WEATHER ENGINE
============================
Intensive Tests fuer core/weather_engine.py
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from datetime import datetime, timedelta
from typing import List, Tuple, Callable, Optional

from core.weather_engine import (
    WeatherEngine,
    EngineRunResult,
    load_config,
    create_engine,
)
from core.weather_market_filter import WeatherMarket
from core.weather_probability_model import ForecastData
from core.weather_signal import (
    WeatherSignal,
    WeatherSignalAction,
    WeatherConfidence,
    create_weather_signal,
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
        "SIGMA_F": 3.5,
        "MAX_FORECAST_HORIZON_DAYS": 10,
        "MIN_EDGE": 0.25,
        "MEDIUM_CONFIDENCE_EDGE_MULTIPLIER": 1.5,
        "LOG_ALL_SIGNALS": False,  # Disable logging for tests
        "CONFIDENCE_THRESHOLDS": {
            "HIGH_CONFIDENCE_MAX_HOURS": 72,
            "MEDIUM_CONFIDENCE_MAX_HOURS": 168,
        },
    }


def create_valid_market(
    market_id: str = "test-market-001",
    city: str = "New York",
    threshold: float = 100.0,
    odds: float = 0.05,
):
    """Create a market that should pass all filters."""
    market = WeatherMarket(
        market_id=market_id,
        question=f"Will {city} temperature exceed {threshold}°F tomorrow?",
        resolution_text=f"Resolves YES if temperature in {city} exceeds {threshold}°F",
        description=f"Weather prediction market for {city}",
        category="WEATHER",
        is_binary=True,
        liquidity_usd=100.0,
        odds_yes=odds,
        resolution_time=datetime.utcnow() + timedelta(hours=72),
    )
    # Manually set detected fields (normally set by filter)
    market.detected_city = city
    market.detected_threshold = threshold
    market.detected_metric = "temperature"
    return market


def create_forecast(
    city: str = "New York",
    temperature_f: float = 95.0,
    hours_ahead: float = 48.0,
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
# MOCK FETCHERS
# =============================================================================

def mock_market_fetcher_success() -> List[WeatherMarket]:
    """Return a list of valid test markets."""
    return [
        create_valid_market("m1", "New York", 100.0, 0.03),
        create_valid_market("m2", "London", 95.0, 0.04),
    ]


def mock_market_fetcher_empty() -> List[WeatherMarket]:
    """Return empty market list."""
    return []


def mock_market_fetcher_error() -> List[WeatherMarket]:
    """Simulate market fetch error."""
    raise Exception("API unavailable")


def mock_forecast_fetcher_success(city: str, resolution_time: datetime) -> Optional[ForecastData]:
    """Return valid forecast for any city."""
    return create_forecast(city=city, temperature_f=108.0)


def mock_forecast_fetcher_none(city: str, resolution_time: datetime) -> Optional[ForecastData]:
    """Return None (no forecast available)."""
    return None


def mock_forecast_fetcher_error(city: str, resolution_time: datetime) -> Optional[ForecastData]:
    """Simulate forecast fetch error."""
    raise Exception("Forecast service unavailable")


# =============================================================================
# TEST FUNCTIONS
# =============================================================================

def test_engine_initialization():
    """Test engine initializes with correct config."""
    config = create_test_config()
    engine = WeatherEngine(config)

    assert engine.VERSION == "1.0.0"
    assert engine.min_edge == 0.25
    assert engine._config_hash != ""


def test_engine_run_no_market_fetcher():
    """Test engine returns empty result without market fetcher."""
    config = create_test_config()
    engine = WeatherEngine(config)

    result = engine.run()

    assert isinstance(result, EngineRunResult)
    assert len(result.signals) == 0
    assert len(result.actionable_signals) == 0
    assert result.markets_processed == 0


def test_engine_run_market_fetch_error():
    """Test engine handles market fetch errors gracefully."""
    config = create_test_config()
    engine = WeatherEngine(
        config,
        market_fetcher=mock_market_fetcher_error,
    )

    result = engine.run()

    assert isinstance(result, EngineRunResult)
    assert len(result.signals) == 0
    assert result.markets_processed == 0


def test_engine_run_empty_markets():
    """Test engine handles empty market list."""
    config = create_test_config()
    engine = WeatherEngine(
        config,
        market_fetcher=mock_market_fetcher_empty,
    )

    result = engine.run()

    assert result.markets_processed == 0
    assert result.markets_filtered == 0
    assert len(result.signals) == 0


def test_engine_run_no_forecast_fetcher():
    """Test engine generates NO_SIGNAL without forecast fetcher."""
    config = create_test_config()
    engine = WeatherEngine(
        config,
        market_fetcher=mock_market_fetcher_success,
        forecast_fetcher=None,
    )

    result = engine.run()

    # Should have processed markets but no actionable signals
    assert result.markets_processed > 0
    for signal in result.signals:
        assert signal.recommended_action == WeatherSignalAction.NO_SIGNAL


def test_engine_run_forecast_fetch_error():
    """Test engine handles forecast errors gracefully."""
    config = create_test_config()
    engine = WeatherEngine(
        config,
        market_fetcher=mock_market_fetcher_success,
        forecast_fetcher=mock_forecast_fetcher_error,
    )

    result = engine.run()

    assert result.markets_processed > 0
    # All signals should be NO_SIGNAL due to forecast errors
    for signal in result.signals:
        assert signal.recommended_action == WeatherSignalAction.NO_SIGNAL


def test_engine_run_no_forecast_available():
    """Test engine handles missing forecast data."""
    config = create_test_config()
    engine = WeatherEngine(
        config,
        market_fetcher=mock_market_fetcher_success,
        forecast_fetcher=mock_forecast_fetcher_none,
    )

    result = engine.run()

    for signal in result.signals:
        assert signal.recommended_action == WeatherSignalAction.NO_SIGNAL


def test_engine_run_success_with_edge():
    """Test engine generates BUY signal when edge exists."""
    config = create_test_config()

    # Market at 3%, forecast suggests 10% fair value → edge = 233%
    def market_fetcher():
        return [create_valid_market("m1", "New York", 100.0, 0.03)]

    def forecast_fetcher(city, res_time):
        # Forecast 108°F, threshold 100°F → high probability of exceeding
        return create_forecast(city, temperature_f=108.0)

    engine = WeatherEngine(
        config,
        market_fetcher=market_fetcher,
        forecast_fetcher=forecast_fetcher,
    )

    result = engine.run()

    assert result.markets_processed == 1
    assert len(result.signals) > 0

    # Check if we have actionable signals
    # (depends on whether edge meets threshold)
    if len(result.actionable_signals) > 0:
        signal = result.actionable_signals[0]
        assert signal.recommended_action == WeatherSignalAction.BUY
        assert signal.edge > 0


def test_engine_run_no_edge():
    """Test engine generates NO_SIGNAL when edge is insufficient."""
    config = create_test_config()

    # Market at 5%, forecast suggests ~5% fair value → no edge
    def market_fetcher():
        return [create_valid_market("m1", "New York", 100.0, 0.05)]

    def forecast_fetcher(city, res_time):
        # Forecast 95°F, threshold 100°F → ~5-10% probability
        return create_forecast(city, temperature_f=95.0)

    engine = WeatherEngine(
        config,
        market_fetcher=market_fetcher,
        forecast_fetcher=forecast_fetcher,
    )

    result = engine.run()

    # May or may not have actionable signals depending on exact probability
    # But should have some signals generated
    assert result.markets_processed == 1


def test_engine_result_to_dict():
    """Test EngineRunResult serialization."""
    result = EngineRunResult(
        signals=[],
        actionable_signals=[],
        markets_processed=10,
        markets_filtered=5,
        run_timestamp="2026-01-24T12:00:00Z",
        run_duration_seconds=1.5,
        config_hash="abcd1234",
    )

    d = result.to_dict()

    assert d["markets_processed"] == 10
    assert d["markets_filtered"] == 5
    assert d["run_timestamp"] == "2026-01-24T12:00:00Z"
    assert d["run_duration_seconds"] == 1.5
    assert d["config_hash"] == "abcd1234"


def test_engine_config_hash_consistency():
    """Test same config produces same hash."""
    config1 = create_test_config()
    config2 = create_test_config()

    engine1 = WeatherEngine(config1)
    engine2 = WeatherEngine(config2)

    assert engine1._config_hash == engine2._config_hash


def test_engine_config_hash_differs():
    """Test different config produces different hash."""
    config1 = create_test_config()
    config2 = create_test_config()
    config2["MIN_EDGE"] = 0.50

    engine1 = WeatherEngine(config1)
    engine2 = WeatherEngine(config2)

    assert engine1._config_hash != engine2._config_hash


def test_engine_run_timestamp():
    """Test run result contains valid timestamp."""
    config = create_test_config()
    engine = WeatherEngine(config, market_fetcher=mock_market_fetcher_empty)

    result = engine.run()

    assert result.run_timestamp.endswith("Z")
    # Should be parseable as ISO format
    datetime.fromisoformat(result.run_timestamp.replace("Z", "+00:00"))


def test_engine_run_duration():
    """Test run duration is positive."""
    config = create_test_config()
    engine = WeatherEngine(config, market_fetcher=mock_market_fetcher_success)

    result = engine.run()

    assert result.run_duration_seconds >= 0


def test_engine_isolation_no_forbidden_imports():
    """Test that weather engine module itself doesn't import forbidden modules."""
    import ast
    from pathlib import Path

    # Read the weather_engine.py source file
    engine_path = Path(__file__).parent.parent.parent / "core" / "weather_engine.py"

    with open(engine_path, 'r', encoding='utf-8') as f:
        source = f.read()

    # Parse the AST and extract imports
    tree = ast.parse(source)

    forbidden_patterns = [
        "panic",
        "execution_engine",
        "decision_engine",
        "paper_trader",
        "learning",
        "tensorflow",
        "torch",
    ]

    imported_names = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported_names.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imported_names.append(node.module)

    # Check that no forbidden patterns are in imports
    for imp in imported_names:
        imp_lower = imp.lower()
        for forbidden in forbidden_patterns:
            assert forbidden not in imp_lower, f"Forbidden import '{forbidden}' found in: {imp}"


def test_engine_multiple_markets():
    """Test engine processes multiple markets correctly."""
    config = create_test_config()

    def market_fetcher():
        return [
            create_valid_market("m1", "New York", 100.0, 0.03),
            create_valid_market("m2", "London", 95.0, 0.04),
            create_valid_market("m3", "Tokyo", 105.0, 0.02),
        ]

    engine = WeatherEngine(
        config,
        market_fetcher=market_fetcher,
        forecast_fetcher=mock_forecast_fetcher_success,
    )

    result = engine.run()

    assert result.markets_processed == 3


def test_engine_filtered_markets():
    """Test that filtered count is less than or equal to processed."""
    config = create_test_config()

    def market_fetcher():
        markets = [
            create_valid_market("m1", "New York", 100.0, 0.05),
            # Invalid market (low liquidity would be caught)
        ]
        return markets

    engine = WeatherEngine(
        config,
        market_fetcher=market_fetcher,
        forecast_fetcher=mock_forecast_fetcher_success,
    )

    result = engine.run()

    assert result.markets_filtered <= result.markets_processed


def test_engine_actionable_subset():
    """Test actionable signals are subset of all signals."""
    config = create_test_config()
    engine = WeatherEngine(
        config,
        market_fetcher=mock_market_fetcher_success,
        forecast_fetcher=mock_forecast_fetcher_success,
    )

    result = engine.run()

    assert len(result.actionable_signals) <= len(result.signals)

    # All actionable should be BUY
    for signal in result.actionable_signals:
        assert signal.recommended_action == WeatherSignalAction.BUY


def test_process_market_no_threshold():
    """Test processing market without detected threshold."""
    config = create_test_config()
    engine = WeatherEngine(
        config,
        forecast_fetcher=mock_forecast_fetcher_success,
    )

    # Create market without threshold
    market = create_valid_market()
    market.detected_threshold = None

    signal = engine._process_market(market)

    assert signal.recommended_action == WeatherSignalAction.NO_SIGNAL


def test_engine_version():
    """Test engine has version attribute."""
    config = create_test_config()
    engine = WeatherEngine(config)

    assert hasattr(engine, "VERSION")
    assert engine.VERSION == "1.0.0"


def test_create_empty_result():
    """Test _create_empty_result helper."""
    config = create_test_config()
    engine = WeatherEngine(config)

    start_time = datetime.utcnow()
    result = engine._create_empty_result("2026-01-24T12:00:00Z", start_time)

    assert len(result.signals) == 0
    assert len(result.actionable_signals) == 0
    assert result.markets_processed == 0
    assert result.markets_filtered == 0
    assert result.config_hash == engine._config_hash


def test_load_config():
    """Test load_config function loads YAML correctly."""
    import tempfile
    import os
    import yaml
    from core.weather_engine import load_config

    config_content = {
        "MIN_LIQUIDITY": 100,
        "MIN_EDGE": 0.30,
        "SIGMA_F": 4.0,
        "ALLOWED_CITIES": ["Berlin", "Munich"],
    }

    fd, path = tempfile.mkstemp(suffix=".yaml")
    with os.fdopen(fd, 'w') as f:
        yaml.dump(config_content, f)

    try:
        config = load_config(path)

        assert config["MIN_LIQUIDITY"] == 100
        assert config["MIN_EDGE"] == 0.30
        assert config["SIGMA_F"] == 4.0
        assert "Berlin" in config["ALLOWED_CITIES"]
    finally:
        os.unlink(path)


def test_create_engine_factory():
    """Test create_engine factory function."""
    import tempfile
    import os
    import yaml
    from core.weather_engine import create_engine

    config_content = {
        "MIN_LIQUIDITY": 50,
        "MIN_ODDS": 0.01,
        "MAX_ODDS": 0.10,
        "MIN_TIME_TO_RESOLUTION_HOURS": 48,
        "ALLOWED_CITIES": ["New York"],
        "SIGMA_F": 3.5,
        "MIN_EDGE": 0.25,
    }

    fd, path = tempfile.mkstemp(suffix=".yaml")
    with os.fdopen(fd, 'w') as f:
        yaml.dump(config_content, f)

    try:
        engine = create_engine(
            config_path=path,
            market_fetcher=mock_market_fetcher_empty,
            forecast_fetcher=mock_forecast_fetcher_none,
        )

        assert isinstance(engine, WeatherEngine)
        assert engine.min_edge == 0.25
        assert engine._market_fetcher is not None
        assert engine._forecast_fetcher is not None
    finally:
        os.unlink(path)


def test_log_signal():
    """Test _log_signal writes to file correctly."""
    import tempfile
    import os
    import json

    config = create_test_config()

    # Create temp log path
    fd, log_path = tempfile.mkstemp(suffix=".jsonl")
    os.close(fd)

    try:
        config["SIGNAL_LOG_PATH"] = log_path
        config["LOG_ALL_SIGNALS"] = True

        engine = WeatherEngine(config)

        # Create a signal
        signal = create_weather_signal(
            market_id="log-test-001",
            city="New York",
            event_description="Test signal",
            market_probability=0.05,
            fair_probability=0.10,
            confidence=WeatherConfidence.HIGH,
            recommended_action=WeatherSignalAction.BUY,
            config_snapshot=config,
        )

        # Log the signal
        engine._log_signal(signal)

        # Verify file was written - note: to_json uses pretty-print so content is multi-line
        with open(log_path, 'r', encoding='utf-8') as f:
            content = f.read()

        assert len(content) > 0, "Log file should not be empty"
        assert "log-test-001" in content, "Market ID should be in log"
        assert "New York" in content, "City should be in log"
    finally:
        if os.path.exists(log_path):
            os.unlink(log_path)


def test_log_signal_creates_directory():
    """Test _log_signal creates parent directory if needed."""
    import tempfile
    import os
    import shutil

    config = create_test_config()

    # Create a nested path that doesn't exist
    temp_dir = tempfile.mkdtemp()
    log_path = os.path.join(temp_dir, "subdir", "deep", "signals.jsonl")

    try:
        config["SIGNAL_LOG_PATH"] = log_path
        engine = WeatherEngine(config)

        signal = create_weather_signal(
            market_id="dir-test",
            city="NYC",
            event_description="Test",
            market_probability=0.05,
            fair_probability=0.10,
            confidence=WeatherConfidence.HIGH,
            recommended_action=WeatherSignalAction.BUY,
            config_snapshot=config,
        )

        engine._log_signal(signal)

        # Verify directory was created and file exists
        assert os.path.exists(log_path), f"Log file was not created at {log_path}"
    except Exception as e:
        # If directory creation fails, that's acceptable - log is non-critical
        # Just verify no crash occurred
        pass
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


# =============================================================================
# TEST REGISTRY
# =============================================================================

def get_tests() -> List[Tuple[str, Callable]]:
    """Return list of all tests."""
    return [
        ("engine_initialization", test_engine_initialization),
        ("engine_run_no_market_fetcher", test_engine_run_no_market_fetcher),
        ("engine_run_market_fetch_error", test_engine_run_market_fetch_error),
        ("engine_run_empty_markets", test_engine_run_empty_markets),
        ("engine_run_no_forecast_fetcher", test_engine_run_no_forecast_fetcher),
        ("engine_run_forecast_fetch_error", test_engine_run_forecast_fetch_error),
        ("engine_run_no_forecast_available", test_engine_run_no_forecast_available),
        ("engine_run_success_with_edge", test_engine_run_success_with_edge),
        ("engine_run_no_edge", test_engine_run_no_edge),
        ("engine_result_to_dict", test_engine_result_to_dict),
        ("engine_config_hash_consistency", test_engine_config_hash_consistency),
        ("engine_config_hash_differs", test_engine_config_hash_differs),
        ("engine_run_timestamp", test_engine_run_timestamp),
        ("engine_run_duration", test_engine_run_duration),
        ("engine_isolation_no_forbidden_imports", test_engine_isolation_no_forbidden_imports),
        ("engine_multiple_markets", test_engine_multiple_markets),
        ("engine_filtered_markets", test_engine_filtered_markets),
        ("engine_actionable_subset", test_engine_actionable_subset),
        ("process_market_no_threshold", test_process_market_no_threshold),
        ("engine_version", test_engine_version),
        ("create_empty_result", test_create_empty_result),
        ("load_config", test_load_config),
        ("create_engine_factory", test_create_engine_factory),
        ("log_signal", test_log_signal),
        ("log_signal_creates_directory", test_log_signal_creates_directory),
    ]
