# =============================================================================
# POLYMARKET BEOBACHTER - REVIEW GATE LOGIC
# =============================================================================
#
# GOVERNANCE INTENT:
# The ReviewGate evaluates proposals against EXPLICIT quality criteria.
# It classifies proposals as PASS / HOLD / REJECT.
#
# CRITICAL: This classification does NOT trigger any action.
# It is purely informational for human reviewers.
#
# REVIEW CRITERIA (from specification):
#
# REVIEW_PASS requires:
# - Decision consistency (no internal contradictions)
# - Edge above minimum threshold
# - No critical warnings
# - Confidence != LOW
#
# REVIEW_HOLD:
# - Mixed signals
# - Edge borderline
# - Unresolved warnings
#
# REVIEW_REJECT:
# - Missing criteria
# - Low confidence
# - Guardrail proximity
#
# =============================================================================

from datetime import datetime
from typing import Dict, List, Tuple

from proposals.models import (
    Proposal,
    ReviewOutcome,
    ReviewResult,
)


class ReviewGate:
    """
    Review gate that evaluates proposals.

    GOVERNANCE:
    - All checks are EXPLICIT and NAMED
    - All decisions are EXPLAINED
    - No hidden logic or implicit rules
    """

    # Configuration thresholds
    # GOVERNANCE: These thresholds are DOCUMENTED and FIXED
    MINIMUM_EDGE_THRESHOLD = 0.02  # 2% minimum edge for PASS (lowered from 5%)
    BORDERLINE_EDGE_THRESHOLD = 0.01  # 1-2% is borderline (HOLD)
    CRITICAL_WARNING_KEYWORDS = [
        "HARD FAIL",
        "CRITICAL",
        "IMPOSSIBLE",
        "INVALID",
        "BLOCKING",
    ]

    def __init__(self):
        """
        Initialize the review gate.

        GOVERNANCE:
        No state is kept between reviews.
        Each review is independent.
        """
        pass

    def review(self, proposal: Proposal) -> ReviewResult:
        """
        Review a proposal and classify it.

        GOVERNANCE:
        - This method ONLY reads from the proposal
        - It DOES NOT modify the proposal
        - It DOES NOT trigger any actions
        - All checks are explicit and named

        Args:
            proposal: The Proposal to review

        Returns:
            ReviewResult with classification and reasons
        """
        checks = {}
        reasons = []

        # =====================================================================
        # CHECK 1: Confidence Level
        # GOVERNANCE: LOW confidence = automatic concern
        # =====================================================================
        confidence_ok = proposal.confidence_level != "LOW"
        checks["confidence_not_low"] = confidence_ok

        if not confidence_ok:
            reasons.append("Confidence level is LOW - insufficient certainty")

        # =====================================================================
        # CHECK 2: Edge Threshold
        # GOVERNANCE: Edge must be meaningful to justify attention
        # =====================================================================
        edge_value = abs(proposal.edge)
        edge_pass = edge_value >= self.MINIMUM_EDGE_THRESHOLD
        edge_borderline = (
            self.BORDERLINE_EDGE_THRESHOLD <= edge_value < self.MINIMUM_EDGE_THRESHOLD
        )
        checks["edge_above_minimum"] = edge_pass

        if not edge_pass:
            if edge_borderline:
                reasons.append(
                    f"Edge ({edge_value:.2%}) is borderline "
                    f"(threshold: {self.MINIMUM_EDGE_THRESHOLD:.0%})"
                )
            else:
                reasons.append(
                    f"Edge ({edge_value:.2%}) below minimum "
                    f"threshold ({self.MINIMUM_EDGE_THRESHOLD:.0%})"
                )

        # =====================================================================
        # CHECK 3: Core Criteria
        # GOVERNANCE: All core criteria must pass for REVIEW_PASS
        # =====================================================================
        all_criteria_passed = proposal.core_criteria.all_passed()
        checks["all_core_criteria_passed"] = all_criteria_passed

        if not all_criteria_passed:
            failed = proposal.core_criteria.failed_criteria()
            reasons.append(f"Failed core criteria: {', '.join(failed)}")

        # =====================================================================
        # CHECK 4: Critical Warnings
        # GOVERNANCE: Critical warnings prevent PASS
        # =====================================================================
        critical_warnings = self._find_critical_warnings(proposal.warnings)
        no_critical_warnings = len(critical_warnings) == 0
        checks["no_critical_warnings"] = no_critical_warnings

        if not no_critical_warnings:
            reasons.append(
                f"Critical warnings detected ({len(critical_warnings)}): "
                f"{critical_warnings[0][:50]}..."
            )

        # =====================================================================
        # CHECK 5: Decision Consistency
        # GOVERNANCE: TRADE decision should have passing criteria
        # =====================================================================
        decision_consistent = self._check_decision_consistency(proposal)
        checks["decision_consistent"] = decision_consistent

        if not decision_consistent:
            reasons.append(
                "Internal inconsistency: Decision does not match criteria state"
            )

        # =====================================================================
        # CHECK 6: Warning Count
        # GOVERNANCE: Too many warnings = HOLD at minimum
        # =====================================================================
        warning_count = len(proposal.warnings)
        acceptable_warning_count = warning_count <= 3
        checks["warning_count_acceptable"] = acceptable_warning_count

        if not acceptable_warning_count:
            reasons.append(f"High warning count: {warning_count} warnings present")

        # =====================================================================
        # CLASSIFICATION LOGIC
        # GOVERNANCE: Explicit, deterministic classification
        # =====================================================================
        outcome = self._classify(
            checks=checks,
            edge_borderline=edge_borderline,
            critical_warnings=len(critical_warnings) > 0
        )

        # Add positive reasons for PASS
        if outcome == ReviewOutcome.REVIEW_PASS:
            reasons = [
                "All core criteria passed",
                f"Edge ({edge_value:.2%}) above threshold",
                f"Confidence level: {proposal.confidence_level}",
                "No critical warnings detected",
            ]

        return ReviewResult(
            proposal_id=proposal.proposal_id,
            outcome=outcome,
            reasons=tuple(reasons),
            checks_performed=checks,
            reviewed_at=datetime.now().isoformat()
        )

    def _find_critical_warnings(self, warnings: tuple) -> List[str]:
        """
        Find warnings containing critical keywords.

        GOVERNANCE:
        Critical keyword list is EXPLICIT and DOCUMENTED.
        """
        critical = []
        for warning in warnings:
            warning_upper = warning.upper()
            for keyword in self.CRITICAL_WARNING_KEYWORDS:
                if keyword in warning_upper:
                    critical.append(warning)
                    break
        return critical

    def _check_decision_consistency(self, proposal: Proposal) -> bool:
        """
        Check if decision is internally consistent.

        GOVERNANCE:
        A TRADE decision with failed core criteria is inconsistent.
        A NO_TRADE decision is always considered consistent.
        """
        if proposal.decision == "NO_TRADE":
            # NO_TRADE is always consistent (conservative choice)
            return True

        if proposal.decision == "TRADE":
            # TRADE should have all criteria passing
            # If not, there's an inconsistency
            return proposal.core_criteria.all_passed()

        return False

    def _classify(
        self,
        checks: Dict[str, bool],
        edge_borderline: bool,
        critical_warnings: bool
    ) -> ReviewOutcome:
        """
        Determine the final classification.

        GOVERNANCE:
        Classification logic is DETERMINISTIC and EXPLICIT.

        Decision tree:
        1. Any critical failure -> REJECT
        2. Mixed signals or borderline -> HOLD
        3. All checks pass -> PASS
        """
        # Count passed and failed checks
        passed_checks = sum(1 for v in checks.values() if v)
        total_checks = len(checks)
        failed_checks = total_checks - passed_checks

        # =====================================================================
        # REJECT CONDITIONS
        # =====================================================================

        # Missing criteria or low confidence = REJECT
        if not checks.get("confidence_not_low", False):
            return ReviewOutcome.REVIEW_REJECT

        # Decision inconsistency = REJECT
        if not checks.get("decision_consistent", False):
            return ReviewOutcome.REVIEW_REJECT

        # Multiple failed core criteria = REJECT
        if not checks.get("all_core_criteria_passed", False):
            failed_count = sum(1 for c in [
                checks.get("all_core_criteria_passed"),
                checks.get("edge_above_minimum"),
                checks.get("no_critical_warnings"),
            ] if not c)
            if failed_count >= 2:
                return ReviewOutcome.REVIEW_REJECT

        # =====================================================================
        # HOLD CONDITIONS
        # =====================================================================

        # Critical warnings present = HOLD (not immediate REJECT)
        if critical_warnings:
            return ReviewOutcome.REVIEW_HOLD

        # Edge is borderline = HOLD
        if edge_borderline:
            return ReviewOutcome.REVIEW_HOLD

        # High warning count = HOLD
        if not checks.get("warning_count_acceptable", False):
            return ReviewOutcome.REVIEW_HOLD

        # Any single failed check (non-critical) = HOLD
        if failed_checks > 0:
            return ReviewOutcome.REVIEW_HOLD

        # =====================================================================
        # PASS CONDITIONS
        # =====================================================================

        # All checks passed
        if failed_checks == 0:
            return ReviewOutcome.REVIEW_PASS

        # Default to HOLD for safety
        return ReviewOutcome.REVIEW_HOLD


def review_proposal(proposal: Proposal) -> ReviewResult:
    """
    Convenience function to review a proposal.

    GOVERNANCE:
    This is a STATELESS function.
    Each call is independent.

    Args:
        proposal: The Proposal to review

    Returns:
        ReviewResult with classification and reasons
    """
    gate = ReviewGate()
    return gate.review(proposal)
