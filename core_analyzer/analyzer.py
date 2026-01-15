# =============================================================================
# POLYMARKET BEOBACHTER - CORE ANALYZER
# Module: core_analyzer/analyzer.py
# Purpose: Main analyzer orchestrating all Layer 1 components
# =============================================================================
#
# LAYER 1 — INSTITUTIONAL / PROCESS EDGE (CORE)
#
# This is the main entry point for Layer 1 analysis.
# All analysis is deterministic, conservative, and fail-closed.
#
# OUTPUT: TRADE / NO_TRADE / INSUFFICIENT_DATA
# (Final decision authority)
#
# =============================================================================

from datetime import datetime
from typing import Optional

from .models.data_models import (
    MarketInput,
    FullAnalysisReport,
)
from .core.resolution_parser import ResolutionParser
from .core.process_model import EUProcessModel
from .core.time_feasibility import TimeFeasibilityChecker
from .core.probability_estimator import ProbabilityEstimator
from .core.market_sanity import MarketSanityChecker
from .core.decision_engine import DecisionEngine


class PolymarketEUAnalyzer:
    """
    Main analyzer class for Polymarket EU regulation markets.

    LAYER 1 AUTHORITY:
    This analyzer has FINAL decision power on market tradeability.
    Output is limited to: TRADE / NO_TRADE / INSUFFICIENT_DATA.

    DESIGN PRINCIPLES:
    - Deterministic: Same input always produces same output
    - Fail-closed: Any uncertainty defaults to NO_TRADE
    - No prices: Does not use market prices in decision logic
    - No ML: Only rule-based structural analysis
    - Auditable: Full reasoning chain for every decision

    FORBIDDEN:
    - External API calls during analysis
    - Price-based signals
    - ML/AI predictions
    - Historical market probabilities
    - PnL calculations
    """

    VERSION = "1.0.0"

    def __init__(self):
        """Initialize all analysis components."""
        # Initialize each component
        # These are all deterministic, stateless analyzers
        self.resolution_parser = ResolutionParser()
        self.process_model = EUProcessModel()
        self.time_feasibility_checker = TimeFeasibilityChecker()
        self.probability_estimator = ProbabilityEstimator()
        self.market_sanity_checker = MarketSanityChecker()
        self.decision_engine = DecisionEngine()

    def analyze(self, market_input: MarketInput) -> FullAnalysisReport:
        """
        Run complete analysis pipeline.

        PIPELINE STAGES:
        1. Resolution parsing (is resolution clean and verifiable?)
        2. Process stage analysis (where is the regulation in EU lifecycle?)
        3. Time feasibility check (is the timeline physically possible?)
        4. Probability estimation (conservative rule-based estimate)
        5. Market sanity check (is there significant divergence?)
        6. Final decision (TRADE only if ALL criteria pass)

        Args:
            market_input: The market to analyze

        Returns:
            FullAnalysisReport with complete analysis and decision

        Raises:
            ValueError: If market_input has invalid fields
        """
        # Step 1: Parse resolution
        resolution_analysis = self.resolution_parser.analyze(market_input)

        # Step 2: Analyze process stage
        process_analysis = self.process_model.analyze(market_input)

        # Step 3: Check time feasibility
        time_feasibility = self.time_feasibility_checker.analyze(
            market_input, process_analysis
        )

        # Step 4: Estimate probability
        probability_estimate = self.probability_estimator.estimate(
            market_input, process_analysis, time_feasibility
        )

        # Step 5: Check market sanity
        market_sanity = self.market_sanity_checker.analyze(
            market_input, probability_estimate
        )

        # Step 6: Make final decision
        final_decision = self.decision_engine.decide(
            resolution_analysis,
            process_analysis,
            time_feasibility,
            probability_estimate,
            market_sanity
        )

        # Assemble report
        return FullAnalysisReport(
            market_input=market_input,
            resolution_analysis=resolution_analysis,
            process_analysis=process_analysis,
            time_feasibility=time_feasibility,
            probability_estimate=probability_estimate,
            market_sanity=market_sanity,
            final_decision=final_decision,
            analysis_version=self.VERSION,
            generated_at=datetime.now().isoformat()
        )
