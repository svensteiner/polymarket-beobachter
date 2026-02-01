#!/usr/bin/env python3
# =============================================================================
# EDGE EVOLUTION TRACKER CLI
# =============================================================================
#
# Command-line interface for the Edge Evolution Tracker module.
#
# GOVERNANCE:
# This tool is for ANALYTICS only.
# It does NOT influence trading decisions.
# It has NO imports from decision_engine or execution_engine.
#
# COMMANDS:
#   snapshot-now      - Capture one snapshot cycle for all open positions
#   stats             - Print counts per position and age
#   history           - Show edge evolution history for a position
#   rebuild-index     - Rebuild derived index (optional)
#   verify-hashes     - Verify record hashes for integrity
#
# USAGE:
#   python tools/edge_tracker_cli.py snapshot-now
#   python tools/edge_tracker_cli.py stats
#   python tools/edge_tracker_cli.py history --position PAPER-20260124-abc12345
#   python tools/edge_tracker_cli.py verify-hashes
#
# =============================================================================

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

# Setup paths
BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR))

from core.edge_evolution_tracker import (
    EdgeEvolutionTracker,
    EdgeEvolutionStorage,
    get_tracker,
    run_snapshot_cycle,
    get_stats,
)
from core.edge_snapshot import (
    EdgeSnapshot,
    compute_hash,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger(__name__)


# =============================================================================
# CLI COMMANDS
# =============================================================================


def cmd_snapshot_now(args):
    """Capture one snapshot cycle for all open positions."""
    print("\n" + "=" * 60)
    print("EDGE EVOLUTION TRACKER - SNAPSHOT CYCLE")
    print("=" * 60)
    print("\nGOVERNANCE: This is an ANALYTICS operation only.")
    print("            It does NOT affect trading decisions.\n")

    result = run_snapshot_cycle(source="cli")

    print(f"\nResults:")
    print(f"  Success:           {result.get('success', False)}")
    print(f"  Positions checked: {result.get('positions_checked', 0)}")
    print(f"  Snapshots written: {result.get('snapshots_written', 0)}")
    print(f"  Skipped (dedup):   {result.get('skipped', 0)}")
    print(f"  Errors:            {result.get('errors', 0)}")

    if result.get('error'):
        print(f"\n  Error message: {result['error']}")

    print()
    return 0 if result.get('success', False) else 1


def cmd_stats(args):
    """Print counts per position and edge statistics."""
    print("\n" + "=" * 60)
    print("EDGE EVOLUTION TRACKER - STATISTICS")
    print("=" * 60)
    print("\nGOVERNANCE: This is an ANALYTICS operation only.\n")

    stats = get_stats()

    print(f"Total Snapshots:   {stats.get('total_snapshots', 0)}")
    print(f"Unique Positions:  {stats.get('unique_positions', 0)}")

    positions = stats.get('positions', {})
    if positions:
        print("\n" + "-" * 60)
        print("Position Details:")
        print("-" * 60)

        for pos_id, data in sorted(positions.items()):
            print(f"\n  Position: {pos_id}")
            print(f"    Market:    {data.get('market_id', 'unknown')}")
            print(f"    Snapshots: {data.get('count', 0)}")
            print(f"    First:     {data.get('first_snapshot', 'unknown')[:19]}")
            print(f"    Last:      {data.get('last_snapshot', 'unknown')[:19]}")
            print(f"    Min Edge:  {data.get('min_edge', 0):.4f}")
            print(f"    Max Edge:  {data.get('max_edge', 0):.4f}")
    else:
        print("\nNo positions tracked yet.")

    print()
    return 0


def cmd_history(args):
    """Show edge evolution history for a specific position."""
    position_id = args.position

    print("\n" + "=" * 60)
    print(f"EDGE EVOLUTION HISTORY - {position_id}")
    print("=" * 60)
    print("\nGOVERNANCE: This is an ANALYTICS record only. NOT a trading signal.\n")

    tracker = get_tracker()
    history = tracker.get_position_history(position_id)

    if not history:
        print(f"No history found for position: {position_id}")
        print()
        return 1

    print(f"Found {len(history)} snapshots\n")

    # Print header
    print(f"{'Time (UTC)':<20} {'Minutes':<10} {'Mkt Prob':<10} {'Fair Prob':<10} {'Edge':<12} {'Delta':<12}")
    print("-" * 74)

    for snapshot in history:
        time_str = snapshot.timestamp_utc[:19]
        print(
            f"{time_str:<20} "
            f"{snapshot.time_since_entry_minutes:<10} "
            f"{snapshot.market_probability_current:<10.4f} "
            f"{snapshot.fair_probability_entry:<10.4f} "
            f"{snapshot.edge_relative:<12.4f} "
            f"{snapshot.edge_delta_since_entry:<12.4f}"
        )

    # Analyze patterns
    if len(history) >= 3:
        print("\n" + "-" * 60)
        print("PATTERN ANALYSIS:")
        print("-" * 60)

        first_edge = history[0].edge_relative
        last_edge = history[-1].edge_relative
        edge_change = last_edge - first_edge

        if abs(last_edge) < 0.05 and abs(first_edge) > 0.10:
            print("\n  Pattern: FAST CONVERGENCE")
            print("  The market has converged toward our fair value estimate.")
            print("  The initial edge has largely disappeared.")

        elif abs(last_edge) >= abs(first_edge) * 0.8 and len(history) >= 5:
            print("\n  Pattern: PERSISTENT EDGE")
            print("  The edge remains stable over time.")
            print("  The market has not moved toward our estimate.")

        elif edge_change < -0.10:
            print("\n  Pattern: POSSIBLE FALSE EDGE")
            print("  The edge has decreased significantly.")
            print("  The market may be moving away from our estimate.")

        else:
            print("\n  Pattern: INSUFFICIENT DATA")
            print("  Not enough data to determine a clear pattern.")

    print()
    return 0


def cmd_rebuild_index(args):
    """Rebuild derived index from JSONL file."""
    print("\n" + "=" * 60)
    print("EDGE EVOLUTION TRACKER - REBUILD INDEX")
    print("=" * 60)

    storage = EdgeEvolutionStorage(BASE_DIR)
    snapshots = storage.read_snapshots()

    # Group by position
    by_position = {}
    for s in snapshots:
        if s.position_id not in by_position:
            by_position[s.position_id] = []
        by_position[s.position_id].append(s.to_dict())

    # Build index
    index = {
        "schema_version": 1,
        "built_at": datetime.now(timezone.utc).isoformat(),
        "total_snapshots": len(snapshots),
        "unique_positions": len(by_position),
        "positions": {
            pos_id: {
                "snapshot_count": len(snaps),
                "snapshots": snaps,
            }
            for pos_id, snaps in by_position.items()
        },
    }

    # Write index
    index_file = storage.edge_dir / "index.json"
    try:
        with open(index_file, "w", encoding="utf-8") as f:
            json.dump(index, f, indent=2)
        print(f"\nIndex rebuilt successfully:")
        print(f"  Total snapshots:  {index['total_snapshots']}")
        print(f"  Unique positions: {index['unique_positions']}")
        print(f"  Output:           {index_file}")
    except Exception as e:
        print(f"\nError writing index: {e}")
        return 1

    print()
    return 0


def cmd_verify_hashes(args):
    """Verify record hashes for integrity."""
    print("\n" + "=" * 60)
    print("EDGE EVOLUTION TRACKER - HASH VERIFICATION")
    print("=" * 60)

    storage = EdgeEvolutionStorage(BASE_DIR)
    snapshots = storage.read_snapshots()

    valid = 0
    invalid = 0

    for snapshot in snapshots:
        expected = compute_hash(snapshot.to_dict())
        if snapshot.record_hash == expected:
            valid += 1
        else:
            invalid += 1
            if args.verbose:
                print(f"  Invalid hash: {snapshot.snapshot_id}")

    print(f"\nResults:")
    print(f"  Valid:   {valid}")
    print(f"  Invalid: {invalid}")

    if invalid > 0:
        print(f"\n  WARNING: {invalid} records have invalid hashes!")
        print("  This may indicate data tampering or corruption.")
        return 1
    else:
        print(f"\n  All {valid} records verified successfully.")
        return 0


def cmd_list_open(args):
    """List currently open positions."""
    print("\n" + "=" * 60)
    print("CURRENTLY OPEN POSITIONS")
    print("=" * 60)

    from paper_trader.position_manager import get_open_positions

    positions = get_open_positions()

    if not positions:
        print("\nNo open positions.")
        print()
        return 0

    print(f"\nFound {len(positions)} open positions:\n")
    print(f"{'Position ID':<25} {'Market ID':<36} {'Side':<6} {'Entry Price':<12}")
    print("-" * 80)

    for pos in positions:
        print(
            f"{pos.position_id:<25} "
            f"{pos.market_id[:36]:<36} "
            f"{pos.side:<6} "
            f"{pos.entry_price:<12.4f}"
        )

    print()
    return 0


# =============================================================================
# MAIN
# =============================================================================


def main():
    parser = argparse.ArgumentParser(
        description="Edge Evolution Tracker CLI - Measure edge evolution (analytics only)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
GOVERNANCE STATEMENT:
This tool is for ANALYTICS only. It does NOT influence trading decisions.
It has NO imports from decision_engine or execution_engine.

The Edge Evolution Tracker answers ONE question:
"How long was our advantage real?"

It is NOT an exit signal generator.

Examples:
  python tools/edge_tracker_cli.py snapshot-now
  python tools/edge_tracker_cli.py stats
  python tools/edge_tracker_cli.py history --position PAPER-20260124-abc12345
  python tools/edge_tracker_cli.py list-open
  python tools/edge_tracker_cli.py verify-hashes
  python tools/edge_tracker_cli.py rebuild-index
        """
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # snapshot-now
    snapshot_parser = subparsers.add_parser(
        "snapshot-now",
        help="Capture one snapshot cycle for all open positions"
    )
    snapshot_parser.set_defaults(func=cmd_snapshot_now)

    # stats
    stats_parser = subparsers.add_parser(
        "stats",
        help="Print counts per position and edge statistics"
    )
    stats_parser.set_defaults(func=cmd_stats)

    # history
    history_parser = subparsers.add_parser(
        "history",
        help="Show edge evolution history for a specific position"
    )
    history_parser.add_argument(
        "--position", "-p", required=True,
        help="Position ID to show history for"
    )
    history_parser.set_defaults(func=cmd_history)

    # list-open
    list_parser = subparsers.add_parser(
        "list-open",
        help="List currently open positions"
    )
    list_parser.set_defaults(func=cmd_list_open)

    # rebuild-index
    rebuild_parser = subparsers.add_parser(
        "rebuild-index",
        help="Rebuild derived index from JSONL file"
    )
    rebuild_parser.set_defaults(func=cmd_rebuild_index)

    # verify-hashes
    verify_parser = subparsers.add_parser(
        "verify-hashes",
        help="Verify record hashes for integrity"
    )
    verify_parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Show verbose output"
    )
    verify_parser.set_defaults(func=cmd_verify_hashes)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
