"""
Unit Tests - Arbitrage Detector
"""
from __future__ import annotations

import pytest
from analytics.arbitrage_detector import (
    _extract_temperature_threshold,
    _extract_city_from_question,
    parse_market_info,
    detect_arbitrage,
)


class TestExtractTemperatureThreshold:
    def test_fahrenheit_above(self):
        val, direction = _extract_temperature_threshold("Will temperature exceed 95°F?")
        assert val == pytest.approx(95.0)
        assert direction == "above"

    def test_celsius_converted_to_fahrenheit(self):
        val, direction = _extract_temperature_threshold("Will it be above 30°C?")
        expected = 30 * 9 / 5 + 32  # 86°F
        assert val == pytest.approx(expected, abs=0.5)

    def test_below_direction(self):
        _, direction = _extract_temperature_threshold("Will temperature be below 32°F?")
        assert direction == "below"

    def test_no_threshold_returns_none(self):
        val, _ = _extract_temperature_threshold("Will it rain tomorrow?")
        assert val is None


class TestExtractCity:
    def test_known_city_detected(self):
        city = _extract_city_from_question("Will the highest temperature in London be above 20°C?")
        assert city == "London"

    def test_dallas_not_detected_as_la(self):
        """Regression: 'la' substring in 'dallas' must not return LA."""
        city = _extract_city_from_question("Will the temperature in Dallas reach 90°F?")
        assert city == "Dallas"
        assert "Los Angeles" not in str(city)

    def test_atlanta_not_detected_as_la(self):
        city = _extract_city_from_question("Will the temperature in Atlanta be above 80°F?")
        assert city == "Atlanta"

    def test_unknown_city_returns_none_or_parsed(self):
        result = _extract_city_from_question("Will it rain with no city mentioned?")
        # Either None or some value - just shouldn't crash
        assert result is None or isinstance(result, str)


class TestDetectArbitrage:
    def _make_market_info(self, city, threshold_f, direction, odds_yes, resolution="march 20"):
        from analytics.arbitrage_detector import WeatherMarketInfo
        return WeatherMarketInfo(
            market_id=f"test-{city}-{threshold_f}",
            question=f"Will temperature in {city} be {direction} {threshold_f}F on {resolution}?",
            city=city,
            threshold_f=threshold_f,
            direction=direction,
            odds_yes=odds_yes,
            resolution_date=resolution,
        )

    def test_no_arbitrage_when_consistent(self):
        """P(>60F) > P(>65F) ist konsistent → keine Arbitrage."""
        markets = [
            self._make_market_info("Dallas", 60.0, "above", 0.70),
            self._make_market_info("Dallas", 65.0, "above", 0.50),
        ]
        opps = detect_arbitrage(markets, min_inconsistency=0.02)
        assert len(opps) == 0

    def test_arbitrage_detected_when_higher_threshold_has_higher_odds(self):
        """P(>65F) > P(>60F) ist logisch falsch → Arbitrage."""
        markets = [
            self._make_market_info("Dallas", 60.0, "above", 0.40),
            self._make_market_info("Dallas", 65.0, "above", 0.60),
        ]
        opps = detect_arbitrage(markets, min_inconsistency=0.02)
        assert len(opps) == 1
        assert opps[0].city == "Dallas"
        assert opps[0].inconsistency_magnitude == pytest.approx(0.20, abs=0.01)

    def test_different_cities_no_cross_arbitrage(self):
        """Märkte verschiedener Städte sollen nicht als Paar geprüft werden."""
        markets = [
            self._make_market_info("London", 60.0, "above", 0.40),
            self._make_market_info("Paris", 65.0, "above", 0.70),
        ]
        opps = detect_arbitrage(markets, min_inconsistency=0.02)
        assert len(opps) == 0

    def test_single_market_no_arbitrage(self):
        markets = [self._make_market_info("Tokyo", 25.0, "above", 0.50)]
        opps = detect_arbitrage(markets)
        assert len(opps) == 0

    def test_below_inconsistency_threshold_not_reported(self):
        """Kleine Inkonsistenz unter min_inconsistency wird ignoriert."""
        markets = [
            self._make_market_info("Miami", 80.0, "above", 0.40),
            self._make_market_info("Miami", 85.0, "above", 0.41),
        ]
        opps = detect_arbitrage(markets, min_inconsistency=0.05)
        assert len(opps) == 0
