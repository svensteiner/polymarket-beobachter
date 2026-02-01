# =============================================================================
# CROSS-MARKET CONSISTENCY ENGINE - RELATION TYPES
# =============================================================================
#
# Defines the logical relations between markets.
#
# PHASE 1: Only IMPLIES relation
#
# ISOLATION: This file has NO imports from trading code.
#
# =============================================================================

from enum import Enum
from dataclasses import dataclass
from typing import Optional


class RelationType(Enum):
    """
    Types of logical relations between markets.

    PHASE 1: Only IMPLIES is implemented.

    Future phases may add:
    - MUTEX (mutually exclusive)
    - SUBSET (one outcome is subset of another)
    - COMPLEMENT (probabilities should sum to 1)

    But for now: IMPLIES only.
    """
    IMPLIES = "IMPLIES"


@dataclass(frozen=True)
class Relation:
    """
    A logical relation between two markets.

    IMPLIES Semantics:
    - If market_a resolves YES, then market_b MUST resolve YES
    - Therefore: P(A) <= P(B) must hold
    - If P(A) > P(B) + tolerance, this is INCONSISTENT

    Example:
    - Market A: "Will X happen by December 2025?"
    - Market B: "Will X happen by December 2026?"
    - A IMPLIES B (if it happens by 2025, it definitely happens by 2026)

    Attributes:
        market_a_id: The antecedent market (if this is true...)
        market_b_id: The consequent market (...then this must be true)
        relation_type: Type of relation (IMPLIES only for Phase 1)
        description: Human-readable explanation of why this relation holds
        tolerance: Allowed deviation before flagging inconsistency (default 5%)
    """
    market_a_id: str  # Antecedent
    market_b_id: str  # Consequent
    relation_type: RelationType
    description: str
    tolerance: float = 0.05  # 5% default tolerance

    def __post_init__(self):
        """Validate relation on creation."""
        if self.relation_type != RelationType.IMPLIES:
            raise ValueError(
                f"Phase 1 only supports IMPLIES relation. Got: {self.relation_type}"
            )

        if not self.market_a_id or not self.market_b_id:
            raise ValueError("Both market_a_id and market_b_id are required")

        if self.market_a_id == self.market_b_id:
            raise ValueError("A market cannot imply itself")

        if not 0.0 <= self.tolerance <= 0.5:
            raise ValueError(
                f"Tolerance must be between 0 and 0.5. Got: {self.tolerance}"
            )

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "market_a_id": self.market_a_id,
            "market_b_id": self.market_b_id,
            "relation_type": self.relation_type.value,
            "description": self.description,
            "tolerance": self.tolerance,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Relation":
        """Create from dictionary."""
        return cls(
            market_a_id=data["market_a_id"],
            market_b_id=data["market_b_id"],
            relation_type=RelationType(data["relation_type"]),
            description=data["description"],
            tolerance=data.get("tolerance", 0.05),
        )


def create_implies_relation(
    antecedent_id: str,
    consequent_id: str,
    description: str,
    tolerance: float = 0.05,
) -> Relation:
    """
    Factory function to create an IMPLIES relation.

    Args:
        antecedent_id: Market that implies the other (A in "A implies B")
        consequent_id: Market that is implied (B in "A implies B")
        description: Why this implication holds
        tolerance: Allowed deviation (default 5%)

    Returns:
        A validated Relation object

    Example:
        relation = create_implies_relation(
            antecedent_id="market_abc",
            consequent_id="market_xyz",
            description="Event by 2025 implies event by 2026",
        )
    """
    return Relation(
        market_a_id=antecedent_id,
        market_b_id=consequent_id,
        relation_type=RelationType.IMPLIES,
        description=description,
        tolerance=tolerance,
    )
