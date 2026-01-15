# =============================================================================
# POLYMARKET BEOBACHTER - EXECUTION POLICY (STATIC)
# =============================================================================
#
# GOVERNANCE INTENT:
# This module defines IMMUTABLE execution parameters.
# These parameters CANNOT be changed at runtime.
# They are CONSTANTS, not configuration.
#
# WHY IMMUTABLE:
# - Prevents runtime manipulation
# - Ensures audit trail integrity
# - Forces code review for any changes
# - Makes policy explicit and visible
#
# TO CHANGE THESE VALUES:
# 1. Stop the system
# 2. Modify THIS SOURCE CODE
# 3. Review changes in code review
# 4. Re-run all tests
# 5. Restart with new parameters
#
# THERE IS NO RUNTIME OVERRIDE. THIS IS INTENTIONAL.
#
# =============================================================================

from dataclasses import dataclass
from typing import Final


# =============================================================================
# EXECUTION POLICY CONSTANTS
# =============================================================================
#
# These are FINAL values. They cannot be modified after module load.
# Any attempt to override them at runtime will fail.
#
# =============================================================================

# Fixed trade amount in EUR
# GOVERNANCE: This is the MAXIMUM amount that can be risked per trade
FIXED_AMOUNT_EUR: Final[float] = 100.0

# Maximum allowed slippage (0.02 = 2%)
# GOVERNANCE: If slippage exceeds this, execution MUST abort
MAX_SLIPPAGE: Final[float] = 0.02

# Maximum exposure per market (in EUR)
# GOVERNANCE: Total position size cannot exceed this value
MAX_EXPOSURE_PER_MARKET_EUR: Final[float] = 500.0

# One-shot execution policy
# GOVERNANCE: Each proposal can only be executed ONCE
ONE_SHOT_ONLY: Final[bool] = True

# No re-entry policy
# GOVERNANCE: Cannot re-enter a market after exiting
NO_REENTRY: Final[bool] = True

# Execution disabled flag
# GOVERNANCE: This is ALWAYS True and CANNOT be changed
EXECUTION_DISABLED: Final[bool] = True

# Dry-run enabled flag
# GOVERNANCE: Dry-run is the ONLY allowed operation
DRY_RUN_ENABLED: Final[bool] = True


# =============================================================================
# POLICY DATACLASS
# =============================================================================


@dataclass(frozen=True)
class ExecutionPolicy:
    """
    Immutable execution policy container.

    GOVERNANCE:
    This dataclass is FROZEN (immutable after creation).
    The class method get_policy() returns the ONLY valid policy.
    There is NO way to construct a policy with different values.

    FIELDS:
    - fixed_amount_eur: Fixed trade amount (EUR)
    - max_slippage: Maximum allowed slippage (decimal)
    - max_exposure_per_market_eur: Maximum position per market (EUR)
    - one_shot_only: Each proposal executes at most once
    - no_reentry: Cannot re-enter after exit
    - execution_disabled: Execution is disabled (ALWAYS True)
    - dry_run_enabled: Dry-run is allowed (ALWAYS True)
    """

    fixed_amount_eur: float
    max_slippage: float
    max_exposure_per_market_eur: float
    one_shot_only: bool
    no_reentry: bool
    execution_disabled: bool
    dry_run_enabled: bool

    def __post_init__(self):
        """
        Validate policy values after initialization.

        GOVERNANCE:
        - execution_disabled MUST be True
        - This check is REDUNDANT by design (defense in depth)
        """
        # CRITICAL: Execution must ALWAYS be disabled
        if not self.execution_disabled:
            raise ValueError(
                "GOVERNANCE VIOLATION: execution_disabled must be True. "
                "Live execution is not permitted."
            )

        # Validate amount is positive
        if self.fixed_amount_eur <= 0:
            raise ValueError(
                f"Invalid fixed_amount_eur: {self.fixed_amount_eur}. "
                "Must be positive."
            )

        # Validate slippage is in range
        if not (0.0 < self.max_slippage <= 0.10):
            raise ValueError(
                f"Invalid max_slippage: {self.max_slippage}. "
                "Must be between 0 and 10%."
            )

        # Validate exposure is positive
        if self.max_exposure_per_market_eur <= 0:
            raise ValueError(
                f"Invalid max_exposure_per_market_eur: "
                f"{self.max_exposure_per_market_eur}. Must be positive."
            )

    @classmethod
    def get_policy(cls) -> "ExecutionPolicy":
        """
        Get the ONLY valid execution policy.

        GOVERNANCE:
        This is the SINGLE SOURCE OF TRUTH for execution policy.
        There is NO other way to get a valid policy.

        Returns:
            ExecutionPolicy with hardcoded values

        Note:
            The returned policy always has execution_disabled=True.
        """
        return cls(
            fixed_amount_eur=FIXED_AMOUNT_EUR,
            max_slippage=MAX_SLIPPAGE,
            max_exposure_per_market_eur=MAX_EXPOSURE_PER_MARKET_EUR,
            one_shot_only=ONE_SHOT_ONLY,
            no_reentry=NO_REENTRY,
            execution_disabled=EXECUTION_DISABLED,
            dry_run_enabled=DRY_RUN_ENABLED,
        )

    def to_dict(self) -> dict:
        """
        Convert policy to dictionary for logging/display.

        Returns:
            Dictionary representation of policy
        """
        return {
            "fixed_amount_eur": self.fixed_amount_eur,
            "max_slippage": self.max_slippage,
            "max_exposure_per_market_eur": self.max_exposure_per_market_eur,
            "one_shot_only": self.one_shot_only,
            "no_reentry": self.no_reentry,
            "execution_disabled": self.execution_disabled,
            "dry_run_enabled": self.dry_run_enabled,
        }

    def format_summary(self) -> str:
        """
        Format policy as human-readable summary.

        Returns:
            Multi-line policy summary string
        """
        return f"""
EXECUTION POLICY SUMMARY
========================
Fixed Amount:     {self.fixed_amount_eur:.2f} EUR
Max Slippage:     {self.max_slippage:.2%}
Max Exposure:     {self.max_exposure_per_market_eur:.2f} EUR per market
One-Shot Only:    {self.one_shot_only}
No Re-Entry:      {self.no_reentry}
Execution Status: {"DISABLED" if self.execution_disabled else "ENABLED"}
Dry-Run Status:   {"ENABLED" if self.dry_run_enabled else "DISABLED"}
"""


# =============================================================================
# MODULE-LEVEL POLICY INSTANCE
# =============================================================================
#
# This is the ONLY valid policy instance.
# It is created once at module load time and cannot be modified.
#
# =============================================================================

# The one and only policy instance
_POLICY: Final[ExecutionPolicy] = ExecutionPolicy.get_policy()


def get_execution_policy() -> ExecutionPolicy:
    """
    Get the current execution policy.

    GOVERNANCE:
    This function returns the SAME immutable policy every time.
    There is no way to get a different policy.

    Returns:
        The immutable execution policy
    """
    return _POLICY


def is_execution_enabled() -> bool:
    """
    Check if execution is enabled.

    GOVERNANCE:
    This function ALWAYS returns False.
    It exists for explicit policy checking in code.

    Returns:
        Always False - execution is permanently disabled
    """
    return not _POLICY.execution_disabled


def is_dry_run_enabled() -> bool:
    """
    Check if dry-run is enabled.

    GOVERNANCE:
    Dry-run is the ONLY allowed operation.
    This function should always return True.

    Returns:
        True if dry-run is enabled
    """
    return _POLICY.dry_run_enabled


# =============================================================================
# POLICY ASSERTIONS (for testing)
# =============================================================================


def assert_policy_invariants():
    """
    Assert that policy invariants hold.

    GOVERNANCE:
    This function can be called in tests to verify policy integrity.
    It raises AssertionError if any invariant is violated.

    Raises:
        AssertionError: If any policy invariant is violated
    """
    policy = get_execution_policy()

    assert policy.execution_disabled is True, \
        "CRITICAL: execution_disabled must be True"

    assert policy.dry_run_enabled is True, \
        "dry_run_enabled should be True"

    assert policy.one_shot_only is True, \
        "one_shot_only must be True"

    assert policy.no_reentry is True, \
        "no_reentry must be True"

    assert policy.fixed_amount_eur > 0, \
        "fixed_amount_eur must be positive"

    assert 0 < policy.max_slippage <= 0.10, \
        "max_slippage must be between 0 and 10%"

    assert policy.max_exposure_per_market_eur > 0, \
        "max_exposure_per_market_eur must be positive"
