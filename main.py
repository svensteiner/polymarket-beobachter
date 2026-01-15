# =============================================================================
# POLYMARKET EU AI REGULATION ANALYZER
# Module: main.py
# Purpose: CLI entry point for running analysis
# =============================================================================
#
# USAGE:
# python main.py --config path/to/market_config.json
# python main.py --example  (runs the built-in EU AI Act example)
#
# CONFIGURATION FILE FORMAT (JSON):
# {
#     "market_title": "...",
#     "resolution_text": "...",
#     "target_date": "YYYY-MM-DD",
#     "referenced_regulation": "...",
#     "authority_involved": "...",
#     "market_implied_probability": 0.XX,
#     "notes": "optional"
# }
#
# OUTPUT:
# - Prints analysis summary to console
# - Saves full analysis to output/analysis.json
# - Saves human-readable report to output/report.md
#
# =============================================================================

import argparse
import json
import os
import sys
from datetime import date, datetime
from typing import Optional

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from polymarket_eu_analyzer.models.data_models import (
    MarketInput,
    FullAnalysisReport,
)
from polymarket_eu_analyzer.core.resolution_parser import ResolutionParser
from polymarket_eu_analyzer.core.process_model import EUProcessModel
from polymarket_eu_analyzer.core.time_feasibility import TimeFeasibilityChecker
from polymarket_eu_analyzer.core.probability_estimator import ProbabilityEstimator
from polymarket_eu_analyzer.core.market_sanity import MarketSanityChecker
from polymarket_eu_analyzer.core.decision_engine import DecisionEngine


class PolymarketEUAnalyzer:
    """
    Main analyzer class that orchestrates all analysis modules.

    Provides a clean interface for running complete analysis.
    """

    VERSION = "1.0.0"

    def __init__(self):
        """Initialize all analysis components."""
        self.resolution_parser = ResolutionParser()
        self.process_model = EUProcessModel()
        self.time_feasibility_checker = TimeFeasibilityChecker()
        self.probability_estimator = ProbabilityEstimator()
        self.market_sanity_checker = MarketSanityChecker()
        self.decision_engine = DecisionEngine()

    def analyze(self, market_input: MarketInput) -> FullAnalysisReport:
        """
        Run complete analysis pipeline.

        Args:
            market_input: The market to analyze

        Returns:
            FullAnalysisReport with all analysis results
        """
        # Step 1: Parse resolution
        resolution_analysis = self.resolution_parser.analyze(market_input)

        # Step 2: Analyze process stage
        process_analysis = self.process_model.analyze(market_input)

        # Step 3: Check time feasibility
        time_feasibility = self.time_feasibility_checker.analyze(
            market_input, process_analysis
        )

        # Step 4: Estimate probability
        probability_estimate = self.probability_estimator.estimate(
            market_input, process_analysis, time_feasibility
        )

        # Step 5: Check market sanity
        market_sanity = self.market_sanity_checker.analyze(
            market_input, probability_estimate
        )

        # Step 6: Make final decision
        final_decision = self.decision_engine.decide(
            resolution_analysis,
            process_analysis,
            time_feasibility,
            probability_estimate,
            market_sanity
        )

        # Assemble report
        return FullAnalysisReport(
            market_input=market_input,
            resolution_analysis=resolution_analysis,
            process_analysis=process_analysis,
            time_feasibility=time_feasibility,
            probability_estimate=probability_estimate,
            market_sanity=market_sanity,
            final_decision=final_decision,
            analysis_version=self.VERSION,
            generated_at=datetime.now().isoformat()
        )


def load_market_input_from_config(config_path: str) -> MarketInput:
    """
    Load market input from a JSON configuration file.

    Args:
        config_path: Path to the JSON config file

    Returns:
        MarketInput object

    Raises:
        SystemExit: If config file is missing, invalid, or has missing/invalid fields
    """
    # Validate file exists and is readable
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
    except FileNotFoundError:
        print(f"ERROR: Config file not found: {config_path}")
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"ERROR: Invalid JSON in {config_path}: {e}")
        sys.exit(1)
    except PermissionError:
        print(f"ERROR: Permission denied reading {config_path}")
        sys.exit(1)

    # Validate required fields exist
    required_fields = [
        "market_title", "resolution_text", "target_date",
        "referenced_regulation", "authority_involved", "market_implied_probability"
    ]
    missing_fields = [f for f in required_fields if f not in config]
    if missing_fields:
        print(f"ERROR: Missing required fields in config: {missing_fields}")
        sys.exit(1)

    # Validate and parse target_date
    try:
        target_date = date.fromisoformat(config["target_date"])
    except ValueError:
        print(f"ERROR: Invalid date format for 'target_date'. Expected YYYY-MM-DD, got: {config['target_date']}")
        sys.exit(1)

    # Validate market_implied_probability
    prob = config["market_implied_probability"]
    if not isinstance(prob, (int, float)):
        print(f"ERROR: 'market_implied_probability' must be a number, got: {type(prob).__name__}")
        sys.exit(1)
    if not 0.0 <= prob <= 1.0:
        print(f"ERROR: 'market_implied_probability' must be between 0.0 and 1.0, got: {prob}")
        if prob > 1.0 and prob <= 100.0:
            print(f"  Hint: Did you mean {prob / 100}?")
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
    """
    Create an example market input for the EU AI Act.

    This is a hypothetical market for demonstration purposes.

    Returns:
        MarketInput for EU AI Act example
    """
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
        market_implied_probability=0.35,  # Market thinks 35% chance
        analysis_date=date.today(),
        notes="Hypothetical market for demonstration. Article 5 provisions apply from February 2, 2025."
    )


def generate_markdown_report(report: FullAnalysisReport) -> str:
    """
    Generate a human-readable markdown report.

    Args:
        report: The full analysis report

    Returns:
        Markdown-formatted string
    """
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
    outcome_emoji = "✅" if decision.outcome.value == "TRADE" else "❌"
    lines.append(f"**Decision:** {outcome_emoji} **{decision.outcome.value}**")
    lines.append("")
    lines.append(f"**Confidence:** {decision.confidence}")
    lines.append("")
    lines.append(f"**Recommendation:** {decision.recommended_action}")
    lines.append("")

    # Market Info
    lines.append("## Market Information")
    lines.append("")
    market = report.market_input
    lines.append(f"**Title:** {market.market_title}")
    lines.append("")
    lines.append(f"**Target Date:** {market.target_date}")
    lines.append("")
    lines.append(f"**Regulation:** {market.referenced_regulation}")
    lines.append("")
    lines.append(f"**Authority:** {market.authority_involved}")
    lines.append("")
    lines.append(f"**Market Implied Probability:** {market.market_implied_probability:.1%}")
    lines.append("")

    # Resolution Analysis
    lines.append("## Resolution Analysis")
    lines.append("")
    res = report.resolution_analysis
    lines.append(f"- Binary: {'Yes' if res.is_binary else 'No'}")
    lines.append(f"- Objectively Verifiable: {'Yes' if res.is_objectively_verifiable else 'No'}")
    lines.append(f"- Source Identified: {'Yes' if res.resolution_source_identified else 'No'}")
    lines.append(f"- Hard Fail: {'Yes' if res.hard_fail else 'No'}")
    lines.append("")
    if res.ambiguity_flags:
        lines.append("**Ambiguity Flags:**")
        for flag in res.ambiguity_flags:
            lines.append(f"- {flag}")
        lines.append("")
    lines.append(f"**Reasoning:** {res.reasoning}")
    lines.append("")

    # Process Analysis
    lines.append("## Process Stage Analysis")
    lines.append("")
    proc = report.process_analysis
    lines.append(f"**Current Stage:** {proc.current_stage.value}")
    lines.append("")
    if proc.stages_remaining:
        lines.append(f"**Remaining Stages:** {len(proc.stages_remaining)}")
        for stage in proc.stages_remaining[:5]:
            lines.append(f"- {stage.value}")
        if len(proc.stages_remaining) > 5:
            lines.append(f"- ... and {len(proc.stages_remaining) - 5} more")
        lines.append("")
    if proc.blocking_factors:
        lines.append("**Blocking Factors:**")
        for factor in proc.blocking_factors:
            lines.append(f"- {factor}")
        lines.append("")
    lines.append(f"**Reasoning:** {proc.reasoning}")
    lines.append("")

    # Time Feasibility
    lines.append("## Time Feasibility Analysis")
    lines.append("")
    time = report.time_feasibility
    lines.append(f"- Days Until Target: {time.days_until_target}")
    lines.append(f"- Minimum Days Required: {time.minimum_days_required}")
    lines.append(f"- Feasible: {'Yes' if time.is_timeline_feasible else 'No'}")
    lines.append(f"- Hard Fail: {'Yes' if time.hard_fail else 'No'}")
    lines.append("")
    if time.institutional_constraints:
        lines.append("**Institutional Constraints:**")
        for constraint in time.institutional_constraints:
            lines.append(f"- {constraint}")
        lines.append("")
    lines.append(f"**Reasoning:** {time.reasoning}")
    lines.append("")

    # Probability Estimate
    lines.append("## Probability Estimate")
    lines.append("")
    prob = report.probability_estimate
    lines.append(f"- Low: {prob.probability_low:.1%}")
    lines.append(f"- Midpoint: {prob.probability_midpoint:.1%}")
    lines.append(f"- High: {prob.probability_high:.1%}")
    lines.append(f"- Confidence: {prob.confidence_level}")
    lines.append("")
    lines.append("**Assumptions:**")
    for assumption in prob.assumptions:
        lines.append(f"- {assumption}")
    lines.append("")
    lines.append("**Historical Precedents:**")
    for precedent in prob.historical_precedents:
        lines.append(f"- {precedent}")
    lines.append("")
    lines.append(f"**Reasoning:** {prob.reasoning}")
    lines.append("")

    # Market Sanity
    lines.append("## Market Sanity Check")
    lines.append("")
    sanity = report.market_sanity
    lines.append(f"- Market Implied: {sanity.market_implied_prob:.1%}")
    lines.append(f"- Our Estimate: {sanity.rule_based_prob:.1%}")
    lines.append(f"- Delta: {sanity.delta:+.1%} ({sanity.delta_percentage_points:.1f}pp)")
    lines.append(f"- Direction: {sanity.direction}")
    lines.append(f"- Meets Threshold: {'Yes' if sanity.meets_threshold else 'No'}")
    lines.append("")
    lines.append(f"**Reasoning:** {sanity.reasoning}")
    lines.append("")

    # Criteria Summary
    lines.append("## Criteria Summary")
    lines.append("")
    lines.append("| Criterion | Result |")
    lines.append("|-----------|--------|")
    for criterion, passed in decision.criteria_met.items():
        result = "✅ PASS" if passed else "❌ FAIL"
        lines.append(f"| {criterion} | {result} |")
    lines.append("")

    # Risk Warnings
    if decision.risk_warnings:
        lines.append("## Risk Warnings")
        lines.append("")
        for warning in decision.risk_warnings:
            lines.append(f"⚠️ {warning}")
            lines.append("")

    # Final Reasoning
    lines.append("## Full Decision Reasoning")
    lines.append("")
    lines.append(decision.reasoning)
    lines.append("")

    # Disclaimer
    lines.append("---")
    lines.append("")
    lines.append("*This analysis is for informational purposes only. It is not financial advice. ")
    lines.append("Always conduct your own research before making any trading decisions.*")

    return "\n".join(lines)


def main():
    """Main entry point for CLI."""
    parser = argparse.ArgumentParser(
        description="Polymarket EU AI Regulation Analyzer - "
                    "Deterministic analysis of EU regulatory markets"
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
        default="output",
        help="Directory to save output files (default: output)"
    )

    args = parser.parse_args()

    # Determine input source
    if args.example:
        print("Running example analysis with EU AI Act market...")
        market_input = create_example_market_input()
    elif args.config:
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
    print("=" * 60)

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
    script_dir = os.path.dirname(os.path.abspath(__file__))
    output_dir = os.path.join(script_dir, args.output_dir)
    try:
        os.makedirs(output_dir, exist_ok=True)
    except OSError as e:
        print(f"\nERROR: Cannot create output directory '{output_dir}': {e}")
        print("Analysis completed but results could not be saved.")
        sys.exit(1)

    # Save JSON output
    json_path = os.path.join(output_dir, "analysis.json")
    try:
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(report.to_dict(), f, indent=2, ensure_ascii=False)
        print(f"\nJSON analysis saved to: {json_path}")
    except (OSError, PermissionError) as e:
        print(f"\nERROR: Failed to write JSON output to '{json_path}': {e}")
        sys.exit(1)
    except TypeError as e:
        print(f"\nERROR: Failed to serialize analysis to JSON: {e}")
        sys.exit(1)

    # Save markdown report
    md_path = os.path.join(output_dir, "report.md")
    md_content = generate_markdown_report(report)
    try:
        with open(md_path, 'w', encoding='utf-8') as f:
            f.write(md_content)
        print(f"Markdown report saved to: {md_path}")
    except (OSError, PermissionError) as e:
        print(f"ERROR: Failed to write markdown report to '{md_path}': {e}")
        sys.exit(1)

    print("\n" + "=" * 60)
    print("Analysis complete.")


if __name__ == "__main__":
    main()
