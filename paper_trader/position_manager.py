# =============================================================================
# POLYMARKET BEOBACHTER - PAPER POSITION MANAGER
# =============================================================================
#
# GOVERNANCE INTENT:
# This module manages the lifecycle of paper positions.
# It tracks open positions and handles exit conditions.
#
# PAPER TRADING ONLY:
# All positions are simulated. No real funds are allocated.
#
# EXIT CONDITIONS:
# A) Resolution-based exit: Market resolves to YES/NO
# B) Time stop (optional): Exit after N days using current price
#
# =============================================================================

import sys
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Any

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from paper_trader.models import PaperPosition, MarketSnapshot
from paper_trader.logger import get_paper_logger
from paper_trader.snapshot_client import get_market_snapshots
from paper_trader.simulator import simulate_exit_resolution, simulate_exit_market


logger = logging.getLogger(__name__)


# =============================================================================
# POSITION MANAGER
# =============================================================================


class PositionManager:
    """
    Manages paper trading positions.

    GOVERNANCE:
    - Tracks open positions
    - Checks for resolution/exit conditions
    - No real positions are managed
    """

    def __init__(self):
        """Initialize the position manager."""
        self._paper_logger = get_paper_logger()

    def get_open_positions(self) -> List[PaperPosition]:
        """
        Get all currently open paper positions.

        Returns:
            List of open PaperPosition objects
        """
        return self._paper_logger.get_open_positions()

    def check_and_close_resolved(self) -> Dict[str, Any]:
        """
        Check open positions and close any that have resolved.

        GOVERNANCE:
        - Fetches current market snapshots
        - If market is resolved, exits position
        - No hindsight used - uses current resolution state

        Returns:
            Summary dictionary with counts and P&L
        """
        open_positions = self.get_open_positions()
        logger.info(f"Checking {len(open_positions)} open positions for resolution")

        if not open_positions:
            return {
                "checked": 0,
                "closed": 0,
                "still_open": 0,
                "total_pnl_eur": 0.0,
            }

        # Get snapshots for all open position markets
        market_ids = [p.market_id for p in open_positions]
        snapshots = get_market_snapshots(market_ids)

        closed_count = 0
        total_pnl = 0.0
        still_open = 0

        for position in open_positions:
            snapshot = snapshots.get(position.market_id)

            if snapshot is None:
                logger.debug(f"No snapshot for {position.market_id} - keeping open")
                still_open += 1
                continue

            if snapshot.is_resolved:
                # Close the position
                logger.info(
                    f"Market {position.market_id} resolved to {snapshot.resolved_outcome}"
                )
                closed_position, record = simulate_exit_resolution(position, snapshot)
                closed_count += 1

                if closed_position.realized_pnl_eur is not None:
                    total_pnl += closed_position.realized_pnl_eur
            else:
                still_open += 1

        summary = {
            "checked": len(open_positions),
            "closed": closed_count,
            "still_open": still_open,
            "total_pnl_eur": total_pnl,
        }

        logger.info(
            f"Position check complete: {closed_count} closed, "
            f"{still_open} still open, P&L: {total_pnl:+.2f} EUR"
        )

        return summary

    # Take-Profit / Stop-Loss thresholds
    TAKE_PROFIT_PCT = 0.15   # 15% gain
    STOP_LOSS_PCT = -0.25    # 25% loss

    def check_mid_trade_exits(self) -> Dict[str, Any]:
        """
        Check open positions for take-profit or stop-loss conditions.

        Compares current market price to entry price.
        Exits if unrealized P&L exceeds thresholds.

        Returns:
            Summary with counts and P&L
        """
        open_positions = self.get_open_positions()
        if not open_positions:
            return {"checked": 0, "take_profit": 0, "stop_loss": 0, "pnl_eur": 0.0}

        market_ids = [p.market_id for p in open_positions]
        snapshots = get_market_snapshots(market_ids)

        tp_count = 0
        sl_count = 0
        total_pnl = 0.0

        for position in open_positions:
            snapshot = snapshots.get(position.market_id)
            if snapshot is None or snapshot.mid_price is None:
                continue
            if snapshot.is_resolved:
                continue  # handled by check_and_close_resolved

            current_price = snapshot.mid_price
            entry_price = position.entry_price

            if entry_price <= 0:
                continue

            # Unrealized P&L as percentage
            # YES positions profit when price goes UP
            # NO positions profit when YES price goes DOWN
            if position.side == "NO":
                unrealized_pct = (entry_price - current_price) / entry_price
            else:
                unrealized_pct = (current_price - entry_price) / entry_price

            if unrealized_pct >= self.TAKE_PROFIT_PCT:
                reason = f"Take-Profit ({unrealized_pct:+.1%})"
                closed, record = simulate_exit_market(position, snapshot, reason)
                tp_count += 1
                if closed.realized_pnl_eur is not None:
                    total_pnl += closed.realized_pnl_eur
                logger.info(f"TP: {position.market_id} | {unrealized_pct:+.1%} | P&L: {closed.realized_pnl_eur:+.2f} EUR")

            elif unrealized_pct <= self.STOP_LOSS_PCT:
                reason = f"Stop-Loss ({unrealized_pct:+.1%})"
                closed, record = simulate_exit_market(position, snapshot, reason)
                sl_count += 1
                if closed.realized_pnl_eur is not None:
                    total_pnl += closed.realized_pnl_eur
                logger.info(f"SL: {position.market_id} | {unrealized_pct:+.1%} | P&L: {closed.realized_pnl_eur:+.2f} EUR")

        summary = {
            "checked": len(open_positions),
            "take_profit": tp_count,
            "stop_loss": sl_count,
            "pnl_eur": total_pnl,
        }

        if tp_count or sl_count:
            logger.info(f"Mid-trade exits: {tp_count} TP, {sl_count} SL, P&L: {total_pnl:+.2f} EUR")

        return summary

    def get_position_summary(self) -> Dict[str, Any]:
        """
        Get summary of all positions.

        Returns:
            Summary dictionary
        """
        all_positions = self._paper_logger.read_all_positions()

        # Build latest state for each position
        position_states: Dict[str, PaperPosition] = {}
        for pos in all_positions:
            position_states[pos.position_id] = pos

        # Count by status
        open_count = 0
        closed_count = 0
        resolved_count = 0
        total_pnl = 0.0
        total_cost = 0.0

        for pos in position_states.values():
            if pos.status == "OPEN":
                open_count += 1
                total_cost += pos.cost_basis_eur
            elif pos.status == "CLOSED":
                closed_count += 1
                if pos.realized_pnl_eur is not None:
                    total_pnl += pos.realized_pnl_eur
            elif pos.status == "RESOLVED":
                resolved_count += 1
                if pos.realized_pnl_eur is not None:
                    total_pnl += pos.realized_pnl_eur

        return {
            "total_positions": len(position_states),
            "open": open_count,
            "closed": closed_count,
            "resolved": resolved_count,
            "total_realized_pnl_eur": total_pnl,
            "open_cost_basis_eur": total_cost,
        }


# =============================================================================
# MODULE-LEVEL FUNCTIONS
# =============================================================================

_manager: Optional[PositionManager] = None


def get_position_manager() -> PositionManager:
    """Get the global position manager instance."""
    global _manager
    if _manager is None:
        _manager = PositionManager()
    return _manager


def get_open_positions() -> List[PaperPosition]:
    """Convenience function to get open positions."""
    return get_position_manager().get_open_positions()


def check_and_close_resolved() -> Dict[str, Any]:
    """Convenience function to check and close resolved positions."""
    return get_position_manager().check_and_close_resolved()


def check_mid_trade_exits() -> Dict[str, Any]:
    """Convenience function to check take-profit/stop-loss exits."""
    return get_position_manager().check_mid_trade_exits()


def get_position_summary() -> Dict[str, Any]:
    """Convenience function to get position summary."""
    return get_position_manager().get_position_summary()
