# =============================================================================
# POLYMARKET BEOBACHTER - EXECUTION CLI
# =============================================================================
#
# GOVERNANCE INTENT:
# This CLI provides command-line access to execution functions.
# By DEFAULT, it runs in DRY-RUN mode.
# EXECUTE command always prints "Execution disabled" and exits.
#
# USAGE:
#   python -m execution.run --proposal <ID>           # Dry-run (default)
#   python -m execution.run --proposal <ID> --dry-run # Dry-run (explicit)
#   python -m execution.run --proposal <ID> --prepare # Prepare only
#   python -m execution.run --proposal <ID> --execute # Always fails
#
# =============================================================================

import argparse
import sys
from pathlib import Path

# Ensure project root is in path
sys.path.insert(0, str(Path(__file__).parent.parent))

from execution.adapter import (
    prepare_execution,
    dry_run,
    execute,
    assert_execution_impossible,
)
from execution.exceptions import (
    ExecutionDisabledError,
    ExecutionError,
)
from execution.policy import get_execution_policy


# =============================================================================
# CLI BANNER
# =============================================================================

BANNER = """
================================================================================
 POLYMARKET BEOBACHTER - EXECUTION MODULE (NON-OPERATIONAL)
================================================================================

 This module exists for READINESS PREPARATION ONLY.
 Live execution is PERMANENTLY DISABLED.

 Modes:
   --dry-run   Simulate execution (DEFAULT, no funds at risk)
   --prepare   Validate and prepare only
   --execute   ALWAYS FAILS - disabled by policy

================================================================================
"""

EXECUTION_DISABLED_MESSAGE = """
================================================================================
              EXECUTION DISABLED BY POLICY - NO ACTION TAKEN
================================================================================

Live execution is permanently disabled in this module.

To enable execution:
1. Stop the entire system
2. Conduct a full governance review
3. Modify the source code (not configuration)
4. Re-run all audit tests
5. Restart with explicit operator approval

This is INTENTIONAL. There are NO shortcuts.

================================================================================
"""


# =============================================================================
# CLI COMMANDS
# =============================================================================


def cmd_dry_run(proposal_id: str) -> int:
    """
    Execute dry-run for a proposal.

    Args:
        proposal_id: The proposal ID

    Returns:
        Exit code (0 for success, 1 for failure)
    """
    print(f"\n[DRY-RUN] Processing proposal: {proposal_id}\n")

    try:
        result = dry_run(proposal_id)
        print(result.format_output())
        return 0

    except ExecutionError as e:
        print(f"\n[ERROR] {e}\n")
        return 1

    except Exception as e:
        print(f"\n[UNEXPECTED ERROR] {type(e).__name__}: {e}\n")
        return 1


def cmd_prepare(proposal_id: str) -> int:
    """
    Prepare a proposal for execution.

    Args:
        proposal_id: The proposal ID

    Returns:
        Exit code (0 for success, 1 for failure)
    """
    print(f"\n[PREPARE] Processing proposal: {proposal_id}\n")

    try:
        result = prepare_execution(proposal_id)
        print(result.format_summary())
        return 0

    except ExecutionError as e:
        print(f"\n[ERROR] {e}\n")
        return 1

    except Exception as e:
        print(f"\n[UNEXPECTED ERROR] {type(e).__name__}: {e}\n")
        return 1


def cmd_execute(proposal_id: str) -> int:
    """
    Attempt to execute a proposal (ALWAYS FAILS).

    Args:
        proposal_id: The proposal ID

    Returns:
        Exit code (always 1 - execution is disabled)
    """
    print(f"\n[EXECUTE] Attempting to execute proposal: {proposal_id}\n")

    try:
        # This will ALWAYS raise ExecutionDisabledError
        execute(proposal_id)

        # This line is UNREACHABLE
        return 0

    except ExecutionDisabledError:
        print(EXECUTION_DISABLED_MESSAGE)
        return 1

    except ExecutionError as e:
        print(f"\n[ERROR] {e}\n")
        return 1

    except Exception as e:
        print(f"\n[UNEXPECTED ERROR] {type(e).__name__}: {e}\n")
        return 1


def cmd_status() -> int:
    """
    Display execution module status.

    Returns:
        Exit code (always 0)
    """
    policy = get_execution_policy()

    print("\n[STATUS] Execution Module Configuration\n")
    print(policy.format_summary())

    # Run safety assertions
    print("\n[SAFETY CHECK] Verifying execution is impossible...\n")
    try:
        assert_execution_impossible()
        print("[OK] All safety checks passed.")
        print("[OK] Execution is confirmed IMPOSSIBLE.\n")
    except AssertionError as e:
        print(f"[CRITICAL] Safety check FAILED: {e}\n")
        return 1

    return 0


# =============================================================================
# ARGUMENT PARSER
# =============================================================================


def create_parser() -> argparse.ArgumentParser:
    """Create the argument parser."""
    parser = argparse.ArgumentParser(
        prog="python -m execution.run",
        description="Execution Module CLI (NON-OPERATIONAL)",
        epilog="Note: Live execution is permanently disabled.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "--proposal", "-p",
        type=str,
        help="Proposal ID to process",
        metavar="ID"
    )

    # Mode selection (mutually exclusive)
    mode_group = parser.add_mutually_exclusive_group()

    mode_group.add_argument(
        "--dry-run", "-d",
        action="store_true",
        default=True,
        help="Simulate execution (DEFAULT, no funds at risk)"
    )

    mode_group.add_argument(
        "--prepare", "-r",
        action="store_true",
        help="Validate and prepare only (no simulation)"
    )

    mode_group.add_argument(
        "--execute", "-e",
        action="store_true",
        help="Attempt execution (ALWAYS FAILS - disabled by policy)"
    )

    mode_group.add_argument(
        "--status", "-s",
        action="store_true",
        help="Display module status and safety checks"
    )

    return parser


# =============================================================================
# MAIN
# =============================================================================


def main() -> int:
    """
    Main entry point.

    Returns:
        Exit code
    """
    parser = create_parser()
    args = parser.parse_args()

    # Print banner
    print(BANNER)

    # Handle status command (no proposal needed)
    if args.status:
        return cmd_status()

    # All other commands require a proposal ID
    if not args.proposal:
        print("[ERROR] --proposal is required for this command.\n")
        parser.print_help()
        return 1

    # Route to appropriate command
    if args.execute:
        return cmd_execute(args.proposal)
    elif args.prepare:
        return cmd_prepare(args.proposal)
    else:
        # Default is dry-run
        return cmd_dry_run(args.proposal)


if __name__ == "__main__":
    sys.exit(main())
