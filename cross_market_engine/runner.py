#!/usr/bin/env python3
# =============================================================================
# CROSS-MARKET CONSISTENCY ENGINE - RUNNER
# =============================================================================
#
# Execution entry point for consistency checks.
#
# ISOLATION GUARANTEES:
# - NO imports from trading, execution, or decision code
# - NO ability to place trades
# - NO callbacks into trading systems
# - Output is ONLY to log files
#
# This runner can be executed:
# - Manually via CLI
# - Scheduled via external scheduler
# - Called from research scripts
#
# It CANNOT be called from trading code.
#
# =============================================================================

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Optional

# Local imports ONLY - no trading code imports
from .relations import Relation, create_implies_relation
from .market_graph import MarketGraph, create_market_snapshot
from .consistency_check import check_all_relations
from .findings import Finding, FindingsSummary

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger(__name__)

# Log file location (within this module's folder)
LOG_DIR = Path(__file__).parent / "logs"
FINDINGS_LOG = LOG_DIR / "findings.jsonl"


# =============================================================================
# LOG WRITING
# =============================================================================


def ensure_log_dir():
    """Ensure log directory exists."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)


def write_finding_to_log(finding: Finding) -> None:
    """
    Write a single finding to the JSONL log.

    This is the ONLY output mechanism.
    Findings are appended, never overwritten.
    """
    ensure_log_dir()
    with open(FINDINGS_LOG, "a", encoding="utf-8") as f:
        f.write(finding.to_json() + "\n")


def write_summary_to_log(summary: FindingsSummary) -> None:
    """
    Write all findings from a summary to the log.
    """
    ensure_log_dir()
    with open(FINDINGS_LOG, "a", encoding="utf-8") as f:
        for finding in summary.findings:
            f.write(finding.to_json() + "\n")


# =============================================================================
# DEMO / SAMPLE DATA
# =============================================================================


def create_demo_graph() -> MarketGraph:
    """
    Create a demo graph with sample data for testing.

    This demonstrates the IMPLIES relation with hypothetical markets.
    All data is synthetic - no real market data.

    Returns:
        A MarketGraph with sample markets and relations
    """
    graph = MarketGraph()

    # Sample markets (hypothetical)
    # Scenario: Event deadlines
    # If event happens by 2025, it certainly happens by 2026

    graph.add_market(create_market_snapshot(
        market_id="event_by_2025",
        question="Will Event X happen by end of 2025?",
        probability=0.45,
    ))

    graph.add_market(create_market_snapshot(
        market_id="event_by_2026",
        question="Will Event X happen by end of 2026?",
        probability=0.70,
    ))

    graph.add_market(create_market_snapshot(
        market_id="event_by_2027",
        question="Will Event X happen by end of 2027?",
        probability=0.85,
    ))

    # Add IMPLIES relations
    # 2025 implies 2026 (if it happens by 2025, it happens by 2026)
    graph.add_relation(create_implies_relation(
        antecedent_id="event_by_2025",
        consequent_id="event_by_2026",
        description="Event by 2025 implies event by 2026",
    ))

    # 2026 implies 2027
    graph.add_relation(create_implies_relation(
        antecedent_id="event_by_2026",
        consequent_id="event_by_2027",
        description="Event by 2026 implies event by 2027",
    ))

    # 2025 implies 2027 (transitive)
    graph.add_relation(create_implies_relation(
        antecedent_id="event_by_2025",
        consequent_id="event_by_2027",
        description="Event by 2025 implies event by 2027 (transitive)",
    ))

    # Add an INCONSISTENT example for demonstration
    graph.add_market(create_market_snapshot(
        market_id="specific_event",
        question="Will specific sub-event Y happen?",
        probability=0.60,  # Higher than the general event!
    ))

    graph.add_market(create_market_snapshot(
        market_id="general_event",
        question="Will general event (that includes Y) happen?",
        probability=0.40,  # Lower - this is inconsistent!
    ))

    # Specific implies general (but prices are inverted - inconsistent!)
    graph.add_relation(create_implies_relation(
        antecedent_id="specific_event",
        consequent_id="general_event",
        description="Specific event Y implies general event (Y is a subset)",
    ))

    return graph


# =============================================================================
# RUNNER FUNCTIONS
# =============================================================================


def run_consistency_check(
    graph: MarketGraph,
    log_to_file: bool = True,
    print_summary: bool = True,
) -> FindingsSummary:
    """
    Run a consistency check on the given graph.

    Args:
        graph: The market graph to check
        log_to_file: Whether to write findings to JSONL log
        print_summary: Whether to print summary to stdout

    Returns:
        FindingsSummary with all results

    ISOLATION: This function only reads from graph and writes to log.
    It has NO connection to trading systems.
    """
    logger.info(
        f"Starting consistency check | "
        f"markets={graph.market_count()} | "
        f"relations={graph.relation_count()}"
    )

    # Run check
    summary = check_all_relations(graph)

    # Log results
    logger.info(
        f"Consistency check complete | "
        f"run_id={summary.run_id} | "
        f"consistent={summary.consistent_count} | "
        f"inconsistent={summary.inconsistent_count} | "
        f"unclear={summary.unclear_count}"
    )

    # Write to file
    if log_to_file:
        write_summary_to_log(summary)
        logger.info(f"Findings written to {FINDINGS_LOG}")

    # Print summary
    if print_summary:
        print("\n" + "=" * 60)
        print(summary.summary_text())
        print("=" * 60 + "\n")

    return summary


def run_demo():
    """
    Run a demo consistency check with sample data.

    This demonstrates the engine without any real market data.
    """
    logger.info("Running DEMO consistency check with synthetic data")

    graph = create_demo_graph()
    summary = run_consistency_check(graph)

    return summary


# =============================================================================
# CLI INTERFACE
# =============================================================================


def main():
    """Main entry point for CLI execution."""
    parser = argparse.ArgumentParser(
        description="Cross-Market Consistency Engine Runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
ISOLATION STATEMENT:
This engine is a RESEARCH TOOL ONLY.
It cannot place trades or influence trading decisions.
It only observes and logs findings.

Examples:
  python -m cross_market_engine.runner --demo
  python -m cross_market_engine.runner --input markets.json
        """,
    )

    parser.add_argument(
        "--demo",
        action="store_true",
        help="Run with demo/synthetic data",
    )

    parser.add_argument(
        "--input",
        type=str,
        help="Path to JSON file with market data and relations",
    )

    parser.add_argument(
        "--no-log",
        action="store_true",
        help="Don't write findings to log file",
    )

    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Don't print summary to stdout",
    )

    args = parser.parse_args()

    print("\n" + "=" * 60)
    print("CROSS-MARKET CONSISTENCY ENGINE")
    print("Research Tool - DOES NOT PLACE TRADES")
    print("=" * 60 + "\n")

    if args.demo:
        run_demo()

    elif args.input:
        # Load from JSON file
        input_path = Path(args.input)
        if not input_path.exists():
            logger.error(f"Input file not found: {input_path}")
            sys.exit(1)

        with open(input_path, "r") as f:
            data = json.load(f)

        # Build graph from data
        graph = MarketGraph()

        for m in data.get("markets", []):
            graph.add_market(create_market_snapshot(
                market_id=m["market_id"],
                question=m["question"],
                probability=m["probability"],
                metadata=m.get("metadata", {}),
            ))

        for r in data.get("relations", []):
            graph.add_relation(create_implies_relation(
                antecedent_id=r["market_a_id"],
                consequent_id=r["market_b_id"],
                description=r["description"],
                tolerance=r.get("tolerance", 0.05),
            ))

        run_consistency_check(
            graph,
            log_to_file=not args.no_log,
            print_summary=not args.quiet,
        )

    else:
        parser.print_help()
        print("\nRun with --demo for a demonstration.")


if __name__ == "__main__":
    main()
