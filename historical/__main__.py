# =============================================================================
# POLYMARKET EU AI REGULATION ANALYZER
# Module: historical/__main__.py
# Purpose: CLI entry point for historical/counterfactual testing
# =============================================================================
#
# USAGE:
# python -m historical.run --all           Run all historical cases
# python -m historical.run --case CASE_001 Run a specific case
# python -m historical.run --list          List available cases
#
# OUTPUT:
# Results are saved to output/historical/
# - cases/*.json       Individual case reports
# - aggregate_report.md Markdown summary
# - run_summary.json    Machine-readable summary
#
# =============================================================================

import argparse
import logging
import sys
from datetime import datetime

from .cases import get_all_cases
from .runner import BlindAnalyzerRunner
from .reports import ReportGenerator


def setup_logging(verbose: bool = False) -> None:
    """Configure logging for CLI."""
    level = logging.DEBUG if verbose else logging.INFO
    format_str = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"

    logging.basicConfig(
        level=level,
        format=format_str,
        handlers=[
            logging.StreamHandler(sys.stdout),
        ],
    )


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        prog="python -m historical",
        description="Historical / Counterfactual Testing for Analyzer Discipline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m historical --all              Run all historical cases
  python -m historical --case CASE_001    Run specific case
  python -m historical --list             List available cases
  python -m historical --all --verbose    Run with debug logging

Output:
  Results are saved to output/historical/

Note:
  This module tests ANALYZER DISCIPLINE, not profitability.
  No prices, probabilities, or PnL are calculated.
        """,
    )

    parser.add_argument(
        "--all",
        action="store_true",
        help="Run all historical cases",
    )

    parser.add_argument(
        "--case",
        type=str,
        help="Run a specific case by ID (e.g., CASE_001)",
    )

    parser.add_argument(
        "--list",
        action="store_true",
        help="List available cases without running",
    )

    parser.add_argument(
        "--output-dir",
        type=str,
        default="output/historical",
        help="Output directory for reports (default: output/historical)",
    )

    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable debug logging",
    )

    return parser.parse_args()


def list_cases() -> None:
    """Print list of available cases."""
    cases = get_all_cases()

    print("\nAvailable Historical Cases:")
    print("=" * 70)

    for case in cases:
        print(f"\n{case.case_id}: {case.title}")
        print(f"  Regulation:   {case.referenced_regulation}")
        print(f"  Target Date:  {case.hypothetical_target_date}")
        print(f"  Analysis As:  {case.analysis_as_of_date}")
        print(f"  Outcome:      {case.known_outcome.value}")
        print(f"  Description:  {case.description[:60]}...")

    print("\n" + "=" * 70)
    print(f"Total: {len(cases)} cases")


def main() -> int:
    """Main entry point."""
    args = parse_args()

    # Setup logging
    setup_logging(verbose=args.verbose)
    logger = logging.getLogger(__name__)

    # Handle --list
    if args.list:
        list_cases()
        return 0

    # Validate arguments
    if not args.all and not args.case:
        print("Error: Please specify --all or --case CASE_ID")
        print("Use --help for usage information")
        return 1

    # Get cases to run
    all_cases = get_all_cases()

    if args.case:
        # Find specific case
        matching = [c for c in all_cases if c.case_id == args.case]
        if not matching:
            print(f"Error: Case '{args.case}' not found")
            print("Use --list to see available cases")
            return 1
        cases_to_run = matching
    else:
        cases_to_run = all_cases

    # Print header
    print("\n" + "=" * 70)
    print("HISTORICAL / COUNTERFACTUAL TESTING")
    print("Evaluating Analyzer Discipline")
    print("=" * 70)
    print(f"\nRun started: {datetime.now().isoformat()}")
    print(f"Cases to run: {len(cases_to_run)}")
    print(f"Output directory: {args.output_dir}")
    print("\n" + "-" * 70)

    # Initialize runner and report generator
    try:
        runner = BlindAnalyzerRunner()
        reporter = ReportGenerator(output_dir=args.output_dir)
    except Exception as e:
        logger.exception(f"Failed to initialize: {e}")
        return 1

    # Run cases
    logger.info("Running historical cases...")
    try:
        results = runner.run_all_cases(cases_to_run)
    except Exception as e:
        logger.exception(f"Failed during case execution: {e}")
        return 1

    # Generate reports
    logger.info("Generating reports...")
    try:
        generated = reporter.generate_all_reports(results)
    except Exception as e:
        logger.exception(f"Failed to generate reports: {e}")
        return 1

    # Print summary
    print("\n" + "=" * 70)
    print("RESULTS SUMMARY")
    print("=" * 70)

    # Classification counts
    counts = {}
    for result in results:
        key = result.classification.value
        counts[key] = counts.get(key, 0) + 1

    print("\nClassification Breakdown:")
    print(f"  CORRECT_REJECTION: {counts.get('CORRECT_REJECTION', 0)}")
    print(f"  SAFE_PASS:         {counts.get('SAFE_PASS', 0)}")
    print(f"  FALSE_ADMISSION:   {counts.get('FALSE_ADMISSION', 0)}")
    print(f"  RARE_SUCCESS:      {counts.get('RARE_SUCCESS', 0)}")

    # Discipline metrics
    total = len(results)
    if total > 0:
        failures = counts.get('FALSE_ADMISSION', 0)
        discipline_rate = (total - failures) / total * 100
        failure_rate = failures / total * 100

        print(f"\nDiscipline Rate: {discipline_rate:.1f}%")
        print(f"Failure Rate:    {failure_rate:.1f}%")

    # Warn about failures
    false_admissions = [r for r in results if r.is_critical_failure()]
    if false_admissions:
        print("\n" + "[!] " * 10)
        print(f"WARNING: {len(false_admissions)} FALSE_ADMISSION case(s) detected!")
        print("[!] " * 10)
        for fa in false_admissions:
            print(f"  - {fa.case.case_id}: {fa.case.title}")
        print("\nReview the aggregate report for details.")

    # Print output locations
    print("\nOutput Files:")
    for report_type, path in generated.items():
        print(f"  {report_type}: {path}")

    print("\n" + "=" * 70)
    print("Historical testing complete.")
    print("=" * 70 + "\n")

    # Return non-zero if any FALSE_ADMISSION
    if false_admissions:
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
