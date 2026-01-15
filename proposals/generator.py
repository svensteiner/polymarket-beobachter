# =============================================================================
# POLYMARKET BEOBACHTER - PROPOSAL GENERATOR
# =============================================================================
#
# GOVERNANCE INTENT:
# The ProposalGenerator transforms analysis results into structured proposals.
# It does NOT make decisions - it only DOCUMENTS decisions made by the analyzer.
#
# GENERATION RULES:
# A proposal is generated ONLY IF:
# - Core Analyzer reached a final decision
# - All mandatory inputs are present
# - No guardrail violation occurred
#
# NO proposal is generated for incomplete analysis.
#
# =============================================================================

from datetime import datetime
from typing import Dict, Any, Optional, List

from proposals.models import (
    Proposal,
    ProposalCoreCriteria,
    generate_proposal_id,
)


class ProposalGenerator:
    """
    Generates structured proposals from analysis results.

    GOVERNANCE:
    This class is READ-ONLY regarding the analyzer.
    It cannot modify analysis results.
    It cannot influence future decisions.
    """

    # Minimum required fields in analysis for proposal generation
    REQUIRED_ANALYSIS_FIELDS = [
        "final_decision",
        "market_input",
        "probability_estimate",
        "market_sanity",
    ]

    def __init__(self):
        """
        Initialize the proposal generator.

        GOVERNANCE:
        No state is kept between proposal generations.
        Each proposal is independent.
        """
        pass

    def can_generate(self, analysis: Dict[str, Any]) -> tuple:
        """
        Check if a proposal can be generated from this analysis.

        GOVERNANCE:
        Returns (can_generate: bool, reason: str)
        Explicit reasons for rejection are required.

        Args:
            analysis: The analysis result dictionary

        Returns:
            Tuple of (can_generate, reason)
        """
        # Check for required fields
        for field in self.REQUIRED_ANALYSIS_FIELDS:
            if field not in analysis:
                return (False, f"Missing required field: {field}")

        # Check for final decision
        final_decision = analysis.get("final_decision", {})
        outcome = final_decision.get("outcome")

        if outcome is None:
            return (False, "No decision outcome in analysis")

        if outcome not in ("TRADE", "NO_TRADE", "INSUFFICIENT_DATA"):
            return (False, f"Invalid decision outcome: {outcome}")

        # INSUFFICIENT_DATA does not generate a proposal
        if outcome == "INSUFFICIENT_DATA":
            return (False, "INSUFFICIENT_DATA decisions do not generate proposals")

        # Check for market input
        market_input = analysis.get("market_input", {})
        if not market_input.get("market_title"):
            return (False, "Missing market title")

        return (True, "All requirements met")

    def generate(self, analysis: Dict[str, Any]) -> Optional[Proposal]:
        """
        Generate a proposal from analysis results.

        GOVERNANCE:
        - This method ONLY reads from the analysis
        - It DOES NOT modify the analysis
        - It DOES NOT trigger any actions

        Args:
            analysis: The analysis result dictionary

        Returns:
            Proposal object if generation successful, None otherwise
        """
        can_gen, reason = self.can_generate(analysis)
        if not can_gen:
            return None

        # Extract data from analysis
        market_input = analysis.get("market_input", {})
        final_decision = analysis.get("final_decision", {})
        probability_estimate = analysis.get("probability_estimate", {})
        market_sanity = analysis.get("market_sanity", {})
        time_feasibility = analysis.get("time_feasibility", {})
        resolution_analysis = analysis.get("resolution_analysis", {})

        # Generate proposal ID
        proposal_id = generate_proposal_id()

        # Extract probabilities
        implied_prob = market_input.get("market_implied_probability", 0.0)
        model_prob = probability_estimate.get("probability_midpoint", 0.0)
        edge = model_prob - implied_prob

        # Build core criteria
        # GOVERNANCE: Criteria are derived from analysis, not invented
        core_criteria = self._extract_core_criteria(
            analysis, time_feasibility, resolution_analysis
        )

        # Collect warnings
        warnings = self._collect_warnings(final_decision, market_sanity)

        # Determine confidence level
        confidence = probability_estimate.get("confidence_level", "LOW")

        # Build justification summary
        justification = self._build_justification(
            final_decision, probability_estimate, market_sanity
        )

        # Create proposal
        proposal = Proposal(
            proposal_id=proposal_id,
            timestamp=datetime.now().isoformat(),
            market_id=market_input.get("market_id", "UNKNOWN"),
            market_question=market_input.get("market_title", "Unknown Market"),
            decision=final_decision.get("outcome", "NO_TRADE"),
            implied_probability=implied_prob,
            model_probability=model_prob,
            edge=edge,
            core_criteria=core_criteria,
            warnings=tuple(warnings),
            confidence_level=confidence,
            justification_summary=justification
        )

        return proposal

    def _extract_core_criteria(
        self,
        analysis: Dict[str, Any],
        time_feasibility: Dict[str, Any],
        resolution_analysis: Dict[str, Any]
    ) -> ProposalCoreCriteria:
        """
        Extract core criteria from analysis results.

        GOVERNANCE:
        Maps analysis criteria to proposal criteria.
        This mapping is EXPLICIT and DOCUMENTED.
        """
        final_decision = analysis.get("final_decision", {})
        criteria_met = final_decision.get("criteria_met", {})

        # Map analysis criteria to proposal criteria
        # GOVERNANCE: These mappings are fixed and documented

        # liquidity_ok: Based on delta threshold meeting (proxy for liquidity)
        liquidity_ok = criteria_met.get("delta_meets_threshold", False)

        # volume_ok: Not directly available in current analysis, default to
        # True if we have enough data to make a decision
        volume_ok = bool(analysis.get("market_sanity"))

        # time_to_resolution_ok: From time feasibility analysis
        time_ok = time_feasibility.get("is_timeline_feasible", False)

        # data_quality_ok: From resolution analysis
        data_quality_ok = (
            resolution_analysis.get("is_binary", False) and
            resolution_analysis.get("is_objectively_verifiable", False) and
            not resolution_analysis.get("hard_fail", True)
        )

        return ProposalCoreCriteria(
            liquidity_ok=liquidity_ok,
            volume_ok=volume_ok,
            time_to_resolution_ok=time_ok,
            data_quality_ok=data_quality_ok
        )

    def _collect_warnings(
        self,
        final_decision: Dict[str, Any],
        market_sanity: Dict[str, Any]
    ) -> List[str]:
        """
        Collect all warnings from analysis.

        GOVERNANCE:
        Warnings are COPIED from analysis, not generated.
        No filtering or modification.
        """
        warnings = []

        # Warnings from final decision
        risk_warnings = final_decision.get("risk_warnings", [])
        warnings.extend(risk_warnings)

        # Direction warning if applicable
        direction = market_sanity.get("direction")
        if direction:
            warnings.append(f"Market direction: {direction}")

        return warnings

    def _build_justification(
        self,
        final_decision: Dict[str, Any],
        probability_estimate: Dict[str, Any],
        market_sanity: Dict[str, Any]
    ) -> str:
        """
        Build human-readable justification summary.

        GOVERNANCE:
        The justification MUST be derived from analysis reasoning.
        No creative interpretation or addition.
        """
        parts = []

        # Decision reasoning
        decision_reasoning = final_decision.get("reasoning", "")
        if decision_reasoning:
            # Take first 200 chars
            parts.append(decision_reasoning[:200])

        # Probability reasoning
        prob_reasoning = probability_estimate.get("reasoning", "")
        if prob_reasoning:
            parts.append(prob_reasoning[:150])

        # Market sanity reasoning
        sanity_reasoning = market_sanity.get("reasoning", "")
        if sanity_reasoning:
            parts.append(sanity_reasoning[:150])

        if not parts:
            return "No detailed justification available from analysis."

        return " | ".join(parts)


def generate_proposal_from_analysis(analysis: Dict[str, Any]) -> Optional[Proposal]:
    """
    Convenience function to generate a proposal from analysis.

    GOVERNANCE:
    This is a STATELESS function.
    Each call is independent.

    Args:
        analysis: Analysis result dictionary

    Returns:
        Proposal if generation successful, None otherwise
    """
    generator = ProposalGenerator()
    return generator.generate(analysis)
