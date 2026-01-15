# =============================================================================
# POLYMARKET EU AI COLLECTOR
# Module: collector/filter.py
# Purpose: Filter markets by EU + AI/Tech regulation relevance
# =============================================================================
#
# FILTERING LOGIC:
# Include if matches:
#   ("EU" OR "European Union" OR "Commission" OR "Parliament") AND
#   ("AI" OR "Artificial Intelligence" OR "tech regulation" OR "AI Act")
#
# Additionally require:
#   - Clear date/deadline in metadata OR extractable from resolution text
#
# Exclude:
#   - Markets about "price/market performance"
#   - Vague opinion questions
#
# =============================================================================

import re
import logging
from typing import Dict, Any, List, Tuple, Optional, Set
from datetime import date, datetime
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class FilterResult(Enum):
    """Result of filtering a market."""
    INCLUDED = "included"
    EXCLUDED_NO_EU_MATCH = "excluded_no_eu_match"
    EXCLUDED_NO_AI_MATCH = "excluded_no_ai_match"
    EXCLUDED_NO_DEADLINE = "excluded_no_deadline"
    EXCLUDED_PRICE_MARKET = "excluded_price_market"
    EXCLUDED_OPINION_MARKET = "excluded_opinion_market"
    EXCLUDED_INCOMPLETE = "excluded_incomplete"


@dataclass
class FilteredMarket:
    """Result of filtering a single market."""
    market: Dict[str, Any]
    result: FilterResult
    matched_eu_keywords: List[str]
    matched_ai_keywords: List[str]
    extracted_deadline: Optional[date]
    notes: List[str]


class MarketFilter:
    """
    Filters markets for EU + AI/Tech regulation relevance.

    Implements fail-closed behavior: if data is missing or ambiguous,
    the market is marked as incomplete and excluded from candidates.
    """

    # =========================================================================
    # EU-RELATED KEYWORDS
    # =========================================================================
    EU_KEYWORDS: Set[str] = {
        "eu",
        "european union",
        "european commission",
        "commission",
        "european parliament",
        "parliament",
        "brussels",
        "eu regulation",
        "eu directive",
        "eu law",
        "member state",
        "member states",
        "council of the eu",
        "eur-lex",
        "official journal",
    }

    # Regex patterns for EU matching (case-insensitive)
    EU_PATTERNS: List[str] = [
        r"\beu\b",
        r"\beuropean\s+union\b",
        r"\beuropean\s+commission\b",
        r"\beuropean\s+parliament\b",
        r"\beu\s+regulation\b",
        r"\beu\s+directive\b",
        r"\beu\s+law\b",
        r"\bmember\s+states?\b",
        r"\bbrussels\b",
        r"\bcouncil\s+of\s+the\s+eu\b",
    ]

    # =========================================================================
    # AI/TECH REGULATION KEYWORDS
    # =========================================================================
    AI_KEYWORDS: Set[str] = {
        "ai",
        "artificial intelligence",
        "ai act",
        "ai regulation",
        "tech regulation",
        "technology regulation",
        "digital services act",
        "dsa",
        "digital markets act",
        "dma",
        "gdpr",
        "data protection",
        "platform regulation",
        "algorithmic",
        "machine learning",
        "generative ai",
        "chatgpt",
        "large language model",
        "llm",
        "foundation model",
    }

    # Regex patterns for AI matching (case-insensitive)
    AI_PATTERNS: List[str] = [
        r"\bai\b",
        r"\bartificial\s+intelligence\b",
        r"\bai\s+act\b",
        r"\btech\s+regulation\b",
        r"\btechnology\s+regulation\b",
        r"\bdigital\s+services\s+act\b",
        r"\bdsa\b",
        r"\bdigital\s+markets\s+act\b",
        r"\bdma\b",
        r"\bgdpr\b",
        r"\bdata\s+protection\b",
        r"\bplatform\s+regulation\b",
        r"\balgorithm\w*\b",
        r"\bmachine\s+learning\b",
        r"\bgenerative\s+ai\b",
        r"\bfoundation\s+model\b",
        r"\blarge\s+language\s+model\b",
        r"\bllm\b",
    ]

    # =========================================================================
    # EXCLUSION PATTERNS
    # =========================================================================
    # Markets matching these patterns are excluded

    PRICE_MARKET_PATTERNS: List[str] = [
        r"\bprice\s+(of|at|above|below|reach|hit)\b",
        r"\bmarket\s+(cap|capitalization)\b",
        r"\bstock\s+price\b",
        r"\btrading\s+at\b",
        r"\b(bitcoin|btc|eth|crypto)\s+(price|reach|hit)\b",
        r"\btoken\s+price\b",
        r"\bworth\s+\$",
        r"\bhit\s+\$\d+",
    ]

    OPINION_MARKET_PATTERNS: List[str] = [
        r"\bwho\s+will\s+win\b",
        r"\bwho\s+is\s+better\b",
        r"\bmost\s+popular\b",
        r"\bfavorite\b",
        r"\bpolling\b",
        r"\bapproval\s+rating\b",
        r"\bwill\s+\w+\s+be\s+president\b",
        r"\belection\s+winner\b",
    ]

    # =========================================================================
    # DATE EXTRACTION PATTERNS
    # =========================================================================
    DATE_PATTERNS: List[Tuple[str, str]] = [
        # ISO format
        (r"(\d{4}-\d{2}-\d{2})", "%Y-%m-%d"),
        # Month day, year
        (r"((?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4})", "%B %d, %Y"),
        (r"((?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4})", "%B %d %Y"),
        # day Month year
        (r"(\d{1,2}\s+(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4})", "%d %B %Y"),
        # Short month
        (r"((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2},?\s+\d{4})", "%b %d, %Y"),
        (r"((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2},?\s+\d{4})", "%b %d %Y"),
        # MM/DD/YYYY
        (r"(\d{1,2}/\d{1,2}/\d{4})", "%m/%d/%Y"),
        # DD.MM.YYYY
        (r"(\d{1,2}\.\d{1,2}\.\d{4})", "%d.%m.%Y"),
        # Year only with context
        (r"by\s+(?:end\s+of\s+)?(\d{4})", None),  # Just year
        (r"before\s+(\d{4})", None),  # Just year
        (r"in\s+(\d{4})", None),  # Just year
    ]

    def __init__(
        self,
        custom_eu_keywords: Optional[List[str]] = None,
        custom_ai_keywords: Optional[List[str]] = None,
    ):
        """
        Initialize the market filter.

        Args:
            custom_eu_keywords: Additional EU keywords to match
            custom_ai_keywords: Additional AI keywords to match
        """
        self.eu_keywords = set(self.EU_KEYWORDS)
        self.ai_keywords = set(self.AI_KEYWORDS)

        if custom_eu_keywords:
            self.eu_keywords.update(k.lower() for k in custom_eu_keywords)
        if custom_ai_keywords:
            self.ai_keywords.update(k.lower() for k in custom_ai_keywords)

        # Compile regex patterns
        self._eu_patterns = [re.compile(p, re.IGNORECASE) for p in self.EU_PATTERNS]
        self._ai_patterns = [re.compile(p, re.IGNORECASE) for p in self.AI_PATTERNS]
        self._price_patterns = [re.compile(p, re.IGNORECASE) for p in self.PRICE_MARKET_PATTERNS]
        self._opinion_patterns = [re.compile(p, re.IGNORECASE) for p in self.OPINION_MARKET_PATTERNS]

    def filter_market(self, market: Dict[str, Any]) -> FilteredMarket:
        """
        Filter a single market for relevance.

        Args:
            market: Sanitized market dictionary

        Returns:
            FilteredMarket with result and metadata
        """
        notes: List[str] = []

        # Extract searchable text
        title = market.get("question") or market.get("title") or ""
        description = market.get("description") or ""
        resolution = market.get("resolutionSource") or market.get("resolution") or ""
        searchable_text = f"{title} {description} {resolution}".lower()

        # Check for incomplete data
        if not title.strip():
            notes.append("missing_title")
            return FilteredMarket(
                market=market,
                result=FilterResult.EXCLUDED_INCOMPLETE,
                matched_eu_keywords=[],
                matched_ai_keywords=[],
                extracted_deadline=None,
                notes=notes,
            )

        # Check exclusion patterns first
        if self._matches_patterns(searchable_text, self._price_patterns):
            notes.append("price_market_detected")
            return FilteredMarket(
                market=market,
                result=FilterResult.EXCLUDED_PRICE_MARKET,
                matched_eu_keywords=[],
                matched_ai_keywords=[],
                extracted_deadline=None,
                notes=notes,
            )

        if self._matches_patterns(searchable_text, self._opinion_patterns):
            notes.append("opinion_market_detected")
            return FilteredMarket(
                market=market,
                result=FilterResult.EXCLUDED_OPINION_MARKET,
                matched_eu_keywords=[],
                matched_ai_keywords=[],
                extracted_deadline=None,
                notes=notes,
            )

        # Check EU keywords
        eu_matches = self._find_keyword_matches(searchable_text, self._eu_patterns)
        if not eu_matches:
            notes.append("no_eu_keywords")
            return FilteredMarket(
                market=market,
                result=FilterResult.EXCLUDED_NO_EU_MATCH,
                matched_eu_keywords=[],
                matched_ai_keywords=[],
                extracted_deadline=None,
                notes=notes,
            )

        # Check AI/Tech keywords
        ai_matches = self._find_keyword_matches(searchable_text, self._ai_patterns)
        if not ai_matches:
            notes.append("no_ai_keywords")
            return FilteredMarket(
                market=market,
                result=FilterResult.EXCLUDED_NO_AI_MATCH,
                matched_eu_keywords=eu_matches,
                matched_ai_keywords=[],
                extracted_deadline=None,
                notes=notes,
            )

        # Extract deadline
        deadline = self._extract_deadline(market, searchable_text)
        if deadline is None:
            notes.append("no_deadline_found")
            return FilteredMarket(
                market=market,
                result=FilterResult.EXCLUDED_NO_DEADLINE,
                matched_eu_keywords=eu_matches,
                matched_ai_keywords=ai_matches,
                extracted_deadline=None,
                notes=notes,
            )

        # All checks passed - include
        return FilteredMarket(
            market=market,
            result=FilterResult.INCLUDED,
            matched_eu_keywords=eu_matches,
            matched_ai_keywords=ai_matches,
            extracted_deadline=deadline,
            notes=notes,
        )

    def filter_markets(
        self, markets: List[Dict[str, Any]]
    ) -> Tuple[List[FilteredMarket], Dict[str, int]]:
        """
        Filter multiple markets.

        Args:
            markets: List of sanitized market dictionaries

        Returns:
            Tuple of (filtered_markets, stats_by_result)
        """
        filtered = []
        stats: Dict[str, int] = {}

        for market in markets:
            result = self.filter_market(market)
            filtered.append(result)

            key = result.result.value
            stats[key] = stats.get(key, 0) + 1

        return filtered, stats

    def _matches_patterns(
        self, text: str, patterns: List[re.Pattern]
    ) -> bool:
        """Check if text matches any pattern."""
        for pattern in patterns:
            if pattern.search(text):
                return True
        return False

    def _find_keyword_matches(
        self, text: str, patterns: List[re.Pattern]
    ) -> List[str]:
        """Find all matching keywords in text."""
        matches = []
        for pattern in patterns:
            found = pattern.findall(text)
            matches.extend(found)
        return list(set(matches))  # Dedupe

    def _extract_deadline(
        self, market: Dict[str, Any], searchable_text: str
    ) -> Optional[date]:
        """
        Extract deadline from market data or text.

        Args:
            market: Market dictionary
            searchable_text: Combined searchable text

        Returns:
            Extracted date or None
        """
        # Try metadata fields first
        for field in ["endDate", "endDateIso", "end_date", "closeTime", "resolutionDate"]:
            value = market.get(field)
            if value:
                parsed = self._parse_date_string(str(value))
                if parsed:
                    return parsed

        # Try to extract from text
        for pattern_str, date_format in self.DATE_PATTERNS:
            pattern = re.compile(pattern_str, re.IGNORECASE)
            match = pattern.search(searchable_text)
            if match:
                date_str = match.group(1)
                parsed = self._parse_date_string(date_str, date_format)
                if parsed:
                    return parsed

        return None

    def _parse_date_string(
        self, date_str: str, format_hint: Optional[str] = None
    ) -> Optional[date]:
        """
        Parse a date string into a date object.

        Args:
            date_str: String to parse
            format_hint: Optional format string

        Returns:
            Parsed date or None
        """
        # Clean the string
        date_str = date_str.strip().replace(",", "")

        # Try ISO format first
        try:
            # Handle ISO datetime
            if "T" in date_str:
                return datetime.fromisoformat(date_str.replace("Z", "+00:00")).date()
            # Handle ISO date
            if re.match(r"^\d{4}-\d{2}-\d{2}$", date_str):
                return date.fromisoformat(date_str)
        except ValueError:
            pass

        # Try format hint
        if format_hint:
            try:
                return datetime.strptime(date_str, format_hint).date()
            except ValueError:
                pass

        # Try common formats
        formats = [
            "%Y-%m-%d",
            "%B %d %Y",
            "%b %d %Y",
            "%d %B %Y",
            "%d %b %Y",
            "%m/%d/%Y",
            "%d.%m.%Y",
        ]

        for fmt in formats:
            try:
                return datetime.strptime(date_str, fmt).date()
            except ValueError:
                continue

        # Handle year-only
        if re.match(r"^\d{4}$", date_str):
            year = int(date_str)
            if 2020 <= year <= 2030:
                return date(year, 12, 31)  # End of year

        return None
