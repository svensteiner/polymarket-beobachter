#!/usr/bin/env python3
# =============================================================================
# POLYMARKET BEOBACHTER - EXECUTION MODE CLI
# =============================================================================
#
# Command-line interface for managing execution engine modes.
#
# SAFETY-CRITICAL TOOL
#
# This tool controls whether the system can execute real trades.
# All state changes are logged and require explicit confirmation.
#
# COMMANDS:
# - status: Show current execution mode and state
# - disarm: Disable execution (safe state)
# - shadow: Set shadow mode (log only)
# - paper: Set paper trading mode
# - arm: Initiate 2-step arm process
# - confirm <code>: Confirm arm with challenge code
# - live: Transition from ARMED to LIVE
#
# SAFETY HIERARCHY:
# DISABLED (default) → SHADOW → PAPER → ARMED (2-step) → LIVE (env+keys)
#
# =============================================================================

import argparse
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.execution_engine import (
    ExecutionEngine,
    get_execution_engine,
    ExecutionMode,
    LIVE_MODE_ENV_VAR,
    LIVE_MODE_ENV_VALUE,
    API_KEY_ENV_VAR,
    API_SECRET_ENV_VAR,
    PRIVATE_KEY_ENV_VAR,
    ARM_CONFIRMATION_TIMEOUT,
)

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger(__name__)


# =============================================================================
# CLI COLORS
# =============================================================================

class Colors:
    """ANSI color codes for terminal output."""
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    MAGENTA = "\033[95m"
    CYAN = "\033[96m"
    WHITE = "\033[97m"
    BOLD = "\033[1m"
    RESET = "\033[0m"

    @classmethod
    def disable(cls):
        """Disable colors (for non-terminal output)."""
        cls.RED = cls.GREEN = cls.YELLOW = cls.BLUE = ""
        cls.MAGENTA = cls.CYAN = cls.WHITE = cls.BOLD = cls.RESET = ""


# Check if output is a terminal
if not sys.stdout.isatty():
    Colors.disable()


# =============================================================================
# STATUS DISPLAY
# =============================================================================


def print_banner():
    """Print CLI banner."""
    print(f"\n{Colors.BOLD}{'='*70}{Colors.RESET}")
    print(f"{Colors.BOLD}POLYMARKET BEOBACHTER - EXECUTION MODE CONTROLLER{Colors.RESET}")
    print(f"{Colors.BOLD}{'='*70}{Colors.RESET}\n")


def print_status(engine: ExecutionEngine):
    """Print current execution status."""
    state = engine.get_state()
    mode = ExecutionMode(state["mode"])

    # Mode color
    mode_colors = {
        ExecutionMode.DISABLED: Colors.RED,
        ExecutionMode.SHADOW: Colors.CYAN,
        ExecutionMode.PAPER: Colors.YELLOW,
        ExecutionMode.ARMED: Colors.MAGENTA,
        ExecutionMode.LIVE: Colors.GREEN,
    }
    mode_color = mode_colors.get(mode, Colors.WHITE)

    print(f"{Colors.BOLD}CURRENT STATE:{Colors.RESET}")
    print(f"  Mode:          {mode_color}{Colors.BOLD}{mode.value}{Colors.RESET}")
    print(f"  Last Change:   {state.get('last_mode_change', 'N/A')}")
    print(f"  Reason:        {state.get('mode_change_reason', 'N/A')}")

    # Arm status
    if state.get("arm_pending"):
        print(f"\n{Colors.YELLOW}ARM PENDING:{Colors.RESET}")
        print(f"  Challenge:     {Colors.BOLD}{state.get('arm_challenge')}{Colors.RESET}")
        print(f"  Expires:       {state.get('arm_challenge_expires')}")

    # Emergency status
    if state.get("emergency_disabled"):
        print(f"\n{Colors.RED}EMERGENCY DISABLED:{Colors.RESET}")
        print(f"  Reason:        {state.get('emergency_reason')}")

    # Statistics
    print(f"\n{Colors.BOLD}STATISTICS:{Colors.RESET}")
    print(f"  Orders Submitted:  {state.get('total_orders_submitted', 0)}")
    print(f"  Orders Filled:     {state.get('total_orders_filled', 0)}")
    print(f"  Orders Rejected:   {state.get('total_orders_rejected', 0)}")

    # Environment check
    print(f"\n{Colors.BOLD}ENVIRONMENT:{Colors.RESET}")

    live_env = os.environ.get(LIVE_MODE_ENV_VAR, "")
    live_status = Colors.GREEN + "SET" if live_env == LIVE_MODE_ENV_VALUE else Colors.RED + "NOT SET"
    print(f"  {LIVE_MODE_ENV_VAR}:  {live_status}{Colors.RESET}")

    api_key = os.environ.get(API_KEY_ENV_VAR, "")
    key_status = Colors.GREEN + "SET" if api_key else Colors.RED + "NOT SET"
    print(f"  {API_KEY_ENV_VAR}:      {key_status}{Colors.RESET}")

    api_secret = os.environ.get(API_SECRET_ENV_VAR, "")
    secret_status = Colors.GREEN + "SET" if api_secret else Colors.RED + "NOT SET"
    print(f"  {API_SECRET_ENV_VAR}:   {secret_status}{Colors.RESET}")

    private_key = os.environ.get(PRIVATE_KEY_ENV_VAR, "")
    pk_status = Colors.GREEN + "SET" if private_key else Colors.RED + "NOT SET"
    print(f"  {PRIVATE_KEY_ENV_VAR}:  {pk_status}{Colors.RESET}")

    print()


# =============================================================================
# COMMANDS
# =============================================================================


def cmd_status(args):
    """Show current status."""
    engine = get_execution_engine()
    print_status(engine)


def cmd_disarm(args):
    """Disable execution engine."""
    engine = get_execution_engine()

    print(f"{Colors.YELLOW}Disabling execution engine...{Colors.RESET}")

    if engine.disable("cli_disarm"):
        print(f"{Colors.GREEN}Execution engine DISABLED.{Colors.RESET}")
        print("All orders will be rejected.")
    else:
        print(f"{Colors.RED}Failed to disable.{Colors.RESET}")


def cmd_shadow(args):
    """Set shadow mode."""
    engine = get_execution_engine()

    print(f"{Colors.CYAN}Setting SHADOW mode...{Colors.RESET}")
    print("Orders will be logged but NOT executed.")

    if engine.set_shadow():
        print(f"{Colors.GREEN}SHADOW mode active.{Colors.RESET}")
    else:
        print(f"{Colors.RED}Failed to set SHADOW mode.{Colors.RESET}")
        print("You may need to DISARM first.")


def cmd_paper(args):
    """Set paper trading mode."""
    engine = get_execution_engine()

    print(f"{Colors.YELLOW}Setting PAPER mode...{Colors.RESET}")
    print("Orders will create paper positions but NOT be sent to exchange.")

    if engine.set_paper():
        print(f"{Colors.GREEN}PAPER mode active.{Colors.RESET}")
    else:
        print(f"{Colors.RED}Failed to set PAPER mode.{Colors.RESET}")
        print("You may need to DISARM first.")


def cmd_arm(args):
    """Initiate 2-step arm process."""
    engine = get_execution_engine()

    print(f"\n{Colors.MAGENTA}{'='*60}{Colors.RESET}")
    print(f"{Colors.MAGENTA}{Colors.BOLD}ARMING EXECUTION ENGINE{Colors.RESET}")
    print(f"{Colors.MAGENTA}{'='*60}{Colors.RESET}")

    print(f"""
{Colors.YELLOW}WARNING: You are about to ARM the execution engine.{Colors.RESET}

This is the first step toward enabling LIVE trading.
Once ARMED, you can transition to LIVE mode with the 'live' command.

{Colors.RED}LIVE TRADING INVOLVES REAL MONEY.{Colors.RESET}

To proceed, you must confirm within {ARM_CONFIRMATION_TIMEOUT} seconds.
""")

    # Initiate arm
    challenge = engine.initiate_arm()

    if not challenge:
        print(f"{Colors.RED}Failed to initiate ARM.{Colors.RESET}")
        return

    print(f"{Colors.BOLD}CHALLENGE CODE: {Colors.MAGENTA}{challenge}{Colors.RESET}")
    print(f"""
To confirm ARM, run:

    python -m tools.execution_mode_cli confirm {challenge}

This challenge expires in {ARM_CONFIRMATION_TIMEOUT} seconds.
""")


def cmd_confirm(args):
    """Confirm arm with challenge code."""
    engine = get_execution_engine()

    if not args.code:
        print(f"{Colors.RED}Error: Challenge code required.{Colors.RESET}")
        print("Usage: python -m tools.execution_mode_cli confirm <CODE>")
        return

    code = args.code.upper()

    print(f"\n{Colors.MAGENTA}Confirming ARM with code: {code}{Colors.RESET}")

    if engine.confirm_arm(code):
        print(f"""
{Colors.GREEN}{'='*60}
EXECUTION ENGINE ARMED
{'='*60}{Colors.RESET}

The execution engine is now ARMED.

{Colors.BOLD}Current capabilities:{Colors.RESET}
- Orders are validated but NOT sent
- Ready to transition to LIVE

{Colors.BOLD}To enable LIVE trading:{Colors.RESET}
1. Set environment variable: {LIVE_MODE_ENV_VAR}={LIVE_MODE_ENV_VALUE}
2. Set API credentials
3. Run: python -m tools.execution_mode_cli live

{Colors.YELLOW}To abort, run: python -m tools.execution_mode_cli disarm{Colors.RESET}
""")
    else:
        print(f"{Colors.RED}ARM confirmation FAILED.{Colors.RESET}")
        print("Check the challenge code and try again.")
        print("You may need to initiate a new ARM process.")


def cmd_live(args):
    """Transition from ARMED to LIVE."""
    engine = get_execution_engine()

    current_mode = engine.get_mode()

    if current_mode != ExecutionMode.ARMED:
        print(f"{Colors.RED}Error: Must be in ARMED mode to go LIVE.{Colors.RESET}")
        print(f"Current mode: {current_mode.value}")
        print("\nTo ARM, run: python -m tools.execution_mode_cli arm")
        return

    print(f"""
{Colors.RED}{'='*60}
GOING LIVE - FINAL WARNING
{'='*60}{Colors.RESET}

{Colors.RED}{Colors.BOLD}YOU ARE ABOUT TO ENABLE LIVE TRADING.{Colors.RESET}

This will:
- Submit REAL orders to Polymarket
- Use REAL money from your wallet
- Execute trades that CANNOT be undone

{Colors.BOLD}Requirements:{Colors.RESET}
- {LIVE_MODE_ENV_VAR}={LIVE_MODE_ENV_VALUE} (environment variable)
- Valid API credentials
""")

    # Check requirements
    live_env = os.environ.get(LIVE_MODE_ENV_VAR, "")
    api_key = os.environ.get(API_KEY_ENV_VAR, "")
    api_secret = os.environ.get(API_SECRET_ENV_VAR, "")
    private_key = os.environ.get(PRIVATE_KEY_ENV_VAR, "")

    missing = []
    if live_env != LIVE_MODE_ENV_VALUE:
        missing.append(f"{LIVE_MODE_ENV_VAR}={LIVE_MODE_ENV_VALUE}")
    if not api_key:
        missing.append(API_KEY_ENV_VAR)
    if not api_secret:
        missing.append(API_SECRET_ENV_VAR)
    if not private_key:
        missing.append(PRIVATE_KEY_ENV_VAR)

    if missing:
        print(f"{Colors.RED}Missing requirements:{Colors.RESET}")
        for m in missing:
            print(f"  - {m}")
        print("\nSet these environment variables and try again.")
        return

    # Final confirmation
    print(f"{Colors.YELLOW}Type 'LIVE' to confirm:{Colors.RESET} ", end="")
    try:
        confirmation = input().strip()
    except (EOFError, KeyboardInterrupt):
        print(f"\n{Colors.YELLOW}Aborted.{Colors.RESET}")
        return

    if confirmation != "LIVE":
        print(f"{Colors.YELLOW}Confirmation failed. Aborting.{Colors.RESET}")
        return

    # Go live
    if engine.go_live():
        print(f"""
{Colors.GREEN}{'='*60}
EXECUTION ENGINE IS NOW LIVE
{'='*60}{Colors.RESET}

{Colors.RED}REAL TRADES WILL BE EXECUTED.{Colors.RESET}

Monitor closely. To disable immediately:
    python -m tools.execution_mode_cli disarm

""")
    else:
        print(f"{Colors.RED}Failed to go LIVE.{Colors.RESET}")
        print("Check logs for details.")


def cmd_positions(args):
    """Show paper positions."""
    engine = get_execution_engine()

    positions = engine.get_paper_positions()

    print(f"\n{Colors.BOLD}PAPER POSITIONS:{Colors.RESET}")

    if not positions:
        print("  No paper positions.")
    else:
        for key, size in positions.items():
            direction = "LONG" if size > 0 else "SHORT"
            color = Colors.GREEN if size > 0 else Colors.RED
            print(f"  {key}: {color}{direction} {abs(size):.2f} shares{Colors.RESET}")

    print()


# =============================================================================
# MAIN
# =============================================================================


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Execution Mode Controller for Polymarket Beobachter",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Commands:
  status      Show current execution mode and state
  disarm      Disable execution (safe state)
  shadow      Set shadow mode (log only)
  paper       Set paper trading mode
  arm         Initiate 2-step arm process
  confirm     Confirm arm with challenge code
  live        Transition from ARMED to LIVE
  positions   Show paper positions

Examples:
  python -m tools.execution_mode_cli status
  python -m tools.execution_mode_cli arm
  python -m tools.execution_mode_cli confirm ABC123
  python -m tools.execution_mode_cli disarm
        """
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to execute")

    # Status
    status_parser = subparsers.add_parser("status", help="Show current status")
    status_parser.set_defaults(func=cmd_status)

    # Disarm
    disarm_parser = subparsers.add_parser("disarm", help="Disable execution")
    disarm_parser.set_defaults(func=cmd_disarm)

    # Shadow
    shadow_parser = subparsers.add_parser("shadow", help="Set shadow mode")
    shadow_parser.set_defaults(func=cmd_shadow)

    # Paper
    paper_parser = subparsers.add_parser("paper", help="Set paper trading mode")
    paper_parser.set_defaults(func=cmd_paper)

    # Arm
    arm_parser = subparsers.add_parser("arm", help="Initiate arm process")
    arm_parser.set_defaults(func=cmd_arm)

    # Confirm
    confirm_parser = subparsers.add_parser("confirm", help="Confirm arm")
    confirm_parser.add_argument("code", nargs="?", help="Challenge code")
    confirm_parser.set_defaults(func=cmd_confirm)

    # Live
    live_parser = subparsers.add_parser("live", help="Go live")
    live_parser.set_defaults(func=cmd_live)

    # Positions
    positions_parser = subparsers.add_parser("positions", help="Show paper positions")
    positions_parser.set_defaults(func=cmd_positions)

    args = parser.parse_args()

    print_banner()

    if args.command is None:
        # Default to status
        cmd_status(args)
    else:
        args.func(args)


if __name__ == "__main__":
    main()
