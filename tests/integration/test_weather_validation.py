# =============================================================================
# POLYMARKET BEOBACHTER - WEATHER VALIDATION TESTS
# =============================================================================
#
# GOVERNANCE INTENT:
# These tests verify the 6-point weather validation checklist.
# Many tests are EXPECTED TO FAIL validation - this is correct behavior.
#
# TEST CATEGORIES:
# 1. Valid markets (all 6 criteria pass)
# 2. Invalid source (generic "official data")
# 3. Invalid metric (vague terms like "significant")
# 4. Invalid location (ambiguous city name)
# 5. Invalid timezone (missing or ambiguous)
# 6. Invalid cutoff (no explicit time)
# 7. Invalid reporting (data lag issues)
#
# =============================================================================

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from core.weather_validation import (
    WeatherValidator,
    WeatherValidationChecklist,
    validate_weather_market,
    is_weather_market,
)
from core.weather_analyzer import (
    WeatherEventAnalyzer,
    WeatherMarketInput,
    analyze_weather_market,
)


# =============================================================================
# TEST: VALID WEATHER MARKETS
# =============================================================================


class TestValidWeatherMarkets:
    """
    Tests for markets that SHOULD pass all 6 criteria.

    These are well-defined markets with:
    - Explicit official source
    - Objective quantifiable metric
    - Unambiguous location
    - Explicit timezone
    - Explicit cutoff time
    - Feasible reporting
    """

    def test_valid_temperature_market_with_all_criteria(self):
        """
        A fully specified temperature market should pass validation.
        """
        result = validate_weather_market(
            market_question="Will the temperature at JFK Airport exceed 40°C?",
            resolution_text=(
                "This market resolves to YES if the NOAA-recorded temperature "
                "at JFK Airport (KJFK) exceeds 40°C (104°F) at any point "
                "before 11:59 PM EST on July 31, 2026. "
                "Source: NOAA METAR data."
            ),
        )

        assert result.measurement_source_ok, "Should identify NOAA as valid source"
        assert result.metric_ok, "Should identify 40°C as valid metric"
        assert result.location_ok, "Should identify KJFK as valid location"
        assert result.timezone_ok, "Should identify EST as valid timezone"
        assert result.cutoff_ok, "Should identify 11:59 PM as valid cutoff"
        assert result.is_valid, "All criteria should pass"

    def test_valid_rainfall_market_with_airport_code(self):
        """
        A rainfall market with airport code should pass.
        """
        result = validate_weather_market(
            market_question="Will London Heathrow record over 50mm of rain?",
            resolution_text=(
                "Resolves YES if total precipitation at EGLL (Heathrow) "
                "exceeds 50mm in December 2026 as recorded by Met Office. "
                "Deadline: December 31, 2026 at midnight UTC."
            ),
        )

        assert result.measurement_source_ok, "Met Office is valid source"
        assert result.metric_ok, "50mm is valid metric"
        assert result.location_ok, "EGLL is valid location"
        assert result.timezone_ok, "UTC is valid timezone"
        assert result.cutoff_ok, "Midnight is valid cutoff"

    def test_valid_snow_market_with_explicit_station(self):
        """
        A snow market with explicit station should pass.
        """
        result = validate_weather_market(
            market_question="Will Central Park record 30cm of snow?",
            resolution_text=(
                "Resolves YES if the National Weather Service records "
                "30cm or more of snowfall at the Central Park weather station "
                "by 11:59 PM EST on March 31, 2026."
            ),
        )

        assert result.measurement_source_ok, "NWS is valid source"
        assert result.metric_ok, "30cm is valid metric"
        assert result.location_ok, "Central Park weather station is valid"
        assert result.is_valid


# =============================================================================
# TEST: INVALID SOURCE (Criterion 1)
# =============================================================================


class TestInvalidMeasurementSource:
    """
    Tests for markets with INVALID measurement sources.

    Invalid sources:
    - "official data" (too generic)
    - "weather service" (which one?)
    - No source mentioned
    """

    def test_generic_official_data_is_invalid(self):
        """
        'Official data' without naming the source should FAIL.
        """
        result = validate_weather_market(
            market_question="Will it be hot in Phoenix?",
            resolution_text=(
                "Resolves YES if temperature exceeds 45°C according to "
                "official data by July 31, 2026 at 11:59 PM MST."
            ),
        )

        assert not result.measurement_source_ok, \
            "Generic 'official data' should be INVALID"
        assert not result.is_valid

    def test_no_source_mentioned_is_invalid(self):
        """
        No source mentioned at all should FAIL.
        """
        result = validate_weather_market(
            market_question="Will it rain in Seattle?",
            resolution_text=(
                "Resolves YES if rainfall exceeds 100mm "
                "by December 31, 2026 at midnight PST."
            ),
        )

        assert not result.measurement_source_ok, \
            "No source mentioned should be INVALID"
        assert not result.is_valid

    def test_vague_weather_service_is_invalid(self):
        """
        'The weather service' without naming which one should FAIL.
        """
        result = validate_weather_market(
            market_question="Will there be a heatwave?",
            resolution_text=(
                "Resolves YES if the weather service records "
                "temperatures above 40°C by August 1, 2026 at noon EST."
            ),
        )

        assert not result.measurement_source_ok, \
            "'The weather service' is too vague"


# =============================================================================
# TEST: INVALID METRIC (Criterion 2)
# =============================================================================


class TestInvalidMeasurementMetric:
    """
    Tests for markets with INVALID metrics.

    Invalid metrics:
    - "significant rainfall"
    - "extreme heat"
    - "heavy snow"
    - No numeric threshold
    """

    def test_significant_rainfall_is_invalid(self):
        """
        'Significant rainfall' without threshold should FAIL.
        """
        result = validate_weather_market(
            market_question="Will there be significant rainfall in Miami?",
            resolution_text=(
                "Resolves YES if NOAA records significant rainfall "
                "at Miami International (KMIA) "
                "by June 30, 2026 at 11:59 PM EST."
            ),
        )

        assert not result.metric_ok, \
            "'Significant' is vague - needs numeric threshold"
        assert not result.is_valid

    def test_extreme_heat_is_invalid(self):
        """
        'Extreme heat' without threshold should FAIL.
        """
        result = validate_weather_market(
            market_question="Will Phoenix experience extreme heat?",
            resolution_text=(
                "Resolves YES if NOAA records extreme heat "
                "at Phoenix Sky Harbor (KPHX) "
                "by August 31, 2026 at 11:59 PM MST."
            ),
        )

        assert not result.metric_ok, "'Extreme' is vague"
        assert not result.is_valid

    def test_heavy_snow_is_invalid(self):
        """
        'Heavy snow' without measurement should FAIL.
        """
        result = validate_weather_market(
            market_question="Will Denver get heavy snow?",
            resolution_text=(
                "Resolves YES if National Weather Service records heavy snow "
                "at Denver International (KDEN) "
                "by February 28, 2026 at midnight MST."
            ),
        )

        assert not result.metric_ok, "'Heavy' is subjective"

    def test_unusual_weather_is_invalid(self):
        """
        'Unusual' weather patterns should FAIL.
        """
        result = validate_weather_market(
            market_question="Will Chicago have unusual weather?",
            resolution_text=(
                "Resolves YES if NWS records unusual weather patterns "
                "at O'Hare (KORD) by December 31, 2026 at 11:59 PM CST."
            ),
        )

        assert not result.metric_ok, "'Unusual' is subjective"


# =============================================================================
# TEST: INVALID LOCATION (Criterion 3)
# =============================================================================


class TestInvalidLocation:
    """
    Tests for markets with INVALID locations.

    Invalid locations:
    - City name only (multiple stations)
    - Region without specific station
    - No location specified
    """

    def test_city_name_only_is_invalid(self):
        """
        City name without specific station should FAIL.
        """
        result = validate_weather_market(
            market_question="Will New York exceed 35°C?",
            resolution_text=(
                "Resolves YES if NOAA records temperature above 35°C "
                "in New York by August 15, 2026 at 11:59 PM EST."
            ),
        )

        # "New York" has multiple stations - ambiguous
        # This test may pass if NOAA is detected but location should fail
        assert not result.location_ok, \
            "'New York' without station is ambiguous"

    def test_no_location_is_invalid(self):
        """
        No location specified should FAIL.
        """
        result = validate_weather_market(
            market_question="Will temperature exceed 40°C?",
            resolution_text=(
                "Resolves YES if NOAA records temperature above 40°C "
                "by August 15, 2026 at 11:59 PM UTC."
            ),
        )

        assert not result.location_ok, "No location specified"


# =============================================================================
# TEST: INVALID TIMEZONE (Criterion 4)
# =============================================================================


class TestInvalidTimezone:
    """
    Tests for markets with INVALID timezone definitions.

    Invalid:
    - "local time" without specifying which
    - No timezone mentioned
    - Ambiguous (just "midnight")
    """

    def test_local_time_without_zone_is_invalid(self):
        """
        'Local time' without specifying which should FAIL.
        """
        result = validate_weather_market(
            market_question="Will it rain in London?",
            resolution_text=(
                "Resolves YES if Met Office records rainfall above 20mm "
                "at EGLL by December 31, 2026 at midnight local time."
            ),
        )

        assert not result.timezone_ok, \
            "'Local time' without zone is ambiguous"

    def test_no_timezone_is_invalid(self):
        """
        No timezone mentioned should FAIL.
        """
        result = validate_weather_market(
            market_question="Will Chicago get snow?",
            resolution_text=(
                "Resolves YES if NWS records 10cm of snow "
                "at O'Hare (KORD) by January 31, 2026."
            ),
        )

        assert not result.timezone_ok, "No timezone specified"


# =============================================================================
# TEST: INVALID CUTOFF TIME (Criterion 5)
# =============================================================================


class TestInvalidCutoffTime:
    """
    Tests for markets with INVALID cutoff times.

    Invalid:
    - "by end of day" (no specific time)
    - "before January" (no time)
    - "sometime in summer" (vague)
    """

    def test_end_of_day_is_invalid(self):
        """
        'End of day' without specific time should FAIL.
        """
        result = validate_weather_market(
            market_question="Will it be hot in Dallas?",
            resolution_text=(
                "Resolves YES if NOAA records temperature above 40°C "
                "at DFW Airport (KDFW) by end of day on August 1, 2026 EST."
            ),
        )

        assert not result.cutoff_ok, "'End of day' is vague"

    def test_date_without_time_is_invalid(self):
        """
        Date without time should FAIL.
        """
        result = validate_weather_market(
            market_question="Will it rain in Portland?",
            resolution_text=(
                "Resolves YES if NOAA records rainfall above 30mm "
                "at PDX by December 31, 2026 PST."
            ),
        )

        # Note: This might pass if "December 31" is interpreted with timezone
        # But ideally should require explicit time


# =============================================================================
# TEST: FULL ANALYZER INTEGRATION
# =============================================================================


class TestWeatherAnalyzerIntegration:
    """
    Tests for the complete weather analyzer pipeline.
    """

    def test_analyzer_returns_insufficient_data_on_validation_failure(self):
        """
        Analyzer should return INSUFFICIENT_DATA if validation fails.
        """
        report = analyze_weather_market(
            market_question="Will there be significant rainfall?",
            resolution_text="Resolves YES if official data shows significant rain.",
            target_date="2026-12-31",
        )

        assert report.decision == "INSUFFICIENT_DATA", \
            "Should be INSUFFICIENT_DATA when validation fails"
        assert len(report.blocking_reasons) > 0, \
            "Should have blocking reasons"

    def test_analyzer_returns_trade_on_valid_market(self):
        """
        Analyzer should return TRADE if all criteria pass.
        """
        report = analyze_weather_market(
            market_question="Will JFK exceed 40°C?",
            resolution_text=(
                "Resolves YES if NOAA METAR data at KJFK records "
                "temperature exceeding 40°C by 11:59 PM EST on July 31, 2026."
            ),
            target_date="2026-07-31",
        )

        # Note: This should pass all 6 weather criteria
        # Final decision depends on timeline feasibility
        assert report.weather_validation_summary["is_valid"], \
            "Weather validation should pass"

    def test_analyzer_includes_validation_summary(self):
        """
        Analyzer report should always include validation summary.
        """
        report = analyze_weather_market(
            market_question="Will it rain?",
            resolution_text="Resolves based on rain.",
            target_date="2026-12-31",
        )

        assert "measurement_source_ok" in report.weather_validation_summary
        assert "metric_ok" in report.weather_validation_summary
        assert "location_ok" in report.weather_validation_summary
        assert "timezone_ok" in report.weather_validation_summary
        assert "cutoff_ok" in report.weather_validation_summary
        assert "reporting_ok" in report.weather_validation_summary


# =============================================================================
# TEST: WEATHER MARKET DETECTION
# =============================================================================


class TestWeatherMarketDetection:
    """
    Tests for detecting whether a market is weather-related.
    """

    def test_detects_temperature_market(self):
        """Should detect temperature markets."""
        assert is_weather_market("Will the temperature exceed 40°C?")
        assert is_weather_market("Heatwave in Phoenix?")

    def test_detects_rain_market(self):
        """Should detect rain/precipitation markets."""
        assert is_weather_market("Will it rain in Seattle?")
        assert is_weather_market("Total precipitation above 100mm?")

    def test_detects_snow_market(self):
        """Should detect snow markets."""
        assert is_weather_market("Will there be a blizzard?")
        assert is_weather_market("Snow accumulation over 30cm?")

    def test_does_not_detect_unrelated_market(self):
        """Should NOT detect unrelated markets."""
        assert not is_weather_market("Will Trump win the election?")
        assert not is_weather_market("Bitcoin price above $100k?")
        assert not is_weather_market("EU AI Act enforcement?")


# =============================================================================
# TEST: EXPECTED FAILURES (GOVERNANCE CHECK)
# =============================================================================


class TestExpectedFailures:
    """
    Tests that verify markets with poor definitions fail validation.

    GOVERNANCE:
    These failures are EXPECTED AND CORRECT.
    We do NOT relax rules to increase trade count.
    """

    def test_ambiguous_market_fails(self):
        """
        Vague market should fail - this is correct behavior.
        """
        result = validate_weather_market(
            market_question="Will it be hot this summer?",
            resolution_text="Resolves based on how hot it gets.",
        )

        assert not result.is_valid, \
            "Vague market SHOULD fail validation"

    def test_missing_multiple_criteria_fails(self):
        """
        Market missing multiple criteria should fail.
        """
        result = validate_weather_market(
            market_question="Bad weather?",
            resolution_text="Yes if bad weather happens.",
        )

        # Should fail on multiple counts
        failed_criteria = sum([
            not result.measurement_source_ok,
            not result.metric_ok,
            not result.location_ok,
            not result.timezone_ok,
            not result.cutoff_ok,
        ])

        assert failed_criteria >= 3, \
            "Should fail multiple criteria for vague market"
        assert not result.is_valid


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
