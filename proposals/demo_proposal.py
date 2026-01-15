#!/usr/bin/env python3
# =============================================================================
# POLYMARKET BEOBACHTER - PROPOSAL DEMO
# =============================================================================
#
# This script demonstrates the proposal generation and review process.
# It creates a test proposal from the existing analysis and runs it
# through the review gate.
#
# GOVERNANCE:
# This is a DEMONSTRATION script. It does NOT:
# - Execute trades
# - Modify the analyzer
# - Trigger notifications
#
# It ONLY:
# - Generates a proposal from analysis data
# - Runs the proposal through the review gate
# - Saves the results to the audit files
#
# =============================================================================

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import json
from datetime import datetime

from proposals.generator import ProposalGenerator
from proposals.review_gate import ReviewGate
from proposals.storage import ProposalStorage


def load_analysis():
    """Load the latest analysis from output/analysis.json"""
    analysis_path = Path(__file__).parent.parent / "output" / "analysis.json"

    if not analysis_path.exists():
        print(f"[ERROR] No analysis found at {analysis_path}")
        return None

    with open(analysis_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def run_demo():
    """
    Run the proposal generation and review demo.

    GOVERNANCE:
    This function demonstrates the full proposal workflow:
    1. Load analysis data
    2. Generate proposal
    3. Run review gate
    4. Save results
    """
    print("=" * 60)
    print("POLYMARKET BEOBACHTER - PROPOSAL DEMO")
    print("=" * 60)
    print()
    print("GOVERNANCE NOTICE:")
    print("This demo generates proposals and reviews.")
    print("No trades are executed. No notifications are sent.")
    print()

    # Step 1: Load analysis
    print("[1/4] Loading analysis data...")
    analysis = load_analysis()

    if not analysis:
        print("[FAIL] Could not load analysis data.")
        return False

    print(f"      Loaded analysis from: {analysis.get('generated_at', 'N/A')}")
    print(f"      Market: {analysis.get('market_input', {}).get('market_title', 'N/A')[:50]}...")
    print()

    # Step 2: Generate proposal
    print("[2/4] Generating proposal...")
    generator = ProposalGenerator()

    can_generate, reason = generator.can_generate(analysis)
    if not can_generate:
        print(f"      [SKIP] Cannot generate proposal: {reason}")
        return False

    proposal = generator.generate(analysis)

    if not proposal:
        print("      [FAIL] Proposal generation failed.")
        return False

    print(f"      Proposal ID: {proposal.proposal_id}")
    print(f"      Decision: {proposal.decision}")
    print(f"      Edge: {proposal.edge:+.2%}")
    print(f"      Confidence: {proposal.confidence_level}")
    print()

    # Step 3: Run review gate
    print("[3/4] Running review gate...")
    gate = ReviewGate()
    review = gate.review(proposal)

    print(f"      Outcome: {review.outcome.value}")
    print(f"      Checks performed: {len(review.checks_performed)}")
    print()

    # Print checks
    print("      Checks:")
    for check_name, passed in review.checks_performed.items():
        status = "[OK]" if passed else "[X]"
        print(f"        {status} {check_name}")
    print()

    # Print reasons
    print("      Reasons:")
    for reason in review.reasons:
        print(f"        - {reason[:60]}...")
    print()

    # Step 4: Save results
    print("[4/4] Saving to audit files...")
    storage = ProposalStorage()

    proposal_saved = storage.save_proposal(proposal)
    review_saved = storage.save_review(proposal, review)

    if proposal_saved:
        print(f"      [OK] Proposal saved to proposals_log.json")
    else:
        print(f"      [X] Failed to save proposal")

    if review_saved:
        print(f"      [OK] Review saved to proposals_reviewed.md")
    else:
        print(f"      [X] Failed to save review")

    print()
    print("=" * 60)
    print("DEMO COMPLETE")
    print("=" * 60)
    print()
    print("GOVERNANCE REMINDER:")
    print("- No trades were executed")
    print("- No notifications were sent")
    print("- This was a READ-ONLY demonstration")
    print()
    print("To view the results:")
    print("  python cockpit.py --proposals")
    print("  python cockpit.py --review")
    print(f"  python cockpit.py --proposal {proposal.proposal_id}")

    return True


if __name__ == "__main__":
    success = run_demo()
    sys.exit(0 if success else 1)
