# =============================================================================
# POLYMARKET BEOBACHTER - PAPER TRADING DATA MODELS
# =============================================================================
#
# GOVERNANCE INTENT:
# These dataclasses define the structure of paper trading records.
# All models are IMMUTABLE (frozen=True) to ensure audit trail integrity.
#
# PAPER TRADING ONLY:
# These models represent SIMULATED trades, not real positions.
# The governance_notice fields are hardcoded to prevent confusion.
#
# =============================================================================

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, Any, Optional, List
import json
import uuid


class PositionStatus(Enum):
    """
    Status of a paper position.

    PAPER TRADING ONLY - No real positions.
    """
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    RESOLVED = "RESOLVED"


class TradeAction(Enum):
    """
    Types of paper trading actions.

    PAPER TRADING ONLY - No real trades.
    """
    PAPER_ENTER = "PAPER_ENTER"
    PAPER_EXIT = "PAPER_EXIT"
    SKIP = "SKIP"


class PositionSide(Enum):
    """Side of a paper position."""
    YES = "YES"
    NO = "NO"


class LiquidityBucket(Enum):
    """
    Liquidity classification for slippage calculation.

    GOVERNANCE:
    Conservative slippage is applied based on bucket.
    """
    HIGH = "HIGH"      # Tight spreads, deep liquidity
    MEDIUM = "MEDIUM"  # Moderate spreads
    LOW = "LOW"        # Wide spreads, thin liquidity
    UNKNOWN = "UNKNOWN"  # Cannot determine - use worst-case


@dataclass(frozen=True)
class MarketSnapshot:
    """
    Point-in-time market price snapshot from Layer 2.

    GOVERNANCE:
    This data is used for paper trading simulation ONLY.
    It is NEVER fed back to Layer 1 decision-making.
    """
    market_id: str
    snapshot_time: str  # ISO timestamp
    best_bid: Optional[float]  # None if unavailable
    best_ask: Optional[float]  # None if unavailable
    mid_price: Optional[float]  # Calculated or provided
    spread_pct: Optional[float]  # Percentage spread
    liquidity_bucket: str  # HIGH/MEDIUM/LOW/UNKNOWN
    is_resolved: bool
    resolved_outcome: Optional[str]  # "YES" or "NO" if resolved

    # Hardcoded governance notice
    governance_notice: str = field(
        default="This snapshot is for paper trading simulation only.",
        init=False
    )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "market_id": self.market_id,
            "snapshot_time": self.snapshot_time,
            "best_bid": self.best_bid,
            "best_ask": self.best_ask,
            "mid_price": self.mid_price,
            "spread_pct": self.spread_pct,
            "liquidity_bucket": self.liquidity_bucket,
            "is_resolved": self.is_resolved,
            "resolved_outcome": self.resolved_outcome,
            "governance_notice": self.governance_notice,
        }

    def has_valid_prices(self) -> bool:
        """Check if snapshot has valid price data."""
        if self.best_bid is not None and self.best_ask is not None:
            return self.best_bid > 0 and self.best_ask > 0
        return self.mid_price is not None and self.mid_price > 0


@dataclass(frozen=True)
class PaperPosition:
    """
    A simulated position in paper trading.

    GOVERNANCE:
    This represents a PAPER position only.
    No real funds are allocated. No real trades are executed.
    """
    position_id: str
    proposal_id: str
    market_id: str
    market_question: str
    side: str  # "YES" or "NO"
    status: str  # "OPEN", "CLOSED", "RESOLVED"

    # Entry details
    entry_time: str  # ISO timestamp
    entry_price: float
    entry_slippage: float
    size_contracts: float  # Number of contracts/shares
    cost_basis_eur: float  # Total cost in EUR (paper)

    # Exit details (None if still open)
    exit_time: Optional[str]
    exit_price: Optional[float]
    exit_slippage: Optional[float]
    exit_reason: Optional[str]

    # P&L (None if still open)
    realized_pnl_eur: Optional[float]
    pnl_pct: Optional[float]

    # Hardcoded governance notice
    governance_notice: str = field(
        default="This is a PAPER position. No real funds were used.",
        init=False
    )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "position_id": self.position_id,
            "proposal_id": self.proposal_id,
            "market_id": self.market_id,
            "market_question": self.market_question,
            "side": self.side,
            "status": self.status,
            "entry_time": self.entry_time,
            "entry_price": self.entry_price,
            "entry_slippage": self.entry_slippage,
            "size_contracts": self.size_contracts,
            "cost_basis_eur": self.cost_basis_eur,
            "exit_time": self.exit_time,
            "exit_price": self.exit_price,
            "exit_slippage": self.exit_slippage,
            "exit_reason": self.exit_reason,
            "realized_pnl_eur": self.realized_pnl_eur,
            "pnl_pct": self.pnl_pct,
            "governance_notice": self.governance_notice,
        }

    def to_json(self) -> str:
        """Serialize to JSON string."""
        return json.dumps(self.to_dict(), ensure_ascii=False)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PaperPosition":
        """Create PaperPosition from dictionary."""
        return cls(
            position_id=data["position_id"],
            proposal_id=data["proposal_id"],
            market_id=data["market_id"],
            market_question=data["market_question"],
            side=data["side"],
            status=data["status"],
            entry_time=data["entry_time"],
            entry_price=data["entry_price"],
            entry_slippage=data["entry_slippage"],
            size_contracts=data["size_contracts"],
            cost_basis_eur=data["cost_basis_eur"],
            exit_time=data.get("exit_time"),
            exit_price=data.get("exit_price"),
            exit_slippage=data.get("exit_slippage"),
            exit_reason=data.get("exit_reason"),
            realized_pnl_eur=data.get("realized_pnl_eur"),
            pnl_pct=data.get("pnl_pct"),
        )


@dataclass(frozen=True)
class PaperTradeRecord:
    """
    Record of a paper trading action.

    GOVERNANCE:
    This represents a PAPER trade record only.
    Used for audit trail and analysis.
    """
    record_id: str
    timestamp: str  # ISO timestamp
    proposal_id: str
    market_id: str
    action: str  # "PAPER_ENTER", "PAPER_EXIT", "SKIP"
    reason: str  # Why this action was taken
    position_id: Optional[str]  # Associated position if any

    # Price information (only in paper logs, never in Layer 1)
    snapshot_time: Optional[str]
    entry_price: Optional[float]
    exit_price: Optional[float]
    slippage_applied: Optional[float]

    # Paper P&L
    pnl_eur: Optional[float]

    # Hardcoded governance notice
    governance_notice: str = field(
        default="This is a PAPER trade record. No real trade was executed.",
        init=False
    )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "record_id": self.record_id,
            "timestamp": self.timestamp,
            "proposal_id": self.proposal_id,
            "market_id": self.market_id,
            "action": self.action,
            "reason": self.reason,
            "position_id": self.position_id,
            "snapshot_time": self.snapshot_time,
            "entry_price": self.entry_price,
            "exit_price": self.exit_price,
            "slippage_applied": self.slippage_applied,
            "pnl_eur": self.pnl_eur,
            "governance_notice": self.governance_notice,
        }

    def to_json(self) -> str:
        """Serialize to JSON string (single line for JSONL)."""
        return json.dumps(self.to_dict(), ensure_ascii=False)


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================


def generate_position_id() -> str:
    """
    Generate a unique paper position ID.

    Format: PAPER-{date}-{short_uuid}
    """
    date_part = datetime.now().strftime("%Y%m%d")
    uuid_part = uuid.uuid4().hex[:8]
    return f"PAPER-{date_part}-{uuid_part}"


def generate_record_id() -> str:
    """
    Generate a unique paper trade record ID.

    Format: REC-{date}-{short_uuid}
    """
    date_part = datetime.now().strftime("%Y%m%d%H%M%S")
    uuid_part = uuid.uuid4().hex[:6]
    return f"REC-{date_part}-{uuid_part}"
