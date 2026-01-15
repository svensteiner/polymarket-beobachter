#!/usr/bin/env python3
# =============================================================================
# POLYMARKET EU AI REGULATION ANALYZER
# Example: EU AI Act Enforcement Market Analysis
# =============================================================================
#
# This script demonstrates a complete analysis run using a hypothetical
# Polymarket market related to EU AI Act enforcement.
#
# SCENARIO:
# A Polymarket asks whether the EU AI Act's prohibited practices provision
# (Article 5) will be enforced by March 31, 2025.
#
# CONTEXT:
# - EU AI Act entered into force: August 1, 2024
# - Prohibited practices (Art. 5) apply from: February 2, 2025
# - Market resolution date: March 31, 2025
# - This gives ~8 weeks for enforcement to occur
#
# MARKET HYPOTHESIS:
# The market is priced at 35% YES.
# Is this structurally reasonable?
#
# =============================================================================

import sys
import os
from datetime import date

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.data_models import MarketInput
from core.resolution_parser import ResolutionParser
from core.process_model import EUProcessModel
from core.time_feasibility import TimeFeasibilityChecker
from core.probability_estimator import ProbabilityEstimator
from core.market_sanity import MarketSanityChecker
from core.decision_engine import DecisionEngine


def run_example():
    """
    Run a complete example analysis.

    Demonstrates all modules and outputs detailed results.
    """
    print("=" * 70)
    print("POLYMARKET EU AI REGULATION ANALYZER")
    print("Example: EU AI Act Enforcement Market")
    print("=" * 70)
    print()

    # =========================================================================
    # STEP 1: Define the Market Input
    # =========================================================================
    print("STEP 1: MARKET INPUT")
    print("-" * 70)

    market_input = MarketInput(
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
        notes="Article 5 provisions apply from February 2, 2025."
    )

    print(f"Market Title: {market_input.market_title}")
    print(f"Target Date: {market_input.target_date}")
    print(f"Market Implied Probability: {market_input.market_implied_probability:.1%}")
    print(f"Analysis Date: {market_input.analysis_date}")
    print()

    # =========================================================================
    # STEP 2: Resolution Analysis
    # =========================================================================
    print("STEP 2: RESOLUTION ANALYSIS")
    print("-" * 70)

    resolution_parser = ResolutionParser()
    resolution_analysis = resolution_parser.analyze(market_input)

    print(f"Is Binary: {resolution_analysis.is_binary}")
    print(f"Is Objectively Verifiable: {resolution_analysis.is_objectively_verifiable}")
    print(f"Resolution Source Identified: {resolution_analysis.resolution_source_identified}")
    print(f"Hard Fail: {resolution_analysis.hard_fail}")
    print()
    if resolution_analysis.ambiguity_flags:
        print("Ambiguity Flags:")
        for flag in resolution_analysis.ambiguity_flags:
            print(f"  - {flag}")
        print()
    print(f"Reasoning: {resolution_analysis.reasoning}")
    print()

    # =========================================================================
    # STEP 3: Process Model Analysis
    # =========================================================================
    print("STEP 3: PROCESS MODEL ANALYSIS")
    print("-" * 70)

    process_model = EUProcessModel()
    process_analysis = process_model.analyze(market_input)

    print(f"Current Stage: {process_analysis.current_stage.value}")
    print()
    print("Key Dates:")
    for key, value in process_analysis.key_dates.items():
        print(f"  - {key}: {value}")
    print()
    print(f"Stages Remaining: {len(process_analysis.stages_remaining)}")
    for stage in process_analysis.stages_remaining[:3]:
        print(f"  - {stage.value}")
    if len(process_analysis.stages_remaining) > 3:
        print(f"  - ... and {len(process_analysis.stages_remaining) - 3} more")
    print()
    if process_analysis.blocking_factors:
        print("Blocking Factors:")
        for factor in process_analysis.blocking_factors:
            print(f"  - {factor}")
        print()
    print(f"Reasoning: {process_analysis.reasoning}")
    print()

    # =========================================================================
    # STEP 4: Time Feasibility Analysis
    # =========================================================================
    print("STEP 4: TIME FEASIBILITY ANALYSIS")
    print("-" * 70)

    time_checker = TimeFeasibilityChecker()
    time_feasibility = time_checker.analyze(market_input, process_analysis)

    print(f"Days Until Target: {time_feasibility.days_until_target}")
    print(f"Minimum Days Required: {time_feasibility.minimum_days_required}")
    print(f"Timeline Feasible: {time_feasibility.is_timeline_feasible}")
    print(f"Hard Fail: {time_feasibility.hard_fail}")
    print()
    if time_feasibility.mandatory_waiting_periods:
        print("Mandatory Waiting Periods:")
        for period in time_feasibility.mandatory_waiting_periods:
            print(f"  - {period}")
        print()
    if time_feasibility.institutional_constraints:
        print("Institutional Constraints:")
        for constraint in time_feasibility.institutional_constraints:
            print(f"  - {constraint}")
        print()
    print(f"Reasoning: {time_feasibility.reasoning}")
    print()

    # =========================================================================
    # STEP 5: Probability Estimation
    # =========================================================================
    print("STEP 5: PROBABILITY ESTIMATION")
    print("-" * 70)

    estimator = ProbabilityEstimator()
    probability_estimate = estimator.estimate(
        market_input, process_analysis, time_feasibility
    )

    print(f"Probability Range: {probability_estimate.probability_low:.1%} - "
          f"{probability_estimate.probability_high:.1%}")
    print(f"Midpoint: {probability_estimate.probability_midpoint:.1%}")
    print(f"Confidence Level: {probability_estimate.confidence_level}")
    print()
    print("Assumptions:")
    for assumption in probability_estimate.assumptions:
        print(f"  - {assumption}")
    print()
    print("Historical Precedents:")
    for precedent in probability_estimate.historical_precedents:
        print(f"  - {precedent}")
    print()
    print(f"Reasoning: {probability_estimate.reasoning}")
    print()

    # =========================================================================
    # STEP 6: Market Sanity Check
    # =========================================================================
    print("STEP 6: MARKET SANITY CHECK")
    print("-" * 70)

    sanity_checker = MarketSanityChecker()
    market_sanity = sanity_checker.analyze(market_input, probability_estimate)

    print(f"Market Implied Probability: {market_sanity.market_implied_prob:.1%}")
    print(f"Our Rule-Based Estimate: {market_sanity.rule_based_prob:.1%}")
    print(f"Delta: {market_sanity.delta:+.1%} ({market_sanity.delta_percentage_points:.1f}pp)")
    print(f"Direction: {market_sanity.direction}")
    print(f"Meets Threshold (15pp): {market_sanity.meets_threshold}")
    print()
    print(f"Reasoning: {market_sanity.reasoning}")
    print()

    # =========================================================================
    # STEP 7: Final Decision
    # =========================================================================
    print("STEP 7: FINAL DECISION")
    print("-" * 70)

    decision_engine = DecisionEngine()
    final_decision = decision_engine.decide(
        resolution_analysis,
        process_analysis,
        time_feasibility,
        probability_estimate,
        market_sanity
    )

    print()
    print("=" * 70)
    print(f">>> DECISION: {final_decision.outcome.value} <<<")
    print("=" * 70)
    print()
    print(f"Confidence: {final_decision.confidence}")
    print()
    print(f"Recommendation: {final_decision.recommended_action}")
    print()

    print("Criteria Results:")
    for criterion, passed in final_decision.criteria_met.items():
        status = "PASS" if passed else "FAIL"
        print(f"  - {criterion}: {status}")
    print()

    if final_decision.blocking_criteria:
        print("Blocking Criteria:")
        for criterion in final_decision.blocking_criteria:
            print(f"  - {criterion}")
        print()

    if final_decision.risk_warnings:
        print("Risk Warnings:")
        for warning in final_decision.risk_warnings:
            print(f"  ⚠️  {warning}")
        print()

    print("Full Reasoning:")
    print(final_decision.reasoning)
    print()

    print("=" * 70)
    print("ANALYSIS COMPLETE")
    print("=" * 70)

    return final_decision


if __name__ == "__main__":
    run_example()
