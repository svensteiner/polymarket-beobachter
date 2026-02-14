# =============================================================================
# POLYMARKET BEOBACHTER - WEATHER MARKET CLASSIFIER
# =============================================================================
#
# MULTI-SIGNAL WEATHER CLASSIFIER
#
# Classifies markets as WEATHER_CONFIRMED, WEATHER_POSSIBLE, or NOT_WEATHER
# using textual signals, structural signals, and negative filters.
#
# DESIGN PRINCIPLES:
# - Accuracy > Coverage
# - False positives are worse than false negatives
# - If ambiguous → NOT_WEATHER
# - Word-boundary aware matching (no substring hacks)
# - Fail-closed on uncertainty
#
# =============================================================================

import re
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Any, List, Optional, Set

logger = logging.getLogger(__name__)


# =============================================================================
# CLASSIFICATION RESULT
# =============================================================================


class WeatherClassification(Enum):
    """Classification result for a market."""
    WEATHER_CONFIRMED = "WEATHER_CONFIRMED"  # Proceed to weather model
    WEATHER_POSSIBLE = "WEATHER_POSSIBLE"    # Log but do not process
    NOT_WEATHER = "NOT_WEATHER"              # Reject


@dataclass
class ClassificationResult:
    """
    Result of classifying a single market.

    Includes:
    - classification: WEATHER_CONFIRMED, WEATHER_POSSIBLE, or NOT_WEATHER
    - matched_text_signals: List of textual signals that matched
    - matched_structural_signals: List of structural signals that matched
    - rejection_reason: Why the market was rejected (if any)
    - confidence_score: 0.0 to 1.0 confidence in classification
    """
    classification: WeatherClassification
    matched_text_signals: List[str] = field(default_factory=list)
    matched_structural_signals: List[str] = field(default_factory=list)
    rejection_reason: Optional[str] = None
    confidence_score: float = 0.0
    market_id: Optional[str] = None
    market_title: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for logging."""
        return {
            "classification": self.classification.value,
            "matched_text_signals": self.matched_text_signals,
            "matched_structural_signals": self.matched_structural_signals,
            "rejection_reason": self.rejection_reason,
            "confidence_score": self.confidence_score,
            "market_id": self.market_id,
            "market_title": self.market_title[:80] if self.market_title else None,
        }


# =============================================================================
# WEATHER MARKET CLASSIFIER
# =============================================================================


class WeatherMarketClassifier:
    """
    Multi-signal weather market classifier.

    A market is WEATHER_CONFIRMED only if:
    1. At least ONE textual signal matches
    2. At least ONE structural signal matches
    3. NO negative filters trigger

    A market is WEATHER_POSSIBLE if:
    - Some signals match but not enough for confirmation
    - No negative filters trigger

    A market is NOT_WEATHER if:
    - Any negative filter triggers
    - No signals match
    """

    # =========================================================================
    # TEXTUAL SIGNALS (at least ONE required for CONFIRMED)
    # =========================================================================

    # Temperature-related terms
    TEMPERATURE_TERMS: Set[str] = {
        "temperature", "temp",
        "fahrenheit", "celsius",
        "degrees",
    }

    # Temperature symbols (handled separately with regex)
    TEMPERATURE_SYMBOL_PATTERN = re.compile(r'\d+\s*°\s*[FC]?', re.IGNORECASE)

    # Precipitation terms
    PRECIPITATION_TERMS: Set[str] = {
        "rain", "rainfall", "precipitation",
        "snow", "snowfall",
        "sleet", "hail",
    }

    # Storm/severe weather terms
    STORM_TERMS: Set[str] = {
        "hurricane", "cyclone", "typhoon",
        "storm", "thunderstorm",
        "tornado", "twister",
        "blizzard",
    }

    # Climate/weather general terms
    CLIMATE_TERMS: Set[str] = {
        "weather", "climate",
        "meteorological", "meteorology",
    }

    # Superlative weather terms
    SUPERLATIVE_WEATHER_TERMS: Set[str] = {
        "heatwave", "heat wave",
        "coldest", "hottest",
        "warmest", "coolest",
        "highest temperature", "lowest temperature",
        "record high", "record low",
        "record temperature",
        "freezing", "freeze",
        "frost",
    }

    # Combined textual keywords (for single-pass check)
    ALL_TEXT_SIGNALS: Set[str] = (
        TEMPERATURE_TERMS | PRECIPITATION_TERMS | STORM_TERMS |
        CLIMATE_TERMS | SUPERLATIVE_WEATHER_TERMS
    )

    # =========================================================================
    # STRUCTURAL SIGNALS (at least ONE required for CONFIRMED)
    # =========================================================================

    # Category keywords (in category/tags field)
    WEATHER_CATEGORIES: Set[str] = {
        "weather", "climate", "meteorology",
        "temperature", "storm", "hurricane",
    }

    # Resolution source authorities
    RESOLUTION_AUTHORITIES: Set[str] = {
        "noaa",
        "national weather service", "nws",
        "met office",
        "weather station",
        "meteorological authority",
        "national hurricane center", "nhc",
        "weather.gov",
        "accuweather",
        "weather underground",
        "weather channel",
    }

    # Location + date pattern (city + specific date/time)
    LOCATION_DATE_PATTERN = re.compile(
        r'\b(?:' +
        r'new york|nyc|manhattan|los angeles|la|chicago|miami|denver|' +
        r'phoenix|seattle|boston|london|tokyo|paris|berlin|sydney|toronto|' +
        r'houston|atlanta|dallas|san francisco|washington|philadelphia|' +
        r'orlando|las vegas|detroit|minneapolis|portland|sacramento|' +
        r'austin|nashville|charlotte|kansas city|cincinnati|cleveland|' +
        r'pittsburgh|indianapolis|columbus|milwaukee|memphis|baltimore|' +
        r'tampa|orlando|jacksonville|honolulu|anchorage|fairbanks' +
        r')\b.*\b(?:' +
        r'january|february|march|april|may|june|july|august|september|october|november|december|' +
        r'jan|feb|mar|apr|jun|jul|aug|sep|oct|nov|dec|' +
        r'\d{1,2}/\d{1,2}|\d{1,2}-\d{1,2}|' +
        r'monday|tuesday|wednesday|thursday|friday|saturday|sunday|' +
        r'tomorrow|next week|this week|this weekend|end of' +
        r')\b',
        re.IGNORECASE
    )

    # Temperature threshold patterns (explicit numeric values)
    TEMPERATURE_THRESHOLD_PATTERNS = [
        # "above 40°F", "exceed 100°F", ">= 32°F", "over 90 degrees"
        re.compile(r'\b(?:above|exceed|over|>=?)\s*\d+\.?\d*\s*(?:°\s*)?(?:f|fahrenheit|c|celsius|degrees)', re.IGNORECASE),
        # "40°F or higher", "100°F+"
        re.compile(r'\b\d+\.?\d*\s*(?:°\s*)?(?:f|fahrenheit|c|celsius)\s*(?:or\s+)?(?:higher|above|\+)', re.IGNORECASE),
        # "below 32°F", "under 0°C", "< 50°F"
        re.compile(r'\b(?:below|under|<=?)\s*\d+\.?\d*\s*(?:°\s*)?(?:f|fahrenheit|c|celsius)', re.IGNORECASE),
        # "reach 100°F", "hit 90°F"
        re.compile(r'\b(?:reach|hit)\s*\d+\.?\d*\s*(?:°\s*)?(?:f|fahrenheit|c|celsius)', re.IGNORECASE),
        # "high of 50", "low of 32"
        re.compile(r'\b(?:high|low)\s+of\s+\d+', re.IGNORECASE),
        # Bare temperature with unit: "100F", "32 F", "100°C"
        re.compile(r'\b\d+\.?\d*\s*°?\s*(?:f|fahrenheit|c|celsius)\b', re.IGNORECASE),
    ]

    # =========================================================================
    # NEGATIVE FILTERS (hard exclusion)
    # =========================================================================

    # Political context keywords
    POLITICAL_KEYWORDS: Set[str] = {
        "election", "vote", "voting", "ballot",
        "president", "presidential", "governor",
        "congress", "senate", "house of representatives",
        "parliament", "prime minister",
        "democrat", "republican", "party",
        "campaign", "candidate",
        "impeach", "impeachment",
        "legislation", "bill", "law", "policy",
        "government", "administration",
    }

    # War/conflict keywords
    WAR_KEYWORDS: Set[str] = {
        "war", "warfare", "invasion",
        "military", "army", "troops", "soldier",
        "attack", "strike", "bombing",
        "conflict", "battle",
        "ukraine", "russia", "putin", "zelensky",
        "israel", "hamas", "gaza",
        "nato", "missile",
    }

    # Sports keywords
    SPORTS_KEYWORDS: Set[str] = {
        "nfl", "nba", "mlb", "nhl", "mls",
        "super bowl", "world series", "playoffs", "championship",
        "league", "tournament", "match", "game score",
        "team", "player", "coach", "quarterback", "mvp",
        "fifa", "world cup", "olympics",
        "tennis", "golf", "boxing", "ufc", "mma",
        "win the", "beat the", "defeat",
    }

    # Financial keywords
    FINANCIAL_KEYWORDS: Set[str] = {
        "stock", "stocks", "share", "shares",
        "bitcoin", "btc", "ethereum", "eth", "crypto", "cryptocurrency",
        "price", "trading", "market cap",
        "interest rate", "fed", "federal reserve",
        "inflation", "gdp", "recession",
        "ipo", "merger", "acquisition",
        "earnings", "revenue", "profit",
        "s&p", "nasdaq", "dow jones",
        "forex", "currency",
    }

    # Court/legal keywords
    COURT_KEYWORDS: Set[str] = {
        "court", "supreme court", "judge", "jury",
        "verdict", "ruling", "lawsuit", "trial",
        "guilty", "innocent", "convicted", "acquitted",
        "indictment", "indicted", "charges",
        "attorney", "lawyer", "prosecutor",
        "sentence", "sentencing", "prison",
    }

    # Entertainment/celebrity keywords
    ENTERTAINMENT_KEYWORDS: Set[str] = {
        "movie", "film", "oscar", "emmy", "grammy",
        "album", "song", "concert", "tour",
        "celebrity", "star", "famous",
        "tv show", "series", "netflix", "streaming",
        "awards", "nomination",
    }

    # Generic prediction words (without physical measurement context)
    GENERIC_PREDICTION_KEYWORDS: Set[str] = {
        "will he", "will she", "will they",
        "resign", "fired", "quit", "retire",
        "die", "death", "alive",
        "married", "divorce", "pregnant",
        "arrested", "jail",
    }

    # Combined negative filters
    ALL_NEGATIVE_KEYWORDS: Set[str] = (
        POLITICAL_KEYWORDS | WAR_KEYWORDS | SPORTS_KEYWORDS |
        FINANCIAL_KEYWORDS | COURT_KEYWORDS | ENTERTAINMENT_KEYWORDS |
        GENERIC_PREDICTION_KEYWORDS
    )

    # =========================================================================
    # METHODS
    # =========================================================================

    def __init__(self):
        """Initialize the classifier."""
        logger.info("WeatherMarketClassifier initialized")

    def classify_market(self, market: Dict[str, Any]) -> ClassificationResult:
        """
        Classify a single market.

        Args:
            market: Raw market data dict with fields:
                - question/title: Market question
                - description: Market description
                - resolution_text/resolutionSource: Resolution criteria
                - category: Market category (if available)
                - tags: Market tags (if available)
                - id/market_id: Market identifier

        Returns:
            ClassificationResult with classification and metadata
        """
        # Extract text fields
        title = market.get("question") or market.get("title") or ""
        description = market.get("description") or ""
        resolution = market.get("resolution_text") or market.get("resolutionSource") or ""
        category = market.get("category") or ""
        tags = market.get("tags") or []
        market_id = market.get("id") or market.get("market_id") or ""

        # Extract event-level metadata (from collector enrichment)
        event_tags = market.get("_event_tags") or []
        event_title = market.get("_event_title") or ""

        # Combine text for analysis (include event title)
        combined_text = f"{title} {description} {resolution} {event_title}".lower()
        category_text = f"{category} {' '.join(tags) if isinstance(tags, list) else tags}".lower()

        matched_text_signals: List[str] = []
        matched_structural_signals: List[str] = []

        # =====================================================================
        # STEP 1: CHECK NEGATIVE FILTERS FIRST (hard exclusion)
        # =====================================================================
        rejection_reason = self._check_negative_filters(combined_text)
        if rejection_reason:
            return ClassificationResult(
                classification=WeatherClassification.NOT_WEATHER,
                rejection_reason=rejection_reason,
                confidence_score=1.0,
                market_id=market_id,
                market_title=title,
            )

        # =====================================================================
        # STEP 2: CHECK TEXTUAL SIGNALS
        # =====================================================================
        matched_text_signals = self._check_text_signals(combined_text)

        # =====================================================================
        # STEP 3: CHECK STRUCTURAL SIGNALS
        # =====================================================================
        matched_structural_signals = self._check_structural_signals(
            combined_text, category_text, resolution, event_tags
        )

        # =====================================================================
        # STEP 4: DETERMINE CLASSIFICATION
        # =====================================================================
        has_text_signal = len(matched_text_signals) > 0
        has_structural_signal = len(matched_structural_signals) > 0

        # Calculate confidence score
        text_score = min(len(matched_text_signals) * 0.2, 0.5)
        structural_score = min(len(matched_structural_signals) * 0.25, 0.5)
        confidence_score = text_score + structural_score

        if has_text_signal and has_structural_signal:
            # Both signals present → CONFIRMED
            return ClassificationResult(
                classification=WeatherClassification.WEATHER_CONFIRMED,
                matched_text_signals=matched_text_signals,
                matched_structural_signals=matched_structural_signals,
                confidence_score=confidence_score,
                market_id=market_id,
                market_title=title,
            )
        elif has_text_signal or has_structural_signal:
            # Only one type of signal → POSSIBLE (log but don't process)
            return ClassificationResult(
                classification=WeatherClassification.WEATHER_POSSIBLE,
                matched_text_signals=matched_text_signals,
                matched_structural_signals=matched_structural_signals,
                rejection_reason="Insufficient signal coverage (needs both text and structural)",
                confidence_score=confidence_score,
                market_id=market_id,
                market_title=title,
            )
        else:
            # No signals → NOT_WEATHER
            return ClassificationResult(
                classification=WeatherClassification.NOT_WEATHER,
                rejection_reason="No weather signals detected",
                confidence_score=0.0,
                market_id=market_id,
                market_title=title,
            )

    def _check_negative_filters(self, text: str) -> Optional[str]:
        """
        Check for hard exclusion keywords.

        Returns rejection reason if any negative filter triggers, None otherwise.
        """
        for keyword in self.ALL_NEGATIVE_KEYWORDS:
            # Use word boundary to avoid false matches
            pattern = r'\b' + re.escape(keyword) + r'\b'
            if re.search(pattern, text, re.IGNORECASE):
                return f"Negative filter: '{keyword}'"

        return None

    def _check_text_signals(self, text: str) -> List[str]:
        """
        Check for textual weather signals.

        Uses word-boundary aware matching.
        """
        matched: List[str] = []

        # Check all text keywords
        for keyword in self.ALL_TEXT_SIGNALS:
            pattern = r'\b' + re.escape(keyword) + r'\b'
            if re.search(pattern, text, re.IGNORECASE):
                matched.append(f"text:{keyword}")

        # Check temperature symbol pattern (°F, °C)
        if self.TEMPERATURE_SYMBOL_PATTERN.search(text):
            matched.append("text:temperature_symbol")

        return matched

    def _check_structural_signals(
        self, text: str, category_text: str, resolution: str,
        event_tags: Optional[List[str]] = None
    ) -> List[str]:
        """
        Check for structural weather signals.
        """
        matched: List[str] = []

        # Check Polymarket event tags (strongest signal - pre-filtered by Polymarket)
        if event_tags:
            event_tags_lower = [t.lower() for t in event_tags]
            for tag in event_tags_lower:
                if any(kw in tag for kw in ["weather", "climate", "hurricane", "storm", "temperature"]):
                    matched.append(f"polymarket_tag:{tag}")

        # Check category contains weather terms
        for cat_keyword in self.WEATHER_CATEGORIES:
            if cat_keyword in category_text:
                matched.append(f"category:{cat_keyword}")

        # Check resolution source references authority
        resolution_lower = resolution.lower()
        for authority in self.RESOLUTION_AUTHORITIES:
            pattern = r'\b' + re.escape(authority) + r'\b'
            if re.search(pattern, resolution_lower, re.IGNORECASE):
                matched.append(f"authority:{authority}")

        # Check for location + date pattern
        if self.LOCATION_DATE_PATTERN.search(text):
            matched.append("structure:location_date")

        # Check for explicit temperature thresholds
        for pattern in self.TEMPERATURE_THRESHOLD_PATTERNS:
            if pattern.search(text):
                matched.append("structure:temperature_threshold")
                break  # Only count once

        return matched

    def classify_markets(
        self, markets: List[Dict[str, Any]]
    ) -> Dict[str, List[ClassificationResult]]:
        """
        Classify multiple markets.

        Returns dict with:
        - confirmed: List of WEATHER_CONFIRMED results
        - possible: List of WEATHER_POSSIBLE results
        - not_weather: List of NOT_WEATHER results
        """
        results: Dict[str, List[ClassificationResult]] = {
            "confirmed": [],
            "possible": [],
            "not_weather": [],
        }

        for market in markets:
            result = self.classify_market(market)

            if result.classification == WeatherClassification.WEATHER_CONFIRMED:
                results["confirmed"].append(result)
            elif result.classification == WeatherClassification.WEATHER_POSSIBLE:
                results["possible"].append(result)
            else:
                results["not_weather"].append(result)

        logger.info(
            f"Classified {len(markets)} markets: "
            f"{len(results['confirmed'])} CONFIRMED, "
            f"{len(results['possible'])} POSSIBLE, "
            f"{len(results['not_weather'])} NOT_WEATHER"
        )

        return results


# =============================================================================
# MODULE-LEVEL CONVENIENCE FUNCTION
# =============================================================================


def classify_weather_market(market: Dict[str, Any]) -> ClassificationResult:
    """
    Classify a single market for weather relevance.

    Args:
        market: Raw market data dict

    Returns:
        ClassificationResult
    """
    classifier = WeatherMarketClassifier()
    return classifier.classify_market(market)


def classify_weather_markets(
    markets: List[Dict[str, Any]]
) -> Dict[str, List[ClassificationResult]]:
    """
    Classify multiple markets for weather relevance.

    Args:
        markets: List of raw market data dicts

    Returns:
        Dict with 'confirmed', 'possible', 'not_weather' lists
    """
    classifier = WeatherMarketClassifier()
    return classifier.classify_markets(markets)
