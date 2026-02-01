#!/usr/bin/env python3
# =============================================================================
# POLYMARKET BEOBACHTER - CALIBRATION CLI
# =============================================================================
#
# Command-line interface for the calibration engine.
#
# GOVERNANCE:
# - Never mutates source data
# - Rebuilds report deterministically
# - ANALYTICS ONLY — no trading influence
#
# Commands:
#   build-report --window all_time|last_7d|last_30d|last_90d
#   print-report
#   json-export
#
# =============================================================================

import argparse
import json
import logging
import sys
from pathlib import Path

# Setup project root
BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR))

from core.calibration_engine import CalibrationEngine, REPORT_OUTPUT_PATH


# =============================================================================
# FORMATTING
# =============================================================================


def _fmt_pct(value, digits=2):
    """Format a float as percentage string, or 'N/A' if None."""
    if value is None:
        return "N/A"
    return f"{value * 100:.{digits}f}%"


def _fmt_float(value, digits=4):
    """Format a float or return 'N/A'."""
    if value is None:
        return "N/A"
    return f"{value:.{digits}f}"


def _print_bucket(label, bucket):
    """Print a single metrics bucket."""
    print(f"  {label}:")
    print(f"    Brier Score:       {_fmt_float(bucket.get('brier_score'))}")
    print(f"    Avg Probability:   {_fmt_pct(bucket.get('avg_probability'))}")
    print(f"    Actual Frequency:  {_fmt_pct(bucket.get('actual_frequency'))}")
    print(f"    Calibration Gap:   {_fmt_float(bucket.get('calibration_gap'), 4)}")
    print(f"    Sample Size:       {bucket.get('sample_size', 0)}")


def print_report(report):
    """Print a formatted calibration report to stdout."""
    print()
    print("=" * 60)
    print("CALIBRATION REPORT")
    print("Analytics Only — Does NOT Influence Trading")
    print("=" * 60)
    print()
    print(f"Generated:    {report.get('generated_at_utc', 'N/A')}")
    print(f"Time Window:  {report.get('time_window', 'N/A')}")
    print()

    # Global metrics
    g = report.get("global", {})
    print("--- GLOBAL METRICS ---")
    print(f"  Brier Score:       {_fmt_float(g.get('brier_score'))}")
    print(f"  Avg Probability:   {_fmt_pct(g.get('avg_probability'))}")
    print(f"  Actual Frequency:  {_fmt_pct(g.get('actual_frequency'))}")
    print(f"  Calibration Gap:   {_fmt_float(g.get('calibration_gap'), 4)}")
    print(f"  Sample Size:       {g.get('sample_size', 0)}")
    print()

    # By model
    by_model = report.get("by_model", {})
    if by_model:
        print("--- BY MODEL ---")
        for model_name, bucket in sorted(by_model.items()):
            _print_bucket(model_name, bucket)
        print()

    # By confidence
    by_conf = report.get("by_confidence", {})
    if by_conf:
        print("--- BY CONFIDENCE ---")
        for level in ["HIGH", "MEDIUM", "LOW", "UNKNOWN"]:
            if level in by_conf:
                _print_bucket(level, by_conf[level])
        print()

    # By odds bucket
    by_odds = report.get("by_odds_bucket", {})
    if by_odds:
        print("--- BY ODDS BUCKET ---")
        for bucket_name in sorted(by_odds.keys()):
            label = bucket_name.replace("_", "-") + "%"
            _print_bucket(label, by_odds[bucket_name])
        print()

    # Interpretation
    brier = g.get("brier_score")
    gap = g.get("calibration_gap")
    n = g.get("sample_size", 0)

    if n > 0:
        print("--- INTERPRETATION ---")
        if brier is not None:
            if brier < 0.15:
                print("  Brier: GOOD calibration (< 0.15)")
            elif brier < 0.25:
                print("  Brier: MODERATE calibration (0.15 - 0.25)")
            else:
                print("  Brier: POOR calibration (> 0.25)")

        if gap is not None:
            if abs(gap) < 0.03:
                print("  Gap: Well-calibrated (|gap| < 3pp)")
            elif gap > 0:
                print(f"  Gap: UNDERCONFIDENT by {_fmt_pct(abs(gap))} — events happen more often than predicted")
            else:
                print(f"  Gap: OVERCONFIDENT by {_fmt_pct(abs(gap))} — events happen less often than predicted")

        if n < 30:
            print(f"  WARNING: Sample size ({n}) too small for reliable statistics")
        print()

    print("=" * 60)
    print()


# =============================================================================
# CLI COMMANDS
# =============================================================================


def cmd_build_report(args):
    """Build (or rebuild) the calibration report."""
    engine = CalibrationEngine(BASE_DIR)
    report, output_path = engine.run_and_save(args.window)
    print(f"Report saved to: {output_path}")
    print(f"Sample size: {report.get('global', {}).get('sample_size', 0)}")
    if args.print:
        print_report(report)


def cmd_print_report(args):
    """Print the most recent calibration report."""
    report_path = BASE_DIR / REPORT_OUTPUT_PATH
    if not report_path.exists():
        print(f"No report found at {report_path}")
        print("Run: python tools/calibration_cli.py build-report")
        sys.exit(1)

    with open(report_path, "r", encoding="utf-8") as f:
        report = json.load(f)

    print_report(report)


def cmd_json_export(args):
    """Export the calibration report as JSON to stdout."""
    report_path = BASE_DIR / REPORT_OUTPUT_PATH
    if not report_path.exists():
        # Build it first
        engine = CalibrationEngine(BASE_DIR)
        report, _ = engine.run_and_save(args.window)
    else:
        with open(report_path, "r", encoding="utf-8") as f:
            report = json.load(f)

    print(json.dumps(report, indent=2, ensure_ascii=False))


# =============================================================================
# MAIN
# =============================================================================


def main():
    parser = argparse.ArgumentParser(
        description="Calibration Engine CLI — Analytics Only",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
GOVERNANCE NOTICE:
This tool is ANALYTICS ONLY. It does not influence trading,
execution, thresholds, sizing, or decisions.

Examples:
  python tools/calibration_cli.py build-report --window all_time
  python tools/calibration_cli.py build-report --window last_30d --print
  python tools/calibration_cli.py print-report
  python tools/calibration_cli.py json-export
        """,
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # build-report
    build_parser = subparsers.add_parser(
        "build-report", help="Build or rebuild calibration report"
    )
    build_parser.add_argument(
        "--window",
        default="all_time",
        choices=["all_time", "last_7d", "last_30d", "last_90d"],
        help="Time window for analysis (default: all_time)",
    )
    build_parser.add_argument(
        "--print",
        action="store_true",
        help="Also print the report after building",
    )
    build_parser.set_defaults(func=cmd_build_report)

    # print-report
    print_parser = subparsers.add_parser(
        "print-report", help="Print the most recent report"
    )
    print_parser.set_defaults(func=cmd_print_report)

    # json-export
    export_parser = subparsers.add_parser(
        "json-export", help="Export report as JSON to stdout"
    )
    export_parser.add_argument(
        "--window",
        default="all_time",
        choices=["all_time", "last_7d", "last_30d", "last_90d"],
        help="Time window if rebuilding (default: all_time)",
    )
    export_parser.set_defaults(func=cmd_json_export)

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(0)

    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
    )

    args.func(args)


if __name__ == "__main__":
    main()
