# =============================================================================
# POLYMARKET BEOBACHTER - PAPER TRADING CLI
# =============================================================================
#
# GOVERNANCE INTENT:
# This CLI provides command-line access to paper trading functions.
# It is designed for autonomous, unattended operation.
#
# USAGE:
#   python -m paper_trader.run --once          # Process new proposals, check positions
#   python -m paper_trader.run --daily-report  # Generate daily report only
#   python -m paper_trader.run --status        # Show current status
#
# WINDOWS TASK SCHEDULER:
#   cd "C:\Chatgpt_Codex\polymarket Beobachter" && python -m paper_trader.run --once
#
# PAPER TRADING ONLY:
# This CLI does NOT place real orders.
# It simulates trades for data collection purposes.
#
# =============================================================================

import argparse
import sys
import logging
from datetime import datetime
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from paper_trader import GOVERNANCE_NOTICE
from paper_trader.intake import get_eligible_proposals
from paper_trader.simulator import simulate_entry
from paper_trader.position_manager import check_and_close_resolved, get_position_summary
from paper_trader.reporter import generate_daily_report, print_summary
from paper_trader.logger import get_paper_logger


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


# =============================================================================
# CLI BANNER
# =============================================================================

BANNER = """
================================================================================
 POLYMARKET BEOBACHTER - PAPER TRADING MODULE
================================================================================

  ____   _    ____  _____ ____    _____ ____      _    ____  _____
 |  _ | / |  |  _ || ____|  _ |  |_   _|  _ |    / |  |  _ || ____|
 | |_)/ _ | | |_)|  _| | |_) |   | | | |_) |  / _ | | | | |  _|
 |  __/ ___ ||  __/| |___|  _ <    | | |  _ <  / ___ || |_| | |___
 |_| /_/   |_|_|   |_____|_| |_|   |_| |_| |_|/_/   |_|____/|_____|

                 SIMULATION ONLY - NO REAL TRADING

================================================================================
"""


# =============================================================================
# CLI COMMANDS
# =============================================================================


def cmd_run_once() -> int:
    """
    Run one cycle of paper trading.

    Steps:
    1. Get eligible proposals
    2. Simulate entry for new proposals
    3. Check and close resolved positions
    4. Print summary

    Returns:
        Exit code (0 for success)
    """
    logger.info("Starting paper trading cycle")
    print("\n[1/3] Fetching eligible proposals...")

    # Step 1: Get eligible proposals
    eligible = get_eligible_proposals()
    print(f"      Found {len(eligible)} eligible proposals")

    # Step 2: Simulate entries
    print("\n[2/3] Simulating entries...")
    entered = 0
    skipped = 0

    for proposal in eligible:
        position, record = simulate_entry(proposal)
        if position is not None:
            entered += 1
            print(f"      ENTER: {proposal.market_id[:30]}... | {position.side} @ {position.entry_price:.4f}")
        else:
            skipped += 1
            print(f"      SKIP:  {proposal.market_id[:30]}... | {record.reason[:50]}")

    print(f"      Entered: {entered} | Skipped: {skipped}")

    # Step 3: Check and close resolved positions
    print("\n[3/3] Checking open positions for resolution...")
    close_summary = check_and_close_resolved()
    print(f"      Checked: {close_summary['checked']} | Closed: {close_summary['closed']} | Still open: {close_summary['still_open']}")

    if close_summary['total_pnl_eur'] != 0:
        print(f"      Realized P&L: {close_summary['total_pnl_eur']:+.2f} EUR")

    # Print summary
    print_summary()

    logger.info("Paper trading cycle complete")
    return 0


def cmd_daily_report() -> int:
    """
    Generate daily report.

    Returns:
        Exit code (0 for success)
    """
    print("\nGenerating daily report...")
    report_path = generate_daily_report()
    print(f"Report saved to: {report_path}")
    return 0


def cmd_status() -> int:
    """
    Show current paper trading status.

    Returns:
        Exit code (0 for success)
    """
    print("\n[STATUS] Paper Trading Module")
    print_summary()

    # Show position details
    summary = get_position_summary()
    print(f"Position Summary:")
    print(f"  Total:    {summary['total_positions']}")
    print(f"  Open:     {summary['open']}")
    print(f"  Closed:   {summary['closed']}")
    print(f"  Resolved: {summary['resolved']}")
    print(f"  P&L:      {summary['total_realized_pnl_eur']:+.2f} EUR (paper)")
    print()

    return 0


# =============================================================================
# ARGUMENT PARSER
# =============================================================================


def create_parser() -> argparse.ArgumentParser:
    """Create the argument parser."""
    parser = argparse.ArgumentParser(
        prog="python -m paper_trader.run",
        description="Paper Trading Module CLI (SIMULATION ONLY)",
        epilog="Note: This module does NOT execute real trades.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # Mode selection (mutually exclusive)
    mode_group = parser.add_mutually_exclusive_group(required=True)

    mode_group.add_argument(
        "--once",
        action="store_true",
        help="Run one paper trading cycle (process new proposals, check positions)"
    )

    mode_group.add_argument(
        "--daily-report",
        action="store_true",
        help="Generate daily summary report"
    )

    mode_group.add_argument(
        "--status",
        action="store_true",
        help="Show current paper trading status"
    )

    # Optional flags
    parser.add_argument(
        "--quiet", "-q",
        action="store_true",
        help="Suppress banner output"
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
    if not args.quiet:
        print(BANNER)

    # Print governance notice
    print(GOVERNANCE_NOTICE)

    # Route to command
    if args.once:
        return cmd_run_once()
    elif args.daily_report:
        return cmd_daily_report()
    elif args.status:
        return cmd_status()
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
