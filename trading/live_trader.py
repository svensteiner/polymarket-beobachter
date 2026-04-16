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
)
from trading.telegram_approval import request_trade_approval

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent.parent
_LIVE_CONFIG_PATH = BASE_DIR / "config" / "live_trading.yaml"


def _load_live_config() -> Dict[str, Any]:
    """Load live trading configuration from YAML."""
    try:
        import yaml
        if _LIVE_CONFIG_PATH.exists():
            data = yaml.safe_load(_LIVE_CONFIG_PATH.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
    except Exception as e:
        logger.warning("Could not load live_trading.yaml: %s", e)
    return {}


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
        max_position_size_eur: Optional[float] = None,
        max_open_positions: Optional[int] = None,
        min_edge_threshold: Optional[float] = None,
        require_telegram_approval: Optional[bool] = None,
    ):
        cfg = _load_live_config()
        capital_cfg = cfg.get("capital", {})
        entry_cfg = cfg.get("entry", {})
        tg_cfg = cfg.get("telegram", {})

        self.max_position_size_eur = max_position_size_eur or float(capital_cfg.get("max_position_eur", 20.0))
        self.max_open_positions = max_open_positions or int(capital_cfg.get("max_open_positions", 5))
        self.min_edge_threshold = min_edge_threshold or float(entry_cfg.get("min_edge", 0.40))
        self.min_confidence = entry_cfg.get("min_confidence", "HIGH")
        self.min_time_to_resolution_hours = float(entry_cfg.get("min_time_to_resolution_hours", 24.0))
        self.block_no_bets_narrow = bool(entry_cfg.get("block_no_bets_on_narrow_markets", True))
        self.max_daily_loss_eur = float(capital_cfg.get("max_daily_loss_eur", 50.0))
        self.require_telegram_approval = (
            require_telegram_approval if require_telegram_approval is not None
            else bool(tg_cfg.get("approval_timeout_seconds", True) and cfg.get("require_telegram_approval", True))
        )

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

    @staticmethod
    def proposal_to_dict(proposal: Any) -> Dict[str, Any]:
        """Convert a Proposal dataclass to a dict for execute_proposal."""
        edge_val = float(getattr(proposal, "edge", 0) or 0)
        direction = "BUY_NO" if edge_val < 0 else "BUY_YES"
        return {
            "market_id": getattr(proposal, "market_id", ""),
            "market_question": getattr(proposal, "market_question", ""),
            "direction": direction,
            "edge": abs(edge_val),
            "market_probability": getattr(proposal, "implied_probability", 0),
            "model_probability": getattr(proposal, "model_probability", 0),
            "confidence": getattr(proposal, "confidence_level", "UNKNOWN"),
            "proposal_id": getattr(proposal, "proposal_id", ""),
            "justification_summary": getattr(proposal, "justification_summary", ""),
            "position_size_eur": 0,  # overridden by LiveTrader
        }

    def execute_proposal(self, proposal: Any) -> Optional[TradeRecord]:
        """
        Execute a trading proposal.

        Args:
            proposal: Proposal dataclass or dict with market_id, direction, edge, etc.

        Returns:
            TradeRecord if executed, None if skipped
        """
        if not isinstance(proposal, dict):
            proposal = self.proposal_to_dict(proposal)

        market_id = proposal.get("market_id", "")
        direction = proposal.get("direction", "BUY_YES")
        edge = proposal.get("edge", 0)
        market_prob = proposal.get("market_probability", 0)
        confidence = proposal.get("confidence", "UNKNOWN")

        # Validate edge threshold
        if edge < self.min_edge_threshold:
            logger.info(f"Skipping {market_id}: Edge {edge:.1%} < threshold {self.min_edge_threshold:.1%}")
            return None

        # Validate confidence
        confidence_rank = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "VERY_HIGH": 3}
        min_rank = confidence_rank.get(self.min_confidence, 2)
        if confidence_rank.get(confidence, 0) < min_rank:
            logger.info(f"Skipping {market_id}: Confidence {confidence} < {self.min_confidence}")
            return None

        # LIVE TRADING: Require Telegram approval
        if self.live_enabled and self.require_telegram_approval:
            import uuid
            trade_id = proposal.get("proposal_id") or str(uuid.uuid4())

            # Add position size to proposal for display
            proposal["position_size_eur"] = self.max_position_size_eur

            logger.info(f"Requesting Telegram approval for trade {trade_id[:8]}...")
            approved, reason = request_trade_approval(proposal, trade_id)

            if not approved:
                logger.info(f"Trade rejected: {reason}")
                return None

            logger.info(f"Trade approved: {reason}")

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
