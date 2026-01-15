# =============================================================================
# POLYMARKET BEOBACHTER - EXECUTION LAYER
# =============================================================================
#
# GOVERNANCE INTENT:
# This module exists for READINESS ONLY.
# Live execution is FORBIDDEN.
#
# PURPOSE:
# - Prepare execution from approved proposals
# - Support dry-run simulation
# - Log all attempts (append-only)
#
# ABSOLUTE CONSTRAINTS:
# - ExecutionDisabledError is raised on ANY execute() call
# - No flags, env vars, or config can enable execution
# - This is INTENTIONAL and PERMANENT
#
# LAYER SEPARATION:
# This module is COMPLETELY ISOLATED from:
# - core_analyzer/
# - proposals/
# - collector/
# - shared/
#
# It MAY ONLY consume:
# - proposal_id
# - review_status == REVIEW_PASS
# - static execution parameters
#
# =============================================================================

"""
Execution Layer - Pre-Flight Module (NON-OPERATIONAL)

This module provides execution readiness capabilities WITHOUT enabling
live trading. Any attempt to execute will raise ExecutionDisabledError.

Usage:
    from execution import dry_run, prepare_execution

    # Prepare and validate a proposal for execution
    result = prepare_execution("PROP-20260115-abc12345")

    # Simulate execution (no funds at risk)
    dry_run("PROP-20260115-abc12345")

WARNING:
    execute() will ALWAYS fail with ExecutionDisabledError.
    This is intentional and cannot be overridden.
"""

from execution.exceptions import (
    ExecutionDisabledError,
    GovernanceViolationError,
    ProposalNotFoundError,
    ProposalAlreadyExecutedError,
    ProposalNotApprovedError,
)
from execution.policy import ExecutionPolicy
from execution.adapter import (
    prepare_execution,
    dry_run,
    execute,  # ALWAYS fails - exported for testing
)

__all__ = [
    # Exceptions
    "ExecutionDisabledError",
    "GovernanceViolationError",
    "ProposalNotFoundError",
    "ProposalAlreadyExecutedError",
    "ProposalNotApprovedError",
    # Policy
    "ExecutionPolicy",
    # Functions
    "prepare_execution",
    "dry_run",
    "execute",
]

# Version info
__version__ = "0.1.0"
__status__ = "NON-OPERATIONAL"

# GOVERNANCE NOTICE - printed on import in debug mode
_GOVERNANCE_NOTICE = """
================================================================================
EXECUTION LAYER - GOVERNANCE NOTICE
================================================================================

This module exists for READINESS PREPARATION ONLY.

Live execution is PERMANENTLY DISABLED.

Any call to execute() will raise:
    ExecutionDisabledError("Live execution is disabled by policy")

To enable execution:
1. Stop the running system
2. Conduct a full governance review
3. Modify source code (not configuration)
4. Re-run all audit tests
5. Restart with explicit operator approval

This is INTENTIONAL. There are NO shortcuts.

================================================================================
"""
