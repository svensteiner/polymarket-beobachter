# =============================================================================
# POLYMARKET EU AI REGULATION ANALYZER
# Module: historical/runner.py
# Purpose: Blind execution of analyzer on historical cases
# =============================================================================
#
# CRITICAL DESIGN PRINCIPLE:
# The analyzer must be run BLIND - it receives ONLY the information that
# would have been available at the time of the hypothetical market.
#
# THE ANALYZER NEVER SEES:
# - known_outcome (the real-world result)
# - Future timeline events (events after analysis_as_of_date)
# - Any form of hindsight
#
# PROBABILITY HANDLING:
# Since we explicitly cannot use historical market prices or probabilities,
# we use a NEUTRAL probability (0.50) as a placeholder. This ensures the
# analyzer's decision is based PURELY on structural factors:
# - Resolution clarity
# - Timeline feasibility
# - Process stage analysis
#
# The delta threshold check will effectively be bypassed (neutral = no edge),
# but this is INTENTIONAL. We are testing analyzer DISCIPLINE (would it have
# rejected structurally unsound markets?), not market-beating ability.
#
# =============================================================================

import logging
from datetime import date
from typing import List, Optional

from .models import (
    HistoricalCase,
    CaseResult,
    KnownOutcome,
    OutcomeClassification,
    classify_outcome,
)

# Import the main analyzer components using relative imports
from ..models.data_models import MarketInput, FullAnalysisReport
from ..core.resolution_parser import ResolutionParser
from ..core.process_model import EUProcessModel
from ..core.time_feasibility import TimeFeasibilityChecker
from ..core.probability_estimator import ProbabilityEstimator
from ..core.market_sanity import MarketSanityChecker
from ..core.decision_engine import DecisionEngine

logger = logging.getLogger(__name__)


# =============================================================================
# NEUTRAL PROBABILITY CONSTANT
# =============================================================================
# We use 0.50 (neutral) because we have NO access to historical market prices.
# This means the delta check will not find a tradeable edge, which is CORRECT.
# We are testing structural discipline, not price-based opportunity detection.
#
NEUTRAL_PROBABILITY = 0.50


class BlindAnalyzerRunner:
    """
    Runs the analyzer on historical cases in a BLIND manner.

    The runner ensures that the analyzer receives ONLY information that
    would have been available at the hypothetical analysis date.

    AUDIT PRINCIPLE:
    This class is the firewall between historical truth and analyzer input.
    It must NEVER leak future information to the analyzer.
    """

    def __init__(self):
        """Initialize the analyzer components."""
        self.resolution_parser = ResolutionParser()
        self.process_model = EUProcessModel()
        self.time_feasibility_checker = TimeFeasibilityChecker()
        self.probability_estimator = ProbabilityEstimator()
        self.market_sanity_checker = MarketSanityChecker()
        self.decision_engine = DecisionEngine()

        logger.info("BlindAnalyzerRunner initialized")

    def run_case(self, case: HistoricalCase) -> CaseResult:
        """
        Run a single historical case through the analyzer.

        The case is converted to a MarketInput with ONLY blind information.
        The known_outcome is used ONLY after analysis for classification.

        Args:
            case: The historical case to evaluate

        Returns:
            CaseResult with analyzer decision and classification
        """
        logger.info(f"Running case: {case.case_id} - {case.title}")

        # ---------------------------------------------------------------------
        # STEP 1: Create BLIND MarketInput
        # ---------------------------------------------------------------------
        # The analyzer receives ONLY:
        # - synthetic_resolution_text (as market resolution)
        # - hypothetical_target_date (as market deadline)
        # - referenced_regulation
        # - authority_involved
        # - NEUTRAL probability (no historical price data)
        # - analysis_as_of_date (NOT today - we simulate past analysis)
        #
        # The analyzer does NOT receive:
        # - known_outcome
        # - formal_timeline (actual dates)
        # - failure_explanation
        # ---------------------------------------------------------------------

        blind_input = MarketInput(
            market_title=case.title,
            resolution_text=case.synthetic_resolution_text,
            target_date=case.hypothetical_target_date,
            referenced_regulation=case.referenced_regulation,
            authority_involved=case.authority_involved,
            market_implied_probability=NEUTRAL_PROBABILITY,
            analysis_date=case.analysis_as_of_date,
            notes=f"[HISTORICAL CASE {case.case_id}] - BLIND ANALYSIS"
        )

        logger.debug(f"  Blind input created for {case.case_id}")
        logger.debug(f"  Target date: {case.hypothetical_target_date}")
        logger.debug(f"  Analysis as of: {case.analysis_as_of_date}")

        # ---------------------------------------------------------------------
        # STEP 2: Run the full analyzer pipeline
        # ---------------------------------------------------------------------
        report = self._run_analyzer(blind_input)

        # ---------------------------------------------------------------------
        # STEP 3: Extract results
        # ---------------------------------------------------------------------
        analyzer_decision = report.final_decision.outcome.value
        blocking_criteria = report.final_decision.blocking_criteria

        # Extract timeline-specific conflicts
        timeline_conflicts = self._extract_timeline_conflicts(report)

        # Risk warnings
        risk_warnings = report.final_decision.risk_warnings

        # Full reasoning
        full_reasoning = report.final_decision.reasoning

        logger.info(f"  Analyzer decision: {analyzer_decision}")
        logger.debug(f"  Blocking criteria: {blocking_criteria}")

        # ---------------------------------------------------------------------
        # STEP 4: Classify outcome (using known_outcome - POST-HOC ONLY)
        # ---------------------------------------------------------------------
        classification = classify_outcome(analyzer_decision, case.known_outcome)

        logger.info(f"  Classification: {classification.value}")
        if classification == OutcomeClassification.FALSE_ADMISSION:
            logger.warning(f"  [!] CRITICAL: FALSE_ADMISSION detected for {case.case_id}")

        # ---------------------------------------------------------------------
        # STEP 5: Build result
        # ---------------------------------------------------------------------
        return CaseResult(
            case=case,
            analyzer_decision=analyzer_decision,
            blocking_criteria=blocking_criteria,
            timeline_conflicts=timeline_conflicts,
            classification=classification,
            risk_warnings=risk_warnings,
            full_reasoning=full_reasoning,
        )

    def run_all_cases(self, cases: List[HistoricalCase]) -> List[CaseResult]:
        """
        Run all historical cases through the analyzer.

        Args:
            cases: List of historical cases to evaluate

        Returns:
            List of CaseResult objects
        """
        logger.info(f"Running {len(cases)} historical cases")
        logger.info("=" * 60)

        results = []
        for i, case in enumerate(cases, 1):
            logger.info(f"Case {i}/{len(cases)}: {case.case_id}")
            result = self.run_case(case)
            results.append(result)

        logger.info("=" * 60)
        logger.info(f"Completed {len(results)} cases")

        # Log summary
        classifications = {}
        for result in results:
            key = result.classification.value
            classifications[key] = classifications.get(key, 0) + 1

        logger.info("Classification summary:")
        for classification, count in sorted(classifications.items()):
            logger.info(f"  {classification}: {count}")

        # Warn about any FALSE_ADMISSION cases
        false_admissions = [r for r in results if r.is_critical_failure()]
        if false_admissions:
            logger.warning(f"[!] {len(false_admissions)} FALSE_ADMISSION cases detected!")
            for fa in false_admissions:
                logger.warning(f"    - {fa.case.case_id}: {fa.case.title}")

        return results

    def _run_analyzer(self, market_input: MarketInput) -> FullAnalysisReport:
        """
        Run the full analyzer pipeline.

        This is a direct copy of the analyzer logic to ensure consistency.

        Args:
            market_input: The blind market input

        Returns:
            Full analysis report
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
        from datetime import datetime
        return FullAnalysisReport(
            market_input=market_input,
            resolution_analysis=resolution_analysis,
            process_analysis=process_analysis,
            time_feasibility=time_feasibility,
            probability_estimate=probability_estimate,
            market_sanity=market_sanity,
            final_decision=final_decision,
            analysis_version="1.0.0-historical",
            generated_at=datetime.now().isoformat()
        )

    def _extract_timeline_conflicts(self, report: FullAnalysisReport) -> List[str]:
        """
        Extract timeline-specific conflicts from the analysis.

        Args:
            report: The full analysis report

        Returns:
            List of timeline conflict descriptions
        """
        conflicts = []

        # From time feasibility
        tf = report.time_feasibility
        if tf.hard_fail:
            conflicts.append(
                f"Timeline hard fail: {tf.days_until_target} days available, "
                f"{tf.minimum_days_required} days required minimum"
            )

        if not tf.is_timeline_feasible:
            conflicts.append("Timeline assessed as not feasible")

        for constraint in tf.institutional_constraints:
            conflicts.append(f"Institutional constraint: {constraint}")

        for period in tf.mandatory_waiting_periods:
            conflicts.append(f"Mandatory waiting period: {period}")

        # From process analysis
        pa = report.process_analysis
        for factor in pa.blocking_factors:
            if "time" in factor.lower() or "delay" in factor.lower():
                conflicts.append(f"Process blocking factor: {factor}")

        return conflicts
