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
from datetime import datetime, timezone
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
    detected_threshold_high: Optional[float] = None  # Upper bound for "between X-Y" markets
    detected_event_type: Optional[str] = None  # "exceeds", "below", or "between_range"
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
        "austin": "Austin",
        "madrid": "Madrid",
        "karachi": "Karachi",
        "chengdu": "Chengdu",
        "qingdao": "Qingdao",
        "helsinki": "Helsinki",
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
        self.min_liquidity = float(config.get("MIN_LIQUIDITY", 50))
        self.min_odds = float(config.get("MIN_ODDS", 0.01))
        self.max_odds = float(config.get("MAX_ODDS", 0.10))
        self.min_time_to_resolution_hours = float(config.get("MIN_TIME_TO_RESOLUTION_HOURS", 48))
        # No hard max — agent decides via LATE_STAGE_EDGE_BONUS
        self.max_time_to_resolution_hours = None
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
        res_time = market.resolution_time
        if hasattr(res_time, 'tzinfo') and res_time.tzinfo is not None:
            res_time = res_time.replace(tzinfo=None)
        hours_to_resolution = (res_time - now).total_seconds() / 3600
        filter_details["hours_to_resolution"] = hours_to_resolution
        filter_details["min_hours"] = self.min_time_to_resolution_hours

        if hours_to_resolution < self.min_time_to_resolution_hours:
            rejection_reasons.append(
                f"TIME: {hours_to_resolution:.1f}h to resolution < "
                f"{self.min_time_to_resolution_hours}h minimum"
            )

        # No hard max filter — LATE_STAGE_EDGE_BONUS steers agent toward <48h organically

        # =====================================================================
        # CHECK 5: Odds in valid range
        # =====================================================================
        # Boundary markets (at_or_above / at_or_below) naturally trade at high
        # YES prices when temperature clearly exceeds / falls below the threshold.
        # Allow these directional markets up to 0.90 YES to unlock YES-edge
        # observations that the standard 0.80 cap would filter.
        # Evidence: at_or_above WR=100%, at_or_below WR=50% — best market types.
        # The MIN_ENTRY_EDGE guard (12%) in the paper trader remains as safety net.
        _question_lower = (market.question or "").lower()
        _is_boundary_market = any(
            kw in _question_lower
            for kw in ("or higher", "or above", "or below", "or lower")
        )
        _effective_max_odds = 0.90 if _is_boundary_market else self.max_odds

        filter_details["odds_yes"] = market.odds_yes
        filter_details["odds_range"] = [self.min_odds, _effective_max_odds]
        filter_details["is_boundary_market"] = _is_boundary_market
        if market.odds_yes < self.min_odds:
            rejection_reasons.append(
                f"ODDS: {market.odds_yes:.4f} below minimum {self.min_odds}"
            )
        elif market.odds_yes > _effective_max_odds:
            rejection_reasons.append(
                f"ODDS: {market.odds_yes:.4f} above maximum {_effective_max_odds}"
                + (" (boundary market 0.90 cap)" if _is_boundary_market else "")
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
            else:
                # Only check threshold when city is valid (avoids LLM calls for non-city markets)
                resolution_check = self._check_resolution_explicit(market)
                filter_details["resolution_check"] = resolution_check
                if not resolution_check["is_explicit"]:
                    rejection_reasons.append(
                        f"RESOLUTION: {resolution_check['reason']}"
                    )

        else:
            # GLOBAL_RANKING, CLIMATE_METRIC, UNKNOWN — WeatherEngine only prices
            # city temperature thresholds; reject all other market types.
            rejection_reasons.append(
                f"TYPE: Only CITY_TEMPERATURE markets are supported (got '{market_type}')"
            )

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
                market.detected_threshold_high = resolution_check.get("threshold_f_high")
                market.detected_event_type = resolution_check.get("event_type", "exceeds")

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

        Uses word-boundary matching to avoid false positives:
        e.g., "la" must not match "dallas" or "atlanta".
        """
        combined_text = f"{market.question} {market.description}".lower()

        for pattern, city_name in self.CITY_PATTERNS.items():
            if re.search(r'\b' + re.escape(pattern) + r'\b', combined_text):
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

        # ---------------------------------------------------------------
        # Priority 1: "between X-Y°F/C" → interval market P(X <= T <= Y)
        # ---------------------------------------------------------------
        between_pattern = re.compile(r'between\s*(\d+\.?\d*)\s*-\s*(\d+\.?\d*)\s*°?\s*([FC])', re.I)
        between_match = between_pattern.search(combined_text)
        if between_match:
            low_val = float(between_match.group(1))
            high_val = float(between_match.group(2))
            unit = between_match.group(3).upper()
            if unit == 'C':
                low_f = low_val * 9/5 + 32
                high_f = high_val * 9/5 + 32
            else:
                low_f = low_val
                high_f = high_val
            return {
                "is_explicit": True,
                "threshold_f": low_f,
                "threshold_f_high": high_f,
                "metric": "temperature",
                "event_type": "between_range",
                "original_value": low_val,
                "original_unit": unit,
            }

        # ---------------------------------------------------------------
        # Priority 2: "be X°F or below/lower" → one-sided below market
        # ---------------------------------------------------------------
        below_be_pat = re.compile(r'\bbe\s+(\d+\.?\d*)\s*°?\s*([FC])\s+or\s+(?:below|lower)\b', re.I)
        below_be_match = below_be_pat.search(combined_text)
        if below_be_match:
            val = float(below_be_match.group(1))
            unit = below_be_match.group(2).upper()
            threshold_f = val * 9/5 + 32 if unit == 'C' else val
            return {
                "is_explicit": True,
                "threshold_f": threshold_f,
                "threshold_f_high": None,
                "metric": "temperature",
                "event_type": "below",
                "original_value": val,
                "original_unit": unit,
            }

        # ---------------------------------------------------------------
        # Priority 3: "be X°F or higher/above" → one-sided exceeds market
        # ---------------------------------------------------------------
        above_be_pat = re.compile(r'\bbe\s+(\d+\.?\d*)\s*°?\s*([FC])\s+or\s+(?:higher|above)\b', re.I)
        above_be_match = above_be_pat.search(combined_text)
        if above_be_match:
            val = float(above_be_match.group(1))
            unit = above_be_match.group(2).upper()
            threshold_f = val * 9/5 + 32 if unit == 'C' else val
            return {
                "is_explicit": True,
                "threshold_f": threshold_f,
                "threshold_f_high": None,
                "metric": "temperature",
                "event_type": "exceeds",
                "original_value": val,
                "original_unit": unit,
            }

        # ---------------------------------------------------------------
        # Priority 4: "be X°F/C" with no directional modifier
        #              → narrow 1-degree band: P(X <= T < X+1)
        # This is how Polymarket weather markets work: "be 22°C" means
        # the high temperature falls exactly in the 22-23°C range.
        # ---------------------------------------------------------------
        exact_be_pat = re.compile(
            r'\bbe\s+(\d+\.?\d*)\s*°?\s*([FC])(?!\s*(?:or|to|\+|-))', re.I
        )
        exact_be_match = exact_be_pat.search(combined_text)
        if exact_be_match:
            val = float(exact_be_match.group(1))
            unit = exact_be_match.group(2).upper()
            if unit == 'C':
                low_f = val * 9/5 + 32
                high_f = (val + 1) * 9/5 + 32
            else:
                low_f = val
                high_f = val + 1
            return {
                "is_explicit": True,
                "threshold_f": low_f,
                "threshold_f_high": high_f,
                "metric": "temperature",
                "event_type": "between_range",
                "original_value": val,
                "original_unit": unit,
            }

        # ---------------------------------------------------------------
        # Priority 5: One-sided patterns (above/exceed/below/reach)
        # ---------------------------------------------------------------
        for pattern in self.TEMPERATURE_PATTERNS:
            match = pattern.search(combined_text)
            if match:
                groups = match.groups()
                threshold = None
                unit = None
                has_below = False

                groups_str = [g for g in groups if g is not None]
                for group in groups_str:
                    try:
                        threshold = float(group)
                    except ValueError:
                        pass
                    if group.upper() in ('F', 'C'):
                        unit = group.upper()
                    if group.lower() in ('below', 'lower', 'under'):
                        has_below = True

                if threshold is not None and unit is not None:
                    if unit == 'C':
                        threshold_f = threshold * 9/5 + 32
                    else:
                        threshold_f = threshold
                    return {
                        "is_explicit": True,
                        "threshold_f": threshold_f,
                        "threshold_f_high": None,
                        "metric": "temperature",
                        "event_type": "below" if has_below else "exceeds",
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
