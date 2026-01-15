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
from paper_trader.simulator import simulate_exit_resolution


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


def get_position_summary() -> Dict[str, Any]:
    """Convenience function to get position summary."""
    return get_position_manager().get_position_summary()
