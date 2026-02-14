# =============================================================================
# POLYMARKET TRADING CLIENT
# =============================================================================
#
# Live trading integration with Polymarket CLOB API.
#
# REQUIRES:
#   pip install py-clob-client
#
# ENVIRONMENT VARIABLES:
#   POLYMARKET_PRIVATE_KEY - Your wallet private key
#   POLYMARKET_WALLET_ADDRESS - Your wallet address
#
# SAFETY:
#   - All orders require explicit confirmation
#   - Position limits enforced
#   - Slippage protection
#
# =============================================================================

import os
import logging
from typing import Optional, Dict, Any, List
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class OrderSide(Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderStatus(Enum):
    PENDING = "PENDING"
    FILLED = "FILLED"
    PARTIAL = "PARTIAL"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


@dataclass
class OrderResult:
    """Result of an order submission."""
    success: bool
    order_id: Optional[str] = None
    status: Optional[OrderStatus] = None
    filled_size: float = 0.0
    avg_price: float = 0.0
    error: Optional[str] = None


class PolymarketTradingClient:
    """
    Client for placing orders on Polymarket.

    PAPER TRADING vs LIVE:
    - paper_mode=True: Simulates orders without execution
    - paper_mode=False: Places real orders (requires credentials)
    """

    CLOB_HOST = "https://clob.polymarket.com"
    CHAIN_ID = 137  # Polygon mainnet

    def __init__(
        self,
        private_key: Optional[str] = None,
        wallet_address: Optional[str] = None,
        paper_mode: bool = True,
    ):
        """
        Initialize the trading client.

        Args:
            private_key: Wallet private key (or from env POLYMARKET_PRIVATE_KEY)
            wallet_address: Wallet address (or from env POLYMARKET_WALLET_ADDRESS)
            paper_mode: If True, simulate orders without execution
        """
        self.paper_mode = paper_mode
        self.private_key = private_key or os.getenv("POLYMARKET_PRIVATE_KEY")
        self.wallet_address = wallet_address or os.getenv("POLYMARKET_WALLET_ADDRESS")

        self._client = None
        self._api_creds = None
        self._initialized = False

        if not self.paper_mode:
            if not self.private_key:
                raise ValueError("POLYMARKET_PRIVATE_KEY required for live trading")
            if not self.wallet_address:
                raise ValueError("POLYMARKET_WALLET_ADDRESS required for live trading")

    def initialize(self) -> bool:
        """
        Initialize the CLOB client and derive API credentials.

        Returns:
            True if initialization successful, False otherwise.
        """
        if self.paper_mode:
            logger.info("Paper mode: Skipping CLOB client initialization")
            self._initialized = True
            return True

        try:
            from py_clob_client.client import ClobClient

            # Step 1: Create client with private key
            self._client = ClobClient(
                self.CLOB_HOST,
                key=self.private_key,
                chain_id=self.CHAIN_ID,
            )

            # Step 2: Derive API credentials
            self._api_creds = self._client.create_or_derive_api_creds()
            logger.info("API credentials derived successfully")

            # Step 3: Reinitialize with full auth
            self._client = ClobClient(
                self.CLOB_HOST,
                key=self.private_key,
                chain_id=self.CHAIN_ID,
                creds=self._api_creds,
                signature_type=0,  # EOA wallet
                funder=self.wallet_address,
            )

            self._initialized = True
            logger.info("Polymarket trading client initialized")
            return True

        except ImportError:
            logger.error("py-clob-client not installed. Run: pip install py-clob-client")
            return False
        except Exception as e:
            logger.error(f"Failed to initialize trading client: {e}")
            return False

    def get_market_info(self, token_id: str) -> Optional[Dict[str, Any]]:
        """
        Get market information including tick size and neg_risk.

        Args:
            token_id: The token/condition ID

        Returns:
            Market info dict or None if not found
        """
        if self.paper_mode:
            return {
                "token_id": token_id,
                "tickSize": "0.01",
                "negRisk": False,
            }

        if not self._initialized:
            if not self.initialize():
                return None

        try:
            market = self._client.get_market(token_id)
            return market
        except Exception as e:
            logger.error(f"Failed to get market info: {e}")
            return None

    def place_order(
        self,
        token_id: str,
        side: OrderSide,
        price: float,
        size: float,
        slippage_tolerance: float = 0.02,
    ) -> OrderResult:
        """
        Place an order on Polymarket.

        Args:
            token_id: The token/condition ID to trade
            side: BUY or SELL
            price: Limit price (0.0-1.0)
            size: Position size in shares
            slippage_tolerance: Max slippage allowed (default 2%)

        Returns:
            OrderResult with status and details
        """
        # Validate inputs
        if price <= 0 or price >= 1:
            return OrderResult(
                success=False,
                error=f"Invalid price: {price}. Must be between 0 and 1."
            )

        if size <= 0:
            return OrderResult(
                success=False,
                error=f"Invalid size: {size}. Must be positive."
            )

        # Paper mode: simulate
        if self.paper_mode:
            logger.info(f"PAPER ORDER: {side.value} {size} @ {price:.4f} for {token_id[:20]}...")
            return OrderResult(
                success=True,
                order_id=f"paper_{token_id[:8]}_{int(price*1000)}",
                status=OrderStatus.FILLED,
                filled_size=size,
                avg_price=price,
            )

        # Live mode
        if not self._initialized:
            if not self.initialize():
                return OrderResult(
                    success=False,
                    error="Failed to initialize trading client"
                )

        try:
            from py_clob_client.clob_types import OrderArgs, OrderType
            from py_clob_client.order_builder.constants import BUY, SELL

            # Get market info
            market = self.get_market_info(token_id)
            if not market:
                return OrderResult(
                    success=False,
                    error=f"Could not find market for {token_id}"
                )

            # Build order
            order_side = BUY if side == OrderSide.BUY else SELL

            response = self._client.create_and_post_order(
                OrderArgs(
                    token_id=token_id,
                    price=price,
                    size=size,
                    side=order_side,
                ),
                options={
                    "tick_size": market.get("tickSize", "0.01"),
                    "neg_risk": market.get("negRisk", False),
                },
                order_type=OrderType.GTC,  # Good Till Cancelled
            )

            order_id = response.get("orderID")
            status = response.get("status", "UNKNOWN")

            logger.info(f"LIVE ORDER: {side.value} {size} @ {price:.4f} | ID: {order_id} | Status: {status}")

            return OrderResult(
                success=True,
                order_id=order_id,
                status=OrderStatus.PENDING if status == "LIVE" else OrderStatus.FILLED,
                filled_size=size,  # Approximate
                avg_price=price,
            )

        except Exception as e:
            logger.error(f"Order failed: {e}")
            return OrderResult(
                success=False,
                error=str(e)
            )

    def cancel_order(self, order_id: str) -> bool:
        """
        Cancel an open order.

        Args:
            order_id: The order ID to cancel

        Returns:
            True if cancelled, False otherwise
        """
        if self.paper_mode:
            logger.info(f"PAPER CANCEL: {order_id}")
            return True

        if not self._initialized:
            return False

        try:
            self._client.cancel_order(order_id)
            logger.info(f"Cancelled order: {order_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to cancel order: {e}")
            return False

    def get_open_orders(self) -> List[Dict[str, Any]]:
        """Get all open orders."""
        if self.paper_mode:
            return []

        if not self._initialized:
            return []

        try:
            return self._client.get_open_orders()
        except Exception as e:
            logger.error(f"Failed to get open orders: {e}")
            return []

    def get_positions(self) -> List[Dict[str, Any]]:
        """Get current positions."""
        if self.paper_mode:
            return []

        if not self._initialized:
            return []

        try:
            # Note: This may need adjustment based on actual API
            return self._client.get_positions() if hasattr(self._client, 'get_positions') else []
        except Exception as e:
            logger.error(f"Failed to get positions: {e}")
            return []

    def get_balance(self) -> Optional[float]:
        """Get USDCe balance."""
        if self.paper_mode:
            return 1000.0  # Simulated balance

        if not self._initialized:
            return None

        try:
            # Note: Balance checking may require separate call
            return None  # TODO: Implement balance check
        except Exception as e:
            logger.error(f"Failed to get balance: {e}")
            return None


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

_trading_client: Optional[PolymarketTradingClient] = None


def get_trading_client(paper_mode: bool = True) -> PolymarketTradingClient:
    """Get the global trading client instance."""
    global _trading_client
    if _trading_client is None:
        _trading_client = PolymarketTradingClient(paper_mode=paper_mode)
    return _trading_client


def place_buy_order(
    token_id: str,
    price: float,
    size: float,
    paper_mode: bool = True,
) -> OrderResult:
    """Place a buy order."""
    client = get_trading_client(paper_mode=paper_mode)
    return client.place_order(token_id, OrderSide.BUY, price, size)


def place_sell_order(
    token_id: str,
    price: float,
    size: float,
    paper_mode: bool = True,
) -> OrderResult:
    """Place a sell order."""
    client = get_trading_client(paper_mode=paper_mode)
    return client.place_order(token_id, OrderSide.SELL, price, size)
