# =============================================================================
# POLYMARKET BEOBACHTER - CORE ANALYZER CLI
# Module: core_analyzer/run.py
# Purpose: CLI entry point for Layer 1 analysis
# =============================================================================
#
# USAGE:
#   python -m core_analyzer.run --config <market.json>
#   python -m core_analyzer.run --example
#
# =============================================================================

import argparse
import json
import os
import sys
from datetime import date, datetime
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core_analyzer.analyzer import PolymarketEUAnalyzer
from core_analyzer.models.data_models import MarketInput


def load_market_input_from_config(config_path: str) -> MarketInput:
    """
    Load market input from a JSON configuration file.

    Args:
        config_path: Path to the JSON config file

    Returns:
        MarketInput object

    Raises:
        SystemExit: If config file is missing, invalid, or has missing fields
    """
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
    except FileNotFoundError:
        print(f"ERROR: Config file not found: {config_path}")
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"ERROR: Invalid JSON in {config_path}: {e}")
        sys.exit(1)

    required_fields = [
        "market_title", "resolution_text", "target_date",
        "referenced_regulation", "authority_involved", "market_implied_probability"
    ]
    missing_fields = [f for f in required_fields if f not in config]
    if missing_fields:
        print(f"ERROR: Missing required fields in config: {missing_fields}")
        sys.exit(1)

    try:
        target_date = date.fromisoformat(config["target_date"])
    except ValueError:
        print(f"ERROR: Invalid date format. Expected YYYY-MM-DD, got: {config['target_date']}")
        sys.exit(1)

    prob = config["market_implied_probability"]
    if not isinstance(prob, (int, float)) or not 0.0 <= prob <= 1.0:
        print(f"ERROR: market_implied_probability must be between 0.0 and 1.0")
        sys.exit(1)

    return MarketInput(
        market_title=config["market_title"],
        resolution_text=config["resolution_text"],
        target_date=target_date,
        referenced_regulation=config["referenced_regulation"],
        authority_involved=config["authority_involved"],
        market_implied_probability=float(prob),
        analysis_date=date.today(),
        notes=config.get("notes")
    )


def create_example_market_input() -> MarketInput:
    """Create an example market input for the EU AI Act."""
    return MarketInput(
        market_title="Will the EU AI Act prohibited practices provision be enforced by March 2025?",
        resolution_text=(
            "This market resolves to YES if the European Commission or any EU Member State "
            "authority has publicly announced enforcement action under Article 5 (Prohibited AI "
            "practices) of Regulation (EU) 2024/1689 (the EU AI Act) by 11:59 PM CET on "
            "March 31, 2025. Resolution source: Official Journal of the European Union, "
            "European Commission press releases, or official communications from national "
            "supervisory authorities published on their official websites."
        ),
        target_date=date(2025, 3, 31),
        referenced_regulation="EU AI Act",
        authority_involved="European Commission, National Supervisory Authorities",
        market_implied_probability=0.35,
        analysis_date=date.today(),
        notes="Hypothetical market for demonstration. Article 5 provisions apply from February 2, 2025."
    )


def generate_markdown_report(report) -> str:
    """Generate a human-readable markdown report."""
    lines = []
    lines.append("# Polymarket EU AI Regulation Analysis Report")
    lines.append("")
    lines.append(f"**Generated:** {report.generated_at}")
    lines.append(f"**Analyzer Version:** {report.analysis_version}")
    lines.append("")

    # Decision Summary
    lines.append("## Decision Summary")
    lines.append("")
    decision = report.final_decision
    lines.append(f"**Decision:** **{decision.outcome.value}**")
    lines.append(f"**Confidence:** {decision.confidence}")
    lines.append(f"**Recommendation:** {decision.recommended_action}")
    lines.append("")

    # Market Info
    lines.append("## Market Information")
    lines.append("")
    market = report.market_input
    lines.append(f"**Title:** {market.market_title}")
    lines.append(f"**Target Date:** {market.target_date}")
    lines.append(f"**Regulation:** {market.referenced_regulation}")
    lines.append(f"**Market Implied Probability:** {market.market_implied_probability:.1%}")
    lines.append("")

    # Criteria Summary
    lines.append("## Criteria Summary")
    lines.append("")
    lines.append("| Criterion | Result |")
    lines.append("|-----------|--------|")
    for criterion, passed in decision.criteria_met.items():
        result = "PASS" if passed else "FAIL"
        lines.append(f"| {criterion} | {result} |")
    lines.append("")

    return "\n".join(lines)


def main():
    """Main entry point for CLI."""
    parser = argparse.ArgumentParser(
        description="LAYER 1: Polymarket EU AI Regulation Analyzer - "
                    "Deterministic structural tradeability analysis"
    )

    parser.add_argument(
        "--config",
        type=str,
        help="Path to market configuration JSON file"
    )

    parser.add_argument(
        "--example",
        action="store_true",
        help="Run example analysis with EU AI Act market"
    )

    parser.add_argument(
        "--output-dir",
        type=str,
        default="output/layer1",
        help="Directory to save output files (default: output/layer1)"
    )

    args = parser.parse_args()

    # Determine input source
    if args.example:
        print("=" * 60)
        print("LAYER 1 ANALYSIS - INSTITUTIONAL/PROCESS EDGE")
        print("=" * 60)
        print("Running example analysis with EU AI Act market...")
        market_input = create_example_market_input()
    elif args.config:
        print("=" * 60)
        print("LAYER 1 ANALYSIS - INSTITUTIONAL/PROCESS EDGE")
        print("=" * 60)
        print(f"Loading market configuration from: {args.config}")
        market_input = load_market_input_from_config(args.config)
    else:
        parser.print_help()
        print("\nError: Please provide --config or --example")
        sys.exit(1)

    # Initialize analyzer
    analyzer = PolymarketEUAnalyzer()

    # Run analysis
    print("\nRunning analysis...")
    print("-" * 60)

    report = analyzer.analyze(market_input)

    # Print summary to console
    print(f"\nMarket: {market_input.market_title}")
    print(f"Target Date: {market_input.target_date}")
    print(f"Market Probability: {market_input.market_implied_probability:.1%}")
    print("-" * 60)
    print(f"Our Estimate: {report.probability_estimate.probability_midpoint:.1%} "
          f"({report.probability_estimate.probability_low:.1%} - "
          f"{report.probability_estimate.probability_high:.1%})")
    print(f"Delta: {report.market_sanity.delta_percentage_points:.1f} percentage points")
    print("-" * 60)
    print(f"\n>>> DECISION: {report.final_decision.outcome.value} <<<\n")
    print(f"Recommendation: {report.final_decision.recommended_action}")

    if report.final_decision.risk_warnings:
        print("\nRisk Warnings:")
        for warning in report.final_decision.risk_warnings:
            print(f"  [!] {warning}")

    # Create output directory
    script_dir = Path(__file__).parent.parent
    output_dir = script_dir / args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    # Save JSON output
    json_path = output_dir / "analysis.json"
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(report.to_dict(), f, indent=2, ensure_ascii=False)
    print(f"\nJSON analysis saved to: {json_path}")

    # Save markdown report
    md_path = output_dir / "report.md"
    md_content = generate_markdown_report(report)
    with open(md_path, 'w', encoding='utf-8') as f:
        f.write(md_content)
    print(f"Markdown report saved to: {md_path}")

    print("\n" + "=" * 60)
    print("Layer 1 analysis complete.")


if __name__ == "__main__":
    main()
