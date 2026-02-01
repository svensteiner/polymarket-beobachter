# =============================================================================
# POLYMARKET EU AI COLLECTOR - Unit Tests
# =============================================================================
#
# Tests cover:
# - Keyword filtering (EU + AI matching)
# - Deadline extraction from various formats
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
from collector.filter import MarketFilter, FilterResult
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
            "question": "Will the EU AI Act be enforced?",
            "description": "This market resolves YES if...",
            "slug": "eu-ai-act",
            "endDate": "2025-06-01",
            "createdAt": "2024-01-15T10:00:00Z",
            "category": "Politics",
            "tags": [{"label": "EU"}, {"label": "AI"}],
        }

        sanitized, removed = self.sanitizer.sanitize(market)

        self.assertEqual(sanitized["id"], "123")
        self.assertEqual(sanitized["question"], "Will the EU AI Act be enforced?")
        self.assertEqual(sanitized["description"], "This market resolves YES if...")
        self.assertEqual(sanitized["slug"], "eu-ai-act")
        self.assertEqual(sanitized["endDate"], "2025-06-01")
        self.assertEqual(len(removed), 0)


class TestMarketFilter(unittest.TestCase):
    """Tests for the MarketFilter class."""

    def setUp(self):
        self.filter = MarketFilter()

    def test_includes_eu_ai_market(self):
        """Markets matching EU + AI keywords should be included."""
        market = {
            "question": "Will the EU AI Act be fully implemented by 2026?",
            "description": "Resolution based on Official Journal of the European Union",
            "endDate": "2026-08-02",
        }

        result = self.filter.filter_market(market)

        self.assertEqual(result.result, FilterResult.INCLUDED)
        self.assertTrue(len(result.matched_eu_keywords) > 0)
        self.assertTrue(len(result.matched_ai_keywords) > 0)
        self.assertIsNotNone(result.extracted_deadline)

    def test_excludes_no_eu_match(self):
        """Markets without EU keywords should be excluded."""
        market = {
            "question": "Will OpenAI release GPT-5 in 2025?",
            "description": "Resolves YES if OpenAI announces GPT-5",
            "endDate": "2025-12-31",
        }

        result = self.filter.filter_market(market)

        self.assertEqual(result.result, FilterResult.EXCLUDED_NO_EU_MATCH)

    def test_excludes_no_ai_match(self):
        """Markets without AI keywords should be excluded."""
        market = {
            "question": "Will the EU approve new trade agreement?",
            "description": "European Commission trade policy",
            "endDate": "2025-06-01",
        }

        result = self.filter.filter_market(market)

        self.assertEqual(result.result, FilterResult.EXCLUDED_NO_AI_MATCH)

    def test_excludes_price_markets(self):
        """Price/market performance markets should be excluded."""
        market = {
            "question": "Will Bitcoin price reach $100k in EU markets?",
            "description": "European AI trading platforms",
            "endDate": "2025-12-31",
        }

        result = self.filter.filter_market(market)

        self.assertEqual(result.result, FilterResult.EXCLUDED_PRICE_MARKET)

    def test_excludes_missing_deadline(self):
        """Markets without extractable deadline should be excluded."""
        market = {
            "question": "Will the EU regulate AI eventually?",
            "description": "European Union artificial intelligence laws",
            # No endDate field
        }

        result = self.filter.filter_market(market)

        self.assertEqual(result.result, FilterResult.EXCLUDED_NO_DEADLINE)

    def test_excludes_incomplete_data(self):
        """Markets with missing title should be excluded."""
        market = {
            "question": "",  # Empty title
            "description": "EU AI regulation",
            "endDate": "2025-06-01",
        }

        result = self.filter.filter_market(market)

        self.assertEqual(result.result, FilterResult.EXCLUDED_INCOMPLETE)


class TestDeadlineExtraction(unittest.TestCase):
    """Tests for deadline extraction from various formats."""

    def setUp(self):
        self.filter = MarketFilter()

    def test_extracts_iso_date(self):
        """Should extract ISO format dates."""
        # Note: Market needs EU + AI keywords to pass filter and extract deadline
        market = {
            "question": "EU AI Act Test",
            "description": "European Union Artificial Intelligence",
            "endDate": "2025-06-15"
        }
        result = self.filter.filter_market(market)
        self.assertEqual(result.extracted_deadline, date(2025, 6, 15))

    def test_extracts_iso_datetime(self):
        """Should extract ISO datetime and convert to date."""
        market = {
            "question": "EU AI Act Test",
            "description": "European Union Artificial Intelligence",
            "endDate": "2025-06-15T23:59:59Z"
        }
        result = self.filter.filter_market(market)
        self.assertEqual(result.extracted_deadline, date(2025, 6, 15))

    def test_extracts_from_text(self):
        """Should extract dates from resolution text."""
        market = {
            "question": "Will EU pass AI law by March 31, 2025?",
            "description": "European Union AI Act deadline"
        }
        result = self.filter.filter_market(market)
        # Should find "March 31, 2025" in the question
        self.assertIsNotNone(result.extracted_deadline)

    def test_extracts_year_only(self):
        """Should handle year-only dates (defaults to Dec 31)."""
        market = {
            "question": "Will EU regulate AI by 2026?",
            "description": "European Union artificial intelligence"
        }
        result = self.filter.filter_market(market)
        # Should extract 2026 as Dec 31, 2026
        if result.extracted_deadline:
            self.assertEqual(result.extracted_deadline.year, 2026)


class TestNormalizer(unittest.TestCase):
    """Tests for the MarketNormalizer class."""

    def setUp(self):
        self.normalizer = MarketNormalizer()

    def test_normalizes_complete_market(self):
        """Should create complete normalized record."""
        market = {
            "id": "abc123",
            "question": "Will EU AI Act be enforced?",
            "description": "Resolution criteria...",
            "endDate": "2025-06-01",
            "createdAt": "2024-01-15T10:00:00Z",
            "category": "Politics",
            "tags": [{"label": "EU"}, {"label": "AI"}],
            "slug": "eu-ai-act",
        }

        normalized = self.normalizer.normalize(market)

        self.assertEqual(normalized.market_id, "abc123")
        self.assertEqual(normalized.title, "Will EU AI Act be enforced?")
        self.assertEqual(normalized.resolution_text, "Resolution criteria...")
        self.assertEqual(normalized.end_date, "2025-06-01")
        self.assertIsNotNone(normalized.created_time)
        self.assertEqual(normalized.category, "Politics")
        self.assertEqual(normalized.tags, ["EU", "AI"])
        self.assertTrue(normalized.url.endswith("eu-ai-act"))
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

    def test_filter_excludes_ambiguous_market(self):
        """Ambiguous markets should be excluded."""
        market_filter = MarketFilter()

        # Market with EU + AI keywords but opinion/poll phrasing
        market = {
            "question": "Who will win the EU AI regulation debate?",
            "description": "European Union artificial intelligence policy polling",
            "endDate": "2025-06-01",
        }

        result = market_filter.filter_market(market)

        # Should be excluded as opinion market (contains "who will win", "polling")
        self.assertEqual(result.result, FilterResult.EXCLUDED_OPINION_MARKET)

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
            "question": "Will the European Union pass the AI Act by 2024?",
            "conditionId": "0xabcdef1234567890",
            "slug": "eu-ai-act-2024",
            "description": "This market resolves YES if the EU AI Act is published in the Official Journal.",
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
                    "title": "EU Regulation",
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
        self.assertEqual(sanitized["question"], "Will the European Union pass the AI Act by 2024?")
        self.assertEqual(sanitized["slug"], "eu-ai-act-2024")
        self.assertEqual(sanitized["endDate"], "2024-12-31T23:59:59Z")
        self.assertEqual(sanitized["events"][0]["id"], "event1")
        self.assertEqual(sanitized["events"][0]["title"], "EU Regulation")

        # Verify removal was tracked
        self.assertGreater(len(removed), 0)
        self.assertIn("price", removed)
        self.assertIn("volume", removed)


if __name__ == "__main__":
    unittest.main()
