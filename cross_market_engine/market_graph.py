# =============================================================================
# CROSS-MARKET CONSISTENCY ENGINE - MARKET GRAPH
# =============================================================================
#
# Represents markets as nodes and relations as edges in a graph structure.
#
# ISOLATION: This file has NO imports from trading code.
# It only uses standard library and local module imports.
#
# =============================================================================

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set
from datetime import datetime

from .relations import Relation, RelationType


@dataclass
class MarketNode:
    """
    A market node in the consistency graph.

    This is a READ-ONLY snapshot of market state.
    It does NOT connect to live data feeds.
    Values must be passed in explicitly.

    Attributes:
        market_id: Unique identifier for the market
        question: The market question text
        probability: Current YES probability (0.0 to 1.0)
        last_updated: When this snapshot was taken
        metadata: Optional additional information
    """
    market_id: str
    question: str
    probability: float
    last_updated: datetime = field(default_factory=datetime.utcnow)
    metadata: Dict[str, str] = field(default_factory=dict)

    def __post_init__(self):
        """Validate market node on creation."""
        if not self.market_id:
            raise ValueError("market_id is required")

        if not 0.0 <= self.probability <= 1.0:
            raise ValueError(
                f"Probability must be between 0 and 1. Got: {self.probability}"
            )

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "market_id": self.market_id,
            "question": self.question,
            "probability": self.probability,
            "last_updated": self.last_updated.isoformat(),
            "metadata": self.metadata,
        }


class MarketGraph:
    """
    A graph of markets connected by logical relations.

    This is a pure data structure with no side effects.
    Markets and relations are added explicitly.
    No automatic data fetching or updates.

    ISOLATION GUARANTEE:
    This class has no network access, no file I/O (except explicit),
    and no connections to trading systems.
    """

    def __init__(self):
        """Initialize an empty market graph."""
        self._markets: Dict[str, MarketNode] = {}
        self._relations: List[Relation] = []
        self._outgoing_edges: Dict[str, List[Relation]] = {}
        self._incoming_edges: Dict[str, List[Relation]] = {}

    def add_market(self, market: MarketNode) -> None:
        """
        Add a market node to the graph.

        Args:
            market: The market node to add

        Raises:
            ValueError: If market with same ID already exists
        """
        if market.market_id in self._markets:
            raise ValueError(f"Market {market.market_id} already exists in graph")

        self._markets[market.market_id] = market
        self._outgoing_edges[market.market_id] = []
        self._incoming_edges[market.market_id] = []

    def update_market_probability(
        self,
        market_id: str,
        probability: float,
        timestamp: Optional[datetime] = None,
    ) -> None:
        """
        Update the probability of an existing market.

        Args:
            market_id: The market to update
            probability: New probability value
            timestamp: When this update occurred (default: now)

        Raises:
            KeyError: If market doesn't exist
            ValueError: If probability is invalid
        """
        if market_id not in self._markets:
            raise KeyError(f"Market {market_id} not found in graph")

        if not 0.0 <= probability <= 1.0:
            raise ValueError(f"Probability must be between 0 and 1. Got: {probability}")

        old_market = self._markets[market_id]
        self._markets[market_id] = MarketNode(
            market_id=old_market.market_id,
            question=old_market.question,
            probability=probability,
            last_updated=timestamp or datetime.utcnow(),
            metadata=old_market.metadata,
        )

    def add_relation(self, relation: Relation) -> None:
        """
        Add a relation between markets.

        Args:
            relation: The relation to add

        Raises:
            KeyError: If either market doesn't exist in the graph
        """
        if relation.market_a_id not in self._markets:
            raise KeyError(
                f"Antecedent market {relation.market_a_id} not found in graph"
            )

        if relation.market_b_id not in self._markets:
            raise KeyError(
                f"Consequent market {relation.market_b_id} not found in graph"
            )

        self._relations.append(relation)
        self._outgoing_edges[relation.market_a_id].append(relation)
        self._incoming_edges[relation.market_b_id].append(relation)

    def get_market(self, market_id: str) -> Optional[MarketNode]:
        """Get a market by ID, or None if not found."""
        return self._markets.get(market_id)

    def get_all_markets(self) -> List[MarketNode]:
        """Get all markets in the graph."""
        return list(self._markets.values())

    def get_all_relations(self) -> List[Relation]:
        """Get all relations in the graph."""
        return list(self._relations)

    def get_relations_for_market(self, market_id: str) -> List[Relation]:
        """
        Get all relations involving a specific market.

        Args:
            market_id: The market ID to query

        Returns:
            List of relations where this market is antecedent or consequent
        """
        outgoing = self._outgoing_edges.get(market_id, [])
        incoming = self._incoming_edges.get(market_id, [])
        return outgoing + incoming

    def get_implies_relations(self) -> List[Relation]:
        """Get all IMPLIES relations."""
        return [
            r for r in self._relations
            if r.relation_type == RelationType.IMPLIES
        ]

    def market_count(self) -> int:
        """Number of markets in the graph."""
        return len(self._markets)

    def relation_count(self) -> int:
        """Number of relations in the graph."""
        return len(self._relations)

    def to_dict(self) -> dict:
        """Serialize the entire graph to a dictionary."""
        return {
            "markets": [m.to_dict() for m in self._markets.values()],
            "relations": [r.to_dict() for r in self._relations],
        }

    def clear(self) -> None:
        """Remove all markets and relations."""
        self._markets.clear()
        self._relations.clear()
        self._outgoing_edges.clear()
        self._incoming_edges.clear()


def create_market_snapshot(
    market_id: str,
    question: str,
    probability: float,
    metadata: Optional[Dict[str, str]] = None,
) -> MarketNode:
    """
    Factory function to create a market snapshot.

    This is the ONLY way to create market data for the consistency engine.
    Data must be passed explicitly - no automatic fetching.

    Args:
        market_id: Unique market identifier
        question: The market question
        probability: Current YES probability (0.0 to 1.0)
        metadata: Optional additional data

    Returns:
        A validated MarketNode

    Example:
        market = create_market_snapshot(
            market_id="abc123",
            question="Will event X happen?",
            probability=0.65,
        )
    """
    return MarketNode(
        market_id=market_id,
        question=question,
        probability=probability,
        metadata=metadata or {},
    )
