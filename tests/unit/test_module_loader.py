"""
UNIT TESTS - MODULE LOADER
===========================
Intensive Tests fuer shared/module_loader.py
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import tempfile
import os
from typing import List, Tuple, Callable

from shared.module_loader import (
    ModuleConfig,
    ModuleInfo,
    get_module_config,
    is_module_enabled,
    require_module_enabled,
)


# =============================================================================
# TEST FIXTURES
# =============================================================================

def create_temp_config_file(content: str) -> Path:
    """Create a temporary config file for testing."""
    fd, path = tempfile.mkstemp(suffix=".yaml")
    with os.fdopen(fd, 'w') as f:
        f.write(content)
    return Path(path)


VALID_CONFIG_YAML = """
global:
  master_enabled: true
  pipeline_interval: 900
  log_level: INFO

collector:
  enabled: true
  description: "Sammelt Marktdaten von Polymarket"
  interval_seconds: 900
  priority: 1
  category: "CORE"

weather_engine:
  enabled: true
  description: "Wetter-Markt Signal Generator"
  interval_seconds: 3600
  priority: 10
  category: "ENGINE"

paper_trader:
  enabled: false
  description: "Simulierter Trading Bot"
  interval_seconds: 60
  priority: 5
  category: "TRADING"
  warning: "Trades simuliert, kein echtes Geld"

disabled_module:
  enabled: false
  description: "A disabled module"
  interval_seconds: 100
  priority: 99
  category: "OTHER"
"""

MASTER_DISABLED_CONFIG = """
global:
  master_enabled: false
  pipeline_interval: 900

collector:
  enabled: true
  description: "Should be disabled by master"
  interval_seconds: 900
  priority: 1
  category: "CORE"
"""


# =============================================================================
# TEST FUNCTIONS
# =============================================================================

def test_module_config_load_valid():
    """Test loading valid configuration."""
    path = create_temp_config_file(VALID_CONFIG_YAML)
    try:
        config = ModuleConfig(path)

        assert config.master_enabled is True
        assert config.pipeline_interval == 900
        assert config.log_level == "INFO"
    finally:
        os.unlink(path)


def test_module_config_is_enabled():
    """Test is_enabled for various modules."""
    path = create_temp_config_file(VALID_CONFIG_YAML)
    try:
        config = ModuleConfig(path)

        assert config.is_enabled("collector") is True
        assert config.is_enabled("weather_engine") is True
        assert config.is_enabled("paper_trader") is False
        assert config.is_enabled("disabled_module") is False
    finally:
        os.unlink(path)


def test_module_config_unknown_module():
    """Test is_enabled for unknown module defaults to True."""
    path = create_temp_config_file(VALID_CONFIG_YAML)
    try:
        config = ModuleConfig(path)

        # Unknown modules default to enabled for backwards compatibility
        assert config.is_enabled("unknown_module") is True
    finally:
        os.unlink(path)


def test_module_config_master_disabled():
    """Test that master switch disables all modules."""
    path = create_temp_config_file(MASTER_DISABLED_CONFIG)
    try:
        config = ModuleConfig(path)

        assert config.master_enabled is False
        assert config.is_enabled("collector") is False  # Disabled by master
    finally:
        os.unlink(path)


def test_module_config_get_module():
    """Test getting module info."""
    path = create_temp_config_file(VALID_CONFIG_YAML)
    try:
        config = ModuleConfig(path)

        module = config.get_module("collector")

        assert module is not None
        assert isinstance(module, ModuleInfo)
        assert module.name == "collector"
        assert module.enabled is True
        assert module.category == "CORE"
        assert module.priority == 1
    finally:
        os.unlink(path)


def test_module_config_get_module_unknown():
    """Test getting unknown module returns None."""
    path = create_temp_config_file(VALID_CONFIG_YAML)
    try:
        config = ModuleConfig(path)

        module = config.get_module("nonexistent")

        assert module is None
    finally:
        os.unlink(path)


def test_module_config_get_enabled_modules():
    """Test getting list of enabled modules."""
    path = create_temp_config_file(VALID_CONFIG_YAML)
    try:
        config = ModuleConfig(path)

        enabled = config.get_enabled_modules()

        assert len(enabled) == 2  # collector and weather_engine
        names = [m.name for m in enabled]
        assert "collector" in names
        assert "weather_engine" in names
        assert "paper_trader" not in names
    finally:
        os.unlink(path)


def test_module_config_get_enabled_sorted_by_priority():
    """Test enabled modules are sorted by priority."""
    path = create_temp_config_file(VALID_CONFIG_YAML)
    try:
        config = ModuleConfig(path)

        enabled = config.get_enabled_modules()

        # Should be sorted by priority (lowest first)
        priorities = [m.priority for m in enabled]
        assert priorities == sorted(priorities)
    finally:
        os.unlink(path)


def test_module_config_get_modules_by_category():
    """Test getting modules by category."""
    path = create_temp_config_file(VALID_CONFIG_YAML)
    try:
        config = ModuleConfig(path)

        core_modules = config.get_modules_by_category("CORE")

        assert len(core_modules) == 1
        assert core_modules[0].name == "collector"
    finally:
        os.unlink(path)


def test_module_config_get_enabled_by_category():
    """Test getting enabled modules by category."""
    path = create_temp_config_file(VALID_CONFIG_YAML)
    try:
        config = ModuleConfig(path)

        trading = config.get_enabled_by_category("TRADING")

        # paper_trader is in TRADING but disabled
        assert len(trading) == 0
    finally:
        os.unlink(path)


def test_module_config_get_all_modules():
    """Test getting all modules."""
    path = create_temp_config_file(VALID_CONFIG_YAML)
    try:
        config = ModuleConfig(path)

        all_modules = config.get_all_modules()

        assert len(all_modules) == 4
    finally:
        os.unlink(path)


def test_module_config_get_categories():
    """Test getting all categories."""
    path = create_temp_config_file(VALID_CONFIG_YAML)
    try:
        config = ModuleConfig(path)

        categories = config.get_categories()

        assert "CORE" in categories
        assert "ENGINE" in categories
        assert "TRADING" in categories
        assert "OTHER" in categories
    finally:
        os.unlink(path)


def test_module_config_to_dict():
    """Test serialization to dict."""
    path = create_temp_config_file(VALID_CONFIG_YAML)
    try:
        config = ModuleConfig(path)

        d = config.to_dict()

        assert "master_enabled" in d
        assert "pipeline_interval" in d
        assert "modules" in d
        assert "collector" in d["modules"]
    finally:
        os.unlink(path)


def test_module_config_reload():
    """Test reloading configuration."""
    path = create_temp_config_file(VALID_CONFIG_YAML)
    try:
        config = ModuleConfig(path)

        # Initial state
        assert config.is_enabled("collector") is True

        # Modify file (disable collector)
        new_content = VALID_CONFIG_YAML.replace(
            "collector:\n  enabled: true",
            "collector:\n  enabled: false"
        )
        with open(path, 'w') as f:
            f.write(new_content)

        # Reload
        config.reload()

        # Should now be disabled
        assert config.is_enabled("collector") is False
    finally:
        os.unlink(path)


def test_module_info_is_dangerous():
    """Test is_dangerous property for modules with warnings."""
    path = create_temp_config_file(VALID_CONFIG_YAML)
    try:
        config = ModuleConfig(path)

        paper_trader = config.get_module("paper_trader")
        collector = config.get_module("collector")

        assert paper_trader.is_dangerous is True  # Has warning
        assert collector.is_dangerous is False    # No warning
    finally:
        os.unlink(path)


def test_module_config_file_not_found():
    """Test handling of missing config file."""
    config = ModuleConfig(Path("/nonexistent/path.yaml"))

    # Should default to enabled for unknown modules
    assert config.master_enabled is True
    assert config.is_enabled("any_module") is True


def test_module_config_invalid_yaml():
    """Test handling of invalid YAML."""
    path = create_temp_config_file("invalid: yaml: content: [")
    try:
        config = ModuleConfig(path)

        # Should handle gracefully
        assert config.master_enabled is True
    finally:
        os.unlink(path)


def test_module_config_empty_file():
    """Test handling of empty config file."""
    path = create_temp_config_file("")
    try:
        config = ModuleConfig(path)

        assert config.master_enabled is True  # Default
    finally:
        os.unlink(path)


def test_require_module_enabled_decorator():
    """Test require_module_enabled decorator."""
    path = create_temp_config_file(VALID_CONFIG_YAML)

    # Temporarily override the singleton
    import shared.module_loader as ml
    old_instance = ml._instance

    try:
        ml._instance = ModuleConfig(path)

        # Create decorated function
        call_count = [0]

        @require_module_enabled("collector")
        def enabled_func():
            call_count[0] += 1
            return "executed"

        @require_module_enabled("disabled_module")
        def disabled_func():
            call_count[0] += 1
            return "executed"

        # Enabled module - should execute
        result1 = enabled_func()
        assert result1 == "executed"
        assert call_count[0] == 1

        # Disabled module - should not execute
        result2 = disabled_func()
        assert result2 is None
        assert call_count[0] == 1  # Not incremented
    finally:
        ml._instance = old_instance
        os.unlink(path)


def test_is_module_enabled_function():
    """Test convenience function is_module_enabled."""
    path = create_temp_config_file(VALID_CONFIG_YAML)

    import shared.module_loader as ml
    old_instance = ml._instance

    try:
        ml._instance = ModuleConfig(path)

        assert is_module_enabled("collector") is True
        assert is_module_enabled("disabled_module") is False
    finally:
        ml._instance = old_instance
        os.unlink(path)


def test_get_module_config_singleton():
    """Test get_module_config returns singleton."""
    import shared.module_loader as ml
    old_instance = ml._instance

    try:
        ml._instance = None  # Reset

        config1 = get_module_config()
        config2 = get_module_config()

        assert config1 is config2
    finally:
        ml._instance = old_instance


def test_module_info_properties():
    """Test ModuleInfo dataclass properties."""
    info = ModuleInfo(
        name="test",
        enabled=True,
        description="Test module",
        interval_seconds=60,
        priority=5,
        category="TEST",
        warning="Be careful!",
    )

    assert info.name == "test"
    assert info.enabled is True
    assert info.description == "Test module"
    assert info.interval_seconds == 60
    assert info.priority == 5
    assert info.category == "TEST"
    assert info.warning == "Be careful!"
    assert info.is_dangerous is True


def test_module_config_defaults():
    """Test configuration defaults."""
    minimal_config = """
global:
  master_enabled: true

minimal_module:
  enabled: true
"""
    path = create_temp_config_file(minimal_config)
    try:
        config = ModuleConfig(path)

        module = config.get_module("minimal_module")

        # Check defaults are applied
        assert module.description == ""
        assert module.interval_seconds == 0
        assert module.priority == 99
        assert module.category == "OTHER"
        assert module.warning is None
    finally:
        os.unlink(path)


# =============================================================================
# TEST REGISTRY
# =============================================================================

def get_tests() -> List[Tuple[str, Callable]]:
    """Return list of all tests."""
    return [
        ("module_config_load_valid", test_module_config_load_valid),
        ("module_config_is_enabled", test_module_config_is_enabled),
        ("module_config_unknown_module", test_module_config_unknown_module),
        ("module_config_master_disabled", test_module_config_master_disabled),
        ("module_config_get_module", test_module_config_get_module),
        ("module_config_get_module_unknown", test_module_config_get_module_unknown),
        ("module_config_get_enabled_modules", test_module_config_get_enabled_modules),
        ("module_config_get_enabled_sorted_by_priority", test_module_config_get_enabled_sorted_by_priority),
        ("module_config_get_modules_by_category", test_module_config_get_modules_by_category),
        ("module_config_get_enabled_by_category", test_module_config_get_enabled_by_category),
        ("module_config_get_all_modules", test_module_config_get_all_modules),
        ("module_config_get_categories", test_module_config_get_categories),
        ("module_config_to_dict", test_module_config_to_dict),
        ("module_config_reload", test_module_config_reload),
        ("module_info_is_dangerous", test_module_info_is_dangerous),
        ("module_config_file_not_found", test_module_config_file_not_found),
        ("module_config_invalid_yaml", test_module_config_invalid_yaml),
        ("module_config_empty_file", test_module_config_empty_file),
        ("require_module_enabled_decorator", test_require_module_enabled_decorator),
        ("is_module_enabled_function", test_is_module_enabled_function),
        ("get_module_config_singleton", test_get_module_config_singleton),
        ("module_info_properties", test_module_info_properties),
        ("module_config_defaults", test_module_config_defaults),
    ]
