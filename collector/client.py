# =============================================================================
# POLYMARKET EU AI COLLECTOR
# Module: collector/client.py
# Purpose: HTTP client for Polymarket Gamma API with retries and timeouts
# =============================================================================
#
# DESIGN:
# - Only uses official Polymarket Gamma API endpoints
# - Implements exponential backoff for retries
# - Clear error handling and logging
# - NO web scraping
#
# API REFERENCE:
# Base URL: https://gamma-api.polymarket.com
# Endpoints: /markets, /events
#
# =============================================================================

import time
import logging
from typing import List, Dict, Any, Optional
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError
from urllib.parse import urlencode
import json
import ssl

logger = logging.getLogger(__name__)


class PolymarketClient:
    """
    HTTP client for Polymarket Gamma API.

    Features:
    - Exponential backoff retry logic
    - Configurable timeouts
    - Pagination support
    - Clear error logging
    """

    BASE_URL = "https://gamma-api.polymarket.com"
    DEFAULT_TIMEOUT = 30  # seconds
    MAX_RETRIES = 3
    INITIAL_BACKOFF = 1.0  # seconds
    MAX_BACKOFF = 30.0  # seconds

    # Delay between paginated API requests (seconds)
    API_DELAY_SECONDS = 0.5
    # Delay between batch event fetches (seconds)
    BATCH_DELAY_SECONDS = 0.3

    def __init__(
        self,
        timeout: int = DEFAULT_TIMEOUT,
        max_retries: int = MAX_RETRIES,
    ):
        """
        Initialize the Polymarket API client.

        Args:
            timeout: Request timeout in seconds
            max_retries: Maximum number of retry attempts
        """
        self.timeout = timeout
        self.max_retries = max_retries

        # Create SSL context that works on Windows
        self.ssl_context = ssl.create_default_context()

    def fetch_markets(
        self,
        limit: int = 100,
        offset: int = 0,
        closed: Optional[bool] = None,
    ) -> List[Dict[str, Any]]:
        """
        Fetch markets from Polymarket Gamma API.

        Args:
            limit: Maximum number of markets to fetch (max 100 per request)
            offset: Pagination offset
            closed: Filter by closed status (None = all)

        Returns:
            List of raw market dictionaries from API

        Raises:
            RuntimeError: If all retry attempts fail
        """
        params = {
            "limit": min(limit, 100),  # API max is 100
            "offset": offset,
        }

        if closed is not None:
            params["closed"] = str(closed).lower()

        return self._request("/markets", params)

    def fetch_all_markets(
        self,
        max_markets: int = 200,
        closed: Optional[bool] = None,
    ) -> List[Dict[str, Any]]:
        """
        Fetch multiple pages of markets up to max_markets.

        Args:
            max_markets: Maximum total markets to fetch
            closed: Filter by closed status

        Returns:
            List of all fetched market dictionaries
        """
        all_markets = []
        offset = 0
        page_size = 100

        while len(all_markets) < max_markets:
            remaining = max_markets - len(all_markets)
            limit = min(page_size, remaining)

            logger.info(f"Fetching markets: offset={offset}, limit={limit}")

            markets = self.fetch_markets(
                limit=limit,
                offset=offset,
                closed=closed,
            )

            if not markets:
                logger.info("No more markets available")
                break

            all_markets.extend(markets)
            offset += len(markets)

            # Small delay between pages to be respectful
            time.sleep(self.API_DELAY_SECONDS)

            if len(markets) < limit:
                logger.info("Received fewer markets than requested - end of data")
                break

        logger.info(f"Total markets fetched: {len(all_markets)}")
        return all_markets

    def fetch_events(
        self,
        limit: int = 100,
        offset: int = 0,
        tag_slug: Optional[str] = None,
        closed: Optional[bool] = None,
    ) -> List[Dict[str, Any]]:
        """
        Fetch events from Polymarket Gamma API.

        Events contain grouped markets.

        Args:
            limit: Maximum number of events to fetch
            offset: Pagination offset
            tag_slug: Filter by tag (e.g., "weather", "climate")
            closed: Filter by closed status (None = all)

        Returns:
            List of raw event dictionaries from API
        """
        params = {
            "limit": min(limit, 100),
            "offset": offset,
        }

        if tag_slug:
            params["tag_slug"] = tag_slug

        if closed is not None:
            params["closed"] = str(closed).lower()

        return self._request("/events", params)

    def fetch_weather_markets(
        self,
        max_markets: int = 500,
        include_closed: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        Fetch weather-related markets from Polymarket.

        Weather markets are tagged with "weather" or "climate" on Polymarket.
        This method fetches events with these tags and extracts the markets.

        Args:
            max_markets: Maximum total markets to return
            include_closed: Whether to include closed markets

        Returns:
            List of market dictionaries from weather events
        """
        all_markets = []
        seen_ids = set()

        # Fetch from both weather and climate tags
        for tag in ["weather", "climate"]:
            offset = 0
            page_size = 100

            while len(all_markets) < max_markets:
                logger.info(f"Fetching {tag} events: offset={offset}")

                events = self.fetch_events(
                    limit=page_size,
                    offset=offset,
                    tag_slug=tag,
                    closed=None,  # Get all, filter later
                )

                if not events:
                    break

                # Extract markets from events
                for event in events:
                    event_closed = event.get("closed", False)
                    event_title = event.get("title", "")
                    event_tags = event.get("tags", [])
                    tag_labels = [
                        t.get("label", "") for t in event_tags
                        if isinstance(t, dict)
                    ]

                    markets = event.get("markets", [])
                    for market in markets:
                        market_id = market.get("id") or market.get("conditionId")
                        market_closed = market.get("closed", False)

                        # Skip if already seen
                        if market_id in seen_ids:
                            continue

                        # Skip closed markets if not requested
                        if not include_closed and (event_closed or market_closed):
                            continue

                        seen_ids.add(market_id)

                        # Enrich market with event metadata
                        market["_event_title"] = event_title
                        market["_event_tags"] = tag_labels
                        market["_source_tag"] = tag

                        all_markets.append(market)

                        if len(all_markets) >= max_markets:
                            break

                    if len(all_markets) >= max_markets:
                        break

                offset += len(events)
                time.sleep(self.BATCH_DELAY_SECONDS)  # Rate limiting

                if len(events) < page_size:
                    break

        logger.info(f"Total weather markets fetched: {len(all_markets)}")
        return all_markets

    def fetch_market_prices(
        self,
        market_ids: List[str],
    ) -> Dict[str, Dict[str, Any]]:
        """
        Fetch current prices/odds for specific markets.

        This is used by the Weather Engine to get live odds for edge calculation.
        Only fetches price data, no trade execution.

        Args:
            market_ids: List of market IDs to fetch prices for

        Returns:
            Dict mapping market_id to price data
        """
        prices = {}

        for market_id in market_ids:
            try:
                result = self._request(f"/markets/{market_id}")
                if result and isinstance(result, list) and len(result) > 0:
                    market = result[0]
                elif isinstance(result, dict):
                    market = result
                else:
                    continue

                prices[market_id] = {
                    "outcomePrices": market.get("outcomePrices"),
                    "bestBid": market.get("bestBid"),
                    "bestAsk": market.get("bestAsk"),
                    "lastTradePrice": market.get("lastTradePrice"),
                    "volume": market.get("volume"),
                    "liquidity": market.get("liquidity"),
                }

                time.sleep(0.2)

            except Exception as e:
                logger.warning(f"Failed to fetch prices for {market_id}: {e}")

        logger.info(f"Fetched prices for {len(prices)}/{len(market_ids)} markets")
        return prices

    def get_market_odds_yes(self, market_id: str) -> Optional[float]:
        """
        Get current YES odds for a specific market.

        Args:
            market_id: Market ID

        Returns:
            YES probability (0.0-1.0) or None if not available
        """
        prices = self.fetch_market_prices([market_id])
        if market_id not in prices:
            return None

        market_prices = prices[market_id]

        # Try outcomePrices first (format: '["0.95", "0.05"]')
        outcome_prices = market_prices.get("outcomePrices")
        if outcome_prices:
            try:
                prices_list = json.loads(outcome_prices)
                if len(prices_list) >= 1:
                    return float(prices_list[0])
            except (json.JSONDecodeError, ValueError, TypeError):
                pass

        # Fallback to lastTradePrice
        last_price = market_prices.get("lastTradePrice")
        if last_price:
            try:
                return float(last_price)
            except (ValueError, TypeError):
                pass

        return None

    def _request(
        self,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Make a GET request with retry logic.

        Args:
            endpoint: API endpoint path (e.g., "/markets")
            params: Query parameters

        Returns:
            Parsed JSON response (list of objects)

        Raises:
            RuntimeError: If all retry attempts fail
        """
        url = f"{self.BASE_URL}{endpoint}"
        if params:
            url = f"{url}?{urlencode(params)}"

        backoff = self.INITIAL_BACKOFF
        last_error = None

        for attempt in range(self.max_retries):
            try:
                logger.debug(f"Request attempt {attempt + 1}: {url}")

                request = Request(
                    url,
                    headers={
                        "User-Agent": "PolymarketEUCollector/1.0",
                        "Accept": "application/json",
                    },
                )

                with urlopen(
                    request,
                    timeout=self.timeout,
                    context=self.ssl_context,
                ) as response:
                    data = response.read().decode("utf-8")
                    result = json.loads(data)

                    # API may return list directly or wrapped in object
                    if isinstance(result, list):
                        return result
                    elif isinstance(result, dict):
                        # Check common wrapper keys
                        for key in ["data", "markets", "events", "results"]:
                            if key in result and isinstance(result[key], list):
                                return result[key]
                        # If it's a single object, wrap in list
                        return [result]
                    else:
                        logger.warning(f"Unexpected response type: {type(result)}")
                        return []

            except HTTPError as e:
                last_error = e
                logger.warning(
                    f"HTTP error {e.code} on attempt {attempt + 1}: {e.reason}"
                )

                # Don't retry client errors (4xx) except 429 (rate limit)
                if 400 <= e.code < 500 and e.code != 429:
                    raise RuntimeError(f"Client error: {e.code} {e.reason}")

            except URLError as e:
                last_error = e
                logger.warning(f"URL error on attempt {attempt + 1}: {e.reason}")

            except json.JSONDecodeError as e:
                last_error = e
                logger.warning(f"JSON decode error on attempt {attempt + 1}: {e}")

            except Exception as e:
                last_error = e
                logger.warning(f"Unexpected error on attempt {attempt + 1}: {e}")

            # Exponential backoff before retry
            if attempt < self.max_retries - 1:
                sleep_time = min(backoff, self.MAX_BACKOFF)
                logger.info(f"Retrying in {sleep_time:.1f}s...")
                time.sleep(sleep_time)
                backoff *= 2

        # All retries exhausted
        raise RuntimeError(
            f"All {self.max_retries} retry attempts failed. Last error: {last_error}"
        )
