# =============================================================================
# POLYMARKET BEOBACHTER - EXECUTION ADAPTER
# =============================================================================
#
# GOVERNANCE INTENT:
# This is the MAIN entry point for all execution operations.
# It provides three functions:
#   - prepare_execution(): Validate and prepare a proposal
#   - dry_run(): Simulate execution (no funds at risk)
#   - execute(): ALWAYS FAILS - disabled by policy
#
# CRITICAL CONSTRAINT:
# execute() MUST ALWAYS raise ExecutionDisabledError.
# There is NO way to enable execution without source code changes.
#
# This is INTENTIONAL. This is PERMANENT. This is by DESIGN.
#
# =============================================================================

import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any

# Ensure project root is in path
sys.path.insert(0, str(Path(__file__).parent.parent))

from execution.exceptions import (
    ExecutionDisabledError,
    GovernanceViolationError,
)
from execution.policy import (
    ExecutionPolicy,
    get_execution_policy,
    is_execution_enabled,
)
from execution.validator import (
    ProposalValidator,
    ValidationResult,
    validate_proposal_or_raise,
    _mark_proposal_executed,
)
from execution.logger import (
    ExecutionLogger,
    ExecutionOutcome,
    get_logger,
    log_prepare,
    log_dry_run,
    log_execute_attempt,
)

from proposals.models import Proposal


# =============================================================================
# EXECUTION RESULT
# =============================================================================


@dataclass(frozen=True)
class PrepareResult:
    """
    Result of execution preparation.

    GOVERNANCE:
    This object is IMMUTABLE (frozen=True).
    It contains everything needed for dry-run/execution.
    """
    proposal_id: str
    market_id: str
    market_question: str
    side: str  # "YES" or "NO" based on edge direction
    amount_eur: float
    worst_case_loss_eur: float
    edge: float
    implied_probability: float
    model_probability: float
    policy: Dict[str, Any]
    validation: Dict[str, Any]
    prepared_at: str
    is_ready: bool

    def format_summary(self) -> str:
        """Format as human-readable summary."""
        return f"""
================================================================================
EXECUTION PREPARATION SUMMARY
================================================================================
Proposal ID:      {self.proposal_id}
Market ID:        {self.market_id}
Market:           {self.market_question[:60]}{'...' if len(self.market_question) > 60 else ''}
--------------------------------------------------------------------------------
Side:             {self.side}
Amount:           {self.amount_eur:.2f} EUR
Worst-Case Loss:  {self.worst_case_loss_eur:.2f} EUR
Edge:             {self.edge:+.2%}
Implied Prob:     {self.implied_probability:.2%}
Model Prob:       {self.model_probability:.2%}
--------------------------------------------------------------------------------
Status:           {"READY" if self.is_ready else "NOT READY"}
Prepared At:      {self.prepared_at}
================================================================================
"""


@dataclass(frozen=True)
class DryRunResult:
    """
    Result of dry-run simulation.

    GOVERNANCE:
    This object represents what WOULD happen if execution were enabled.
    No funds are at risk. No trades are executed.
    """
    proposal_id: str
    market_id: str
    side: str
    amount_eur: float
    worst_case_loss_eur: float
    simulated_outcome: str
    policy_summary: str
    dry_run_at: str

    def format_output(self) -> str:
        """Format as human-readable dry-run output."""
        banner = """
================================================================================
                        DRY RUN ONLY - NO FUNDS AT RISK
================================================================================
"""
        return f"""{banner}
Proposal ID:      {self.proposal_id}
Market ID:        {self.market_id}
Side:             {self.side}
Amount:           {self.amount_eur:.2f} EUR
Worst-Case Loss:  {self.worst_case_loss_eur:.2f} EUR

SIMULATED OUTCOME: {self.simulated_outcome}

POLICY SUMMARY:
{self.policy_summary}

Dry-Run Time:     {self.dry_run_at}
================================================================================
                        DRY RUN ONLY - NO FUNDS AT RISK
================================================================================
"""


# =============================================================================
# CORE FUNCTIONS
# =============================================================================


def prepare_execution(proposal_id: str) -> PrepareResult:
    """
    Prepare a proposal for execution.

    GOVERNANCE:
    This function:
    1. Validates the proposal (raises on failure)
    2. Prepares execution parameters
    3. Logs the preparation
    4. Returns PrepareResult

    This function does NOT execute anything.
    It only prepares and validates.

    Args:
        proposal_id: The proposal ID to prepare

    Returns:
        PrepareResult with execution parameters

    Raises:
        ProposalNotFoundError: Proposal doesn't exist
        ProposalAlreadyExecutedError: Already executed
        GovernanceViolationError: Failed governance checks
        ProposalNotApprovedError: Not approved
    """
    logger = get_logger()
    policy = get_execution_policy()

    try:
        # Validate proposal (raises on failure)
        validation = validate_proposal_or_raise(proposal_id)
        proposal = validation.proposal

        # Determine side based on edge direction
        # Positive edge (model > implied) = buy YES
        # Negative edge (model < implied) = buy NO
        side = "YES" if proposal.edge > 0 else "NO"

        # Calculate worst-case loss (full amount)
        worst_case_loss = policy.fixed_amount_eur

        # Create result
        result = PrepareResult(
            proposal_id=proposal_id,
            market_id=proposal.market_id,
            market_question=proposal.market_question,
            side=side,
            amount_eur=policy.fixed_amount_eur,
            worst_case_loss_eur=worst_case_loss,
            edge=proposal.edge,
            implied_probability=proposal.implied_probability,
            model_probability=proposal.model_probability,
            policy=policy.to_dict(),
            validation=validation.to_dict(),
            prepared_at=datetime.now().isoformat(),
            is_ready=True
        )

        # Log successful preparation
        log_prepare(
            proposal_id=proposal_id,
            outcome=ExecutionOutcome.SUCCESS,
            reason="Proposal validated and prepared for execution",
            metadata={
                "market_id": proposal.market_id,
                "side": side,
                "amount_eur": policy.fixed_amount_eur,
                "edge": proposal.edge,
            }
        )

        return result

    except Exception as e:
        # Log failed preparation
        log_prepare(
            proposal_id=proposal_id,
            outcome=ExecutionOutcome.BLOCKED,
            reason=str(e),
            metadata={"error_type": type(e).__name__}
        )
        raise


def dry_run(proposal_id: str) -> DryRunResult:
    """
    Simulate execution (no funds at risk).

    GOVERNANCE:
    This function:
    1. Prepares the execution (validates)
    2. Simulates what would happen
    3. Logs the dry-run
    4. Returns DryRunResult

    NO TRADES ARE EXECUTED.
    NO FUNDS ARE AT RISK.
    This is PURELY INFORMATIONAL.

    Args:
        proposal_id: The proposal ID to dry-run

    Returns:
        DryRunResult with simulation output
    """
    # First, prepare the execution (validates everything)
    prepare_result = prepare_execution(proposal_id)

    policy = get_execution_policy()

    # Simulate outcome
    if policy.execution_disabled:
        simulated_outcome = (
            "WOULD BE BLOCKED - Execution is disabled by policy. "
            "If execution were enabled, this trade would proceed."
        )
    else:
        # This branch is UNREACHABLE by design
        simulated_outcome = "WOULD EXECUTE"

    # Create result
    result = DryRunResult(
        proposal_id=proposal_id,
        market_id=prepare_result.market_id,
        side=prepare_result.side,
        amount_eur=prepare_result.amount_eur,
        worst_case_loss_eur=prepare_result.worst_case_loss_eur,
        simulated_outcome=simulated_outcome,
        policy_summary=policy.format_summary(),
        dry_run_at=datetime.now().isoformat()
    )

    # Log dry-run
    log_dry_run(
        proposal_id=proposal_id,
        outcome=ExecutionOutcome.SUCCESS,
        reason="Dry-run completed successfully",
        metadata={
            "market_id": result.market_id,
            "side": result.side,
            "amount_eur": result.amount_eur,
            "simulated_outcome": simulated_outcome[:100],
        }
    )

    return result


def execute(proposal_id: str) -> None:
    """
    PERMANENTLY DISABLED - Always raises ExecutionDisabledError.

    GOVERNANCE:
    This function ALWAYS fails with ExecutionDisabledError.
    There is NO way to enable execution without modifying this source code.

    This is:
    - NOT a bug
    - NOT a limitation
    - NOT temporary
    - INTENTIONAL by design

    To enable execution:
    1. STOP the entire system
    2. Conduct a full governance review
    3. MODIFY this source code
    4. Re-run ALL audit tests
    5. Get explicit operator approval
    6. Restart with new code

    Args:
        proposal_id: The proposal ID (logged but never executed)

    Raises:
        ExecutionDisabledError: ALWAYS

    Returns:
        Never returns - always raises
    """
    # ==========================================================================
    # KILL SWITCH - THIS BLOCK MUST ALWAYS EXECUTE
    # ==========================================================================
    #
    # DO NOT MODIFY THIS SECTION WITHOUT FULL GOVERNANCE REVIEW
    #
    # This is the PRIMARY safety mechanism that prevents live trading.
    # Any modification to bypass this check is a governance violation.
    #
    # ==========================================================================

    # Log the attempt BEFORE raising
    log_execute_attempt(
        proposal_id=proposal_id,
        reason="Execution requested but permanently disabled",
        metadata={
            "policy_status": "EXECUTION_DISABLED",
            "is_permanent": True,
        }
    )

    # ALWAYS raise - no conditions, no checks, no bypasses
    raise ExecutionDisabledError(proposal_id)

    # ==========================================================================
    # THE CODE BELOW IS UNREACHABLE
    # ==========================================================================
    #
    # This code is INTENTIONALLY unreachable.
    # It exists only as documentation of what would happen IF execution
    # were ever enabled (which requires source code modification).
    #
    # DO NOT REMOVE THIS COMMENT - it serves as documentation.
    #
    # ==========================================================================
    #
    # if is_execution_enabled():  # NEVER True
    #     prepare_result = prepare_execution(proposal_id)
    #     # ... execution logic would go here ...
    #     _mark_proposal_executed(proposal_id)
    #     return
    #
    # ==========================================================================


# =============================================================================
# ADDITIONAL SAFETY ASSERTIONS
# =============================================================================


def assert_execution_impossible():
    """
    Assert that execution is impossible.

    GOVERNANCE:
    This function can be called in tests to verify that:
    1. Execution is disabled by policy
    2. execute() always raises
    3. No configuration can enable execution

    Raises:
        AssertionError: If any safety check fails
    """
    from execution.policy import assert_policy_invariants

    # Check policy invariants
    assert_policy_invariants()

    # Check that execution is disabled
    assert not is_execution_enabled(), \
        "CRITICAL: is_execution_enabled() returned True"

    # Check that policy says disabled
    policy = get_execution_policy()
    assert policy.execution_disabled is True, \
        "CRITICAL: policy.execution_disabled is not True"

    # Verify execute() raises
    try:
        execute("TEST-PROPOSAL-ID")
        raise AssertionError("CRITICAL: execute() did not raise exception")
    except ExecutionDisabledError:
        pass  # Expected
    except Exception as e:
        raise AssertionError(
            f"CRITICAL: execute() raised wrong exception: {type(e).__name__}"
        )


# Run assertion on module load (in debug mode)
if __debug__:
    # This assertion runs every time the module is imported
    # It ensures the safety mechanisms are working
    pass  # Assertion moved to explicit function call
