# =============================================================================
# POLYMARKET BEOBACHTER - WEATHER MARKET FILTER
# =============================================================================
#
# GOVERNANCE INTENT:
# This module filters weather markets using STRICT, STATIC criteria.
# All parameters come from config/weather.yaml.
# NO adaptive thresholds. NO learning. NO exceptions.
#
# FAIL-CLOSED PRINCIPLE:
# Any criterion that fails → market is REJECTED.
# Any missing data → market is REJECTED.
# Any uncertainty → market is REJECTED.
#
# FILTER CRITERIA (ALL MUST PASS):
# 1. category == "WEATHER" (market type check)
# 2. binary == true (yes/no market)
# 3. liquidity_usd >= MIN_LIQUIDITY
# 4. resolution_time >= now + MIN_TIME_TO_RESOLUTION_HOURS
# 5. odds_yes between MIN_ODDS and MAX_ODDS
# 6. city in ALLOWED_CITIES
# 7. resolution_definition is explicit and verifiable
#
# =============================================================================

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, List, Tuple

logger = logging.getLogger(__name__)


# =============================================================================
# DATA MODELS
# =============================================================================


@dataclass
class WeatherMarket:
    """
    Representation of a weather market from Polymarket.

    This is READ-ONLY input data.
    The filter does not modify market data.
    """
    market_id: str
    question: str
    resolution_text: str
    description: str
    category: str
    is_binary: bool
    liquidity_usd: float
    odds_yes: float  # Current YES price (probability)
    resolution_time: datetime
    created_at: Optional[datetime] = None

    # Extracted fields (populated by filter)
    detected_city: Optional[str] = None
    detected_threshold: Optional[float] = None
    detected_metric: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for logging."""
        return {
            "market_id": self.market_id,
            "question": self.question,
            "resolution_text": self.resolution_text[:200] if self.resolution_text else None,
            "category": self.category,
            "is_binary": self.is_binary,
            "liquidity_usd": self.liquidity_usd,
            "odds_yes": self.odds_yes,
            "resolution_time": self.resolution_time.isoformat() if self.resolution_time else None,
            "detected_city": self.detected_city,
            "detected_threshold": self.detected_threshold,
            "detected_metric": self.detected_metric,
        }


@dataclass
class FilterResult:
    """
    Result of filtering a single market.

    Contains:
    - passed: whether market passed all filters
    - market: the original market (if passed)
    - rejection_reasons: list of reasons why market was rejected
    - filter_details: detailed results of each filter check
    """
    passed: bool
    market: Optional[WeatherMarket] = None
    rejection_reasons: List[str] = field(default_factory=list)
    filter_details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for logging."""
        return {
            "passed": self.passed,
            "market_id": self.market.market_id if self.market else None,
            "rejection_reasons": self.rejection_reasons,
            "filter_details": self.filter_details,
        }


# =============================================================================
# WEATHER MARKET FILTER
# =============================================================================


class WeatherMarketFilter:
    """
    Filters weather markets using strict, static criteria.

    GOVERNANCE:
    - All thresholds are from config (no hardcoded values that could change)
    - No adaptive behavior
    - No learning from past decisions
    - Fail-closed on any uncertainty

    ISOLATION:
    - Does NOT import from panic, execution, or learning modules
    - Does NOT call external APIs
    - Pure filtering logic only
    """

    # City name patterns for detection
    CITY_PATTERNS = {
        "london": "London",
        "new york city": "New York",
        "new york": "New York",
        "nyc": "New York",
        "manhattan": "New York",
        "seoul": "Seoul",
        "los angeles": "Los Angeles",
        "la": "Los Angeles",
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

    # Weather category indicators
    WEATHER_CATEGORY_KEYWORDS = {
        "weather", "temperature", "rain", "snow", "wind",
        "storm", "hurricane", "tornado", "climate", "heat",
        "cold", "freeze", "precipitation", "humidity",
    }

    # Temperature threshold patterns
    TEMPERATURE_PATTERNS = [
        # "between 48-49°F", "between 50-51°F"
        re.compile(r'between\s*(\d+)\s*-\s*(\d+)\s*°?\s*([FC])', re.I),
        # "be 10°C", "be 56°F or higher", "be 31°F or below"
        re.compile(r'be\s+(\d+)\s*°?\s*([FC])\s*(or\s+)?(higher|below|lower)?', re.I),
        # "above 40°F", "exceed 100°F", ">= 32°F", "over 90°F"
        re.compile(r'(above|exceed|>=?|over)\s*(\d+\.?\d*)\s*°?\s*([FC])', re.I),
        # "40°F or higher", "100°F+"
        re.compile(r'(\d+\.?\d*)\s*°?\s*([FC])\s*(or\s+)?(higher|above|\+)', re.I),
        # "below 32°F", "under 0°C", "< 50°F"
        re.compile(r'(below|under|<=?)\s*(\d+\.?\d*)\s*°?\s*([FC])', re.I),
        # "reach 100°F", "hit 90°F"
        re.compile(r'(reach|hit)\s*(\d+\.?\d*)\s*°?\s*([FC])', re.I),
        # "highest temperature" + number (implicit threshold)
        re.compile(r'highest\s+temperature.*?(\d+)\s*°?\s*([FC])', re.I),
        # "temperature increase" patterns (global temp markets)
        re.compile(r'temperature\s+increase.*?(\d+\.?\d*)\s*°?\s*([FC])', re.I),
    ]

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize filter with configuration.

        Args:
            config: Configuration dictionary from weather.yaml
        """
        self.config = config

        # Extract filter parameters with defaults
        self.min_liquidity = config.get("MIN_LIQUIDITY", 50)
        self.min_odds = config.get("MIN_ODDS", 0.01)
        self.max_odds = config.get("MAX_ODDS", 0.10)
        self.min_time_to_resolution_hours = config.get("MIN_TIME_TO_RESOLUTION_HOURS", 48)
        self.safety_buffer_hours = config.get("SAFETY_BUFFER_HOURS", 48)
        self.allowed_cities = set(config.get("ALLOWED_CITIES", []))

        logger.info(
            f"WeatherMarketFilter initialized | "
            f"min_liquidity={self.min_liquidity} | "
            f"odds_range=[{self.min_odds}, {self.max_odds}] | "
            f"min_hours={self.min_time_to_resolution_hours} | "
            f"cities={len(self.allowed_cities)}"
        )

    def filter_market(self, market: WeatherMarket) -> FilterResult:
        """
        Apply all filter criteria to a single market.

        Supports multiple market types:
        - CITY_TEMPERATURE: City-specific temperature thresholds
        - GLOBAL_RANKING: Global temperature rankings (hottest year)
        - CLIMATE_METRIC: Arctic ice, hurricane count, etc.

        Args:
            market: Weather market to filter

        Returns:
            FilterResult with pass/fail status and details
        """
        rejection_reasons: List[str] = []
        filter_details: Dict[str, Any] = {}

        # =====================================================================
        # DETECT MARKET TYPE
        # =====================================================================
        market_type = self._detect_market_type(market)
        filter_details["market_type"] = market_type

        # =====================================================================
        # CHECK 1: Category is WEATHER
        # =====================================================================
        is_weather = self._check_weather_category(market)
        filter_details["is_weather_category"] = is_weather
        if not is_weather:
            rejection_reasons.append(
                f"CATEGORY: Not a weather market (category={market.category})"
            )

        # =====================================================================
        # CHECK 2: Market is binary
        # =====================================================================
        filter_details["is_binary"] = market.is_binary
        if not market.is_binary:
            rejection_reasons.append("BINARY: Market is not binary (yes/no)")

        # =====================================================================
        # CHECK 3: Sufficient liquidity
        # =====================================================================
        filter_details["liquidity_usd"] = market.liquidity_usd
        filter_details["min_liquidity"] = self.min_liquidity
        if market.liquidity_usd < self.min_liquidity:
            rejection_reasons.append(
                f"LIQUIDITY: ${market.liquidity_usd:.2f} < ${self.min_liquidity} minimum"
            )

        # =====================================================================
        # CHECK 4: Resolution time is far enough
        # =====================================================================
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        hours_to_resolution = (market.resolution_time - now).total_seconds() / 3600
        filter_details["hours_to_resolution"] = hours_to_resolution
        filter_details["min_hours"] = self.min_time_to_resolution_hours

        if hours_to_resolution < self.min_time_to_resolution_hours:
            rejection_reasons.append(
                f"TIME: {hours_to_resolution:.1f}h to resolution < "
                f"{self.min_time_to_resolution_hours}h minimum"
            )

        # =====================================================================
        # CHECK 5: Odds in valid range
        # =====================================================================
        filter_details["odds_yes"] = market.odds_yes
        filter_details["odds_range"] = [self.min_odds, self.max_odds]
        if market.odds_yes < self.min_odds:
            rejection_reasons.append(
                f"ODDS: {market.odds_yes:.4f} below minimum {self.min_odds}"
            )
        elif market.odds_yes > self.max_odds:
            rejection_reasons.append(
                f"ODDS: {market.odds_yes:.4f} above maximum {self.max_odds}"
            )

        # =====================================================================
        # CHECK 6: Market type specific validation
        # =====================================================================
        detected_city = self._detect_city(market)
        filter_details["detected_city"] = detected_city

        if market_type == "CITY_TEMPERATURE":
            # City-specific markets require city detection
            if detected_city is None:
                rejection_reasons.append("CITY: Could not detect city from market text")
            elif detected_city not in self.allowed_cities:
                rejection_reasons.append(
                    f"CITY: '{detected_city}' not in allowed cities"
                )

            # Also check for explicit temperature threshold
            resolution_check = self._check_resolution_explicit(market)
            filter_details["resolution_check"] = resolution_check
            if not resolution_check["is_explicit"]:
                rejection_reasons.append(
                    f"RESOLUTION: {resolution_check['reason']}"
                )

        elif market_type == "GLOBAL_RANKING":
            # Global ranking markets don't need city, but need ranking criteria
            ranking_check = self._check_ranking_explicit(market)
            filter_details["ranking_check"] = ranking_check
            if not ranking_check["is_explicit"]:
                rejection_reasons.append(
                    f"RANKING: {ranking_check['reason']}"
                )

        elif market_type == "CLIMATE_METRIC":
            # Climate metric markets need explicit measurement criteria
            metric_check = self._check_metric_explicit(market)
            filter_details["metric_check"] = metric_check
            if not metric_check["is_explicit"]:
                rejection_reasons.append(
                    f"METRIC: {metric_check['reason']}"
                )

        else:
            # Unknown type - require manual review
            rejection_reasons.append(f"TYPE: Unknown market type '{market_type}'")

        # =====================================================================
        # FINAL RESULT
        # =====================================================================
        passed = len(rejection_reasons) == 0

        # Populate detected fields if passed
        if passed:
            market.detected_city = detected_city
            market.detected_metric = market_type

            # Set threshold for CITY_TEMPERATURE markets
            if market_type == "CITY_TEMPERATURE":
                resolution_check = filter_details.get("resolution_check", {})
                market.detected_threshold = resolution_check.get("threshold_f")

        return FilterResult(
            passed=passed,
            market=market if passed else None,
            rejection_reasons=rejection_reasons,
            filter_details=filter_details,
        )

    def _detect_market_type(self, market: WeatherMarket) -> str:
        """
        Detect the type of weather market.

        Returns one of:
        - CITY_TEMPERATURE: City-specific temperature market
        - GLOBAL_RANKING: Global temperature ranking
        - CLIMATE_METRIC: Arctic ice, hurricane, etc.
        - UNKNOWN: Unrecognized type
        """
        text = f"{market.question} {market.description}".lower()

        # Check for global ranking keywords
        if any(kw in text for kw in ["hottest year", "coldest year", "warmest year",
                                      "hottest on record", "coldest on record",
                                      "1st hottest", "2nd hottest", "3rd hottest",
                                      "4th hottest", "5th hottest", "6th hottest"]):
            return "GLOBAL_RANKING"

        # Check for climate metric keywords
        if any(kw in text for kw in ["arctic", "sea ice", "ice extent",
                                      "hurricane", "tropical storm", "landfall",
                                      "tornado", "earthquake", "global temperature increase"]):
            return "CLIMATE_METRIC"

        # Check for temperature-related market (city validation happens in CHECK 6)
        if any(kw in text for kw in ["temperature", "high", "low", "degrees", "heat", "hot", "cold", "warm"]):
            return "CITY_TEMPERATURE"

        return "UNKNOWN"

    def _check_ranking_explicit(self, market: WeatherMarket) -> Dict[str, Any]:
        """
        Check if global ranking criteria are explicit.
        """
        text = f"{market.question} {market.description}".lower()

        # Check for explicit ranking position
        ranking_patterns = [
            r"(1st|first|2nd|second|3rd|third|4th|fourth|5th|fifth|6th|sixth)",
            r"(hottest|coldest|warmest|coolest)\s+(year|month|day)",
            r"on record",
        ]

        for pattern in ranking_patterns:
            if re.search(pattern, text, re.I):
                return {
                    "is_explicit": True,
                    "metric": "global_ranking",
                }

        return {
            "is_explicit": False,
            "reason": "No explicit ranking criteria found",
        }

    def _check_metric_explicit(self, market: WeatherMarket) -> Dict[str, Any]:
        """
        Check if climate metric criteria are explicit.
        """
        text = f"{market.question} {market.description}".lower()

        # Check for explicit measurement criteria
        metric_patterns = [
            (r"(\d+\.?\d*)\s*(million|m)\s*(square\s*)?(kilo)?", "ice_extent"),
            (r"(hurricane|tropical storm).*(landfall|form)", "hurricane"),
            (r"(category\s*\d|cat\s*\d)", "hurricane_category"),
            (r"(\d+)\s*(tornado|tornadoes)", "tornado_count"),
            (r"(\d+\.?\d*)\s*°?\s*[FC]", "temperature_increase"),
            (r"(magnitude|richter)\s*(\d+\.?\d*)", "earthquake"),
        ]

        for pattern, metric_type in metric_patterns:
            if re.search(pattern, text, re.I):
                return {
                    "is_explicit": True,
                    "metric": metric_type,
                }

        return {
            "is_explicit": False,
            "reason": "No explicit metric criteria found",
        }

    def filter_markets(
        self, markets: List[WeatherMarket]
    ) -> Tuple[List[WeatherMarket], List[FilterResult]]:
        """
        Filter multiple markets at once.

        Args:
            markets: List of markets to filter

        Returns:
            Tuple of (passed_markets, all_results)
        """
        passed_markets: List[WeatherMarket] = []
        all_results: List[FilterResult] = []

        for market in markets:
            result = self.filter_market(market)
            all_results.append(result)
            if result.passed and result.market:
                passed_markets.append(result.market)

        logger.info(
            f"Filtered {len(markets)} markets: "
            f"{len(passed_markets)} passed, {len(markets) - len(passed_markets)} rejected"
        )

        return passed_markets, all_results

    def _check_weather_category(self, market: WeatherMarket) -> bool:
        """
        Check if market is a weather category market.

        Uses both explicit category field and keyword detection.
        """
        # Check explicit category
        if market.category and "weather" in market.category.lower():
            return True

        # Check keywords in question/description
        combined_text = f"{market.question} {market.description}".lower()
        return any(kw in combined_text for kw in self.WEATHER_CATEGORY_KEYWORDS)

    def _detect_city(self, market: WeatherMarket) -> Optional[str]:
        """
        Detect city name from market text.

        Returns standardized city name or None if not detected.
        """
        combined_text = f"{market.question} {market.description}".lower()

        for pattern, city_name in self.CITY_PATTERNS.items():
            if pattern in combined_text:
                return city_name

        return None

    def _check_resolution_explicit(self, market: WeatherMarket) -> Dict[str, Any]:
        """
        Check if resolution criteria are explicit and verifiable.

        Requirements:
        - Must have a numeric threshold
        - Must specify temperature unit (F or C)
        - Must not contain vague terms

        Returns dict with:
        - is_explicit: bool
        - reason: str (if not explicit)
        - threshold_f: float (if detected, in Fahrenheit)
        - metric: str (if detected)
        """
        combined_text = f"{market.question} {market.resolution_text} {market.description}"

        # Check for vague terms that invalidate the market
        vague_terms = [
            "significant", "extreme", "unusual", "abnormal",
            "heavy", "light", "moderate", "severe",
            "approximately", "roughly", "about",
            "at our discretion", "may be adjusted",
        ]

        for vague in vague_terms:
            if vague.lower() in combined_text.lower():
                return {
                    "is_explicit": False,
                    "reason": f"Contains vague term: '{vague}'",
                }

        # Try to extract temperature threshold
        for pattern in self.TEMPERATURE_PATTERNS:
            match = pattern.search(combined_text)
            if match:
                groups = match.groups()

                # Extract threshold value
                threshold = None
                unit = None

                for group in groups:
                    if group is None:
                        continue
                    # Check if it's a number
                    try:
                        threshold = float(group)
                    except ValueError:
                        pass
                    # Check if it's a unit
                    if group.upper() in ('F', 'C'):
                        unit = group.upper()

                if threshold is not None and unit is not None:
                    # Convert to Fahrenheit if needed
                    if unit == 'C':
                        threshold_f = threshold * 9/5 + 32
                    else:
                        threshold_f = threshold

                    return {
                        "is_explicit": True,
                        "threshold_f": threshold_f,
                        "metric": "temperature",
                        "original_value": threshold,
                        "original_unit": unit,
                    }

        # No threshold detected
        return {
            "is_explicit": False,
            "reason": "No explicit temperature threshold found",
        }


# =============================================================================
# MODULE-LEVEL FUNCTION
# =============================================================================


def create_filter_from_config(config_path: str) -> WeatherMarketFilter:
    """
    Create a WeatherMarketFilter from a YAML config file.

    Args:
        config_path: Path to weather.yaml

    Returns:
        Configured WeatherMarketFilter instance
    """
    import yaml

    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)

    return WeatherMarketFilter(config)
