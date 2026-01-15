# =============================================================================
# POLYMARKET EU AI COLLECTOR
# Module: collector/sanitizer.py
# Purpose: Strip forbidden fields (prices, volumes, probabilities) from API data
# =============================================================================
#
# ABSOLUTE EXCLUSIONS:
# - price, lastTradePrice, bestBid, bestAsk
# - volume, volume24hr, volume1wk, volume1mo, volume1yr (all variants)
# - liquidity, liquidityNum, liquidityAmm, liquidityClob
# - outcomePrices, impliedProbability
# - Any numeric market probability field
#
# DESIGN:
# - Recursively sanitizes nested structures
# - Deterministic: same input => same output
# - Logs all removed fields for audit trail
#
# =============================================================================

import logging
import re
from typing import Dict, Any, List, Set, Tuple
from copy import deepcopy

logger = logging.getLogger(__name__)


class Sanitizer:
    """
    Sanitizes raw API responses by removing forbidden fields.

    Ensures that price, volume, liquidity, and probability data
    is NEVER stored, even if present in API responses.
    """

    # =========================================================================
    # FORBIDDEN FIELD PATTERNS
    # =========================================================================
    # These patterns match field names that must be removed.
    # Uses regex for flexible matching of variants.
    # =========================================================================

    FORBIDDEN_EXACT_FIELDS: Set[str] = {
        # Price fields
        "price",
        "lastTradePrice",
        "lastPrice",
        "bestBid",
        "bestAsk",
        "bid",
        "ask",
        "midpoint",
        "spread",
        "outcomePrices",
        "tokenPrice",
        "priceChange",
        # Volume fields
        "volume",
        "volumeNum",
        "volume24hr",
        "volume1wk",
        "volume1mo",
        "volume1yr",
        "volume24hrAmm",
        "volume1wkAmm",
        "volume1moAmm",
        "volume1yrAmm",
        "volume24hrClob",
        "volume1wkClob",
        "volume1moClob",
        "volume1yrClob",
        "volumeAmm",
        "volumeClob",
        "tradeVolume",
        "tradingVolume",
        # Liquidity fields
        "liquidity",
        "liquidityNum",
        "liquidityAmm",
        "liquidityClob",
        "liquidityUsd",
        # Probability fields
        "probability",
        "impliedProbability",
        "odds",
        "winProbability",
        # Order book fields
        "orderbook",
        "orders",
        "bids",
        "asks",
        "openInterest",
        # Reward/financial fields
        "clobRewards",
        "rewards",
        "umaBond",
        "umaReward",
        "makerBaseFee",
        "takerBaseFee",
        # Score/ranking (often price-derived)
        "score",
    }

    # Patterns for partial matching (case-insensitive)
    FORBIDDEN_PATTERNS: List[str] = [
        r".*price.*",
        r".*volume.*",
        r".*liquidity.*",
        r".*probability.*",
        r".*odds.*",
        r".*bid.*",
        r".*ask.*",
        r".*reward.*",
        r".*fee.*",
        r".*trade.*amount.*",
        r".*open.*interest.*",
    ]

    def __init__(self, log_removals: bool = True):
        """
        Initialize the sanitizer.

        Args:
            log_removals: Whether to log each removed field
        """
        self.log_removals = log_removals
        self._compiled_patterns = [
            re.compile(p, re.IGNORECASE) for p in self.FORBIDDEN_PATTERNS
        ]
        self._removal_stats: Dict[str, int] = {}

    def sanitize(self, data: Any) -> Tuple[Any, Dict[str, int]]:
        """
        Sanitize data by removing all forbidden fields.

        Args:
            data: Raw API response (dict, list, or primitive)

        Returns:
            Tuple of (sanitized_data, removal_stats)
            removal_stats maps field_name -> count_removed
        """
        self._removal_stats = {}
        sanitized = self._sanitize_recursive(data, path="root")
        return sanitized, dict(self._removal_stats)

    def sanitize_market(self, market: Dict[str, Any]) -> Dict[str, Any]:
        """
        Sanitize a single market dictionary.

        Convenience method for sanitizing individual markets.

        Args:
            market: Raw market dictionary from API

        Returns:
            Sanitized market dictionary
        """
        sanitized, _ = self.sanitize(market)
        return sanitized

    def sanitize_markets(
        self, markets: List[Dict[str, Any]]
    ) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
        """
        Sanitize a list of market dictionaries.

        Args:
            markets: List of raw market dictionaries

        Returns:
            Tuple of (sanitized_markets, total_removal_stats)
        """
        self._removal_stats = {}
        sanitized_list = []

        for i, market in enumerate(markets):
            sanitized = self._sanitize_recursive(market, path=f"market[{i}]")
            sanitized_list.append(sanitized)

        return sanitized_list, dict(self._removal_stats)

    def _sanitize_recursive(self, data: Any, path: str) -> Any:
        """
        Recursively sanitize data structure.

        Args:
            data: Data to sanitize
            path: Current path for logging

        Returns:
            Sanitized data
        """
        if isinstance(data, dict):
            return self._sanitize_dict(data, path)
        elif isinstance(data, list):
            return self._sanitize_list(data, path)
        else:
            # Primitive value - return as-is
            return data

    def _sanitize_dict(self, d: Dict[str, Any], path: str) -> Dict[str, Any]:
        """
        Sanitize a dictionary by removing forbidden keys.

        Args:
            d: Dictionary to sanitize
            path: Current path for logging

        Returns:
            Sanitized dictionary
        """
        result = {}

        for key, value in d.items():
            if self._is_forbidden_field(key):
                self._record_removal(key, path)
                continue

            # Recursively sanitize nested structures
            sanitized_value = self._sanitize_recursive(value, f"{path}.{key}")
            result[key] = sanitized_value

        return result

    def _sanitize_list(self, lst: List[Any], path: str) -> List[Any]:
        """
        Sanitize a list by recursively sanitizing each element.

        Args:
            lst: List to sanitize
            path: Current path for logging

        Returns:
            Sanitized list
        """
        return [
            self._sanitize_recursive(item, f"{path}[{i}]")
            for i, item in enumerate(lst)
        ]

    def _is_forbidden_field(self, field_name: str) -> bool:
        """
        Check if a field name is forbidden.

        Args:
            field_name: Field name to check

        Returns:
            True if field should be removed
        """
        # Check exact match (case-insensitive)
        if field_name.lower() in {f.lower() for f in self.FORBIDDEN_EXACT_FIELDS}:
            return True

        # Check pattern match
        for pattern in self._compiled_patterns:
            if pattern.match(field_name):
                return True

        return False

    def _record_removal(self, field_name: str, path: str) -> None:
        """
        Record a field removal for statistics.

        Args:
            field_name: Name of removed field
            path: Path where field was removed
        """
        self._removal_stats[field_name] = self._removal_stats.get(field_name, 0) + 1

        if self.log_removals:
            logger.debug(f"Removed forbidden field: {path}.{field_name}")

    def get_removal_summary(self) -> str:
        """
        Get a human-readable summary of removed fields.

        Returns:
            Summary string
        """
        if not self._removal_stats:
            return "No forbidden fields removed."

        lines = ["Forbidden fields removed:"]
        for field, count in sorted(self._removal_stats.items()):
            lines.append(f"  - {field}: {count} occurrences")

        return "\n".join(lines)
