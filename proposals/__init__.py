# =============================================================================
# POLYMARKET BEOBACHTER - PROPOSAL REVIEW SYSTEM
# =============================================================================
#
# GOVERNANCE INTENT:
# This module implements a JUSTIFICATION + DISCIPLINE layer.
# It does NOT execute trades.
# It does NOT modify decisions.
# It ONLY structures and evaluates decision justifications.
#
# ARCHITECTURE:
#   Decision -> Proposal -> Review Gate -> Documentation
#
# ABSOLUTE CONSTRAINTS:
# - No trading
# - No notifications (Telegram, etc.)
# - No code execution based on proposals
# - No feedback loop into the analyzer
# - No learning from outcomes
#
# This system exists to PREVENT impulsive automation.
# Clarity beats speed. Discipline beats activity.
#
# =============================================================================

from proposals.models import (
    Proposal,
    ProposalCoreCriteria,
    ReviewOutcome,
    ReviewResult,
    ConfidenceLevel,
)
from proposals.generator import ProposalGenerator
from proposals.review_gate import ReviewGate
from proposals.storage import ProposalStorage

__all__ = [
    "Proposal",
    "ProposalCoreCriteria",
    "ReviewOutcome",
    "ReviewResult",
    "ConfidenceLevel",
    "ProposalGenerator",
    "ReviewGate",
    "ProposalStorage",
]
