# =============================================================================
# POLYMARKET EU AI REGULATION ANALYZER
# Module: core/__init__.py
# Purpose: Package initialization for core analysis modules
# =============================================================================
#
# AUDIT NOTE:
# This package contains all analysis logic.
# Each module is deterministic and side-effect free.
# No network calls. No file I/O except explicit output writing.
#
# MODULE OVERVIEW:
# 1. resolution_parser: Analyzes market resolution criteria
# 2. process_model: Models EU regulatory lifecycle stages
# 3. time_feasibility: Checks timeline plausibility
# 4. probability_estimator: Rule-based probability calculation
# 5. market_sanity: Compares estimate to market price
# 6. decision_engine: Final TRADE/NO_TRADE decision
#
# =============================================================================

from .resolution_parser import ResolutionParser
from .process_model import EUProcessModel
from .time_feasibility import TimeFeasibilityChecker
from .probability_estimator import ProbabilityEstimator
from .market_sanity import MarketSanityChecker
from .decision_engine import DecisionEngine

__all__ = [
    "ResolutionParser",
    "EUProcessModel",
    "TimeFeasibilityChecker",
    "ProbabilityEstimator",
    "MarketSanityChecker",
    "DecisionEngine",
]
