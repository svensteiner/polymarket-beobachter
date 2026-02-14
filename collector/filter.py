# =============================================================================
# WEATHER OBSERVER - MARKET FILTER
# =============================================================================
#
# WEATHER-ONLY FILTER
#
# Filters Polymarket markets to find weather-related markets only.
# Uses the multi-signal WeatherMarketClassifier for accurate detection.
#
# Classification levels:
# - WEATHER_CONFIRMED: Proceed to weather analysis
# - WEATHER_POSSIBLE: Log for review, do not process
# - NOT_WEATHER: Reject
#
# =============================================================================

import logging
from typing import Dict, Any, List, Tuple
from dataclasses import dataclass
from enum import Enum
from datetime import datetime

# Import the classifier
from core.weather_market_classifier import (
    WeatherMarketClassifier,
    WeatherClassification,
    ClassificationResult,
)

logger = logging.getLogger(__name__)


class FilterResult(Enum):
    """Result of filtering a market."""
    INCLUDED_WEATHER = "included_weather"
    POSSIBLE_WEATHER = "possible_weather"
    EXCLUDED_NOT_WEATHER = "excluded_not_weather"
    EXCLUDED_INCOMPLETE = "excluded_incomplete"


@dataclass
class FilteredMarket:
    """Result of filtering a single market."""
    market: Dict[str, Any]
    result: FilterResult
    matched_keywords: List[str]
    notes: List[str]
    classification_result: ClassificationResult = None


class MarketFilter:
    """
    Filters markets for weather relevance using multi-signal classification.

    WEATHER-ONLY:
    - Temperature thresholds
    - Rain/snow/precipitation occurrence
    - Hurricane/storm events
    - Other measurable meteorological events

    Uses WeatherMarketClassifier for accurate detection with:
    - Textual signals (temperature, rain, snow, hurricane, etc.)
    - Structural signals (category, resolution source, location+date)
    - Negative filters (politics, sports, finance, etc.)
    """

    def __init__(self):
        """Initialize the weather filter with classifier."""
        self._classifier = WeatherMarketClassifier()

    def filter_market(self, market: Dict[str, Any]) -> FilteredMarket:
        """
        Filter a single market for weather relevance.

        Args:
            market: Raw market data

        Returns:
            FilteredMarket with result and metadata
        """
        # Classify the market
        classification = self._classifier.classify_market(market)

        # Map classification to filter result
        if classification.classification == WeatherClassification.WEATHER_CONFIRMED:
            result = FilterResult.INCLUDED_WEATHER
            notes = [
                "weather_confirmed",
                f"confidence={classification.confidence_score:.2f}",
            ]
            matched_keywords = (
                classification.matched_text_signals +
                classification.matched_structural_signals
            )

            logger.debug(
                f"INCLUDED: {classification.market_id} | "
                f"{classification.market_title[:60] if classification.market_title else 'N/A'} | "
                f"signals={matched_keywords}"
            )

        elif classification.classification == WeatherClassification.WEATHER_POSSIBLE:
            result = FilterResult.POSSIBLE_WEATHER
            notes = [
                "weather_possible",
                f"reason={classification.rejection_reason}",
            ]
            matched_keywords = (
                classification.matched_text_signals +
                classification.matched_structural_signals
            )

            logger.info(
                f"POSSIBLE: {classification.market_id} | "
                f"{classification.market_title[:60] if classification.market_title else 'N/A'} | "
                f"text_signals={classification.matched_text_signals} | "
                f"structural_signals={classification.matched_structural_signals}"
            )

        else:
            result = FilterResult.EXCLUDED_NOT_WEATHER
            notes = [classification.rejection_reason or "No weather signals"]
            matched_keywords = []

            # Only log interesting rejections (not obvious non-weather)
            if classification.rejection_reason and "Negative filter" in classification.rejection_reason:
                logger.debug(
                    f"EXCLUDED: {classification.market_id} | "
                    f"{classification.rejection_reason}"
                )

        return FilteredMarket(
            market=market,
            result=result,
            matched_keywords=matched_keywords,
            notes=notes,
            classification_result=classification,
        )

    def filter_markets(
        self,
        markets: List[Dict[str, Any]]
    ) -> Tuple[List[FilteredMarket], Dict[str, int]]:
        """
        Filter multiple markets.

        Args:
            markets: List of raw market data

        Returns:
            Tuple of (filtered_markets, result_counts)
        """
        filtered = []
        counts = {
            "included_weather": 0,
            "possible_weather": 0,
            "excluded_not_weather": 0,
            "excluded_incomplete": 0,
            "total": len(markets),
        }

        for market in markets:
            try:
                result = self.filter_market(market)
                filtered.append(result)
                counts[result.result.value] = counts.get(result.result.value, 0) + 1
            except Exception as e:
                logger.warning(f"Filter error for market {market.get('id', 'unknown')}: {e}")
                filtered.append(FilteredMarket(
                    market=market,
                    result=FilterResult.EXCLUDED_INCOMPLETE,
                    matched_keywords=[],
                    notes=[f"Filter error: {str(e)[:100]}"],
                ))
                counts["excluded_incomplete"] += 1

        # Log summary
        logger.info(
            f"Filter results: {counts['total']} total | "
            f"{counts['included_weather']} CONFIRMED | "
            f"{counts['possible_weather']} POSSIBLE | "
            f"{counts['excluded_not_weather']} NOT_WEATHER | "
            f"{counts['excluded_incomplete']} errors"
        )

        # Log POSSIBLE markets for manual review
        possible_markets = [f for f in filtered if f.result == FilterResult.POSSIBLE_WEATHER]
        if possible_markets:
            logger.info(f"=== {len(possible_markets)} WEATHER_POSSIBLE markets for review ===")
            for fm in possible_markets[:10]:  # Limit to first 10
                title = fm.market.get("question") or fm.market.get("title") or "N/A"
                logger.info(f"  - [{fm.market.get('id', '?')}] {title[:70]}")
                logger.info(f"    Text signals: {fm.classification_result.matched_text_signals}")
                logger.info(f"    Structural signals: {fm.classification_result.matched_structural_signals}")

        return filtered, counts


# Module-level convenience function
def filter_for_weather(markets: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    """
    Filter markets for weather relevance.

    Args:
        markets: List of raw market data

    Returns:
        Tuple of (weather_markets, counts)

    Note:
        Only WEATHER_CONFIRMED markets are included in the result.
        WEATHER_POSSIBLE markets are logged but not included.
    """
    filter_instance = MarketFilter()
    filtered, counts = filter_instance.filter_markets(markets)

    # Only include CONFIRMED weather markets
    weather_markets = []
    for fm in filtered:
        if fm.result == FilterResult.INCLUDED_WEATHER:
            # Add classification metadata to market
            fm.market["matched_keywords"] = fm.matched_keywords
            fm.market["collector_notes"] = fm.notes
            fm.market["category"] = "WEATHER_EVENT"
            fm.market["classification"] = "WEATHER_CONFIRMED"
            fm.market["confidence_score"] = fm.classification_result.confidence_score
            weather_markets.append(fm.market)

    return weather_markets, counts


def get_possible_weather_markets(
    markets: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """
    Get WEATHER_POSSIBLE markets for manual review.

    These markets show some weather signals but not enough for confirmation.
    Useful for identifying patterns that should be added to the classifier.

    Args:
        markets: List of raw market data

    Returns:
        List of possible weather markets with classification metadata
    """
    filter_instance = MarketFilter()
    filtered, _ = filter_instance.filter_markets(markets)

    possible_markets = []
    for fm in filtered:
        if fm.result == FilterResult.POSSIBLE_WEATHER:
            fm.market["matched_keywords"] = fm.matched_keywords
            fm.market["collector_notes"] = fm.notes
            fm.market["classification"] = "WEATHER_POSSIBLE"
            fm.market["text_signals"] = fm.classification_result.matched_text_signals
            fm.market["structural_signals"] = fm.classification_result.matched_structural_signals
            possible_markets.append(fm.market)

    return possible_markets
