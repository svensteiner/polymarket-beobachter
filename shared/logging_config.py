# =============================================================================
# POLYMARKET BEOBACHTER - LOGGING CONFIGURATION
# =============================================================================
#
# GOVERNANCE:
# Logs are STRICTLY SEPARATED by layer.
# - Layer 1 logs go to logs/layer1/
# - Layer 2 logs go to logs/layer2/
# - Collector logs go to logs/collector/
#
# This ensures audit trail integrity and prevents cross-contamination.
#
# =============================================================================

import logging
import os
from datetime import datetime
from typing import Optional
from pathlib import Path

from .enums import Layer


# =============================================================================
# LOG DIRECTORIES (relative to project root)
# =============================================================================

def _get_project_root() -> Path:
    """Get the project root directory."""
    # This file is at shared/logging_config.py
    # Project root is one level up
    return Path(__file__).parent.parent


def _get_log_dir(layer: Optional[Layer] = None) -> Path:
    """Get the log directory for a specific layer."""
    root = _get_project_root()

    if layer == Layer.LAYER1_INSTITUTIONAL:
        return root / "logs" / "layer1"
    elif layer == Layer.LAYER2_MICROSTRUCTURE:
        return root / "logs" / "layer2"
    else:
        return root / "logs" / "collector"


# =============================================================================
# LOGGING SETUP
# =============================================================================

def setup_logging(
    layer: Optional[Layer] = None,
    level: int = logging.INFO,
    console_output: bool = True,
    file_output: bool = True,
) -> None:
    """
    Configure logging for a specific layer.

    Args:
        layer: The layer to configure logging for (None for collector)
        level: Logging level
        console_output: Whether to log to console
        file_output: Whether to log to file
    """
    # Determine log directory and file name
    log_dir = _get_log_dir(layer)
    log_dir.mkdir(parents=True, exist_ok=True)

    # Create timestamp for log file
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    if layer == Layer.LAYER1_INSTITUTIONAL:
        log_file = log_dir / f"layer1_{timestamp}.log"
        logger_name = "layer1"
    elif layer == Layer.LAYER2_MICROSTRUCTURE:
        log_file = log_dir / f"layer2_{timestamp}.log"
        logger_name = "layer2"
    else:
        log_file = log_dir / f"collector_{timestamp}.log"
        logger_name = "collector"

    # Create formatter
    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # Get or create logger
    logger = logging.getLogger(logger_name)
    logger.setLevel(level)

    # Remove existing handlers to avoid duplicates
    logger.handlers.clear()

    # Add console handler
    if console_output:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(level)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

    # Add file handler
    if file_output:
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    # Log startup
    logger.info(f"Logging initialized for {logger_name}")
    logger.info(f"Log file: {log_file}")


def get_layer_logger(layer: Optional[Layer] = None) -> logging.Logger:
    """
    Get a logger for a specific layer.

    Args:
        layer: The layer to get logger for

    Returns:
        Configured logger instance
    """
    if layer == Layer.LAYER1_INSTITUTIONAL:
        return logging.getLogger("layer1")
    elif layer == Layer.LAYER2_MICROSTRUCTURE:
        return logging.getLogger("layer2")
    else:
        return logging.getLogger("collector")


# =============================================================================
# AUDIT LOGGING
# =============================================================================

class AuditLogger:
    """
    Special logger for audit-grade records.

    Audit logs are:
    - Always written to file
    - Include full context
    - Cannot be disabled
    - Stored separately from operational logs
    - Include cryptographic hash of inputs for traceability
    """

    def __init__(self, layer: Layer):
        self.layer = layer
        self._setup_audit_logger()

    def _setup_audit_logger(self) -> None:
        """Set up the audit logger with a dedicated file."""
        root = _get_project_root()
        audit_dir = root / "logs" / "audit"
        audit_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d")
        layer_name = self.layer.value.lower()
        audit_file = audit_dir / f"audit_{layer_name}_{timestamp}.jsonl"

        self.logger = logging.getLogger(f"audit.{layer_name}")
        self.logger.setLevel(logging.INFO)
        self.logger.handlers.clear()

        # JSON-lines format for audit records
        handler = logging.FileHandler(audit_file, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(message)s"))
        self.logger.addHandler(handler)

    @staticmethod
    def _compute_hash(data: dict) -> str:
        """
        Compute SHA-256 hash of input data for traceability.

        Args:
            data: Dictionary to hash

        Returns:
            Hex-encoded SHA-256 hash
        """
        import hashlib
        import json
        # Serialize deterministically (sorted keys, no whitespace)
        serialized = json.dumps(data, sort_keys=True, separators=(',', ':'))
        return hashlib.sha256(serialized.encode('utf-8')).hexdigest()

    def log_decision(
        self,
        market_id: str,
        decision: str,
        criteria: dict,
        reasoning: str,
        input_data: Optional[dict] = None,
    ) -> None:
        """
        Log a trading decision for audit.

        Args:
            market_id: Unique identifier for the market
            decision: The decision outcome (TRADE/NO_TRADE/INSUFFICIENT_DATA)
            criteria: Dictionary of criteria and their pass/fail status
            reasoning: Human-readable explanation of the decision
            input_data: Optional input data to hash for traceability
        """
        import json

        # Compute input hash if data provided
        input_hash = None
        if input_data is not None:
            input_hash = self._compute_hash(input_data)

        record = {
            "timestamp": datetime.now().isoformat(),
            "layer": self.layer.value,
            "event": "DECISION",
            "market_id": market_id,
            "decision": decision,
            "criteria": criteria,
            "reasoning": reasoning,
            "input_hash": input_hash,
        }
        self.logger.info(json.dumps(record, ensure_ascii=False))

    def log_event(self, event_type: str, details: dict) -> None:
        """
        Log a generic audit event.

        Args:
            event_type: Type of event being logged
            details: Event details as a dictionary
        """
        import json

        # Compute hash of details for traceability
        details_hash = self._compute_hash(details)

        record = {
            "timestamp": datetime.now().isoformat(),
            "layer": self.layer.value,
            "event": event_type,
            "details": details,
            "details_hash": details_hash,
        }
        self.logger.info(json.dumps(record, ensure_ascii=False))
