# =============================================================================
# POLYMARKET BEOBACHTER - MODULE LOADER
# =============================================================================
#
# GOVERNANCE:
# This module provides centralized module configuration loading.
# It reads from config/modules.yaml and determines which modules should run.
#
# USAGE:
#   from shared.module_loader import ModuleConfig
#
#   config = ModuleConfig()
#   if config.is_enabled("weather_engine"):
#       # Run weather engine
#
# =============================================================================

import sys
import logging
from pathlib import Path
from typing import Dict, Any, Optional, List
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Base directory
BASE_DIR = Path(__file__).parent.parent
CONFIG_PATH = BASE_DIR / "config" / "modules.yaml"


@dataclass
class ModuleInfo:
    """Information about a single module."""
    name: str
    enabled: bool
    description: str
    interval_seconds: int
    priority: int
    category: str
    warning: Optional[str] = None

    @property
    def is_dangerous(self) -> bool:
        """Check if module has a warning (potentially dangerous)."""
        return self.warning is not None


class ModuleConfig:
    """
    Central module configuration manager.

    Reads from config/modules.yaml and provides methods to check
    which modules are enabled.

    GOVERNANCE:
    - This is READ-ONLY access to configuration
    - Changes require editing the YAML file
    - The control_center.py provides GUI for editing
    """

    def __init__(self, config_path: Optional[Path] = None):
        """
        Initialize module configuration.

        Args:
            config_path: Path to modules.yaml. Defaults to config/modules.yaml
        """
        self.config_path = config_path or CONFIG_PATH
        self._config: Dict[str, Any] = {}
        self._modules: Dict[str, ModuleInfo] = {}
        self._load_config()

    def _load_config(self):
        """Load configuration from YAML file."""
        try:
            import yaml
        except ImportError:
            logger.warning("PyYAML not installed, using defaults")
            self._config = {"global": {"master_enabled": True}}
            return

        if not self.config_path.exists():
            logger.warning(f"Config file not found: {self.config_path}")
            self._config = {"global": {"master_enabled": True}}
            return

        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                self._config = yaml.safe_load(f) or {}
        except Exception as e:
            logger.error(f"Failed to load config: {e}")
            self._config = {"global": {"master_enabled": True}}
            return

        # Parse modules
        for name, mod_config in self._config.items():
            if name == "global" or not isinstance(mod_config, dict):
                continue

            self._modules[name] = ModuleInfo(
                name=name,
                enabled=mod_config.get("enabled", False),
                description=mod_config.get("description", ""),
                interval_seconds=mod_config.get("interval_seconds", 0),
                priority=mod_config.get("priority", 99),
                category=mod_config.get("category", "OTHER"),
                warning=mod_config.get("warning"),
            )

        logger.info(f"Loaded {len(self._modules)} modules from config")

    def reload(self):
        """Reload configuration from file."""
        self._modules.clear()
        self._load_config()

    @property
    def master_enabled(self) -> bool:
        """Check if master switch is enabled."""
        global_config = self._config.get("global", {})
        return global_config.get("master_enabled", True)

    @property
    def pipeline_interval(self) -> int:
        """Get pipeline interval in seconds."""
        global_config = self._config.get("global", {})
        return global_config.get("pipeline_interval", 900)

    @property
    def log_level(self) -> str:
        """Get configured log level."""
        global_config = self._config.get("global", {})
        return global_config.get("log_level", "INFO")

    def is_enabled(self, module_name: str) -> bool:
        """
        Check if a module is enabled.

        Args:
            module_name: Name of the module (e.g., "collector", "weather_engine")

        Returns:
            True if module is enabled AND master is enabled
        """
        if not self.master_enabled:
            return False

        if module_name not in self._modules:
            # Module not in config - default to enabled for backwards compatibility
            logger.warning(f"Module '{module_name}' not in config, defaulting to enabled")
            return True

        return self._modules[module_name].enabled

    def get_module(self, module_name: str) -> Optional[ModuleInfo]:
        """Get module info by name."""
        return self._modules.get(module_name)

    def get_enabled_modules(self) -> List[ModuleInfo]:
        """Get list of all enabled modules, sorted by priority."""
        if not self.master_enabled:
            return []

        enabled = [m for m in self._modules.values() if m.enabled]
        return sorted(enabled, key=lambda m: m.priority)

    def get_modules_by_category(self, category: str) -> List[ModuleInfo]:
        """Get all modules in a category."""
        return [m for m in self._modules.values() if m.category == category]

    def get_enabled_by_category(self, category: str) -> List[ModuleInfo]:
        """Get enabled modules in a category."""
        if not self.master_enabled:
            return []
        return [m for m in self._modules.values() if m.category == category and m.enabled]

    def get_all_modules(self) -> List[ModuleInfo]:
        """Get all configured modules."""
        return list(self._modules.values())

    def get_categories(self) -> List[str]:
        """Get list of all categories."""
        return list(set(m.category for m in self._modules.values()))

    def to_dict(self) -> Dict[str, Any]:
        """Export configuration as dictionary."""
        return {
            "master_enabled": self.master_enabled,
            "pipeline_interval": self.pipeline_interval,
            "modules": {
                name: {
                    "enabled": m.enabled,
                    "category": m.category,
                    "priority": m.priority,
                }
                for name, m in self._modules.items()
            }
        }


# =============================================================================
# MODULE-LEVEL FUNCTIONS
# =============================================================================

# Singleton instance
_instance: Optional[ModuleConfig] = None


def get_module_config() -> ModuleConfig:
    """
    Get the global ModuleConfig instance.

    Returns:
        ModuleConfig singleton
    """
    global _instance
    if _instance is None:
        _instance = ModuleConfig()
    return _instance


def is_module_enabled(module_name: str) -> bool:
    """
    Convenience function to check if a module is enabled.

    Args:
        module_name: Name of the module

    Returns:
        True if enabled
    """
    return get_module_config().is_enabled(module_name)


def require_module_enabled(module_name: str):
    """
    Decorator to require a module to be enabled.

    If module is disabled, the function returns None without executing.

    Usage:
        @require_module_enabled("weather_engine")
        def run_weather_engine():
            ...
    """
    def decorator(func):
        def wrapper(*args, **kwargs):
            if not is_module_enabled(module_name):
                logger.info(f"Module '{module_name}' is disabled, skipping {func.__name__}")
                return None
            return func(*args, **kwargs)
        return wrapper
    return decorator


# =============================================================================
# CLI INTERFACE
# =============================================================================

def print_status():
    """Print module status to console."""
    config = get_module_config()

    print("\n" + "=" * 60)
    print("POLYMARKET BEOBACHTER - MODULE STATUS")
    print("=" * 60)

    print(f"\nMaster Switch: {'ON' if config.master_enabled else 'OFF'}")
    print(f"Pipeline Interval: {config.pipeline_interval}s")

    print("\n" + "-" * 60)
    print(f"{'MODULE':<25} {'STATUS':<10} {'CATEGORY':<15} {'PRIORITY'}")
    print("-" * 60)

    for module in sorted(config.get_all_modules(), key=lambda m: (m.category, m.priority)):
        status = "ENABLED" if module.enabled else "disabled"
        status_color = "\033[92m" if module.enabled else "\033[91m"
        reset = "\033[0m"

        print(f"{module.name:<25} {status_color}{status:<10}{reset} {module.category:<15} {module.priority}")

    print("-" * 60)

    enabled = config.get_enabled_modules()
    print(f"\nEnabled: {len(enabled)} / {len(config.get_all_modules())} modules")
    print()


if __name__ == "__main__":
    print_status()
