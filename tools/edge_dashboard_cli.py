#!/usr/bin/env python3
# =============================================================================
# EDGE DASHBOARD CLI
# =============================================================================
#
# Command-line interface for Edge Exposure Dashboard metrics.
#
# GOVERNANCE:
# This tool is for ANALYTICS only.
# It does NOT influence trading decisions.
# It has NO imports from decision_engine or execution_engine.
#
# COMMANDS:
#   build-summary     - Build edge exposure summary for a time window
#   print-summary     - Print the latest saved summary
#   position-details  - Show per-position breakdown
#
# USAGE:
#   python tools/edge_dashboard_cli.py build-summary --window last_24h
#   python tools/edge_dashboard_cli.py build-summary --window last_7d
#   python tools/edge_dashboard_cli.py build-summary --window all_time
#   python tools/edge_dashboard_cli.py print-summary
#   python tools/edge_dashboard_cli.py position-details
#
# =============================================================================

import argparse
import json
import logging
import sys
from pathlib import Path

# Setup paths
BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR))

from core.edge_exposure_aggregator import (
    EdgeExposureAggregator,
    build_summary,
    get_summary,
    get_aggregator,
)
from core.edge_exposure_metrics import (
    TimeWindow,
    EdgeExposureSummary,
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


def cmd_build_summary(args):
    """Build edge exposure summary for a time window."""
    print("\n" + "=" * 70)
    print("EDGE EXPOSURE DASHBOARD - BUILD SUMMARY")
    print("=" * 70)
    print("\nGOVERNANCE: This is an ANALYTICS operation only.")
    print("            It does NOT suggest trading actions.\n")

    try:
        window = TimeWindow.from_string(args.window)
    except ValueError as e:
        print(f"Error: {e}")
        return 1

    print(f"Time window: {window.value}")
    print("-" * 70)

    summary = build_summary(window=window, save=True)

    _print_summary_table(summary)

    print(f"\nSummary saved to: data/edge_evolution/edge_exposure_summary.json")
    print()
    return 0


def cmd_print_summary(args):
    """Print the latest saved summary."""
    print("\n" + "=" * 70)
    print("EDGE EXPOSURE DASHBOARD - LATEST SUMMARY")
    print("=" * 70)
    print("\nGOVERNANCE: This is an ANALYTICS display only.")
    print("            It does NOT suggest trading actions.\n")

    summary = get_summary()

    if summary is None:
        print("No summary found. Run 'build-summary' first.")
        return 1

    _print_summary_table(summary)
    print()
    return 0


def cmd_position_details(args):
    """Show per-position breakdown."""
    print("\n" + "=" * 70)
    print("EDGE EXPOSURE DASHBOARD - POSITION DETAILS")
    print("=" * 70)
    print("\nGOVERNANCE: This is an ANALYTICS display only.")
    print("            It does NOT suggest trading actions.\n")

    try:
        window = TimeWindow.from_string(args.window)
    except ValueError as e:
        print(f"Error: {e}")
        return 1

    aggregator = get_aggregator()
    summary = aggregator.run(window)

    if not summary.position_metrics:
        print("No positions found.")
        return 0

    print(f"Time window: {window.value}")
    print(f"Positions: {len(summary.position_metrics)}")
    print("-" * 70)

    # Sort by edge area (descending)
    sorted_positions = sorted(
        summary.position_metrics,
        key=lambda p: p.edge_area_minutes,
        reverse=True,
    )

    # Print header
    print(f"\n{'Position ID':<28} {'Snaps':>6} {'Edge Area (h)':>13} {'Pos Area (h)':>12} {'Ratio':>8}")
    print("-" * 70)

    for pm in sorted_positions[:args.limit]:
        edge_hours = pm.edge_area_minutes / 60
        pos_hours = pm.positive_edge_area_minutes / 60
        neg_hours = abs(pm.negative_edge_area_minutes) / 60
        total = pos_hours + neg_hours
        ratio = pos_hours / total if total > 0 else 0.0

        print(
            f"{pm.position_id:<28} "
            f"{pm.snapshot_count:>6} "
            f"{edge_hours:>13.2f} "
            f"{pos_hours:>12.2f} "
            f"{ratio:>8.2%}"
        )

    if len(summary.position_metrics) > args.limit:
        print(f"\n... and {len(summary.position_metrics) - args.limit} more positions")

    print()
    return 0


def cmd_json_export(args):
    """Export summary as JSON to stdout."""
    try:
        window = TimeWindow.from_string(args.window)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    aggregator = get_aggregator()
    summary = aggregator.run(window)

    print(summary.to_json(include_positions=args.include_positions))
    return 0


def _print_summary_table(summary: EdgeExposureSummary):
    """Print a formatted summary table."""
    print(f"Generated at:      {summary.generated_at_utc[:19]} UTC")
    print(f"Time window:       {summary.time_window}")
    print()
    print(f"{'Metric':<35} {'Value':>15}")
    print("-" * 52)
    print(f"{'Open Positions':<35} {summary.open_positions_count:>15}")
    print(f"{'Total Snapshots':<35} {summary.snapshot_count:>15}")
    print()
    print(f"{'Total Edge Exposure (hours)':<35} {summary.total_edge_exposure_hours:>15.2f}")
    print(f"{'Positive Edge Exposure (hours)':<35} {summary.positive_edge_exposure_hours:>15.2f}")
    print(f"{'Negative Edge Exposure (hours)':<35} {summary.negative_edge_exposure_hours:>15.2f}")
    print()

    if summary.edge_exposure_ratio is not None:
        print(f"{'Edge Exposure Ratio':<35} {summary.edge_exposure_ratio:>15.2%}")
    else:
        print(f"{'Edge Exposure Ratio':<35} {'N/A':>15}")

    if summary.median_edge_duration_minutes is not None:
        print(f"{'Median Positive Edge Duration':<35} {summary.median_edge_duration_minutes:>12} min")
    else:
        print(f"{'Median Positive Edge Duration':<35} {'N/A':>15}")

    print()
    print("-" * 52)
    print("INTERPRETATION GUIDE:")
    print("-" * 52)
    print("  Edge Exposure Ratio:")
    print("    1.0  = All positive edge (consistent advantage)")
    print("    0.5  = Equal positive and negative")
    print("    0.0  = All negative edge (consistent disadvantage)")
    print()
    print("  WHAT THIS TELLS YOU:")
    print("    - High ratio = We consistently had an advantage")
    print("    - Low ratio = Our edge was frequently negative")
    print()
    print("  WHAT THIS DOES NOT TELL YOU:")
    print("    - When to exit positions")
    print("    - How much profit we made")
    print("    - What actions to take")


# =============================================================================
# MAIN
# =============================================================================


def main():
    parser = argparse.ArgumentParser(
        description="Edge Dashboard CLI - Aggregate edge exposure metrics (analytics only)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
GOVERNANCE STATEMENT:
This tool is for ANALYTICS only. It does NOT influence trading decisions.
It has NO imports from decision_engine or execution_engine.

The Edge Dashboard answers: "Did we consistently have an advantage?"
It must NEVER answer: "What should we do now?"

Examples:
  python tools/edge_dashboard_cli.py build-summary --window last_24h
  python tools/edge_dashboard_cli.py build-summary --window last_7d
  python tools/edge_dashboard_cli.py build-summary --window all_time
  python tools/edge_dashboard_cli.py print-summary
  python tools/edge_dashboard_cli.py position-details --window last_7d
  python tools/edge_dashboard_cli.py json-export --window all_time
        """
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # build-summary
    build_parser = subparsers.add_parser(
        "build-summary",
        help="Build edge exposure summary for a time window"
    )
    build_parser.add_argument(
        "--window", "-w", default="all_time",
        choices=["last_24h", "last_7d", "all_time"],
        help="Time window for aggregation (default: all_time)"
    )
    build_parser.set_defaults(func=cmd_build_summary)

    # print-summary
    print_parser = subparsers.add_parser(
        "print-summary",
        help="Print the latest saved summary"
    )
    print_parser.set_defaults(func=cmd_print_summary)

    # position-details
    details_parser = subparsers.add_parser(
        "position-details",
        help="Show per-position breakdown"
    )
    details_parser.add_argument(
        "--window", "-w", default="all_time",
        choices=["last_24h", "last_7d", "all_time"],
        help="Time window (default: all_time)"
    )
    details_parser.add_argument(
        "--limit", "-l", type=int, default=20,
        help="Maximum positions to show (default: 20)"
    )
    details_parser.set_defaults(func=cmd_position_details)

    # json-export
    json_parser = subparsers.add_parser(
        "json-export",
        help="Export summary as JSON to stdout"
    )
    json_parser.add_argument(
        "--window", "-w", default="all_time",
        choices=["last_24h", "last_7d", "all_time"],
        help="Time window (default: all_time)"
    )
    json_parser.add_argument(
        "--include-positions", "-p", action="store_true",
        help="Include per-position breakdown"
    )
    json_parser.set_defaults(func=cmd_json_export)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
