# =============================================================================
# WEATHER OBSERVER - LOGGING CONFIGURATION
# =============================================================================
#
# Simplified logging for weather observation system.
#
# =============================================================================

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path


def _get_project_root() -> Path:
    """Get the project root directory."""
    return Path(__file__).parent.parent


def _get_log_dir() -> Path:
    """Get the log directory."""
    return _get_project_root() / "logs"


def setup_logging(
    level: int = logging.INFO,
    console_output: bool = True,
    file_output: bool = True,
) -> None:
    """
    Configure logging for the weather observer.

    Uses RotatingFileHandler to prevent unbounded log growth.
    Max 5 MB per file, keeps 3 backups (= 20 MB total max).

    Args:
        level: Logging level
        console_output: Whether to log to console
        file_output: Whether to log to file
    """
    log_dir = _get_log_dir()
    log_dir.mkdir(parents=True, exist_ok=True)

    log_file = log_dir / "observer.log"

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    root_logger.handlers.clear()

    if console_output:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(level)
        console_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)

    if file_output:
        # Ensure log directory exists right before creating file handler
        os.makedirs(str(log_dir), exist_ok=True)
        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=5 * 1024 * 1024,  # 5 MB
            backupCount=3,
            encoding="utf-8",
        )
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)
