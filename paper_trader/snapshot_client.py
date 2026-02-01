# =============================================================================
# POLYMARKET BEOBACHTER - MARKET SNAPSHOT CLIENT
# =============================================================================
#
# GOVERNANCE INTENT:
# This module fetches price snapshots using Layer 2 infrastructure.
# It provides READ-ONLY access to market price data.
#
# LAYER ISOLATION:
# - This module uses collector/client.py (shared infrastructure)
# - Price data is used for PAPER TRADING ONLY
# - Price data NEVER flows back to Layer 1
#
# DATA FLOW:
#   Polymarket API → collector/client → snapshot_client → paper_trader logs
#   ❌ NO FLOW to core_analyzer (Layer 1)
#
# =============================================================================

import sys
import json
import logging
import ssl
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError
from urllib.parse import urlencode, quote

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from collector.client import PolymarketClient
from paper_trader.models import MarketSnapshot, LiquidityBucket

logger = logging.getLogger(__name__)


# =============================================================================
# LIQUIDITY CLASSIFICATION
# =============================================================================

# Spread thresholds for liquidity bucketing (percentage)
SPREAD_HIGH_THRESHOLD = 2.0    # < 2% spread = HIGH liquidity
SPREAD_MEDIUM_THRESHOLD = 5.0  # 2-5% spread = MEDIUM liquidity
# > 5% spread = LOW liquidity


def classify_liquidity(spread_pct: Optional[float]) -> str:
    """
    Classify market liquidity based on spread.

    Args:
        spread_pct: Bid-ask spread as percentage

    Returns:
        LiquidityBucket value string
    """
    if spread_pct is None:
        return LiquidityBucket.UNKNOWN.value

    if spread_pct < SPREAD_HIGH_THRESHOLD:
        return LiquidityBucket.HIGH.value
    elif spread_pct < SPREAD_MEDIUM_THRESHOLD:
        return LiquidityBucket.MEDIUM.value
    else:
        return LiquidityBucket.LOW.value


# =============================================================================
# SNAPSHOT CLIENT
# =============================================================================


class MarketSnapshotClient:
    """
    Read-only client for fetching market price snapshots.

    GOVERNANCE:
    - This client is READ-ONLY
    - It does NOT place orders
    - It does NOT modify any state
    - Price data is for paper trading simulation ONLY

    LAYER ISOLATION:
    - Uses collector/client.py (shared infrastructure)
    - Output is used ONLY in paper_trader logs
    - NEVER feeds back to Layer 1 (core_analyzer)
    """

    GAMMA_API_BASE = "https://gamma-api.polymarket.com"

    def __init__(self, timeout: int = 30, max_retries: int = 3):
        """
        Initialize the snapshot client.

        Args:
            timeout: Request timeout in seconds
            max_retries: Maximum retry attempts
        """
        self._client = PolymarketClient(
            timeout=timeout,
            max_retries=max_retries
        )
        self._timeout = timeout
        self._ssl_context = ssl.create_default_context()
        logger.info("MarketSnapshotClient initialized (READ-ONLY, Gamma API)")

    def _fetch_gamma_market(self, market_id: str) -> Optional[Dict[str, Any]]:
        """
        Fetch a single market directly from Gamma API.

        Args:
            market_id: The market/condition ID

        Returns:
            Market data dict or None
        """
        # Try fetching by condition_id (slug-based lookup)
        url = f"{self.GAMMA_API_BASE}/markets?id={quote(market_id)}&limit=1"
        try:
            request = Request(url, headers={
                "User-Agent": "PolymarketBeobachter/2.0",
                "Accept": "application/json",
            })
            with urlopen(request, timeout=self._timeout, context=self._ssl_context) as response:
                data = json.loads(response.read().decode("utf-8"))
                if isinstance(data, list) and data:
                    return data[0]
                elif isinstance(data, dict):
                    return data
        except Exception as e:
            logger.debug(f"Gamma API direct fetch failed for {market_id}: {e}")
        return None

    def _fetch_gamma_markets_batch(self, market_ids: List[str]) -> Dict[str, Dict[str, Any]]:
        """
        Fetch multiple markets from Gamma API.

        Args:
            market_ids: List of market IDs

        Returns:
            Dict mapping market_id to market data
        """
        results = {}
        # Gamma API supports filtering - fetch in batches
        try:
            all_markets = self._client.fetch_all_markets(max_markets=500)
            for m in all_markets:
                mid = m.get("id") or m.get("condition_id") or ""
                if mid in market_ids:
                    results[mid] = m
        except Exception as e:
            logger.debug(f"Gamma batch fetch failed: {e}")
        return results

    def get_snapshot(self, market_id: str) -> Optional[MarketSnapshot]:
        """
        Get a price snapshot for a specific market.

        Uses Gamma API directly for real outcomePrices, volume, liquidity.
        Falls back to paginated fetch if direct lookup fails.

        GOVERNANCE:
        This is a READ-ONLY operation.
        The snapshot is used for paper trading simulation ONLY.

        Args:
            market_id: The market ID to fetch

        Returns:
            MarketSnapshot if available, None otherwise
        """
        try:
            # Try direct Gamma API fetch first (fast, single market)
            market_data = self._fetch_gamma_market(market_id)

            if market_data is None:
                # Fallback: search in paginated fetch
                markets = self._client.fetch_markets(limit=100)
                for market in markets:
                    if market.get("id") == market_id or market.get("condition_id") == market_id:
                        market_data = market
                        break

            if market_data is None:
                logger.warning(f"Market not found: {market_id}")
                return None

            return self._create_snapshot(market_data)

        except ConnectionError as e:
            logger.warning(f"Network error getting snapshot for {market_id}: {e} (transient)")
            return None
        except TimeoutError as e:
            logger.warning(f"Timeout getting snapshot for {market_id}: {e} (transient)")
            return None
        except ValueError as e:
            logger.error(f"Data parsing error for {market_id}: {e} (permanent)")
            return None
        except Exception as e:
            logger.error(f"Unexpected error getting snapshot for {market_id}: {e}", exc_info=True)
            return None

    def get_snapshots_batch(
        self,
        market_ids: List[str]
    ) -> Dict[str, Optional[MarketSnapshot]]:
        """
        Get price snapshots for multiple markets efficiently.

        Args:
            market_ids: List of market IDs to fetch

        Returns:
            Dictionary mapping market_id to MarketSnapshot (or None)
        """
        results = {}

        try:
            # Fetch all markets at once
            markets = self._client.fetch_all_markets(max_markets=500)

            # Create lookup
            market_lookup = {m.get("id"): m for m in markets}

            # Create snapshots
            for market_id in market_ids:
                market_data = market_lookup.get(market_id)
                if market_data:
                    results[market_id] = self._create_snapshot(market_data)
                else:
                    results[market_id] = None
                    logger.debug(f"Market not found in batch: {market_id}")

        except ConnectionError as e:
            logger.warning(f"Network error in batch snapshots: {e} (transient)")
            for market_id in market_ids:
                results[market_id] = None
        except TimeoutError as e:
            logger.warning(f"Timeout in batch snapshots: {e} (transient)")
            for market_id in market_ids:
                results[market_id] = None
        except Exception as e:
            logger.error(f"Unexpected error in batch snapshots: {e}", exc_info=True)
            for market_id in market_ids:
                results[market_id] = None

        return results

    def _create_snapshot(self, market_data: Dict[str, Any]) -> MarketSnapshot:
        """
        Create a MarketSnapshot from raw API data.

        Handles Gamma API fields: outcomePrices, volume, liquidity.

        Args:
            market_data: Raw market data from API

        Returns:
            MarketSnapshot object
        """
        market_id = market_data.get("id", "") or market_data.get("condition_id", "")

        # Extract prices - try outcomePrices first (Gamma API format)
        best_bid = None
        best_ask = None
        mid_price = None

        outcome_prices = market_data.get("outcomePrices")
        if outcome_prices:
            try:
                if isinstance(outcome_prices, str):
                    # Gamma API returns JSON string like "[0.55, 0.45]"
                    prices = json.loads(outcome_prices)
                elif isinstance(outcome_prices, list):
                    prices = outcome_prices
                else:
                    prices = None

                if prices and len(prices) >= 1:
                    yes_price = float(prices[0])
                    # Use YES price as mid price, simulate spread
                    mid_price = yes_price
                    best_bid = max(0.01, yes_price - 0.01)
                    best_ask = min(0.99, yes_price + 0.01)
            except (json.JSONDecodeError, ValueError, TypeError) as e:
                logger.debug(f"Could not parse outcomePrices: {e}")

        # Fallback to bestBid/bestAsk fields
        if best_bid is None:
            best_bid = self._extract_price(market_data, ["bestBid", "best_bid", "bid"])
        if best_ask is None:
            best_ask = self._extract_price(market_data, ["bestAsk", "best_ask", "ask"])

        # Calculate mid price from bid/ask if not set
        if mid_price is None and best_bid is not None and best_ask is not None:
            mid_price = (best_bid + best_ask) / 2

        # Final fallback
        if mid_price is None:
            mid_price = self._extract_price(
                market_data,
                ["price", "lastTradePrice"]
            )

        # Calculate spread
        if best_bid is not None and best_ask is not None and mid_price and mid_price > 0:
            spread_pct = ((best_ask - best_bid) / mid_price) * 100
        else:
            spread_pct = None

        # Classify liquidity
        liquidity_bucket = classify_liquidity(spread_pct)

        # Check resolution status
        is_resolved = market_data.get("closed", False) or market_data.get("resolved", False)
        resolved_outcome = None

        if is_resolved:
            # Try to determine outcome
            outcome = market_data.get("outcome", market_data.get("resolution"))
            if outcome in ["Yes", "YES", "1", 1, True]:
                resolved_outcome = "YES"
            elif outcome in ["No", "NO", "0", 0, False]:
                resolved_outcome = "NO"

        return MarketSnapshot(
            market_id=market_id,
            snapshot_time=datetime.now().isoformat(),
            best_bid=best_bid,
            best_ask=best_ask,
            mid_price=mid_price,
            spread_pct=spread_pct,
            liquidity_bucket=liquidity_bucket,
            is_resolved=is_resolved,
            resolved_outcome=resolved_outcome,
        )

    def _extract_price(
        self,
        data: Dict[str, Any],
        field_names: List[str]
    ) -> Optional[float]:
        """
        Extract price from data, trying multiple field names.

        Args:
            data: Raw data dictionary
            field_names: List of field names to try

        Returns:
            Price as float, or None if not found
        """
        for name in field_names:
            value = data.get(name)
            if value is not None:
                try:
                    if isinstance(value, (int, float)):
                        return float(value)
                    elif isinstance(value, str):
                        return float(value)
                    elif isinstance(value, list) and len(value) > 0:
                        # Some APIs return [yes_price, no_price]
                        return float(value[0])
                except (ValueError, TypeError):
                    continue
        return None


# =============================================================================
# MODULE-LEVEL CLIENT
# =============================================================================

_snapshot_client: Optional[MarketSnapshotClient] = None


def get_snapshot_client() -> MarketSnapshotClient:
    """Get the global snapshot client instance."""
    global _snapshot_client
    if _snapshot_client is None:
        _snapshot_client = MarketSnapshotClient()
    return _snapshot_client


def get_market_snapshot(market_id: str) -> Optional[MarketSnapshot]:
    """Convenience function to get a single market snapshot."""
    return get_snapshot_client().get_snapshot(market_id)


def get_market_snapshots(market_ids: List[str]) -> Dict[str, Optional[MarketSnapshot]]:
    """Convenience function to get multiple market snapshots."""
    return get_snapshot_client().get_snapshots_batch(market_ids)
