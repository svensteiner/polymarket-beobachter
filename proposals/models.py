# =============================================================================
# POLYMARKET BEOBACHTER - PROPOSAL DATA MODELS
# =============================================================================
#
# GOVERNANCE INTENT:
# These dataclasses define the IMMUTABLE structure of proposals.
# Immutability ensures audit trail integrity.
# All fields are explicit - no hidden state.
#
# SCHEMA COMPLIANCE:
# The Proposal schema matches the specification exactly.
# Any deviation from the schema is a governance violation.
#
# =============================================================================

from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from typing import List, Optional, Dict, Any
import uuid
import json


class ConfidenceLevel(Enum):
    """
    Confidence level for probability estimates.

    GOVERNANCE:
    LOW confidence proposals should trigger REVIEW_REJECT or REVIEW_HOLD.
    Only MEDIUM/HIGH confidence proposals can pass the review gate.
    """
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class ReviewOutcome(Enum):
    """
    Review gate classification.

    GOVERNANCE:
    - REVIEW_PASS: Proposal meets all quality criteria
    - REVIEW_HOLD: Mixed signals, requires human attention
    - REVIEW_REJECT: Does not meet minimum quality standards

    CRITICAL: This classification does NOT trigger any action.
    It is purely informational for human reviewers.
    """
    REVIEW_PASS = "REVIEW_PASS"
    REVIEW_HOLD = "REVIEW_HOLD"
    REVIEW_REJECT = "REVIEW_REJECT"


@dataclass(frozen=True)
class ProposalCoreCriteria:
    """
    Core criteria that must be evaluated for every proposal.

    GOVERNANCE:
    These criteria are MANDATORY. Missing criteria = invalid proposal.
    Each criterion must be explicitly TRUE or FALSE, never None.
    """
    liquidity_ok: bool
    volume_ok: bool
    time_to_resolution_ok: bool
    data_quality_ok: bool

    def all_passed(self) -> bool:
        """Check if all core criteria passed."""
        return all([
            self.liquidity_ok,
            self.volume_ok,
            self.time_to_resolution_ok,
            self.data_quality_ok
        ])

    def failed_criteria(self) -> List[str]:
        """Return list of failed criteria names."""
        failed = []
        if not self.liquidity_ok:
            failed.append("liquidity_ok")
        if not self.volume_ok:
            failed.append("volume_ok")
        if not self.time_to_resolution_ok:
            failed.append("time_to_resolution_ok")
        if not self.data_quality_ok:
            failed.append("data_quality_ok")
        return failed

    def to_dict(self) -> Dict[str, bool]:
        """Convert to dictionary for JSON serialization."""
        return {
            "liquidity_ok": self.liquidity_ok,
            "volume_ok": self.volume_ok,
            "time_to_resolution_ok": self.time_to_resolution_ok,
            "data_quality_ok": self.data_quality_ok
        }


@dataclass(frozen=True)
class Proposal:
    """
    Structured proposal object.

    GOVERNANCE:
    - This object is IMMUTABLE (frozen=True)
    - All fields are MANDATORY
    - The governance_notice field is HARDCODED to prevent modification

    SCHEMA:
    Matches the specification exactly. Any field addition/removal
    must be approved and documented.
    """
    proposal_id: str
    timestamp: str  # ISO format
    market_id: str
    market_question: str
    decision: str  # "TRADE" or "NO_TRADE"
    implied_probability: float  # 0.0 to 1.0
    model_probability: float  # 0.0 to 1.0
    edge: float  # model_probability - implied_probability
    core_criteria: ProposalCoreCriteria
    warnings: tuple  # Immutable list of warning strings
    confidence_level: str  # "LOW", "MEDIUM", "HIGH"
    justification_summary: str

    # HARDCODED governance notice - cannot be modified
    governance_notice: str = field(
        default="This proposal is informational only and does not execute trades.",
        init=False
    )

    def __post_init__(self):
        """Validate proposal fields after initialization."""
        # Validate decision
        if self.decision not in ("TRADE", "NO_TRADE"):
            raise ValueError(f"Invalid decision: {self.decision}")

        # Validate confidence level
        if self.confidence_level not in ("LOW", "MEDIUM", "HIGH"):
            raise ValueError(f"Invalid confidence_level: {self.confidence_level}")

        # Validate probabilities are in range
        if not (0.0 <= self.implied_probability <= 1.0):
            raise ValueError(f"implied_probability out of range: {self.implied_probability}")
        if not (0.0 <= self.model_probability <= 1.0):
            raise ValueError(f"model_probability out of range: {self.model_probability}")

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert to dictionary for JSON serialization.

        GOVERNANCE:
        This method ensures consistent JSON output format.
        The governance_notice is always included.
        """
        return {
            "proposal_id": self.proposal_id,
            "timestamp": self.timestamp,
            "market_id": self.market_id,
            "market_question": self.market_question,
            "decision": self.decision,
            "implied_probability": self.implied_probability,
            "model_probability": self.model_probability,
            "edge": self.edge,
            "core_criteria": self.core_criteria.to_dict(),
            "warnings": list(self.warnings),
            "confidence_level": self.confidence_level,
            "justification_summary": self.justification_summary,
            "governance_notice": self.governance_notice
        }

    def to_json(self, indent: int = 2) -> str:
        """Serialize to JSON string."""
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Proposal":
        """
        Create Proposal from dictionary.

        GOVERNANCE:
        This factory method ensures all required fields are present.
        Missing fields will raise KeyError.
        """
        core_criteria = ProposalCoreCriteria(
            liquidity_ok=data["core_criteria"]["liquidity_ok"],
            volume_ok=data["core_criteria"]["volume_ok"],
            time_to_resolution_ok=data["core_criteria"]["time_to_resolution_ok"],
            data_quality_ok=data["core_criteria"]["data_quality_ok"]
        )

        return cls(
            proposal_id=data["proposal_id"],
            timestamp=data["timestamp"],
            market_id=data["market_id"],
            market_question=data["market_question"],
            decision=data["decision"],
            implied_probability=data["implied_probability"],
            model_probability=data["model_probability"],
            edge=data["edge"],
            core_criteria=core_criteria,
            warnings=tuple(data.get("warnings", [])),
            confidence_level=data["confidence_level"],
            justification_summary=data["justification_summary"]
        )


@dataclass(frozen=True)
class ReviewResult:
    """
    Result of the review gate evaluation.

    GOVERNANCE:
    - outcome: The classification (PASS/HOLD/REJECT)
    - reasons: EXPLICIT list of reasons for the classification
    - checks_performed: All checks that were evaluated

    CRITICAL: Reasons must be HUMAN-READABLE.
    Opaque or implicit logic is a governance violation.
    """
    proposal_id: str
    outcome: ReviewOutcome
    reasons: tuple  # Immutable list of reason strings
    checks_performed: Dict[str, bool]  # Map of check_name -> passed
    reviewed_at: str  # ISO timestamp

    # HARDCODED governance notice
    governance_notice: str = field(
        default="This review does not trigger any action. No trade was executed.",
        init=False
    )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "proposal_id": self.proposal_id,
            "outcome": self.outcome.value,
            "reasons": list(self.reasons),
            "checks_performed": self.checks_performed,
            "reviewed_at": self.reviewed_at,
            "governance_notice": self.governance_notice
        }

    def to_markdown(self, proposal: Proposal) -> str:
        """
        Generate human-readable markdown review output.

        GOVERNANCE:
        This output is designed for human reviewers.
        It must be clear, complete, and honest.
        """
        lines = [
            f"## Proposal Review - {self.proposal_id}",
            "",
            f"**Market:** {proposal.market_question[:80]}{'...' if len(proposal.market_question) > 80 else ''}",
            f"**Decision:** {proposal.decision}",
            f"**Edge:** {proposal.edge:+.2%}",
            f"**Confidence:** {proposal.confidence_level}",
            "",
            "### Review Outcome",
            f"**{self.outcome.value}**",
            "",
            "### Key Reasons",
        ]

        for reason in self.reasons:
            lines.append(f"- {reason}")

        if not self.reasons:
            lines.append("- No specific reasons recorded")

        lines.append("")
        lines.append("### Checks Performed")

        for check_name, passed in self.checks_performed.items():
            status = "[OK]" if passed else "[X]"
            lines.append(f"- {status} {check_name}")

        if proposal.warnings:
            lines.append("")
            lines.append("### Warnings")
            for warning in proposal.warnings:
                lines.append(f"- {warning}")

        lines.append("")
        lines.append("### Governance Notice")
        lines.append(self.governance_notice)
        lines.append("")
        lines.append("---")
        lines.append("")

        return "\n".join(lines)


def generate_proposal_id() -> str:
    """
    Generate a unique proposal ID.

    Format: PROP-{date}-{short_uuid}
    Example: PROP-20260115-a1b2c3d4
    """
    date_part = datetime.now().strftime("%Y%m%d")
    uuid_part = uuid.uuid4().hex[:8]
    return f"PROP-{date_part}-{uuid_part}"
