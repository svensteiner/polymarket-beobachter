# =============================================================================
# POLYMARKET BEOBACHTER - PAPER TRADING SIMULATOR
# =============================================================================
#
# GOVERNANCE INTENT:
# This module simulates trade entry and exit for paper trading.
# NO real orders are placed. NO funds are at risk.
#
# SIMULATION PRINCIPLES:
# - Never use hindsight
# - Never pick best price
# - Always apply conservative slippage
# - If market snapshot is unavailable, SKIP with reason
#
# PAPER TRADING ONLY:
# All execution is simulated. This module has NO access to:
# - Trading endpoints
# - Wallet functions
# - Order placement APIs
#
# =============================================================================

import sys
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple, Final

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from proposals.models import Proposal

from paper_trader.models import (
    PaperPosition,
    PaperTradeRecord,
    MarketSnapshot,
    TradeAction,
    generate_position_id,
    generate_record_id,
)
from paper_trader.slippage import calculate_entry_price, calculate_exit_price
from paper_trader.snapshot_client import get_market_snapshot
from paper_trader.logger import get_paper_logger, log_trade, log_position


logger = logging.getLogger(__name__)


# =============================================================================
# CONSTANTS
# =============================================================================

# Fixed paper trading amount in EUR
FIXED_AMOUNT_EUR: Final[float] = 100.0


# =============================================================================
# EXECUTION SIMULATOR
# =============================================================================


class ExecutionSimulator:
    """
    Simulates trade entry and exit for paper trading.

    GOVERNANCE:
    - NO real orders are placed
    - NO real funds are at risk
    - All execution is simulated with conservative slippage
    - If data is unavailable, SKIP with documented reason
    """

    def __init__(self, fixed_amount_eur: float = FIXED_AMOUNT_EUR):
        """
        Initialize the simulator.

        Args:
            fixed_amount_eur: Fixed paper trading amount per trade
        """
        self.fixed_amount_eur = fixed_amount_eur
        self._paper_logger = get_paper_logger()

    def simulate_entry(
        self,
        proposal: Proposal
    ) -> Tuple[Optional[PaperPosition], PaperTradeRecord]:
        """
        Simulate entering a paper position.

        GOVERNANCE:
        - Uses current market snapshot (no hindsight)
        - Applies conservative slippage
        - If snapshot unavailable, returns SKIP record

        Args:
            proposal: The proposal to simulate entry for

        Returns:
            Tuple of (PaperPosition or None, PaperTradeRecord)
            Position is None if entry was skipped.
        """
        now = datetime.now().isoformat()

        # Get market snapshot
        snapshot = get_market_snapshot(proposal.market_id)

        if snapshot is None:
            # SKIP: No snapshot available
            record = PaperTradeRecord(
                record_id=generate_record_id(),
                timestamp=now,
                proposal_id=proposal.proposal_id,
                market_id=proposal.market_id,
                action=TradeAction.SKIP.value,
                reason="Market snapshot unavailable - cannot simulate entry",
                position_id=None,
                snapshot_time=None,
                entry_price=None,
                exit_price=None,
                slippage_applied=None,
                pnl_eur=None,
            )
            log_trade(record)
            logger.warning(f"SKIP: No snapshot for {proposal.market_id}")
            return (None, record)

        if not snapshot.has_valid_prices():
            # SKIP: No valid prices
            record = PaperTradeRecord(
                record_id=generate_record_id(),
                timestamp=now,
                proposal_id=proposal.proposal_id,
                market_id=proposal.market_id,
                action=TradeAction.SKIP.value,
                reason="Market snapshot has no valid prices - cannot simulate entry",
                position_id=None,
                snapshot_time=snapshot.snapshot_time,
                entry_price=None,
                exit_price=None,
                slippage_applied=None,
                pnl_eur=None,
            )
            log_trade(record)
            logger.warning(f"SKIP: No valid prices for {proposal.market_id}")
            return (None, record)

        if snapshot.is_resolved:
            # SKIP: Market already resolved
            record = PaperTradeRecord(
                record_id=generate_record_id(),
                timestamp=now,
                proposal_id=proposal.proposal_id,
                market_id=proposal.market_id,
                action=TradeAction.SKIP.value,
                reason=f"Market already resolved ({snapshot.resolved_outcome}) - cannot enter",
                position_id=None,
                snapshot_time=snapshot.snapshot_time,
                entry_price=None,
                exit_price=None,
                slippage_applied=None,
                pnl_eur=None,
            )
            log_trade(record)
            logger.warning(f"SKIP: Market {proposal.market_id} already resolved")
            return (None, record)

        # Determine side based on edge direction
        # Positive edge (model > implied) = buy YES
        # Negative edge (model < implied) = buy NO
        side = "YES" if proposal.edge > 0 else "NO"

        # Calculate entry price with slippage
        price_result = calculate_entry_price(snapshot, side)

        if price_result is None:
            # SKIP: Cannot calculate entry price
            record = PaperTradeRecord(
                record_id=generate_record_id(),
                timestamp=now,
                proposal_id=proposal.proposal_id,
                market_id=proposal.market_id,
                action=TradeAction.SKIP.value,
                reason="Cannot calculate entry price with slippage",
                position_id=None,
                snapshot_time=snapshot.snapshot_time,
                entry_price=None,
                exit_price=None,
                slippage_applied=None,
                pnl_eur=None,
            )
            log_trade(record)
            logger.warning(f"SKIP: Cannot calculate entry price for {proposal.market_id}")
            return (None, record)

        entry_price, slippage_applied = price_result

        # Calculate position size
        # In prediction markets: price is probability, contracts pay $1 if correct
        # Size = amount / price
        size_contracts = self.fixed_amount_eur / entry_price

        # Create paper position
        position_id = generate_position_id()
        position = PaperPosition(
            position_id=position_id,
            proposal_id=proposal.proposal_id,
            market_id=proposal.market_id,
            market_question=proposal.market_question,
            side=side,
            status="OPEN",
            entry_time=now,
            entry_price=entry_price,
            entry_slippage=slippage_applied,
            size_contracts=size_contracts,
            cost_basis_eur=self.fixed_amount_eur,
            exit_time=None,
            exit_price=None,
            exit_slippage=None,
            exit_reason=None,
            realized_pnl_eur=None,
            pnl_pct=None,
        )

        # Create trade record
        record = PaperTradeRecord(
            record_id=generate_record_id(),
            timestamp=now,
            proposal_id=proposal.proposal_id,
            market_id=proposal.market_id,
            action=TradeAction.PAPER_ENTER.value,
            reason=f"Paper entry: {side} at {entry_price:.4f} ({size_contracts:.2f} contracts)",
            position_id=position_id,
            snapshot_time=snapshot.snapshot_time,
            entry_price=entry_price,
            exit_price=None,
            slippage_applied=slippage_applied,
            pnl_eur=None,
        )

        # Log both
        log_position(position)
        log_trade(record)

        logger.info(
            f"PAPER_ENTER: {proposal.market_id} | {side} @ {entry_price:.4f} | "
            f"{size_contracts:.2f} contracts | slippage: {slippage_applied:.4f}"
        )

        return (position, record)

    def simulate_exit_resolution(
        self,
        position: PaperPosition,
        snapshot: MarketSnapshot
    ) -> Tuple[PaperPosition, PaperTradeRecord]:
        """
        Simulate exit due to market resolution.

        GOVERNANCE:
        - Uses resolution outcome (no hindsight on timing)
        - Pays 1.0 for winning side, 0.0 for losing side
        - No slippage on resolution

        Args:
            position: The open position to close
            snapshot: Market snapshot showing resolution

        Returns:
            Tuple of (closed PaperPosition, PaperTradeRecord)
        """
        now = datetime.now().isoformat()

        # Calculate exit price based on resolution
        exit_result = calculate_exit_price(snapshot, position.side, is_resolution=True)

        if exit_result is None:
            # Should not happen for resolved markets, but handle gracefully
            exit_price = 0.5  # Assume 50/50 as fallback
            exit_slippage = 0.0
        else:
            exit_price, exit_slippage = exit_result

        # Calculate P&L
        # Revenue = size * exit_price
        revenue_eur = position.size_contracts * exit_price
        realized_pnl = revenue_eur - position.cost_basis_eur
        pnl_pct = (realized_pnl / position.cost_basis_eur) * 100

        # Create closed position
        closed_position = PaperPosition(
            position_id=position.position_id,
            proposal_id=position.proposal_id,
            market_id=position.market_id,
            market_question=position.market_question,
            side=position.side,
            status="RESOLVED",
            entry_time=position.entry_time,
            entry_price=position.entry_price,
            entry_slippage=position.entry_slippage,
            size_contracts=position.size_contracts,
            cost_basis_eur=position.cost_basis_eur,
            exit_time=now,
            exit_price=exit_price,
            exit_slippage=exit_slippage,
            exit_reason=f"Market resolved: {snapshot.resolved_outcome}",
            realized_pnl_eur=realized_pnl,
            pnl_pct=pnl_pct,
        )

        # Create trade record
        record = PaperTradeRecord(
            record_id=generate_record_id(),
            timestamp=now,
            proposal_id=position.proposal_id,
            market_id=position.market_id,
            action=TradeAction.PAPER_EXIT.value,
            reason=f"Resolution exit: {snapshot.resolved_outcome} | P&L: {realized_pnl:+.2f} EUR",
            position_id=position.position_id,
            snapshot_time=snapshot.snapshot_time,
            entry_price=position.entry_price,
            exit_price=exit_price,
            slippage_applied=exit_slippage,
            pnl_eur=realized_pnl,
        )

        # Log both
        log_position(closed_position)
        log_trade(record)

        logger.info(
            f"PAPER_EXIT (RESOLVED): {position.market_id} | {position.side} | "
            f"exit @ {exit_price:.4f} | P&L: {realized_pnl:+.2f} EUR ({pnl_pct:+.1f}%)"
        )

        return (closed_position, record)


# =============================================================================
# MODULE-LEVEL FUNCTIONS
# =============================================================================

_simulator: Optional[ExecutionSimulator] = None


def get_simulator() -> ExecutionSimulator:
    """Get the global simulator instance."""
    global _simulator
    if _simulator is None:
        _simulator = ExecutionSimulator()
    return _simulator


def simulate_entry(proposal: Proposal) -> Tuple[Optional[PaperPosition], PaperTradeRecord]:
    """Convenience function to simulate entry."""
    return get_simulator().simulate_entry(proposal)


def simulate_exit_resolution(
    position: PaperPosition,
    snapshot: MarketSnapshot
) -> Tuple[PaperPosition, PaperTradeRecord]:
    """Convenience function to simulate resolution exit."""
    return get_simulator().simulate_exit_resolution(position, snapshot)
