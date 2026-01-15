# =============================================================================
# POLYMARKET EU AI REGULATION ANALYZER
# Module: historical/models.py
# Purpose: Data models for historical/counterfactual testing
# =============================================================================
#
# AUDIT CONTEXT:
# These models define the structure for testing analyzer discipline.
# A HistoricalCase represents a market that could have existed at a point
# in time, with a known real-world outcome we use ONLY for evaluation.
#
# CRITICAL PRINCIPLE:
# The analyzer NEVER sees the known_outcome during evaluation.
# We simulate "blind" analysis as if the case were a live market.
#
# =============================================================================

from dataclasses import dataclass, field, asdict
from datetime import date
from enum import Enum
from typing import Optional, List, Dict, Any


class KnownOutcome(Enum):
    """
    The actual real-world outcome of the hypothetical market.

    This is used ONLY for post-hoc classification, NEVER fed to the analyzer.

    YES: The event described in the resolution DID occur by the target date.
    NO:  The event described in the resolution did NOT occur by the target date.
    """
    YES = "YES"
    NO = "NO"


class OutcomeClassification(Enum):
    """
    Classification of the analyzer's decision vs. real-world outcome.

    CORRECT_REJECTION:
        Analyzer said NO_TRADE, outcome was NO.
        This is CORRECT behavior - the analyzer protected against a bad trade.

    SAFE_PASS:
        Analyzer said NO_TRADE, outcome was YES.
        This is ACCEPTABLE conservatism - we missed an opportunity but stayed safe.

    FALSE_ADMISSION:
        Analyzer said TRADE, outcome was NO.
        This is a CRITICAL FAILURE - the analyzer would have allowed a losing trade.

    RARE_SUCCESS:
        Analyzer said TRADE, outcome was YES.
        This is rare but acceptable - the analyzer identified a valid opportunity.

    SEVERITY RANKING (worst to best):
    1. FALSE_ADMISSION (worst - structural failure)
    2. SAFE_PASS (acceptable - conservative)
    3. CORRECT_REJECTION (good - worked as intended)
    4. RARE_SUCCESS (best but rare - found real edge)
    """
    CORRECT_REJECTION = "CORRECT_REJECTION"
    SAFE_PASS = "SAFE_PASS"
    FALSE_ADMISSION = "FALSE_ADMISSION"
    RARE_SUCCESS = "RARE_SUCCESS"


@dataclass
class FormalTimeline:
    """
    Formal timeline of EU regulatory milestones.

    These are the ACTUAL dates of regulatory events.
    Used only for post-hoc evaluation, never fed to analyzer.

    FIELDS:
    - proposal_date: When the regulation was proposed
    - adoption_date: When the regulation was adopted by co-legislators
    - publication_date: When published in the Official Journal
    - entry_into_force: When the regulation legally enters into force
    - application_date: When the regulation starts applying (may differ)
    - enforcement_start: When enforcement actions can begin
    - additional_milestones: Any other relevant dated events
    """
    proposal_date: Optional[date] = None
    adoption_date: Optional[date] = None
    publication_date: Optional[date] = None
    entry_into_force: Optional[date] = None
    application_date: Optional[date] = None
    enforcement_start: Optional[date] = None
    additional_milestones: Dict[str, date] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        result = {
            "proposal_date": self.proposal_date.isoformat() if self.proposal_date else None,
            "adoption_date": self.adoption_date.isoformat() if self.adoption_date else None,
            "publication_date": self.publication_date.isoformat() if self.publication_date else None,
            "entry_into_force": self.entry_into_force.isoformat() if self.entry_into_force else None,
            "application_date": self.application_date.isoformat() if self.application_date else None,
            "enforcement_start": self.enforcement_start.isoformat() if self.enforcement_start else None,
            "additional_milestones": {
                k: v.isoformat() for k, v in self.additional_milestones.items()
            }
        }
        return result


@dataclass
class HistoricalCase:
    """
    A historical case for testing analyzer discipline.

    This represents a market that COULD have existed at a point in time.
    The synthetic_resolution_text mimics how Polymarket would have phrased it.

    CRITICAL: The known_outcome is NEVER passed to the analyzer.
    It is used ONLY for post-hoc classification of the analyzer's decision.

    FIELDS:
    - case_id: Unique identifier for this case
    - title: Human-readable title of the case
    - description: Context about what this case tests
    - synthetic_resolution_text: How Polymarket WOULD have phrased this market
    - hypothetical_target_date: The deadline the market would have used
    - referenced_regulation: Which EU regulation this relates to
    - authority_involved: Which EU institutions are relevant
    - analysis_as_of_date: The date we pretend the analysis is being run
    - formal_timeline: ACTUAL timeline of regulatory events (for evaluation only)
    - known_outcome: YES/NO - did the event actually happen? (for evaluation only)
    - notes: Optional additional context
    - failure_explanation: If outcome was NO, why? (for learning, not tuning)
    """
    case_id: str
    title: str
    description: str
    synthetic_resolution_text: str
    hypothetical_target_date: date
    referenced_regulation: str
    authority_involved: str
    analysis_as_of_date: date
    formal_timeline: FormalTimeline
    known_outcome: KnownOutcome
    notes: Optional[str] = None
    failure_explanation: Optional[str] = None

    def __post_init__(self):
        """Validate case data."""
        # Validate required string fields
        if not self.case_id.strip():
            raise ValueError("case_id cannot be empty")
        if not self.title.strip():
            raise ValueError("title cannot be empty")
        if not self.synthetic_resolution_text.strip():
            raise ValueError("synthetic_resolution_text cannot be empty")
        if not self.referenced_regulation.strip():
            raise ValueError("referenced_regulation cannot be empty")

        # Validate date relationships
        if self.hypothetical_target_date < self.analysis_as_of_date:
            raise ValueError(
                f"hypothetical_target_date ({self.hypothetical_target_date}) "
                f"must be >= analysis_as_of_date ({self.analysis_as_of_date})"
            )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "case_id": self.case_id,
            "title": self.title,
            "description": self.description,
            "synthetic_resolution_text": self.synthetic_resolution_text,
            "hypothetical_target_date": self.hypothetical_target_date.isoformat(),
            "referenced_regulation": self.referenced_regulation,
            "authority_involved": self.authority_involved,
            "analysis_as_of_date": self.analysis_as_of_date.isoformat(),
            "formal_timeline": self.formal_timeline.to_dict(),
            "known_outcome": self.known_outcome.value,
            "notes": self.notes,
            "failure_explanation": self.failure_explanation,
        }


@dataclass
class CaseResult:
    """
    Result of running a historical case through the analyzer.

    Contains both the analyzer's blind decision and the post-hoc classification.

    FIELDS:
    - case: The original historical case
    - analyzer_decision: "TRADE" or "NO_TRADE" from the analyzer
    - blocking_criteria: Which criteria blocked trading (if NO_TRADE)
    - timeline_conflicts: Timeline issues detected by the analyzer
    - classification: Post-hoc classification vs. known outcome
    - risk_warnings: Warnings generated by the analyzer
    - full_reasoning: Complete reasoning from the analyzer
    """
    case: HistoricalCase
    analyzer_decision: str  # "TRADE" or "NO_TRADE"
    blocking_criteria: List[str]
    timeline_conflicts: List[str]
    classification: OutcomeClassification
    risk_warnings: List[str]
    full_reasoning: str

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "case_id": self.case.case_id,
            "case_title": self.case.title,
            "analyzer_decision": self.analyzer_decision,
            "known_outcome": self.case.known_outcome.value,
            "classification": self.classification.value,
            "blocking_criteria": self.blocking_criteria,
            "timeline_conflicts": self.timeline_conflicts,
            "risk_warnings": self.risk_warnings,
            "full_reasoning": self.full_reasoning,
            "failure_explanation": self.case.failure_explanation,
        }

    def is_critical_failure(self) -> bool:
        """Check if this is a FALSE_ADMISSION (critical failure)."""
        return self.classification == OutcomeClassification.FALSE_ADMISSION

    def is_correct_behavior(self) -> bool:
        """Check if analyzer behaved correctly (CORRECT_REJECTION or RARE_SUCCESS)."""
        return self.classification in {
            OutcomeClassification.CORRECT_REJECTION,
            OutcomeClassification.RARE_SUCCESS,
        }


def classify_outcome(
    analyzer_decision: str,
    known_outcome: KnownOutcome
) -> OutcomeClassification:
    """
    Classify the outcome based on analyzer decision and known real-world result.

    Args:
        analyzer_decision: "TRADE" or "NO_TRADE" from the analyzer
        known_outcome: The actual real-world outcome

    Returns:
        OutcomeClassification indicating correctness of analyzer behavior

    CLASSIFICATION MATRIX:
    +------------------+-------------+-------------+
    |                  | Outcome YES | Outcome NO  |
    +------------------+-------------+-------------+
    | Analyzer TRADE   | RARE_SUCCESS| FALSE_ADM.  |
    | Analyzer NO_TRADE| SAFE_PASS   | CORRECT_REJ.|
    +------------------+-------------+-------------+
    """
    if analyzer_decision == "TRADE":
        if known_outcome == KnownOutcome.YES:
            return OutcomeClassification.RARE_SUCCESS
        else:  # known_outcome == KnownOutcome.NO
            return OutcomeClassification.FALSE_ADMISSION
    else:  # analyzer_decision == "NO_TRADE"
        if known_outcome == KnownOutcome.YES:
            return OutcomeClassification.SAFE_PASS
        else:  # known_outcome == KnownOutcome.NO
            return OutcomeClassification.CORRECT_REJECTION
