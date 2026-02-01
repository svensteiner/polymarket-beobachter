# =============================================================================
# POLYMARKET EU AI COLLECTOR
# Module: collector/normalizer.py
# Purpose: Normalize raw market data into standardized records
# =============================================================================
#
# OUTPUT SCHEMA:
# {
#     "market_id": string,
#     "title": string,
#     "resolution_text": string,
#     "end_date": string (ISO) | null,
#     "created_time": string (ISO) | null,
#     "category": string | null,
#     "tags": [string],
#     "url": string,
#     "collector_notes": [string],
#     "collected_at": string (ISO),
# }
#
# DESIGN:
# - Deterministic: same input => same output
# - Fail-closed: missing required fields => incomplete record
#
# =============================================================================

import logging
from datetime import datetime, date, timezone
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field, asdict

logger = logging.getLogger(__name__)


@dataclass
class NormalizedMarket:
    """
    Standardized market record.

    Contains ONLY allowed fields - no prices, volumes, or probabilities.
    """
    market_id: str
    title: str
    resolution_text: str
    end_date: Optional[str]  # ISO format
    created_time: Optional[str]  # ISO format
    category: Optional[str]
    tags: List[str]
    url: str
    collector_notes: List[str]
    collected_at: str  # ISO format

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)

    def is_complete(self) -> bool:
        """
        Check if record has all required fields.

        Required: market_id, title, resolution_text, end_date
        """
        return bool(
            self.market_id and
            self.title and
            self.resolution_text and
            self.end_date
        )


class MarketNormalizer:
    """
    Normalizes raw API data into standardized NormalizedMarket records.

    Extracts only allowed fields and constructs URLs.
    """

    POLYMARKET_BASE_URL = "https://polymarket.com/event"

    def __init__(self, collection_time: Optional[datetime] = None):
        """
        Initialize the normalizer.

        Args:
            collection_time: Timestamp for collected_at field (defaults to now)
        """
        self.collection_time = collection_time or datetime.now(timezone.utc)

    def normalize(
        self,
        market: Dict[str, Any],
        extracted_deadline: Optional[date] = None,
        notes: Optional[List[str]] = None,
    ) -> NormalizedMarket:
        """
        Normalize a single market into standardized format.

        Args:
            market: Sanitized market dictionary
            extracted_deadline: Deadline extracted by filter (if available)
            notes: Collector notes from filtering

        Returns:
            NormalizedMarket record
        """
        collector_notes = list(notes) if notes else []

        # Extract market_id
        market_id = self._extract_market_id(market)
        if not market_id:
            collector_notes.append("missing_market_id")

        # Extract title
        title = self._extract_title(market)
        if not title:
            collector_notes.append("missing_title")

        # Extract resolution text
        resolution_text = self._extract_resolution_text(market)
        if not resolution_text:
            collector_notes.append("missing_resolution_text")

        # Extract end_date
        end_date = self._extract_end_date(market, extracted_deadline)
        if not end_date:
            collector_notes.append("missing_end_date")

        # Extract created_time
        created_time = self._extract_created_time(market)

        # Extract category and tags
        category = self._extract_category(market)
        tags = self._extract_tags(market)

        # Construct URL
        url = self._construct_url(market)

        return NormalizedMarket(
            market_id=market_id or "",
            title=title or "",
            resolution_text=resolution_text or "",
            end_date=end_date,
            created_time=created_time,
            category=category,
            tags=tags,
            url=url,
            collector_notes=collector_notes,
            collected_at=self.collection_time.isoformat() + "Z",
        )

    def normalize_many(
        self,
        markets_with_metadata: List[Dict[str, Any]],
    ) -> List[NormalizedMarket]:
        """
        Normalize multiple markets.

        Args:
            markets_with_metadata: List of dicts with 'market', 'deadline', 'notes' keys

        Returns:
            List of NormalizedMarket records
        """
        normalized = []
        for item in markets_with_metadata:
            market = item.get("market", {})
            deadline = item.get("deadline")
            notes = item.get("notes", [])

            record = self.normalize(market, deadline, notes)
            normalized.append(record)

        return normalized

    def _extract_market_id(self, market: Dict[str, Any]) -> Optional[str]:
        """Extract market ID from various possible field names."""
        for field_name in ["id", "market_id", "marketId", "conditionId"]:
            value = market.get(field_name)
            if value:
                return str(value)
        return None

    def _extract_title(self, market: Dict[str, Any]) -> Optional[str]:
        """Extract market title/question."""
        for field_name in ["question", "title", "name"]:
            value = market.get(field_name)
            if value and str(value).strip():
                return str(value).strip()
        return None

    def _extract_resolution_text(self, market: Dict[str, Any]) -> Optional[str]:
        """Extract resolution criteria text."""
        # Try multiple possible field names
        for field_name in [
            "description",
            "resolutionSource",
            "resolution",
            "resolutionDetails",
            "rules",
        ]:
            value = market.get(field_name)
            if value and str(value).strip():
                return str(value).strip()

        return None

    def _extract_end_date(
        self,
        market: Dict[str, Any],
        extracted_deadline: Optional[date],
    ) -> Optional[str]:
        """
        Extract end date in ISO format.

        Args:
            market: Market dictionary
            extracted_deadline: Deadline extracted by filter

        Returns:
            ISO date string or None
        """
        # Use filter-extracted deadline if available
        if extracted_deadline:
            return extracted_deadline.isoformat()

        # Try metadata fields
        for field_name in [
            "endDate",
            "endDateIso",
            "end_date",
            "closeTime",
            "resolutionDate",
            "expirationDate",
        ]:
            value = market.get(field_name)
            if value:
                parsed = self._parse_to_iso_date(value)
                if parsed:
                    return parsed

        return None

    def _extract_created_time(self, market: Dict[str, Any]) -> Optional[str]:
        """Extract creation timestamp in ISO format."""
        for field_name in ["createdAt", "created_at", "createTime"]:
            value = market.get(field_name)
            if value:
                parsed = self._parse_to_iso_datetime(value)
                if parsed:
                    return parsed

        return None

    def _extract_category(self, market: Dict[str, Any]) -> Optional[str]:
        """Extract market category."""
        # Direct category field
        category = market.get("category")
        if category:
            return str(category)

        # From categories array
        categories = market.get("categories", [])
        if categories and isinstance(categories, list) and len(categories) > 0:
            first = categories[0]
            if isinstance(first, dict):
                return first.get("name") or first.get("label")
            return str(first)

        return None

    def _extract_tags(self, market: Dict[str, Any]) -> List[str]:
        """Extract market tags."""
        tags = []

        # From tags array
        raw_tags = market.get("tags", [])
        if isinstance(raw_tags, list):
            for tag in raw_tags:
                if isinstance(tag, dict):
                    tag_name = tag.get("label") or tag.get("name") or tag.get("slug")
                    if tag_name:
                        tags.append(str(tag_name))
                elif tag:
                    tags.append(str(tag))

        return tags

    def _construct_url(self, market: Dict[str, Any]) -> str:
        """Construct Polymarket URL for market."""
        slug = market.get("slug")
        if slug:
            return f"{self.POLYMARKET_BASE_URL}/{slug}"

        market_id = self._extract_market_id(market)
        if market_id:
            return f"{self.POLYMARKET_BASE_URL}/{market_id}"

        return ""

    def _parse_to_iso_date(self, value: Any) -> Optional[str]:
        """Parse value to ISO date string."""
        if not value:
            return None

        value_str = str(value).strip()

        # Already ISO date
        if len(value_str) == 10 and value_str[4] == "-" and value_str[7] == "-":
            return value_str

        # ISO datetime - extract date part
        if "T" in value_str:
            return value_str.split("T")[0]

        # Unix timestamp (seconds)
        if value_str.isdigit():
            ts = int(value_str)
            if ts > 1000000000000:  # Milliseconds
                ts = ts // 1000
            try:
                return datetime.fromtimestamp(ts, tz=timezone.utc).date().isoformat()
            except (ValueError, OSError):
                pass

        return None

    def _parse_to_iso_datetime(self, value: Any) -> Optional[str]:
        """Parse value to ISO datetime string."""
        if not value:
            return None

        value_str = str(value).strip()

        # Already ISO datetime
        if "T" in value_str:
            # Normalize timezone
            if value_str.endswith("Z"):
                return value_str
            if "+" in value_str or value_str.count("-") > 2:
                return value_str
            return value_str + "Z"

        # Unix timestamp
        if value_str.isdigit():
            ts = int(value_str)
            if ts > 1000000000000:  # Milliseconds
                ts = ts // 1000
            try:
                return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat().replace("+00:00", "Z")
            except (ValueError, OSError):
                pass

        return None
