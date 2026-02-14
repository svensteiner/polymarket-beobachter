# =============================================================================
# POLYMARKET WEATHER COLLECTOR - Unit Tests
# =============================================================================
#
# Tests cover:
# - Weather keyword filtering
# - Price/probability field exclusion (CRITICAL)
# - Fail-closed behavior for incomplete data
# - Contract test for raw response sanitization
#
# =============================================================================

import unittest
import json
from datetime import date
from pathlib import Path

# Import collector modules
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from collector.sanitizer import Sanitizer
from collector.filter import MarketFilter, FilterResult, FilteredMarket
from collector.normalizer import MarketNormalizer, NormalizedMarket


class TestSanitizer(unittest.TestCase):
    """Tests for the Sanitizer class."""

    def setUp(self):
        self.sanitizer = Sanitizer(log_removals=False)

    def test_removes_price_fields(self):
        """CRITICAL: Price fields must NEVER be stored."""
        market = {
            "id": "123",
            "question": "Test market",
            "price": 0.75,
            "lastTradePrice": 0.74,
            "bestBid": 0.73,
            "bestAsk": 0.76,
        }

        sanitized, removed = self.sanitizer.sanitize(market)

        # Assert forbidden fields are removed
        self.assertNotIn("price", sanitized)
        self.assertNotIn("lastTradePrice", sanitized)
        self.assertNotIn("bestBid", sanitized)
        self.assertNotIn("bestAsk", sanitized)

        # Assert allowed fields remain
        self.assertEqual(sanitized["id"], "123")
        self.assertEqual(sanitized["question"], "Test market")

        # Assert removal was tracked
        self.assertIn("price", removed)
        self.assertIn("lastTradePrice", removed)

    def test_removes_volume_fields(self):
        """CRITICAL: Volume fields must NEVER be stored."""
        market = {
            "id": "123",
            "volume": 1000000,
            "volume24hr": 50000,
            "volume1wk": 200000,
            "volumeNum": 1000000,
            "volumeAmm": 500000,
            "volumeClob": 500000,
        }

        sanitized, removed = self.sanitizer.sanitize(market)

        for field in ["volume", "volume24hr", "volume1wk", "volumeNum", "volumeAmm", "volumeClob"]:
            self.assertNotIn(field, sanitized, f"Field '{field}' should be removed")

    def test_removes_liquidity_fields(self):
        """CRITICAL: Liquidity fields must NEVER be stored."""
        market = {
            "id": "123",
            "liquidity": 50000,
            "liquidityNum": 50000,
            "liquidityAmm": 25000,
            "liquidityClob": 25000,
        }

        sanitized, removed = self.sanitizer.sanitize(market)

        for field in ["liquidity", "liquidityNum", "liquidityAmm", "liquidityClob"]:
            self.assertNotIn(field, sanitized, f"Field '{field}' should be removed")

    def test_removes_probability_fields(self):
        """CRITICAL: Probability fields must NEVER be stored."""
        market = {
            "id": "123",
            "probability": 0.65,
            "impliedProbability": 0.65,
            "outcomePrices": "[0.65, 0.35]",
            "odds": 1.54,
        }

        sanitized, removed = self.sanitizer.sanitize(market)

        for field in ["probability", "impliedProbability", "outcomePrices", "odds"]:
            self.assertNotIn(field, sanitized, f"Field '{field}' should be removed")

    def test_removes_nested_forbidden_fields(self):
        """CRITICAL: Nested forbidden fields must also be removed."""
        market = {
            "id": "123",
            "events": [
                {
                    "id": "event1",
                    "volume": 100000,
                    "price": 0.5,
                }
            ],
            "nested": {
                "liquidity": 50000,
                "deep": {
                    "probability": 0.7,
                }
            }
        }

        sanitized, removed = self.sanitizer.sanitize(market)

        # Check nested structures
        self.assertNotIn("volume", sanitized["events"][0])
        self.assertNotIn("price", sanitized["events"][0])
        self.assertNotIn("liquidity", sanitized["nested"])
        self.assertNotIn("probability", sanitized["nested"]["deep"])

        # Allowed fields should remain
        self.assertEqual(sanitized["events"][0]["id"], "event1")

    def test_preserves_allowed_fields(self):
        """Allowed fields should not be removed."""
        market = {
            "id": "123",
            "question": "Will New York temperature exceed 100F tomorrow?",
            "description": "This market resolves YES if...",
            "slug": "nyc-weather",
            "endDate": "2025-06-01",
            "createdAt": "2024-01-15T10:00:00Z",
            "category": "Weather",
            "tags": [{"label": "weather"}, {"label": "NYC"}],
        }

        sanitized, removed = self.sanitizer.sanitize(market)

        self.assertEqual(sanitized["id"], "123")
        self.assertEqual(sanitized["question"], "Will New York temperature exceed 100F tomorrow?")
        self.assertEqual(sanitized["description"], "This market resolves YES if...")
        self.assertEqual(sanitized["slug"], "nyc-weather")
        self.assertEqual(sanitized["endDate"], "2025-06-01")
        self.assertEqual(len(removed), 0)


class TestMarketFilter(unittest.TestCase):
    """Tests for the MarketFilter class - WEATHER ONLY."""

    def setUp(self):
        self.filter = MarketFilter()

    def test_includes_weather_temperature_market(self):
        """Markets with temperature keywords should be included."""
        market = {
            "title": "Will New York temperature exceed 100F tomorrow?",
            "description": "Resolves YES if NOAA reports temperature above 100 degrees Fahrenheit in NYC.",
        }

        result = self.filter.filter_market(market)

        self.assertEqual(result.result, FilterResult.INCLUDED_WEATHER)
        self.assertTrue(len(result.matched_keywords) >= 2)

    def test_includes_weather_rain_market(self):
        """Markets with rain keywords should be included."""
        market = {
            "title": "Will it rain in Chicago tomorrow?",
            "description": "Weather forecast prediction market",
        }

        result = self.filter.filter_market(market)

        self.assertEqual(result.result, FilterResult.INCLUDED_WEATHER)

    def test_includes_weather_snow_market(self):
        """Markets with snow keywords should be included."""
        market = {
            "title": "Will Denver get snow this weekend?",
            "description": "National Weather Service forecast for precipitation",
        }

        result = self.filter.filter_market(market)

        self.assertEqual(result.result, FilterResult.INCLUDED_WEATHER)

    def test_excludes_non_weather_market(self):
        """Markets without weather keywords should be excluded."""
        market = {
            "title": "Will Bitcoin reach $100k by 2026?",
            "description": "Cryptocurrency price prediction",
        }

        result = self.filter.filter_market(market)

        self.assertEqual(result.result, FilterResult.EXCLUDED_NOT_WEATHER)

    def test_excludes_politics_market(self):
        """Political markets should be excluded."""
        market = {
            "title": "Will Trump win the 2024 election?",
            "description": "US presidential race prediction",
        }

        result = self.filter.filter_market(market)

        self.assertEqual(result.result, FilterResult.EXCLUDED_NOT_WEATHER)

    def test_excludes_crypto_market(self):
        """Crypto markets should be excluded even with weather-like phrasing."""
        market = {
            "title": "Will Bitcoin price storm past $100k?",
            "description": "Crypto forecast for Bitcoin price",
        }

        result = self.filter.filter_market(market)

        self.assertEqual(result.result, FilterResult.EXCLUDED_NOT_WEATHER)

    def test_requires_multiple_indicators(self):
        """Markets need at least 2 weather indicators to be included."""
        market = {
            "title": "Random market about humidity",
            "description": "Nothing specific here about anything",
        }

        result = self.filter.filter_market(market)

        # Should be excluded - only 1 weather indicator (humidity)
        # Need 2+ indicators to be included
        self.assertEqual(result.result, FilterResult.EXCLUDED_NOT_WEATHER)

    def test_filter_markets_batch(self):
        """Should correctly filter a batch of markets."""
        markets = [
            {"title": "NYC temperature 100F", "description": "weather forecast"},
            {"title": "Bitcoin price prediction", "description": "crypto market"},
            {"title": "Chicago rain tomorrow", "description": "weather event"},
        ]

        filtered, counts = self.filter.filter_markets(markets)

        self.assertEqual(counts["total"], 3)
        self.assertEqual(counts["included_weather"], 2)
        self.assertEqual(counts["excluded_not_weather"], 1)


class TestNormalizer(unittest.TestCase):
    """Tests for the MarketNormalizer class."""

    def setUp(self):
        self.normalizer = MarketNormalizer()

    def test_normalizes_complete_market(self):
        """Should create complete normalized record."""
        market = {
            "id": "abc123",
            "question": "Will NYC temperature exceed 100F?",
            "description": "Resolution criteria...",
            "endDate": "2025-06-01",
            "createdAt": "2024-01-15T10:00:00Z",
            "category": "Weather",
            "tags": [{"label": "weather"}, {"label": "NYC"}],
            "slug": "nyc-temperature",
        }

        normalized = self.normalizer.normalize(market)

        self.assertEqual(normalized.market_id, "abc123")
        self.assertEqual(normalized.title, "Will NYC temperature exceed 100F?")
        self.assertEqual(normalized.resolution_text, "Resolution criteria...")
        self.assertEqual(normalized.end_date, "2025-06-01")
        self.assertIsNotNone(normalized.created_time)
        self.assertEqual(normalized.category, "Weather")
        self.assertEqual(normalized.tags, ["weather", "NYC"])
        self.assertTrue(normalized.url.endswith("nyc-temperature"))
        self.assertTrue(normalized.is_complete())

    def test_marks_incomplete_record(self):
        """Should mark records with missing fields as incomplete."""
        market = {
            "id": "abc123",
            # Missing question/title
            # Missing description
            # Missing endDate
        }

        normalized = self.normalizer.normalize(market)

        self.assertFalse(normalized.is_complete())
        self.assertIn("missing_title", normalized.collector_notes)
        self.assertIn("missing_resolution_text", normalized.collector_notes)
        self.assertIn("missing_end_date", normalized.collector_notes)

    def test_uses_extracted_deadline(self):
        """Should use filter-extracted deadline if provided."""
        market = {
            "id": "abc123",
            "question": "Test market",
            "description": "Description",
        }
        extracted = date(2025, 8, 15)

        normalized = self.normalizer.normalize(market, extracted_deadline=extracted)

        self.assertEqual(normalized.end_date, "2025-08-15")


class TestFailClosedBehavior(unittest.TestCase):
    """Tests for fail-closed behavior."""

    def test_normalizer_flags_missing_fields(self):
        """Normalizer should flag all missing required fields."""
        normalizer = MarketNormalizer()

        market = {}  # Completely empty

        normalized = normalizer.normalize(market)

        self.assertFalse(normalized.is_complete())
        self.assertIn("missing_market_id", normalized.collector_notes)
        self.assertIn("missing_title", normalized.collector_notes)
        self.assertIn("missing_resolution_text", normalized.collector_notes)
        self.assertIn("missing_end_date", normalized.collector_notes)

    def test_filter_handles_empty_market(self):
        """Filter should handle empty market data gracefully."""
        market_filter = MarketFilter()

        market = {}  # Empty

        result = market_filter.filter_market(market)

        # Should be excluded, not crash
        self.assertEqual(result.result, FilterResult.EXCLUDED_NOT_WEATHER)

    def test_filter_handles_none_fields(self):
        """Filter should handle None fields gracefully."""
        market_filter = MarketFilter()

        market = {
            "title": None,
            "description": None,
            "resolution_text": None,
        }

        result = market_filter.filter_market(market)

        # Should be excluded, not crash
        self.assertEqual(result.result, FilterResult.EXCLUDED_NOT_WEATHER)


class TestContractSanitization(unittest.TestCase):
    """Contract test: verify sanitization of realistic API response."""

    def test_sanitize_realistic_response(self):
        """
        Contract test: Load a realistic API response structure
        and verify all forbidden fields are removed.
        """
        # Simulate a realistic Polymarket API response
        raw_response = {
            "id": "0x1234567890abcdef",
            "question": "Will NYC temperature exceed 100F tomorrow?",
            "conditionId": "0xabcdef1234567890",
            "slug": "nyc-weather",
            "description": "This market resolves YES if NOAA reports temp above 100F.",
            "endDate": "2024-12-31T23:59:59Z",
            "createdAt": "2024-01-01T00:00:00Z",
            "active": True,
            "closed": False,
            # FORBIDDEN FIELDS - must be removed
            "price": 0.72,
            "lastTradePrice": 0.71,
            "bestBid": 0.70,
            "bestAsk": 0.73,
            "volume": 1500000,
            "volume24hr": 75000,
            "volume1wk": 300000,
            "volumeNum": 1500000,
            "liquidity": 250000,
            "liquidityNum": 250000,
            "outcomePrices": "[0.72, 0.28]",
            "clobRewards": [{"amount": 100}],
            "makerBaseFee": 0.001,
            "takerBaseFee": 0.002,
            "score": 95.5,
            # Nested forbidden fields
            "events": [
                {
                    "id": "event1",
                    "title": "Weather Event",
                    "volume": 500000,
                    "liquidity": 100000,
                }
            ],
        }

        sanitizer = Sanitizer(log_removals=False)
        sanitized, removed = sanitizer.sanitize(raw_response)

        # Assert ALL forbidden fields are removed from root
        forbidden_root_fields = [
            "price", "lastTradePrice", "bestBid", "bestAsk",
            "volume", "volume24hr", "volume1wk", "volumeNum",
            "liquidity", "liquidityNum", "outcomePrices",
            "clobRewards", "makerBaseFee", "takerBaseFee", "score",
        ]
        for field in forbidden_root_fields:
            self.assertNotIn(
                field, sanitized,
                f"CRITICAL: Forbidden field '{field}' was not removed!"
            )

        # Assert forbidden fields removed from nested structures
        self.assertNotIn("volume", sanitized["events"][0])
        self.assertNotIn("liquidity", sanitized["events"][0])

        # Assert allowed fields preserved
        self.assertEqual(sanitized["id"], "0x1234567890abcdef")
        self.assertEqual(sanitized["question"], "Will NYC temperature exceed 100F tomorrow?")
        self.assertEqual(sanitized["slug"], "nyc-weather")
        self.assertEqual(sanitized["endDate"], "2024-12-31T23:59:59Z")
        self.assertEqual(sanitized["events"][0]["id"], "event1")
        self.assertEqual(sanitized["events"][0]["title"], "Weather Event")

        # Verify removal was tracked
        self.assertGreater(len(removed), 0)
        self.assertIn("price", removed)
        self.assertIn("volume", removed)


if __name__ == "__main__":
    unittest.main()
