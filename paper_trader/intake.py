# =============================================================================
# POLYMARKET BEOBACHTER - PROPOSAL INTAKE FOR PAPER TRADING
# =============================================================================
#
# GOVERNANCE INTENT:
# This module loads and filters proposals for paper trading.
# It implements READ-ONLY access to the proposals/ storage.
#
# FILTERING CRITERIA:
# Only proposals that meet ALL of the following are selected:
# 1. decision == "TRADE"
# 2. review_result == "REVIEW_PASS" (after running review gate)
# 3. Not already paper-executed (idempotency)
#
# DATA FLOW:
#   proposals/proposals_log.json → intake.py → paper_trader
#   ❌ NO REVERSE FLOW (paper trading never modifies proposals)
#
# =============================================================================

import sys
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Set

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from proposals.models import Proposal, ReviewOutcome
from proposals.storage import get_storage
from proposals.review_gate import ReviewGate

from paper_trader.logger import get_paper_logger

logger = logging.getLogger(__name__)


# =============================================================================
# PROPOSAL INTAKE
# =============================================================================


class ProposalIntake:
    """
    Loads and filters proposals for paper trading.

    GOVERNANCE:
    - READ-ONLY access to proposals
    - Does NOT modify proposals
    - Does NOT write back to proposals/
    - Enforces idempotency (no re-execution)
    """

    def __init__(self):
        """Initialize the intake module."""
        self._storage = get_storage()
        self._review_gate = ReviewGate()
        self._paper_logger = get_paper_logger()

    def get_eligible_proposals(self) -> List[Proposal]:
        """
        Get proposals eligible for paper trading.

        CRITERIA:
        1. decision == "TRADE"
        2. Passes review gate (REVIEW_PASS)
        3. Not already paper-executed

        Returns:
            List of eligible Proposal objects
        """
        # Get all proposals
        all_proposals = self._storage.load_proposals()
        logger.info(f"Loaded {len(all_proposals)} total proposals")

        # Get already-executed proposal IDs
        executed_ids = self._paper_logger.get_executed_proposal_ids()
        logger.info(f"Found {len(executed_ids)} already paper-executed proposals")

        # Filter
        eligible = []
        for proposal in all_proposals:
            # Check 1: Decision is TRADE
            if proposal.decision != "TRADE":
                continue

            # Check 2: Not already executed (idempotency)
            if proposal.proposal_id in executed_ids:
                continue

            # Check 3: Passes review gate
            review = self._review_gate.review(proposal)
            if review.outcome != ReviewOutcome.REVIEW_PASS:
                continue

            eligible.append(proposal)

        logger.info(f"Found {len(eligible)} eligible proposals for paper trading")
        return eligible

    def get_proposal_by_id(self, proposal_id: str) -> Optional[Proposal]:
        """
        Get a specific proposal by ID.

        Args:
            proposal_id: The proposal ID

        Returns:
            Proposal if found, None otherwise
        """
        return self._storage.get_proposal_by_id(proposal_id)

    def is_proposal_eligible(self, proposal: Proposal) -> tuple:
        """
        Check if a specific proposal is eligible for paper trading.

        Returns:
            Tuple of (is_eligible: bool, reason: str)
        """
        # Check 1: Decision
        if proposal.decision != "TRADE":
            return (False, f"Decision is {proposal.decision}, not TRADE")

        # Check 2: Already executed
        executed_ids = self._paper_logger.get_executed_proposal_ids()
        if proposal.proposal_id in executed_ids:
            return (False, "Proposal already paper-executed (idempotency)")

        # Check 3: Review gate
        review = self._review_gate.review(proposal)
        if review.outcome != ReviewOutcome.REVIEW_PASS:
            return (False, f"Review outcome is {review.outcome.value}, not REVIEW_PASS")

        return (True, "Proposal eligible for paper trading")


# =============================================================================
# MODULE-LEVEL FUNCTIONS
# =============================================================================

_intake: Optional[ProposalIntake] = None


def get_intake() -> ProposalIntake:
    """Get the global intake instance."""
    global _intake
    if _intake is None:
        _intake = ProposalIntake()
    return _intake


def get_eligible_proposals() -> List[Proposal]:
    """Convenience function to get eligible proposals."""
    return get_intake().get_eligible_proposals()


def is_proposal_eligible(proposal: Proposal) -> tuple:
    """Convenience function to check proposal eligibility."""
    return get_intake().is_proposal_eligible(proposal)
