# =============================================================================
# POLYMARKET BEOBACHTER - HISTORICAL TESTING CLI
# Module: core_analyzer/historical/run.py
# Purpose: CLI entry point for historical/counterfactual testing
# =============================================================================
#
# USAGE:
#   python -m core_analyzer.historical.run --all
#   python -m core_analyzer.historical.run --case <case_id>
#
# =============================================================================

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from core_analyzer.historical.runner import BlindAnalyzerRunner
from core_analyzer.historical.cases import get_all_cases, get_case_by_id
from core_analyzer.historical.reports import generate_aggregate_report


def setup_logging(verbose: bool = False) -> None:
    """Configure logging."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


def main():
    """Main entry point for historical testing CLI."""
    parser = argparse.ArgumentParser(
        description="LAYER 1: Historical/Counterfactual Testing - "
                    "Run analyzer BLIND on historical cases"
    )

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--all",
        action="store_true",
        help="Run all historical test cases"
    )
    group.add_argument(
        "--case",
        type=str,
        help="Run specific case by ID"
    )

    parser.add_argument(
        "--output-dir",
        type=str,
        default="output/layer1/historical",
        help="Directory to save output reports"
    )

    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose logging"
    )

    args = parser.parse_args()

    # Setup logging
    setup_logging(args.verbose)
    logger = logging.getLogger(__name__)

    print("=" * 70)
    print("LAYER 1 - HISTORICAL / COUNTERFACTUAL TESTING")
    print("=" * 70)
    print()
    print("METHODOLOGY:")
    print("  - Analyzer runs BLIND (no knowledge of actual outcomes)")
    print("  - Uses NEUTRAL probability (no historical market prices)")
    print("  - Tests structural discipline, not prediction accuracy")
    print()
    print("=" * 70)

    # Ensure output directory
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Initialize runner
    runner = BlindAnalyzerRunner()

    # Get cases
    if args.all:
        cases = get_all_cases()
        logger.info(f"Running {len(cases)} historical cases")
    else:
        case = get_case_by_id(args.case)
        if case is None:
            print(f"ERROR: Case '{args.case}' not found")
            sys.exit(1)
        cases = [case]
        logger.info(f"Running single case: {args.case}")

    # Run cases
    results = runner.run_all_cases(cases)

    # Generate aggregate report
    report = generate_aggregate_report(results)

    # Save report
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    report_path = output_dir / f"historical_report_{timestamp}.md"
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write(report)

    print(f"\nAggregate report saved to: {report_path}")

    # Save JSON results
    json_path = output_dir / f"historical_results_{timestamp}.json"
    json_results = []
    for r in results:
        json_results.append({
            "case_id": r.case.case_id,
            "title": r.case.title,
            "analyzer_decision": r.analyzer_decision,
            "known_outcome": r.case.known_outcome.value,
            "classification": r.classification.value,
            "blocking_criteria": r.blocking_criteria,
        })
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(json_results, f, indent=2)

    print(f"JSON results saved to: {json_path}")

    # Summary
    print("\n" + "=" * 70)
    print("HISTORICAL TESTING COMPLETE")
    print("=" * 70)

    # Count classifications
    classifications = {}
    for r in results:
        key = r.classification.value
        classifications[key] = classifications.get(key, 0) + 1

    print("\nClassification Summary:")
    for classification, count in sorted(classifications.items()):
        print(f"  {classification}: {count}")

    # Check for critical failures
    false_admissions = [r for r in results if r.is_critical_failure()]
    if false_admissions:
        print(f"\n[!] CRITICAL: {len(false_admissions)} FALSE_ADMISSION cases detected!")
        print("    These indicate the analyzer would have admitted structurally unsound markets.")
        for fa in false_admissions:
            print(f"    - {fa.case.case_id}: {fa.case.title[:50]}...")

    print("\n" + "=" * 70)


if __name__ == "__main__":
    main()
