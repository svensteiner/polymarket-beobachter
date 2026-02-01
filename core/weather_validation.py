# =============================================================================
# POLYMARKET BEOBACHTER - WEATHER EVENT VALIDATION
# =============================================================================
#
# GOVERNANCE INTENT:
# This module validates WEATHER_EVENT markets for STRUCTURAL TRADEABILITY.
# It does NOT predict weather outcomes.
# It does NOT use forecasts or weather APIs.
#
# CORE PRINCIPLE:
# We do NOT ask: "Will it rain / be hot / storm?"
# We ask: "Is it objectively and unambiguously MEASURABLE
#          whether this happened by the stated deadline?"
#
# VALIDATION CHECKLIST (ALL MUST PASS):
# 1. MEASUREMENT_SOURCE - Official source explicitly named
# 2. MEASUREMENT_METRIC - Objective, quantifiable metric
# 3. MEASUREMENT_LOCATION - Unambiguous location
# 4. TIMEZONE_DEFINITION - Explicit timezone
# 5. CUTOFF_TIME - Explicit date + time
# 6. REPORTING_FEASIBILITY - Data published in time
#
# IF ANY FAILS: Decision = INSUFFICIENT_DATA
#
# =============================================================================

import re
import logging
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any, Tuple
from enum import Enum

logger = logging.getLogger(__name__)


# =============================================================================
# DATA MODELS
# =============================================================================


@dataclass(frozen=True)
class WeatherValidationChecklist:
    """
    Result of the 6-point weather validation checklist.

    GOVERNANCE:
    All fields must be True for market to be VALID.
    Any False field results in INSUFFICIENT_DATA decision.
    """
    measurement_source_ok: bool
    metric_ok: bool
    location_ok: bool
    timezone_ok: bool
    cutoff_ok: bool
    reporting_ok: bool

    # Details for audit trail
    source_identified: Optional[str] = None
    metric_identified: Optional[str] = None
    location_identified: Optional[str] = None
    timezone_identified: Optional[str] = None
    cutoff_identified: Optional[str] = None
    reporting_lag_days: Optional[int] = None

    # Blocking reasons
    blocking_reasons: tuple = field(default_factory=tuple)

    @property
    def is_valid(self) -> bool:
        """Check if all 6 criteria passed."""
        return all([
            self.measurement_source_ok,
            self.metric_ok,
            self.location_ok,
            self.timezone_ok,
            self.cutoff_ok,
            self.reporting_ok,
        ])

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for logging."""
        return {
            "measurement_source_ok": self.measurement_source_ok,
            "metric_ok": self.metric_ok,
            "location_ok": self.location_ok,
            "timezone_ok": self.timezone_ok,
            "cutoff_ok": self.cutoff_ok,
            "reporting_ok": self.reporting_ok,
            "source_identified": self.source_identified,
            "metric_identified": self.metric_identified,
            "location_identified": self.location_identified,
            "timezone_identified": self.timezone_identified,
            "cutoff_identified": self.cutoff_identified,
            "reporting_lag_days": self.reporting_lag_days,
            "blocking_reasons": list(self.blocking_reasons),
            "is_valid": self.is_valid,
        }


# =============================================================================
# WEATHER VALIDATOR
# =============================================================================


class WeatherValidator:
    """
    Validates WEATHER_EVENT markets against the 6-point checklist.

    STRICT PRINCIPLE:
    This class does NOT:
    - Call weather APIs
    - Use forecasts
    - Estimate probabilities
    - Compare to meteorological models

    It ONLY validates:
    - Resolution clarity
    - Measurement definition
    - Timing feasibility
    """

    # =========================================================================
    # OFFICIAL MEASUREMENT SOURCES (explicit names required)
    # =========================================================================
    VALID_SOURCES = {
        # US
        "noaa", "national weather service", "nws",
        "national oceanic and atmospheric administration",
        # UK
        "met office", "uk met office",
        # Germany
        "dwd", "deutscher wetterdienst",
        # EU
        "ecmwf", "european centre for medium-range weather forecasts",
        "copernicus",
        # International
        "wmo", "world meteorological organization",
        # Airport codes (ICAO)
        "metar",
    }

    # Patterns for airport codes (e.g., KJFK, EGLL, EDDF)
    AIRPORT_CODE_PATTERN = re.compile(r'\b[A-Z]{4}\b')

    # =========================================================================
    # OBJECTIVE METRICS (explicit thresholds required)
    # =========================================================================
    VALID_METRIC_PATTERNS = [
        # Temperature
        re.compile(r'(\d+\.?\d*)\s*(°?[CF]|celsius|fahrenheit|degrees)', re.I),
        re.compile(r'temperature\s*(>=?|<=?|above|below|exceed)\s*(\d+)', re.I),
        # Rainfall / Precipitation
        re.compile(r'(\d+\.?\d*)\s*(mm|inch|inches|cm)\s*(of\s*)?(rain|precipitation|rainfall)', re.I),
        re.compile(r'(rain|precipitation|rainfall)\s*(>=?|<=?|above|exceed)\s*(\d+)', re.I),
        # Snow
        re.compile(r'(\d+\.?\d*)\s*(mm|inch|inches|cm|feet|ft)\s*(of\s*)?snow', re.I),
        re.compile(r'snow\s*(>=?|<=?|above|exceed|accumulation)\s*(\d+)', re.I),
        # Wind
        re.compile(r'(\d+\.?\d*)\s*(mph|km/h|knots|m/s)\s*(wind|gusts?)', re.I),
        re.compile(r'(wind|gusts?)\s*(>=?|<=?|above|exceed)\s*(\d+)', re.I),
        # Humidity
        re.compile(r'(\d+\.?\d*)\s*%\s*(humidity|relative humidity)', re.I),
    ]

    # VAGUE terms that INVALIDATE the metric
    # Note: These are checked with word boundaries to avoid false matches
    # e.g., "any" should match "any rain" but NOT "at any point"
    VAGUE_METRIC_TERMS = {
        "significant", "extreme", "unusual", "abnormal",
        "heavy", "light", "moderate", "severe",
        "a lot", "some", "considerable",
        "record-breaking", "historic", "unprecedented",
    }

    # Patterns for vague terms that need context checking
    VAGUE_METRIC_PATTERNS = [
        re.compile(r'\bany\s+(rain|snow|precipitation|weather|storm|heat|cold)', re.I),
    ]

    # =========================================================================
    # TIMEZONE PATTERNS
    # =========================================================================
    VALID_TIMEZONES = {
        # UTC variants
        "utc", "gmt", "zulu", "z",
        # US
        "est", "edt", "eastern", "cst", "cdt", "central",
        "mst", "mdt", "mountain", "pst", "pdt", "pacific",
        # EU
        "cet", "cest", "central european", "wet", "west european",
        "eet", "east european",
        # Explicit offset
    }
    TIMEZONE_OFFSET_PATTERN = re.compile(r'UTC[+-]\d{1,2}', re.I)

    # =========================================================================
    # CUTOFF TIME PATTERNS
    # =========================================================================
    EXPLICIT_TIME_PATTERNS = [
        # ISO datetime
        re.compile(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}', re.I),
        # Date + time
        re.compile(r'\d{1,2}[:/]\d{2}\s*(am|pm|hours?)?', re.I),
        re.compile(r'(midnight|noon|12:00)', re.I),
        # Explicit times
        re.compile(r'(\d{1,2})\s*(am|pm)\s*(on|by)?\s*', re.I),
        re.compile(r'(11:59|23:59)', re.I),
    ]

    # VAGUE cutoff terms
    VAGUE_CUTOFF_TERMS = {
        "end of day", "eod", "close of business", "cob",
        "by evening", "by morning", "by night",
        "sometime", "around", "approximately",
    }

    def __init__(self):
        """Initialize the weather validator."""
        pass

    def validate(
        self,
        market_question: str,
        resolution_text: str,
        description: str = "",
    ) -> WeatherValidationChecklist:
        """
        Validate a weather market against the 6-point checklist.

        GOVERNANCE:
        This method ONLY checks structural validity.
        It does NOT assess the likelihood of weather outcomes.

        Args:
            market_question: The market's main question
            resolution_text: The resolution criteria text
            description: Additional market description

        Returns:
            WeatherValidationChecklist with all 6 criteria results
        """
        full_text = f"{market_question} {resolution_text} {description}".lower()
        blocking_reasons: List[str] = []

        # ---------------------------------------------------------------------
        # CHECK 1: MEASUREMENT SOURCE
        # ---------------------------------------------------------------------
        source_ok, source_id = self._check_measurement_source(full_text)
        if not source_ok:
            blocking_reasons.append(
                "MEASUREMENT_SOURCE: No official source explicitly named. "
                "Generic terms like 'official data' are insufficient."
            )

        # ---------------------------------------------------------------------
        # CHECK 2: MEASUREMENT METRIC
        # ---------------------------------------------------------------------
        metric_ok, metric_id = self._check_measurement_metric(full_text)
        if not metric_ok:
            blocking_reasons.append(
                "MEASUREMENT_METRIC: No objective, quantifiable metric found. "
                "Vague terms like 'significant' or 'extreme' are invalid."
            )

        # ---------------------------------------------------------------------
        # CHECK 3: MEASUREMENT LOCATION
        # ---------------------------------------------------------------------
        location_ok, location_id = self._check_measurement_location(full_text)
        if not location_ok:
            blocking_reasons.append(
                "MEASUREMENT_LOCATION: Location is ambiguous or not specified. "
                "If multiple stations exist, resolution must specify which one."
            )

        # ---------------------------------------------------------------------
        # CHECK 4: TIMEZONE DEFINITION
        # ---------------------------------------------------------------------
        timezone_ok, timezone_id = self._check_timezone(full_text)
        if not timezone_ok:
            blocking_reasons.append(
                "TIMEZONE_DEFINITION: No explicit timezone defined. "
                "UTC vs local time ambiguity invalidates the market."
            )

        # ---------------------------------------------------------------------
        # CHECK 5: CUTOFF TIME
        # ---------------------------------------------------------------------
        cutoff_ok, cutoff_id = self._check_cutoff_time(full_text)
        if not cutoff_ok:
            blocking_reasons.append(
                "CUTOFF_TIME: No explicit cutoff time (date + time). "
                "'By end of day' without timezone is invalid."
            )

        # ---------------------------------------------------------------------
        # CHECK 6: REPORTING FEASIBILITY
        # ---------------------------------------------------------------------
        reporting_ok, lag_days = self._check_reporting_feasibility(
            full_text, source_id
        )
        if not reporting_ok:
            blocking_reasons.append(
                "REPORTING_FEASIBILITY: Publication lag likely exceeds "
                "resolution window. Data may not be available in time."
            )

        # Build result
        return WeatherValidationChecklist(
            measurement_source_ok=source_ok,
            metric_ok=metric_ok,
            location_ok=location_ok,
            timezone_ok=timezone_ok,
            cutoff_ok=cutoff_ok,
            reporting_ok=reporting_ok,
            source_identified=source_id,
            metric_identified=metric_id,
            location_identified=location_id,
            timezone_identified=timezone_id,
            cutoff_identified=cutoff_id,
            reporting_lag_days=lag_days,
            blocking_reasons=tuple(blocking_reasons),
        )

    def _check_measurement_source(
        self, text: str
    ) -> Tuple[bool, Optional[str]]:
        """
        Check if an official measurement source is explicitly named.

        Valid sources include:
        - Named national weather services (NOAA, Met Office, DWD)
        - ICAO airport codes (KJFK, EGLL, etc.)
        - International organizations (WMO, ECMWF)

        Invalid:
        - "official data" (too vague)
        - "weather service" without name
        - No source mentioned

        Returns:
            (is_valid, source_identified)
        """
        # Check for named sources
        for source in self.VALID_SOURCES:
            if source in text:
                return True, source.upper()

        # Check for ICAO airport codes
        airport_matches = self.AIRPORT_CODE_PATTERN.findall(text.upper())
        if airport_matches:
            # Validate it looks like a weather station code
            for code in airport_matches:
                if code.startswith(('K', 'E', 'L', 'C', 'P')):  # Common prefixes
                    return True, f"METAR:{code}"

        # "official" alone is NOT sufficient
        if "official" in text and not any(s in text for s in self.VALID_SOURCES):
            return False, None

        return False, None

    def _check_measurement_metric(
        self, text: str
    ) -> Tuple[bool, Optional[str]]:
        """
        Check if the metric is objective and quantifiable.

        Valid:
        - "temperature >= 40°C"
        - "rainfall exceeds 50mm"
        - "wind gusts above 100 mph"

        Invalid:
        - "significant rainfall"
        - "extreme heat"
        - "heavy snow"

        Returns:
            (is_valid, metric_identified)
        """
        # First check for disqualifying vague terms (use word boundaries to avoid false matches)
        for vague_term in self.VAGUE_METRIC_TERMS:
            # Use word boundary regex to avoid matching "some" in "handsome", etc.
            pattern = re.compile(rf'\b{re.escape(vague_term)}\b', re.I)
            if pattern.search(text):
                # Vague term found - INVALID
                return False, f"VAGUE:{vague_term}"

        # Check for vague patterns that need context (e.g., "any rain")
        for pattern in self.VAGUE_METRIC_PATTERNS:
            if pattern.search(text):
                return False, f"VAGUE:{pattern.pattern}"

        # Check for valid metric patterns
        for pattern in self.VALID_METRIC_PATTERNS:
            match = pattern.search(text)
            if match:
                return True, match.group(0)

        return False, None

    def _check_measurement_location(
        self, text: str
    ) -> Tuple[bool, Optional[str]]:
        """
        Check if the measurement location is unambiguous.

        Valid:
        - "at JFK Airport (KJFK)"
        - "London Heathrow official station"
        - "Central Park weather station"

        Invalid:
        - "New York" (multiple stations)
        - "London" (which station?)
        - No location specified

        Returns:
            (is_valid, location_identified)
        """
        # Check for ICAO airport codes (most unambiguous)
        # Valid ICAO codes start with specific prefixes:
        # K = USA, E = Northern Europe, L = Southern Europe, C = Canada, P = Pacific
        airport_matches = self.AIRPORT_CODE_PATTERN.findall(text.upper())
        for code in airport_matches:
            # Validate it's a real airport code prefix, not random 4-letter words
            if code.startswith(('K', 'E', 'L', 'C', 'P')):
                return True, code

        # Check for "station" or "airport" with qualifier
        station_pattern = re.compile(
            r'([\w\s]+)\s+(weather\s+)?station|'
            r'([\w\s]+)\s+airport|'
            r'station\s+(at|in|near)\s+([\w\s]+)',
            re.I
        )
        station_match = station_pattern.search(text)
        if station_match:
            return True, station_match.group(0).strip()

        # Check for specific named locations with qualifiers
        # Use word boundaries to avoid matching inside words (e.g., "ord" in "records")
        specific_location = re.compile(
            r'\b(central\s+park|heathrow|gatwick|jfk|lax|ord|'
            r'frankfurt\s+airport|munich\s+airport)\b',
            re.I
        )
        specific_match = specific_location.search(text)
        if specific_match:
            return True, specific_match.group(0)

        # Generic city names are NOT sufficient
        return False, None

    def _check_timezone(
        self, text: str
    ) -> Tuple[bool, Optional[str]]:
        """
        Check if timezone is explicitly defined.

        Valid:
        - "UTC"
        - "11:59 PM EST"
        - "local time (CET)"
        - "UTC+1"

        Invalid:
        - "local time" without specifying which
        - No timezone mentioned
        - Ambiguous (e.g., just "midnight")

        Returns:
            (is_valid, timezone_identified)
        """
        # Check for UTC offset pattern
        offset_match = self.TIMEZONE_OFFSET_PATTERN.search(text)
        if offset_match:
            return True, offset_match.group(0)

        # Check for named timezones
        for tz in self.VALID_TIMEZONES:
            if tz in text:
                return True, tz.upper()

        # "local time" without specification is INVALID
        if "local time" in text and not any(tz in text for tz in self.VALID_TIMEZONES):
            return False, "AMBIGUOUS:local_time"

        return False, None

    def _check_cutoff_time(
        self, text: str
    ) -> Tuple[bool, Optional[str]]:
        """
        Check if cutoff time is explicit (date + time).

        Valid:
        - "by 11:59 PM EST on January 15, 2026"
        - "2026-01-15T23:59:00Z"
        - "by midnight UTC on December 31"

        Invalid:
        - "by end of day"
        - "before January 15" (no time)
        - "sometime in January"

        Returns:
            (is_valid, cutoff_identified)
        """
        # First check for disqualifying vague terms
        for vague_term in self.VAGUE_CUTOFF_TERMS:
            if vague_term in text:
                return False, f"VAGUE:{vague_term}"

        # Check for explicit time patterns
        for pattern in self.EXPLICIT_TIME_PATTERNS:
            match = pattern.search(text)
            if match:
                return True, match.group(0)

        return False, None

    def _check_reporting_feasibility(
        self, text: str, source: Optional[str]
    ) -> Tuple[bool, Optional[int]]:
        """
        Check if measurement data will be published in time.

        Considers:
        - METAR data: Available within hours
        - NOAA daily summaries: 1-2 day lag
        - Monthly climate reports: 1-2 week lag

        If publication lag exceeds resolution window, INVALID.

        Returns:
            (is_valid, estimated_lag_days)
        """
        # METAR/airport data - very fast (hours)
        if source and ("METAR" in source or self.AIRPORT_CODE_PATTERN.search(source or "")):
            return True, 0

        # NOAA daily data - ~1-2 days
        if source and source.upper() in ("NOAA", "NWS", "NATIONAL WEATHER SERVICE"):
            return True, 2

        # If source is identified and standard, assume reasonable lag
        if source:
            return True, 3

        # No source identified - cannot assess feasibility
        return False, None


# =============================================================================
# MODULE-LEVEL FUNCTION
# =============================================================================


def validate_weather_market(
    market_question: str,
    resolution_text: str,
    description: str = "",
) -> WeatherValidationChecklist:
    """
    Convenience function to validate a weather market.

    GOVERNANCE:
    Returns INSUFFICIENT_DATA if any checklist item fails.
    This is by design - we do NOT relax rules to increase trade count.

    Args:
        market_question: The market's main question
        resolution_text: The resolution criteria text
        description: Additional market description

    Returns:
        WeatherValidationChecklist with validation results
    """
    validator = WeatherValidator()
    return validator.validate(market_question, resolution_text, description)


def is_weather_market(text: str) -> bool:
    """
    Detect if a market is likely a WEATHER_EVENT category.

    Simple keyword detection - does NOT validate the market.

    Args:
        text: Market question or description

    Returns:
        True if likely a weather market
    """
    weather_keywords = {
        "temperature", "rain", "rainfall", "precipitation",
        "snow", "snowfall", "wind", "hurricane", "tornado",
        "storm", "weather", "forecast", "climate", "heat",
        "cold", "freeze", "drought", "flood", "celsius",
        "fahrenheit", "humidity", "heatwave", "blizzard",
    }

    text_lower = text.lower()
    return any(kw in text_lower for kw in weather_keywords)
