# =============================================================================
# POLYMARKET BEOBACHTER - MICROSTRUCTURE RESEARCH CLI
# Module: microstructure_research/run.py
# Purpose: CLI entry point for Layer 2 research
# =============================================================================
#
# ╔═══════════════════════════════════════════════════════════════════════════╗
# ║                    RESEARCH ONLY - NO DECISION AUTHORITY                  ║
# ╚═══════════════════════════════════════════════════════════════════════════╝
#
# USAGE:
#   python -m microstructure_research.run --analysis spread
#   python -m microstructure_research.run --analysis liquidity
#   python -m microstructure_research.run --analysis orderbook
#
# =============================================================================

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from microstructure_research.research.spread_analysis import SpreadAnalyzer
from microstructure_research.research.liquidity_study import LiquidityAnalyzer
from microstructure_research.research.orderbook_stats import OrderbookStatsAnalyzer


def setup_logging(verbose: bool = False) -> None:
    """Configure logging for CLI."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


def print_governance_banner():
    """Print governance warning banner."""
    print("=" * 70)
    print()
    print("    LAYER 2 - MICROSTRUCTURE RESEARCH")
    print()
    print("    ╔══════════════════════════════════════════════════════════════╗")
    print("    ║                                                              ║")
    print("    ║          THIS MODULE HAS ZERO DECISION AUTHORITY            ║")
    print("    ║                                                              ║")
    print("    ║   Output is purely statistical - NO trade recommendations   ║")
    print("    ║                                                              ║")
    print("    ╚══════════════════════════════════════════════════════════════╝")
    print()
    print("=" * 70)


def load_sample_data(data_path: str) -> list:
    """Load sample data for analysis."""
    path = Path(data_path)
    if not path.exists():
        print(f"Warning: Data file not found: {data_path}")
        print("Using synthetic sample data for demonstration.")
        # Return synthetic sample data
        return [
            {"market_id": "demo_1", "best_bid": 0.45, "best_ask": 0.47, "bids": [{"price": 0.45, "size": 100}], "asks": [{"price": 0.47, "size": 150}]},
            {"market_id": "demo_2", "best_bid": 0.60, "best_ask": 0.63, "bids": [{"price": 0.60, "size": 200}], "asks": [{"price": 0.63, "size": 180}]},
            {"market_id": "demo_3", "best_bid": 0.30, "best_ask": 0.32, "bids": [{"price": 0.30, "size": 50}], "asks": [{"price": 0.32, "size": 75}]},
            {"market_id": "demo_4", "best_bid": 0.75, "best_ask": 0.78, "bids": [{"price": 0.75, "size": 300}], "asks": [{"price": 0.78, "size": 250}]},
            {"market_id": "demo_5", "best_bid": 0.50, "best_ask": 0.52, "bids": [{"price": 0.50, "size": 125}], "asks": [{"price": 0.52, "size": 130}]},
            {"market_id": "demo_6", "best_bid": 0.40, "best_ask": 0.42, "bids": [{"price": 0.40, "size": 80}], "asks": [{"price": 0.42, "size": 90}]},
            {"market_id": "demo_7", "best_bid": 0.55, "best_ask": 0.57, "bids": [{"price": 0.55, "size": 160}], "asks": [{"price": 0.57, "size": 170}]},
            {"market_id": "demo_8", "best_bid": 0.65, "best_ask": 0.68, "bids": [{"price": 0.65, "size": 220}], "asks": [{"price": 0.68, "size": 200}]},
            {"market_id": "demo_9", "best_bid": 0.35, "best_ask": 0.37, "bids": [{"price": 0.35, "size": 70}], "asks": [{"price": 0.37, "size": 65}]},
            {"market_id": "demo_10", "best_bid": 0.70, "best_ask": 0.73, "bids": [{"price": 0.70, "size": 280}], "asks": [{"price": 0.73, "size": 260}]},
        ]

    with open(path, 'r') as f:
        return json.load(f)


def run_spread_analysis(data: list, output_dir: Path) -> None:
    """Run spread analysis."""
    print("\nRunning spread analysis...")
    analyzer = SpreadAnalyzer()
    stats = analyzer.analyze_spreads(data)

    if stats:
        report = analyzer.generate_report(stats)
        print("\n" + report)

        # Save report
        report_path = output_dir / f"spread_analysis_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
        with open(report_path, 'w') as f:
            f.write(report)
        print(f"\nReport saved to: {report_path}")
    else:
        print("Insufficient data for spread analysis.")


def run_liquidity_analysis(data: list, output_dir: Path) -> None:
    """Run liquidity analysis."""
    print("\nRunning liquidity analysis...")
    analyzer = LiquidityAnalyzer()
    summary = analyzer.analyze_liquidity(data)

    if summary:
        report = analyzer.generate_report(summary)
        print("\n" + report)

        # Save report
        report_path = output_dir / f"liquidity_analysis_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
        with open(report_path, 'w') as f:
            f.write(report)
        print(f"\nReport saved to: {report_path}")
    else:
        print("Insufficient data for liquidity analysis.")


def run_orderbook_analysis(data: list, output_dir: Path) -> None:
    """Run orderbook statistics analysis."""
    print("\nRunning orderbook statistics analysis...")
    analyzer = OrderbookStatsAnalyzer()
    stats = analyzer.analyze(data)

    if stats:
        report = analyzer.generate_report(stats)
        print("\n" + report)

        # Save report
        report_path = output_dir / f"orderbook_stats_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
        with open(report_path, 'w') as f:
            f.write(report)
        print(f"\nReport saved to: {report_path}")
    else:
        print("Insufficient data for orderbook analysis.")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="LAYER 2: Microstructure Research - Market mechanics analysis (NO DECISION AUTHORITY)"
    )

    parser.add_argument(
        "--analysis",
        type=str,
        required=True,
        choices=["spread", "liquidity", "orderbook", "all"],
        help="Type of analysis to run"
    )

    parser.add_argument(
        "--data",
        type=str,
        default="data/research/market_data.json",
        help="Path to market data JSON file"
    )

    parser.add_argument(
        "--output-dir",
        type=str,
        default="output/layer2",
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

    # Print governance banner
    print_governance_banner()

    # Ensure output directory exists
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Load data
    data = load_sample_data(args.data)

    # Run requested analysis
    if args.analysis in ("spread", "all"):
        run_spread_analysis(data, output_dir)

    if args.analysis in ("liquidity", "all"):
        run_liquidity_analysis(data, output_dir)

    if args.analysis in ("orderbook", "all"):
        run_orderbook_analysis(data, output_dir)

    print("\n" + "=" * 70)
    print("Research analysis complete.")
    print("REMINDER: This output is for research only - NO trade recommendations.")
    print("=" * 70)


if __name__ == "__main__":
    main()
