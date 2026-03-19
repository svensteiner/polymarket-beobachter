"""
Unit Tests - Edge Reversal (reine Funktionen)
"""
from __future__ import annotations

from datetime import datetime, timezone
from paper_trader.edge_reversal import _parse_resolution_date


class TestParseResolutionDate:
    def test_march_date_parsed(self):
        question = "Will the highest temperature in Dallas be above 70°F on March 25?"
        result = _parse_resolution_date(question)
        assert result is not None
        assert result.month == 3
        assert result.day == 25

    def test_february_date_parsed(self):
        question = "Will it snow in Boston on February 14?"
        result = _parse_resolution_date(question)
        assert result is not None
        assert result.month == 2
        assert result.day == 14

    def test_no_date_returns_none(self):
        question = "Will temperature in Miami exceed 85°F this summer?"
        result = _parse_resolution_date(question)
        assert result is None

    def test_result_is_utc_aware(self):
        question = "Will the temperature in Chicago be above 60°F on April 10?"
        result = _parse_resolution_date(question)
        assert result is not None
        assert result.tzinfo is not None

    def test_result_end_of_day(self):
        """Resolution date sollte auf 23:59 gesetzt sein (Market schließt EOD)."""
        question = "Will temperature exceed 90°F on July 4?"
        result = _parse_resolution_date(question)
        assert result is not None
        assert result.hour == 23
        assert result.minute == 59

    def test_case_insensitive(self):
        question = "Will it rain on march 15?"
        result = _parse_resolution_date(question)
        assert result is not None
        assert result.month == 3
        assert result.day == 15
