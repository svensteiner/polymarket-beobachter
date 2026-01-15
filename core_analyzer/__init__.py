# =============================================================================
# POLYMARKET BEOBACHTER - CORE ANALYZER (LAYER 1)
# =============================================================================
#
# LAYER 1 — INSTITUTIONAL / PROCESS EDGE (CORE)
#
# PURPOSE:
# Evaluate whether a Polymarket market is STRUCTURALLY TRADEABLE.
# Focus: EU regulation, AI Act, tech governance, deadlines, formal processes.
#
# ABSOLUTE RULES:
# - Deterministic behavior
# - Fail-closed on any uncertainty
# - NO prices
# - NO volumes
# - NO historical market probabilities
# - NO PnL calculations
# - NO learning loops
# - NO ML/AI predictions
#
# AUTHORITY:
# This layer has FINAL decision power.
# Output is limited to: TRADE / NO_TRADE / INSUFFICIENT_DATA
#
# LAYER ISOLATION:
# This module CANNOT import from microstructure_research/.
# This module CANNOT import execution or trading libraries.
# Violation will cause a hard failure.
#
# =============================================================================

import sys

# Enforce layer isolation at import time
from shared.layer_guard import assert_layer_isolation, Layer
assert_layer_isolation(Layer.LAYER1_INSTITUTIONAL)

from .analyzer import PolymarketEUAnalyzer
from .models.data_models import (
    MarketInput,
    FullAnalysisReport,
    FinalDecision,
    DecisionOutcome,
)

__all__ = [
    "PolymarketEUAnalyzer",
    "MarketInput",
    "FullAnalysisReport",
    "FinalDecision",
    "DecisionOutcome",
]

# Version
__version__ = "1.0.0"
