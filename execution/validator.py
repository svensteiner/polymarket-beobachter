# =============================================================================
# POLYMARKET BEOBACHTER - PROPOSAL VALIDATION GATE
# =============================================================================
#
# GOVERNANCE INTENT:
# This module validates proposals BEFORE any execution preparation.
# All validation failures result in explicit, logged exceptions.
#
# VALIDATION CHECKS (in order):
# 1. Proposal exists in storage
# 2. Proposal has review_result == REVIEW_PASS
# 3. Proposal decision == TRADE (not NO_TRADE)
# 4. Proposal has not been executed before (one-shot-only)
#
# FAILURE BEHAVIOR:
# - Each check failure raises a specific exception
# - All failures are logged to the audit log
# - No partial validation (all-or-nothing)
#
# =============================================================================

import json
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, Set

# Import proposal models for type checking
# NOTE: This is a READ-ONLY import - we only read proposal data
sys.path.insert(0, str(Path(__file__).parent.parent))

from proposals.models import Proposal, ReviewOutcome
from proposals.storage import get_storage
from proposals.review_gate import ReviewGate

from execution.exceptions import (
    GovernanceViolationError,
    ProposalNotFoundError,
    ProposalAlreadyExecutedError,
    ProposalNotApprovedError,
)


# =============================================================================
# EXECUTED PROPOSALS TRACKING
# =============================================================================
#
# GOVERNANCE:
# We track which proposals have been executed (or attempted) in a separate
# file to enforce ONE_SHOT_ONLY. This file is append-only.
#
# =============================================================================

EXECUTED_PROPOSALS_FILE = Path(__file__).parent / "executed_proposals.json"


def _load_executed_proposals() -> Set[str]:
    """
    Load the set of already-executed proposal IDs.

    GOVERNANCE:
    This is a READ-ONLY operation.
    Returns empty set if file doesn't exist.

    Returns:
        Set of proposal IDs that have been executed/attempted
    """
    if not EXECUTED_PROPOSALS_FILE.exists():
        return set()

    try:
        with open(EXECUTED_PROPOSALS_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return set(data.get("executed_proposals", []))
    except (json.JSONDecodeError, IOError):
        return set()


def _mark_proposal_executed(proposal_id: str) -> None:
    """
    Mark a proposal as executed.

    GOVERNANCE:
    This is an APPEND-ONLY operation.
    Once a proposal is marked, it cannot be un-marked.

    Args:
        proposal_id: The proposal ID to mark as executed
    """
    executed = _load_executed_proposals()
    executed.add(proposal_id)

    data = {
        "_metadata": {
            "description": "Tracking of executed/attempted proposals",
            "governance_notice": "This file is append-only. Do not remove entries.",
            "last_updated": datetime.now().isoformat(),
        },
        "executed_proposals": list(executed)
    }

    with open(EXECUTED_PROPOSALS_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2)


def is_proposal_executed(proposal_id: str) -> bool:
    """
    Check if a proposal has already been executed.

    GOVERNANCE:
    This enforces the ONE_SHOT_ONLY policy.

    Args:
        proposal_id: The proposal ID to check

    Returns:
        True if already executed, False otherwise
    """
    return proposal_id in _load_executed_proposals()


# =============================================================================
# VALIDATION RESULT
# =============================================================================


@dataclass(frozen=True)
class ValidationResult:
    """
    Result of proposal validation.

    GOVERNANCE:
    This object is IMMUTABLE (frozen=True).
    It contains all validation outcomes in one place.
    """

    proposal_id: str
    is_valid: bool
    proposal: Optional[Proposal]
    review_outcome: Optional[str]
    checks_passed: Dict[str, bool]
    failure_reason: Optional[str]
    validated_at: str

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for logging."""
        return {
            "proposal_id": self.proposal_id,
            "is_valid": self.is_valid,
            "review_outcome": self.review_outcome,
            "checks_passed": self.checks_passed,
            "failure_reason": self.failure_reason,
            "validated_at": self.validated_at,
        }


# =============================================================================
# PROPOSAL VALIDATOR
# =============================================================================


class ProposalValidator:
    """
    Validates proposals for execution readiness.

    GOVERNANCE:
    This validator enforces ALL prerequisites before any execution.
    No shortcuts. No bypasses. No exceptions.
    """

    def __init__(self):
        """Initialize validator with storage access."""
        self._storage = get_storage()
        self._review_gate = ReviewGate()

    def validate(self, proposal_id: str) -> ValidationResult:
        """
        Validate a proposal for execution.

        GOVERNANCE:
        All checks are performed. All failures are explicit.

        Args:
            proposal_id: The proposal ID to validate

        Returns:
            ValidationResult with validation outcome

        Note:
            This method does NOT raise exceptions.
            Use validate_or_raise() for exception-based validation.
        """
        checks = {}
        failure_reason = None
        proposal = None
        review_outcome = None

        # =====================================================================
        # CHECK 1: Proposal Exists
        # =====================================================================
        proposal = self._storage.get_proposal_by_id(proposal_id)
        checks["proposal_exists"] = proposal is not None

        if not checks["proposal_exists"]:
            failure_reason = f"Proposal not found: {proposal_id}"
            return self._create_result(
                proposal_id, False, None, None, checks, failure_reason
            )

        # =====================================================================
        # CHECK 2: Not Already Executed
        # =====================================================================
        checks["not_executed"] = not is_proposal_executed(proposal_id)

        if not checks["not_executed"]:
            failure_reason = f"Proposal already executed: {proposal_id}"
            return self._create_result(
                proposal_id, False, proposal, None, checks, failure_reason
            )

        # =====================================================================
        # CHECK 3: Decision is TRADE
        # =====================================================================
        checks["decision_is_trade"] = proposal.decision == "TRADE"

        if not checks["decision_is_trade"]:
            failure_reason = f"Proposal decision is {proposal.decision}, not TRADE"
            return self._create_result(
                proposal_id, False, proposal, None, checks, failure_reason
            )

        # =====================================================================
        # CHECK 4: Review Result is REVIEW_PASS
        # =====================================================================
        review_result = self._review_gate.review(proposal)
        review_outcome = review_result.outcome.value
        checks["review_passed"] = review_result.outcome == ReviewOutcome.REVIEW_PASS

        if not checks["review_passed"]:
            failure_reason = f"Review outcome is {review_outcome}, not REVIEW_PASS"
            return self._create_result(
                proposal_id, False, proposal, review_outcome, checks, failure_reason
            )

        # =====================================================================
        # CHECK 5: Core Criteria All Passed
        # =====================================================================
        checks["core_criteria_passed"] = proposal.core_criteria.all_passed()

        if not checks["core_criteria_passed"]:
            failed = proposal.core_criteria.failed_criteria()
            failure_reason = f"Core criteria failed: {', '.join(failed)}"
            return self._create_result(
                proposal_id, False, proposal, review_outcome, checks, failure_reason
            )

        # =====================================================================
        # ALL CHECKS PASSED
        # =====================================================================
        return self._create_result(
            proposal_id, True, proposal, review_outcome, checks, None
        )

    def _create_result(
        self,
        proposal_id: str,
        is_valid: bool,
        proposal: Optional[Proposal],
        review_outcome: Optional[str],
        checks: Dict[str, bool],
        failure_reason: Optional[str]
    ) -> ValidationResult:
        """Create a ValidationResult."""
        return ValidationResult(
            proposal_id=proposal_id,
            is_valid=is_valid,
            proposal=proposal,
            review_outcome=review_outcome,
            checks_passed=checks,
            failure_reason=failure_reason,
            validated_at=datetime.now().isoformat()
        )

    def validate_or_raise(self, proposal_id: str) -> ValidationResult:
        """
        Validate a proposal and raise exception on failure.

        GOVERNANCE:
        This method raises SPECIFIC exceptions for each failure type.
        Use this when you want exception-based control flow.

        Args:
            proposal_id: The proposal ID to validate

        Returns:
            ValidationResult (only if valid)

        Raises:
            ProposalNotFoundError: Proposal doesn't exist
            ProposalAlreadyExecutedError: Proposal was already executed
            GovernanceViolationError: Decision is not TRADE
            ProposalNotApprovedError: Review did not pass
        """
        result = self.validate(proposal_id)

        if result.is_valid:
            return result

        # Map failure to specific exception
        checks = result.checks_passed

        if not checks.get("proposal_exists", False):
            raise ProposalNotFoundError(proposal_id)

        if not checks.get("not_executed", False):
            raise ProposalAlreadyExecutedError(proposal_id)

        if not checks.get("decision_is_trade", False):
            raise GovernanceViolationError(
                result.failure_reason,
                proposal_id,
                violation_type="DECISION_NOT_TRADE"
            )

        if not checks.get("review_passed", False):
            raise ProposalNotApprovedError(
                proposal_id,
                review_status=result.review_outcome
            )

        if not checks.get("core_criteria_passed", False):
            raise GovernanceViolationError(
                result.failure_reason,
                proposal_id,
                violation_type="CRITERIA_FAILED"
            )

        # Generic governance violation for unknown failures
        raise GovernanceViolationError(
            result.failure_reason or "Unknown validation failure",
            proposal_id
        )


# =============================================================================
# MODULE-LEVEL FUNCTIONS
# =============================================================================


def validate_proposal(proposal_id: str) -> ValidationResult:
    """
    Convenience function to validate a proposal.

    Args:
        proposal_id: The proposal ID to validate

    Returns:
        ValidationResult with validation outcome
    """
    validator = ProposalValidator()
    return validator.validate(proposal_id)


def validate_proposal_or_raise(proposal_id: str) -> ValidationResult:
    """
    Convenience function to validate a proposal with exceptions.

    Args:
        proposal_id: The proposal ID to validate

    Returns:
        ValidationResult (only if valid)

    Raises:
        Various exceptions on failure (see ProposalValidator.validate_or_raise)
    """
    validator = ProposalValidator()
    return validator.validate_or_raise(proposal_id)
