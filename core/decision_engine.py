# =============================================================================
# POLYMARKET EU AI REGULATION ANALYZER
# Module: core/decision_engine.py
# Purpose: Make final TRADE / NO_TRADE decision based on all analysis
# =============================================================================
#
# DECISION LOGIC:
# This is the final gatekeeper. TRADE is only recommended if ALL criteria pass.
# A single failure results in NO_TRADE.
#
# REQUIRED CRITERIA FOR TRADE:
# 1. Resolution is clean (not ambiguous, objectively verifiable)
# 2. Timeline is feasible (not physically impossible)
# 3. Probability delta >= 15 percentage points
#
# FAIL CLOSED PRINCIPLE:
# - Any ambiguity → NO_TRADE
# - Any missing data → NO_TRADE
# - Any hard fail from upstream modules → NO_TRADE
# - Uncertain? → NO_TRADE
#
# OUTPUT:
# - Clear TRADE / NO_TRADE decision
# - Explicit list of which criteria passed/failed
# - Risk warnings even if decision is TRADE
# - Human-readable action recommendation
#
# THIS MODULE DOES NOT:
# - Recommend position direction (YES/NO)
# - Suggest position size
# - Consider portfolio effects
# - Execute any trades
#
# =============================================================================

from typing import Dict, List
from models.data_models import (
    ResolutionAnalysis,
    ProcessStageAnalysis,
    TimeFeasibilityAnalysis,
    ProbabilityEstimate,
    MarketSanityAnalysis,
    FinalDecision,
    DecisionOutcome,
)
from shared.enums import MarketDirection


class DecisionEngine:
    """
    Makes final trading decision based on all analysis components.

    Implements FAIL CLOSED logic - any doubt results in NO_TRADE.

    DESIGN PRINCIPLE:
    This is a conservative gatekeeper.
    Better to miss opportunities than to trade on bad data.
    """

    # =========================================================================
    # CRITERIA NAMES (for reporting)
    # =========================================================================

    CRITERION_RESOLUTION_CLEAN = "resolution_clean"
    CRITERION_RESOLUTION_BINARY = "resolution_binary"
    CRITERION_RESOLUTION_VERIFIABLE = "resolution_verifiable"
    CRITERION_TIMELINE_FEASIBLE = "timeline_feasible"
    CRITERION_TIMELINE_NOT_IMPOSSIBLE = "timeline_not_impossible"
    CRITERION_DELTA_THRESHOLD = "delta_meets_threshold"
    CRITERION_ESTIMATE_CONFIDENCE = "estimate_confidence_acceptable"
    CRITERION_NO_BLOCKING_FACTORS = "no_critical_blocking_factors"

    # =========================================================================
    # CONFIDENCE REQUIREMENTS
    # =========================================================================

    # Minimum acceptable confidence level for trading
    # We accept MEDIUM or HIGH, not LOW
    ACCEPTABLE_CONFIDENCE_LEVELS = {"MEDIUM", "HIGH"}

    def __init__(self):
        """Initialize the decision engine."""
        pass

    def decide(
        self,
        resolution_analysis: ResolutionAnalysis,
        process_analysis: ProcessStageAnalysis,
        time_feasibility: TimeFeasibilityAnalysis,
        probability_estimate: ProbabilityEstimate,
        market_sanity: MarketSanityAnalysis
    ) -> FinalDecision:
        """
        Make final trading decision.

        PROCESS:
        1. Evaluate each criterion
        2. Identify any blocking criteria
        3. Determine outcome (TRADE only if all pass)
        4. Generate risk warnings
        5. Build recommendation

        Args:
            resolution_analysis: Resolution parsing results
            process_analysis: Process stage analysis
            time_feasibility: Timeline feasibility check
            probability_estimate: Rule-based probability estimate
            market_sanity: Market comparison analysis

        Returns:
            FinalDecision with outcome and reasoning
        """
        # ---------------------------------------------------------------------
        # STEP 1: Evaluate all criteria
        # ---------------------------------------------------------------------
        criteria_met: Dict[str, bool] = {}

        # Resolution criteria
        criteria_met[self.CRITERION_RESOLUTION_CLEAN] = (
            not resolution_analysis.hard_fail
        )
        criteria_met[self.CRITERION_RESOLUTION_BINARY] = (
            resolution_analysis.is_binary
        )
        criteria_met[self.CRITERION_RESOLUTION_VERIFIABLE] = (
            resolution_analysis.is_objectively_verifiable
        )

        # Timeline criteria
        criteria_met[self.CRITERION_TIMELINE_NOT_IMPOSSIBLE] = (
            not time_feasibility.hard_fail
        )
        criteria_met[self.CRITERION_TIMELINE_FEASIBLE] = (
            time_feasibility.is_timeline_feasible
        )

        # Probability criteria
        criteria_met[self.CRITERION_DELTA_THRESHOLD] = (
            market_sanity.meets_threshold
        )
        criteria_met[self.CRITERION_ESTIMATE_CONFIDENCE] = (
            probability_estimate.confidence_level in self.ACCEPTABLE_CONFIDENCE_LEVELS
        )

        # Process criteria
        criteria_met[self.CRITERION_NO_BLOCKING_FACTORS] = (
            len(process_analysis.blocking_factors) == 0
        )

        # ---------------------------------------------------------------------
        # STEP 2: Identify blocking criteria
        # ---------------------------------------------------------------------
        blocking_criteria: List[str] = [
            criterion for criterion, passed in criteria_met.items()
            if not passed
        ]

        # ---------------------------------------------------------------------
        # STEP 3: Determine outcome
        # ---------------------------------------------------------------------
        # TRADE only if ALL criteria pass
        if len(blocking_criteria) == 0:
            outcome = DecisionOutcome.TRADE
        else:
            outcome = DecisionOutcome.NO_TRADE

        # ---------------------------------------------------------------------
        # STEP 4: Generate risk warnings
        # ---------------------------------------------------------------------
        risk_warnings = self._generate_risk_warnings(
            resolution_analysis,
            process_analysis,
            time_feasibility,
            probability_estimate,
            market_sanity
        )

        # ---------------------------------------------------------------------
        # STEP 5: Determine confidence
        # ---------------------------------------------------------------------
        confidence = self._determine_confidence(
            criteria_met,
            probability_estimate.confidence_level
        )

        # ---------------------------------------------------------------------
        # STEP 6: Build recommendation
        # ---------------------------------------------------------------------
        recommended_action = self._build_recommendation(
            outcome,
            blocking_criteria,
            market_sanity.direction
        )

        # ---------------------------------------------------------------------
        # STEP 7: Build reasoning
        # ---------------------------------------------------------------------
        reasoning = self._build_reasoning(
            outcome,
            criteria_met,
            blocking_criteria,
            risk_warnings
        )

        return FinalDecision(
            outcome=outcome,
            criteria_met=criteria_met,
            blocking_criteria=blocking_criteria,
            confidence=confidence,
            recommended_action=recommended_action,
            risk_warnings=risk_warnings,
            reasoning=reasoning
        )

    def _generate_risk_warnings(
        self,
        resolution_analysis: ResolutionAnalysis,
        process_analysis: ProcessStageAnalysis,
        time_feasibility: TimeFeasibilityAnalysis,
        probability_estimate: ProbabilityEstimate,
        market_sanity: MarketSanityAnalysis
    ) -> List[str]:
        """
        Generate risk warnings even for TRADE decisions.

        Highlights potential issues that don't block trading
        but should be considered.

        Args:
            All analysis components

        Returns:
            List of warning strings
        """
        warnings = []

        # Resolution warnings
        if resolution_analysis.ambiguity_flags:
            count = len(resolution_analysis.ambiguity_flags)
            warnings.append(
                f"Resolution has {count} ambiguity flag(s) - "
                "review manually before trading"
            )

        # Timeline warnings
        min_days = time_feasibility.minimum_days_required
        if min_days is None or min_days <= 0:
            # This should not happen - indicates a bug upstream
            # Log warning and use 1 to avoid division by zero
            warnings.append(
                f"WARNING: minimum_days_required is invalid ({min_days}), expected > 0. "
                "This may indicate a configuration issue."
            )
            min_days = 1

        # Validate days_until_target before division
        days_until = time_feasibility.days_until_target
        if days_until is None or days_until <= 0:
            buffer_ratio = 0.0
        else:
            buffer_ratio = days_until / min_days
        if buffer_ratio < 2.0:
            warnings.append(
                f"Timeline buffer is tight ({buffer_ratio:.1f}x minimum) - "
                "delays could cause issues"
            )

        # Institutional constraint warnings
        if time_feasibility.institutional_constraints:
            warnings.append(
                f"Institutional constraints identified: "
                f"{len(time_feasibility.institutional_constraints)}"
            )

        # Confidence warnings
        if probability_estimate.confidence_level == "MEDIUM":
            warnings.append(
                "Probability estimate confidence is MEDIUM - "
                "wider uncertainty bands"
            )

        # Process blocking factor warnings
        if process_analysis.blocking_factors:
            for factor in process_analysis.blocking_factors:
                warnings.append(f"Process blocking factor: {factor}")

        # Market edge case warnings
        if market_sanity.market_implied_prob < 0.10:
            warnings.append(
                "Market priced below 10% - extreme pricing, verify thesis"
            )
        elif market_sanity.market_implied_prob > 0.90:
            warnings.append(
                "Market priced above 90% - extreme pricing, verify thesis"
            )

        return warnings

    def _determine_confidence(
        self,
        criteria_met: Dict[str, bool],
        estimate_confidence: str
    ) -> str:
        """
        Determine overall decision confidence.

        Args:
            criteria_met: Dictionary of criteria results
            estimate_confidence: Probability estimate confidence

        Returns:
            "LOW", "MEDIUM", or "HIGH"
        """
        # Count how many criteria passed
        passed_count = sum(1 for v in criteria_met.values() if v)
        total_count = len(criteria_met)

        # Start with estimate confidence as baseline
        if estimate_confidence == "LOW":
            return "LOW"

        # If all criteria pass with HIGH estimate confidence
        if passed_count == total_count and estimate_confidence == "HIGH":
            return "HIGH"

        # Default to MEDIUM
        return "MEDIUM"

    def _build_recommendation(
        self,
        outcome: DecisionOutcome,
        blocking_criteria: List[str],
        market_direction: str
    ) -> str:
        """
        Build human-readable action recommendation.

        Args:
            outcome: TRADE or NO_TRADE
            blocking_criteria: List of failed criteria
            market_direction: Direction of mispricing

        Returns:
            Recommendation string
        """
        if outcome == DecisionOutcome.NO_TRADE:
            if blocking_criteria:
                blocker_summary = ", ".join(blocking_criteria[:3])
                if len(blocking_criteria) > 3:
                    blocker_summary += f" (+{len(blocking_criteria) - 3} more)"
                return (
                    f"DO NOT TRADE. Blocking criteria: {blocker_summary}. "
                    "Market does not meet structural tradeability requirements."
                )
            else:
                return "DO NOT TRADE. No clear edge identified."

        # outcome == TRADE
        if market_direction == MarketDirection.MARKET_TOO_HIGH.value:
            return (
                "STRUCTURALLY TRADEABLE. Market appears to OVERESTIMATE "
                "probability. If trading, consider NO position. "
                "Verify all assumptions before execution."
            )
        elif market_direction == MarketDirection.MARKET_TOO_LOW.value:
            return (
                "STRUCTURALLY TRADEABLE. Market appears to UNDERESTIMATE "
                "probability. If trading, consider YES position. "
                "Verify all assumptions before execution."
            )
        else:
            return (
                "STRUCTURALLY TRADEABLE but direction unclear. "
                "Verify all assumptions before execution."
            )

    def _build_reasoning(
        self,
        outcome: DecisionOutcome,
        criteria_met: Dict[str, bool],
        blocking_criteria: List[str],
        risk_warnings: List[str]
    ) -> str:
        """
        Build detailed reasoning for the decision.

        Args:
            outcome: TRADE or NO_TRADE
            criteria_met: Dictionary of criteria results
            blocking_criteria: List of failed criteria
            risk_warnings: List of risk warnings

        Returns:
            Detailed reasoning string
        """
        parts = []

        # Summary
        passed = sum(1 for v in criteria_met.values() if v)
        total = len(criteria_met)
        parts.append(f"Criteria passed: {passed}/{total}.")

        # Outcome statement
        if outcome == DecisionOutcome.TRADE:
            parts.append("DECISION: TRADE - All criteria met.")
        else:
            parts.append(
                f"DECISION: NO TRADE - {len(blocking_criteria)} "
                f"blocking criterion/criteria."
            )

        # Detail blocking criteria
        if blocking_criteria:
            parts.append("BLOCKING CRITERIA:")
            for criterion in blocking_criteria:
                parts.append(f"  - {criterion}: FAILED")

        # Risk warnings summary
        if risk_warnings:
            parts.append(f"RISK WARNINGS: {len(risk_warnings)} identified.")

        # Explicit pass/fail list
        parts.append("CRITERIA DETAILS:")
        for criterion, passed in criteria_met.items():
            status = "PASS" if passed else "FAIL"
            parts.append(f"  - {criterion}: {status}")

        return " ".join(parts)
