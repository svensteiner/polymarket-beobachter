# =============================================================================
# POLYMARKET BEOBACHTER - EXECUTION EXCEPTIONS
# =============================================================================
#
# GOVERNANCE INTENT:
# These exceptions encode governance violations at the type level.
# Each exception type has a specific meaning and required response.
#
# EXCEPTION HIERARCHY:
#
# ExecutionError (base)
# ├── ExecutionDisabledError    - PERMANENT: execution is disabled by policy
# ├── GovernanceViolationError  - Proposal failed governance checks
# ├── ProposalNotFoundError     - Proposal does not exist
# ├── ProposalAlreadyExecutedError - Proposal was already executed
# └── ProposalNotApprovedError  - Proposal did not pass review
#
# CRITICAL:
# ExecutionDisabledError is ALWAYS raised by execute().
# There is NO way to bypass this without code modification.
#
# =============================================================================


class ExecutionError(Exception):
    """
    Base class for all execution-related errors.

    GOVERNANCE:
    All execution errors inherit from this class.
    This allows catching all execution errors in a single except block.
    """

    def __init__(self, message: str, proposal_id: str = None):
        """
        Initialize execution error.

        Args:
            message: Error description
            proposal_id: Optional proposal ID for context
        """
        self.message = message
        self.proposal_id = proposal_id
        super().__init__(message)

    def __str__(self) -> str:
        if self.proposal_id:
            return f"[{self.proposal_id}] {self.message}"
        return self.message


class ExecutionDisabledError(ExecutionError):
    """
    CRITICAL: Execution is disabled by policy.

    GOVERNANCE:
    This exception is ALWAYS raised by execute().
    There is NO runtime mechanism to bypass this.

    To enable execution:
    1. Stop the entire system
    2. Conduct governance review
    3. Modify THIS SOURCE CODE
    4. Re-run audit tests
    5. Restart with explicit approval

    This is INTENTIONAL. Accidental execution is IMPOSSIBLE.
    """

    # This message is HARDCODED and cannot be changed at runtime
    _POLICY_MESSAGE = "Live execution is disabled by policy"

    def __init__(self, proposal_id: str = None):
        """
        Initialize with hardcoded policy message.

        GOVERNANCE:
        The message cannot be customized. This is intentional.
        """
        super().__init__(self._POLICY_MESSAGE, proposal_id)

    @property
    def is_permanent(self) -> bool:
        """
        Indicates this is a permanent policy, not a transient error.

        Returns:
            Always True - this is not fixable without code changes
        """
        return True


class GovernanceViolationError(ExecutionError):
    """
    Proposal failed governance validation.

    GOVERNANCE:
    Raised when a proposal does not meet execution prerequisites.
    The violation_type field specifies the exact failure mode.

    VIOLATION TYPES:
    - REVIEW_NOT_PASSED: Proposal review_result != REVIEW_PASS
    - DECISION_NOT_TRADE: Proposal decision != TRADE
    - CRITERIA_FAILED: Core criteria not all passed
    - ALREADY_EXECUTED: Proposal was already executed once
    """

    def __init__(
        self,
        message: str,
        proposal_id: str = None,
        violation_type: str = None
    ):
        """
        Initialize governance violation.

        Args:
            message: Error description
            proposal_id: The violating proposal ID
            violation_type: Category of violation
        """
        super().__init__(message, proposal_id)
        self.violation_type = violation_type

    def __str__(self) -> str:
        base = super().__str__()
        if self.violation_type:
            return f"{base} (violation: {self.violation_type})"
        return base


class ProposalNotFoundError(ExecutionError):
    """
    Proposal does not exist in storage.

    GOVERNANCE:
    Raised when attempting to execute a non-existent proposal.
    This prevents execution of fabricated proposal IDs.
    """

    def __init__(self, proposal_id: str):
        """
        Initialize not found error.

        Args:
            proposal_id: The missing proposal ID
        """
        super().__init__(
            f"Proposal not found: {proposal_id}",
            proposal_id
        )


class ProposalAlreadyExecutedError(ExecutionError):
    """
    Proposal has already been executed.

    GOVERNANCE:
    Each proposal can only be executed ONCE.
    This prevents double execution (replay attacks).

    ONE_SHOT_ONLY is a fundamental invariant.
    """

    def __init__(self, proposal_id: str, executed_at: str = None):
        """
        Initialize already executed error.

        Args:
            proposal_id: The proposal ID
            executed_at: When the proposal was previously executed
        """
        message = f"Proposal already executed: {proposal_id}"
        if executed_at:
            message += f" (executed at: {executed_at})"

        super().__init__(message, proposal_id)
        self.executed_at = executed_at


class ProposalNotApprovedError(ExecutionError):
    """
    Proposal has not passed review.

    GOVERNANCE:
    Only proposals with REVIEW_PASS can be prepared for execution.
    This is validated BEFORE any execution attempt.
    """

    def __init__(self, proposal_id: str, review_status: str = None):
        """
        Initialize not approved error.

        Args:
            proposal_id: The proposal ID
            review_status: The actual review status (if known)
        """
        message = f"Proposal not approved for execution: {proposal_id}"
        if review_status:
            message += f" (status: {review_status})"

        super().__init__(message, proposal_id)
        self.review_status = review_status
