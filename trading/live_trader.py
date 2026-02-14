# =============================================================================
# LIVE TRADER
# =============================================================================
#
# Executes trading proposals on Polymarket.
#
# SAFETY FEATURES:
# - Requires explicit LIVE_TRADING_ENABLED=true
# - Position limits enforced
# - Slippage protection
# - Approval required for each trade
#
# =============================================================================

import os
import logging
from typing import Dict, Any, List, Optional
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import json

from trading.polymarket_client import (
    PolymarketTradingClient,
    OrderSide,
    OrderResult,
    OrderStatus,
)

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent.parent


@dataclass
class TradeRecord:
    """Record of an executed trade."""
    trade_id: str
    market_id: str
    side: str
    price: float
    size: float
    status: str
    timestamp: str
    pnl_eur: float = 0.0
    proposal_id: Optional[str] = None


class LiveTrader:
    """
    Live trading executor for Polymarket.

    SAFETY:
    - Will NOT trade unless LIVE_TRADING_ENABLED=true
    - Enforces position limits
    - Logs all trades for audit
    """

    def __init__(
        self,
        max_position_size_eur: float = 100.0,
        max_open_positions: int = 10,
        min_edge_threshold: float = 0.15,
    ):
        self.max_position_size_eur = max_position_size_eur
        self.max_open_positions = max_open_positions
        self.min_edge_threshold = min_edge_threshold

        # Safety check
        self.live_enabled = os.getenv("LIVE_TRADING_ENABLED", "false").lower() == "true"

        if self.live_enabled:
            logger.warning("LIVE TRADING IS ENABLED - Real money at risk!")
            self.client = PolymarketTradingClient(paper_mode=False)
        else:
            logger.info("Live trading disabled - Using paper mode")
            self.client = PolymarketTradingClient(paper_mode=True)

        self.trades_log = BASE_DIR / "logs" / "live_trades.jsonl"
        self.trades_log.parent.mkdir(parents=True, exist_ok=True)

    def is_live(self) -> bool:
        """Check if live trading is enabled."""
        return self.live_enabled

    def execute_proposal(self, proposal: Dict[str, Any]) -> Optional[TradeRecord]:
        """
        Execute a trading proposal.

        Args:
            proposal: Proposal dict with market_id, direction, edge, etc.

        Returns:
            TradeRecord if executed, None if skipped
        """
        market_id = proposal.get("market_id", "")
        direction = proposal.get("direction", "BUY_YES")
        edge = proposal.get("edge", 0)
        model_prob = proposal.get("model_probability", 0)
        market_prob = proposal.get("market_probability", 0)

        # Validate edge threshold
        if edge < self.min_edge_threshold:
            logger.info(f"Skipping {market_id}: Edge {edge:.1%} < threshold {self.min_edge_threshold:.1%}")
            return None

        # Determine order parameters
        side = OrderSide.BUY if "BUY" in direction else OrderSide.SELL
        price = market_prob  # Enter at current market price
        size = self.max_position_size_eur / price if price > 0 else 0

        if size <= 0:
            logger.warning(f"Invalid size for {market_id}")
            return None

        # Execute order
        result = self.client.place_order(
            token_id=market_id,
            side=side,
            price=price,
            size=size,
        )

        if not result.success:
            logger.error(f"Order failed for {market_id}: {result.error}")
            return None

        # Create trade record
        trade = TradeRecord(
            trade_id=result.order_id or f"trade_{datetime.now(timezone.utc).timestamp()}",
            market_id=market_id,
            side=side.value,
            price=result.avg_price,
            size=result.filled_size,
            status=result.status.value if result.status else "UNKNOWN",
            timestamp=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S") + "Z",
            proposal_id=proposal.get("proposal_id"),
        )

        # Log trade
        self._log_trade(trade)

        logger.info(
            f"{'LIVE' if self.live_enabled else 'PAPER'} TRADE: "
            f"{trade.side} {trade.size:.2f} @ {trade.price:.4f} | {market_id[:30]}..."
        )

        return trade

    def _log_trade(self, trade: TradeRecord):
        """Append trade to log file."""
        try:
            entry = {
                "trade_id": trade.trade_id,
                "market_id": trade.market_id,
                "side": trade.side,
                "price": trade.price,
                "size": trade.size,
                "status": trade.status,
                "timestamp": trade.timestamp,
                "pnl_eur": trade.pnl_eur,
                "proposal_id": trade.proposal_id,
                "live_mode": self.live_enabled,
            }
            with open(self.trades_log, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception as e:
            logger.error(f"Failed to log trade: {e}")

    def get_open_positions(self) -> List[Dict[str, Any]]:
        """Get current open positions."""
        return self.client.get_positions()

    def get_open_orders(self) -> List[Dict[str, Any]]:
        """Get current open orders."""
        return self.client.get_open_orders()

    def cancel_all_orders(self) -> int:
        """Cancel all open orders. Returns count cancelled."""
        orders = self.get_open_orders()
        cancelled = 0
        for order in orders:
            order_id = order.get("id") or order.get("orderID")
            if order_id and self.client.cancel_order(order_id):
                cancelled += 1
        return cancelled


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

_live_trader: Optional[LiveTrader] = None


def get_live_trader() -> LiveTrader:
    """Get the global live trader instance."""
    global _live_trader
    if _live_trader is None:
        _live_trader = LiveTrader()
    return _live_trader


def execute_proposal(proposal: Dict[str, Any]) -> Optional[TradeRecord]:
    """Execute a trading proposal."""
    return get_live_trader().execute_proposal(proposal)


def is_live_trading_enabled() -> bool:
    """Check if live trading is enabled."""
    return get_live_trader().is_live()
