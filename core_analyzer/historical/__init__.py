# =============================================================================
# POLYMARKET EU AI REGULATION ANALYZER
# Module: historical/
# Purpose: Historical / Counterfactual Testing for Analyzer Discipline
# =============================================================================
#
# THIS MODULE EVALUATES DECISION QUALITY, NOT PROFITABILITY.
#
# Core question:
#   Would the analyzer have REJECTED markets where the real-world outcome
#   later proved that timelines were impossible or misinterpreted?
#
# Non-goals (STRICT):
#   - No prices
#   - No probabilities from historical markets
#   - No PnL calculation
#   - No hindsight signals
#   - No optimization
#   - No learning or tuning loops
#
# Outcome classification:
#   - CORRECT_REJECTION: Analyzer rejected, outcome was NO (good discipline)
#   - SAFE_PASS: Analyzer rejected, outcome was YES (acceptable conservatism)
#   - FALSE_ADMISSION: Analyzer accepted, outcome was NO (CRITICAL FAILURE)
#   - RARE_SUCCESS: Analyzer accepted, outcome was YES
#
# =============================================================================

from .models import HistoricalCase, OutcomeClassification, CaseResult
from .runner import BlindAnalyzerRunner
from .reports import ReportGenerator

__all__ = [
    "HistoricalCase",
    "OutcomeClassification",
    "CaseResult",
    "BlindAnalyzerRunner",
    "ReportGenerator",
]
