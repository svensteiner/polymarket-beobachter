# =============================================================================
# POLYMARKET BEOBACHTER - SHARED MODULE
# =============================================================================
#
# GOVERNANCE:
# This module contains ONLY shared utilities that are explicitly permitted
# for both Layer 1 and Layer 2. No business logic lives here.
#
# CONTENTS:
# - Enums (shared type definitions)
# - Schemas (JSON validation schemas)
# - Logging utilities (separated by layer)
# - Layer isolation guards
#
# =============================================================================

from .enums import DecisionOutcome, ConfidenceLevel, Layer
from .layer_guard import (
    assert_layer_isolation,
    LayerViolationError,
    set_active_layer,
    get_active_layer,
    check_import_attempt,
)
from .logging_config import setup_logging, get_layer_logger

__all__ = [
    "DecisionOutcome",
    "ConfidenceLevel",
    "Layer",
    "assert_layer_isolation",
    "LayerViolationError",
    "set_active_layer",
    "get_active_layer",
    "check_import_attempt",
    "setup_logging",
    "get_layer_logger",
]
