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
            time.sleep(0.5)

            if len(markets) < limit:
                logger.info("Received fewer markets than requested - end of data")
                break

        logger.info(f"Total markets fetched: {len(all_markets)}")
        return all_markets

    def fetch_events(
        self,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """
        Fetch events from Polymarket Gamma API.

        Events contain grouped markets.

        Args:
            limit: Maximum number of events to fetch
            offset: Pagination offset

        Returns:
            List of raw event dictionaries from API
        """
        params = {
            "limit": min(limit, 100),
            "offset": offset,
        }

        return self._request("/events", params)

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
