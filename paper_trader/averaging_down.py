# =============================================================================
# POLYMARKET BEOBACHTER - AVERAGING DOWN (NACHKAUF)
# =============================================================================
#
# GOVERNANCE INTENT:
# Averaging down is intentionally disabled until the strategy proves that
# add-ons improve performance instead of amplifying drawdown.
#
# PAPER TRADING ONLY:
# This module returns a disabled status and performs no add-on trades.
#
# =============================================================================

import re
from typing import Any, Dict, Optional


CITY_PATTERNS = {
    "london": "London",
    "new york city": "New York",
    "new york": "New York",
    "nyc": "New York",
    "manhattan": "New York",
    "seoul": "Seoul",
    "los angeles": "Los Angeles",
    "la ": "Los Angeles",
    "chicago": "Chicago",
    "miami": "Miami",
    "denver": "Denver",
    "phoenix": "Phoenix",
    "seattle": "Seattle",
    "boston": "Boston",
    "tokyo": "Tokyo",
    "paris": "Paris",
    "berlin": "Berlin",
    "sydney": "Sydney",
    "toronto": "Toronto",
    "houston": "Houston",
    "atlanta": "Atlanta",
    "dallas": "Dallas",
    "san francisco": "San Francisco",
    "washington": "Washington",
    "philadelphia": "Philadelphia",
    "buenos aires": "Buenos Aires",
    "ankara": "Ankara",
}

TEMPERATURE_PATTERNS = [
    re.compile(r"between\s*(\d+)\s*-\s*(\d+)\s*Â°?\s*([FC])", re.I),
    re.compile(r"be\s+(\d+)\s*Â°?\s*([FC])\s*(or\s+)?(higher|below|lower)?", re.I),
    re.compile(r"(?:above|exceed|over|>=|â‰¥)\s*(\d+)\s*Â°?\s*([FC])", re.I),
    re.compile(r"(?:below|under|<=|â‰¤|less than)\s*(\d+)\s*Â°?\s*([FC])", re.I),
    re.compile(r"(\d+)\s*Â°\s*([FC])", re.I),
]


def extract_city(market_question: str) -> Optional[str]:
    """Extract city name from market question text."""
    text = market_question.lower()
    for pattern, city_name in CITY_PATTERNS.items():
        if pattern in text:
            return city_name
    return None


def extract_threshold_f(market_question: str) -> Optional[float]:
    """Extract temperature threshold in Fahrenheit from market question."""
    for pattern in TEMPERATURE_PATTERNS:
        match = pattern.search(market_question)
        if match:
            groups = match.groups()
            threshold = None
            unit = None
            for group in groups:
                if group is None:
                    continue
                try:
                    threshold = float(group)
                except ValueError:
                    pass
                if group.upper() in ("F", "C"):
                    unit = group.upper()
            if threshold is not None and unit is not None:
                if unit == "C":
                    return threshold * 9 / 5 + 32
                return threshold
    return None


def check_averaging_down() -> Dict[str, Any]:
    """Averaging down is disabled by policy."""
    return {"checked": 0, "addons": 0, "skipped": 0, "cost_eur": 0.0, "disabled": True}
