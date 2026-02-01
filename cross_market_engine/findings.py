# =============================================================================
# CROSS-MARKET CONSISTENCY ENGINE - FINDINGS
# =============================================================================
#
# Structured findings from consistency checks.
#
# ISOLATION: This file has NO imports from trading code.
# Findings are INFORMATIONAL ONLY - they cannot trigger trades.
#
# =============================================================================

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional, Dict, Any
import json


class ConsistencyStatus(Enum):
    """
    Status of a consistency check.

    CONSISTENT: The relation holds within tolerance.
    INCONSISTENT: The relation is violated beyond tolerance.
    UNCLEAR: Cannot determine (missing data, edge cases).

    Default behavior: If unclear, treat as UNCLEAR (not INCONSISTENT).
    This is FAIL-CLOSED for alerting but conservative for flagging.
    """
    CONSISTENT = "CONSISTENT"
    INCONSISTENT = "INCONSISTENT"
    UNCLEAR = "UNCLEAR"


@dataclass
class Finding:
    """
    A finding from a consistency check.

    This is a pure data object representing a single observation.
    It has NO side effects and cannot trigger any actions.

    CRITICAL: Findings are INFORMATIONAL ONLY.
    They are logged for research purposes.
    They CANNOT:
    - Place trades
    - Modify trading parameters
    - Trigger alerts to execution systems
    - Influence decision engine thresholds

    Attributes:
        finding_id: Unique identifier for this finding
        timestamp: When this finding was generated
        market_a_id: The antecedent market
        market_b_id: The consequent market
        relation_type: Type of relation checked
        p_a: Probability of market A
        p_b: Probability of market B
        delta: p_a - p_b (positive means A > B)
        tolerance: Tolerance used for this check
        status: Result of the check
        explanation: Human-readable explanation
        metadata: Optional additional context
    """
    finding_id: str
    timestamp: datetime
    market_a_id: str
    market_b_id: str
    relation_type: str
    p_a: float
    p_b: float
    delta: float
    tolerance: float
    status: ConsistencyStatus
    explanation: str
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "finding_id": self.finding_id,
            "timestamp": self.timestamp.isoformat(),
            "market_a_id": self.market_a_id,
            "market_b_id": self.market_b_id,
            "relation_type": self.relation_type,
            "p_a": self.p_a,
            "p_b": self.p_b,
            "delta": self.delta,
            "tolerance": self.tolerance,
            "status": self.status.value,
            "explanation": self.explanation,
            "metadata": self.metadata,
        }

    def to_json(self) -> str:
        """Convert to JSON string."""
        return json.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Finding":
        """Create from dictionary."""
        return cls(
            finding_id=data["finding_id"],
            timestamp=datetime.fromisoformat(data["timestamp"]),
            market_a_id=data["market_a_id"],
            market_b_id=data["market_b_id"],
            relation_type=data["relation_type"],
            p_a=data["p_a"],
            p_b=data["p_b"],
            delta=data["delta"],
            tolerance=data["tolerance"],
            status=ConsistencyStatus(data["status"]),
            explanation=data["explanation"],
            metadata=data.get("metadata", {}),
        )

    def is_inconsistent(self) -> bool:
        """Check if this finding indicates an inconsistency."""
        return self.status == ConsistencyStatus.INCONSISTENT

    def is_unclear(self) -> bool:
        """Check if this finding is unclear."""
        return self.status == ConsistencyStatus.UNCLEAR

    def summary(self) -> str:
        """One-line summary of the finding."""
        status_symbol = {
            ConsistencyStatus.CONSISTENT: "OK",
            ConsistencyStatus.INCONSISTENT: "!!",
            ConsistencyStatus.UNCLEAR: "??",
        }
        symbol = status_symbol[self.status]
        return (
            f"[{symbol}] {self.market_a_id} -> {self.market_b_id}: "
            f"P(A)={self.p_a:.2%}, P(B)={self.p_b:.2%}, "
            f"delta={self.delta:+.2%}"
        )


@dataclass
class FindingsSummary:
    """
    Summary of multiple findings from a consistency run.

    This is INFORMATIONAL ONLY.
    """
    run_id: str
    timestamp: datetime
    total_relations_checked: int
    consistent_count: int
    inconsistent_count: int
    unclear_count: int
    findings: list  # List[Finding]

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "run_id": self.run_id,
            "timestamp": self.timestamp.isoformat(),
            "total_relations_checked": self.total_relations_checked,
            "consistent_count": self.consistent_count,
            "inconsistent_count": self.inconsistent_count,
            "unclear_count": self.unclear_count,
            "findings": [f.to_dict() for f in self.findings],
        }

    def has_inconsistencies(self) -> bool:
        """Check if any inconsistencies were found."""
        return self.inconsistent_count > 0

    def summary_text(self) -> str:
        """Human-readable summary."""
        lines = [
            f"Consistency Check Summary (Run: {self.run_id})",
            f"Timestamp: {self.timestamp.isoformat()}",
            f"Relations Checked: {self.total_relations_checked}",
            f"  - Consistent: {self.consistent_count}",
            f"  - Inconsistent: {self.inconsistent_count}",
            f"  - Unclear: {self.unclear_count}",
        ]

        if self.inconsistent_count > 0:
            lines.append("")
            lines.append("INCONSISTENCIES DETECTED:")
            for f in self.findings:
                if f.is_inconsistent():
                    lines.append(f"  {f.summary()}")

        return "\n".join(lines)
