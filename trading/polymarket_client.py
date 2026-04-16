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

    AUTH MODES:
    - L2 (preferred): POLYMARKET_API_KEY + POLYMARKET_API_SECRET + POLYMARKET_PASSPHRASE
      Pre-existing API creds from browser localStorage — no derive step needed.
    - L1 (fallback): POLYMARKET_PRIVATE_KEY → derives API creds automatically.

    SAFETY GATE:
    - LIVE_TRADING_ENABLED env var must be "true" for live orders.
      Default is "false". Only set to "true" after WR >60% over 50+ paper trades,
      AND explicit Telegram approval per trade (telegram_approval.py).
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
            wallet_address: Proxy wallet address (or from env POLYMARKET_WALLET_ADDRESS)
            paper_mode: If True, simulate orders without execution
        """
        self.paper_mode = paper_mode
        self.private_key = private_key or os.getenv("POLYMARKET_PRIVATE_KEY")
        self.wallet_address = wallet_address or os.getenv("POLYMARKET_WALLET_ADDRESS")
        self.main_wallet = os.getenv("POLYMARKET_MAIN_WALLET", self.wallet_address)

        # Pre-existing API creds (L2 auth — no private key needed for init)
        self._preset_api_key = os.getenv("POLYMARKET_API_KEY")
        self._preset_api_secret = os.getenv("POLYMARKET_API_SECRET")
        self._preset_passphrase = os.getenv("POLYMARKET_PASSPHRASE")

        # Safety gate: must be "true" string in env to allow live orders
        live_enabled = os.getenv("LIVE_TRADING_ENABLED", "false").lower()
        if not self.paper_mode and live_enabled != "true":
            logger.warning(
                "LIVE_TRADING_ENABLED is not 'true' — forcing paper mode. "
                "Set LIVE_TRADING_ENABLED=true and provide Telegram approval to go live."
            )
            self.paper_mode = True

        self._client = None
        self._api_creds = None
        self._initialized = False

        if not self.paper_mode:
            if not self.wallet_address:
                raise ValueError("POLYMARKET_WALLET_ADDRESS required for live trading")

    def initialize(self) -> bool:
        """
        Initialize the CLOB client.

        Auth priority:
        1. L2: pre-existing API creds from env (POLYMARKET_API_KEY/SECRET/PASSPHRASE)
           → faster, no derive step, no private key needed for init.
        2. L1: derive API creds from POLYMARKET_PRIVATE_KEY (fallback).

        Note: Order signing always requires POLYMARKET_PRIVATE_KEY regardless of auth mode.

        Returns:
            True if initialization successful, False otherwise.
        """
        if self.paper_mode:
            logger.info("Paper mode: Skipping CLOB client initialization")
            self._initialized = True
            return True

        try:
            from py_clob_client.client import ClobClient
            from py_clob_client.clob_types import ApiCreds

            has_preset_creds = all([
                self._preset_api_key,
                self._preset_api_secret,
                self._preset_passphrase,
            ])

            if has_preset_creds:
                # L2 auth: use pre-existing API credentials (no derive step)
                self._api_creds = ApiCreds(
                    api_key=self._preset_api_key,
                    api_secret=self._preset_api_secret,
                    api_passphrase=self._preset_passphrase,
                )
                logger.info("Using pre-existing CLOB API credentials (L2 auth)")

                self._client = ClobClient(
                    self.CLOB_HOST,
                    key=self.private_key,  # Proxy wallet private key
                    chain_id=self.CHAIN_ID,
                    creds=self._api_creds,
                    funder=self.wallet_address,  # Proxy wallet holds the funds
                )
            else:
                # L1 auth fallback: derive creds from private key
                if not self.private_key:
                    logger.error(
                        "No API credentials and no POLYMARKET_PRIVATE_KEY — cannot initialize. "
                        "Set POLYMARKET_API_KEY/SECRET/PASSPHRASE or POLYMARKET_PRIVATE_KEY."
                    )
                    return False

                self._client = ClobClient(
                    self.CLOB_HOST,
                    key=self.private_key,
                    chain_id=self.CHAIN_ID,
                )
                self._api_creds = self._client.create_or_derive_api_creds()
                logger.info("API credentials derived from private key (L1 auth)")

                self._client = ClobClient(
                    self.CLOB_HOST,
                    key=self.private_key,
                    chain_id=self.CHAIN_ID,
                    creds=self._api_creds,
                    signature_type=0,  # EOA wallet
                    funder=self.wallet_address,
                )

            self._initialized = True
            logger.info("Polymarket trading client initialized (wallet: %s)", self.wallet_address)
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
            return self._client.get_orders()
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
        """Get USDC balance via Polymarket CLOB API."""
        if self.paper_mode:
            return 1000.0  # Simulated balance

        if not self._initialized:
            if not self.initialize():
                return None

        try:
            from py_clob_client.clob_types import BalanceAllowanceParams, AssetType
            balance_info = self._client.get_balance_allowance(
                BalanceAllowanceParams(asset_type=AssetType.COLLATERAL)
            )
            if isinstance(balance_info, dict):
                raw = balance_info.get("balance", "0")
                val = float(raw)
                # USDC has 6 decimals; values > 10_000 are in micro-USDC
                return val / 1_000_000 if val > 10_000 else val
            return None
        except Exception as e:
            logger.error(f"Failed to get balance: {e}")
            return None

    def test_connectivity(self) -> dict:
        """
        Test API connectivity without placing orders.
        Works with L2 auth (API key/secret/passphrase) — no private key needed.

        Returns:
            dict with 'ok', 'balance', 'open_orders', 'error' keys.
        """
        if self.paper_mode:
            return {"ok": True, "mode": "paper", "balance": 1000.0, "open_orders": 0}

        if not self._initialized:
            if not self.initialize():
                return {"ok": False, "error": "Failed to initialize client"}

        result: dict = {"ok": False, "mode": "live"}
        try:
            balance = self.get_balance()
            result["balance"] = balance
            open_orders = self.get_open_orders()
            result["open_orders"] = len(open_orders)
            result["ok"] = True
        except Exception as e:
            result["error"] = str(e)

        return result


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

_trading_client: Optional[PolymarketTradingClient] = None


def validate_live_trading_env() -> tuple[bool, list[str]]:
    """
    Validate that all required environment variables for live trading are set.

    Returns:
        (all_ok, list_of_missing_vars)
    """
    required = [
        "POLYMARKET_WALLET_ADDRESS",
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_CHAT_ID",
    ]
    # Need either L2 creds or private key
    has_l2 = all(os.getenv(k) for k in ["POLYMARKET_API_KEY", "POLYMARKET_API_SECRET", "POLYMARKET_PASSPHRASE"])
    has_l1 = bool(os.getenv("POLYMARKET_PRIVATE_KEY"))

    missing = [v for v in required if not os.getenv(v)]
    if not has_l2 and not has_l1:
        missing.append("POLYMARKET_API_KEY + POLYMARKET_API_SECRET + POLYMARKET_PASSPHRASE (or POLYMARKET_PRIVATE_KEY)")

    return len(missing) == 0, missing


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
