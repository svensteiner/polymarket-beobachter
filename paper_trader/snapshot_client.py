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
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List

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
        logger.info("MarketSnapshotClient initialized (READ-ONLY)")

    def get_snapshot(self, market_id: str) -> Optional[MarketSnapshot]:
        """
        Get a price snapshot for a specific market.

        GOVERNANCE:
        This is a READ-ONLY operation.
        The snapshot is used for paper trading simulation ONLY.

        Args:
            market_id: The market ID to fetch

        Returns:
            MarketSnapshot if available, None otherwise
        """
        try:
            # Fetch market data
            markets = self._client.fetch_markets(limit=100)

            # Find the specific market
            market_data = None
            for market in markets:
                if market.get("id") == market_id:
                    market_data = market
                    break

            if market_data is None:
                logger.warning(f"Market not found: {market_id}")
                return None

            return self._create_snapshot(market_data)

        except Exception as e:
            logger.error(f"Failed to get snapshot for {market_id}: {e}")
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

        except Exception as e:
            logger.error(f"Failed to get batch snapshots: {e}")
            # Return None for all
            for market_id in market_ids:
                results[market_id] = None

        return results

    def _create_snapshot(self, market_data: Dict[str, Any]) -> MarketSnapshot:
        """
        Create a MarketSnapshot from raw API data.

        Args:
            market_data: Raw market data from API

        Returns:
            MarketSnapshot object
        """
        market_id = market_data.get("id", "")

        # Extract prices
        # API may have different field names - try multiple
        best_bid = self._extract_price(market_data, ["bestBid", "best_bid", "bid"])
        best_ask = self._extract_price(market_data, ["bestAsk", "best_ask", "ask"])

        # Calculate mid price
        if best_bid is not None and best_ask is not None:
            mid_price = (best_bid + best_ask) / 2
            spread_pct = ((best_ask - best_bid) / mid_price) * 100
        else:
            # Try to get price from other fields
            mid_price = self._extract_price(
                market_data,
                ["price", "lastTradePrice", "outcomePrices"]
            )
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
