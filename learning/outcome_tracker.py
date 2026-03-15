# =============================================================================
# POLYMARKET BEOBACHTER - OUTCOME TRACKER
# =============================================================================
#
# GOVERNANCE INTENT:
# Links predictions to market resolutions. This is the foundation for all
# learning - without outcome tracking, calibration and patterns are impossible.
#
# =============================================================================

import logging
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any, Callable
from dataclasses import dataclass

from .learning_database import LearningDatabase, PredictionRecord

logger = logging.getLogger(__name__)


@dataclass
class TradeContext:
    """Context information for a trade."""
    trade_id: str
    market_id: str
    city: Optional[str] = None
    weather_type: Optional[str] = None
    season: Optional[str] = None
    forecast_horizon_hours: Optional[float] = None
    hours_to_resolution: Optional[float] = None


class OutcomeTracker:
    """
    Tracks predictions and their outcomes.

    Responsibilities:
    1. Record predictions at trade time
    2. Fetch market resolutions
    3. Link predictions to outcomes
    4. Provide accuracy statistics
    """

    def __init__(self, db: LearningDatabase):
        """
        Initialize outcome tracker.

        Args:
            db: Learning database instance
        """
        self.db = db
        self._resolution_fetcher: Optional[Callable[[str], Optional[str]]] = None
        logger.info("OutcomeTracker initialized")

    def set_resolution_fetcher(self, fetcher: Callable[[str], Optional[str]]):
        """
        Set function to fetch market resolutions.

        Args:
            fetcher: Function that takes market_id and returns 'YES', 'NO', or None
        """
        self._resolution_fetcher = fetcher
        logger.info("Resolution fetcher configured")

    def record_prediction(
        self,
        trade_id: str,
        market_id: str,
        prediction_side: str,
        predicted_probability: float,
        market_price: float,
        edge: float,
        confidence: float,
        hours_to_resolution: float,
        context: Optional[TradeContext] = None
    ) -> bool:
        """
        Record a prediction at trade time.

        Args:
            trade_id: Unique trade identifier
            market_id: Market being traded
            prediction_side: 'YES' or 'NO'
            predicted_probability: Our probability estimate
            market_price: Market price at trade time
            edge: Calculated edge
            confidence: Confidence level
            hours_to_resolution: Hours until market resolves
            context: Additional context (city, weather, etc.)

        Returns:
            True if recorded successfully
        """
        prediction = PredictionRecord(
            trade_id=trade_id,
            market_id=market_id,
            prediction_side=prediction_side,
            predicted_probability=predicted_probability,
            market_price=market_price,
            edge=edge,
            confidence=confidence,
            hours_to_resolution=hours_to_resolution,
            city=context.city if context else None,
            weather_type=context.weather_type if context else None,
            season=context.season if context else None,
            forecast_horizon_hours=context.forecast_horizon_hours if context else None
        )

        success = self.db.record_prediction(prediction)
        if success:
            logger.info(
                "Recorded prediction: %s %s @ %.2f (edge=%.1f%%, conf=%.1f%%)",
                trade_id, prediction_side, market_price, edge * 100, confidence * 100
            )
        return success

    def record_outcome(
        self,
        market_id: str,
        actual_outcome: str,
        resolved_at: Optional[str] = None
    ) -> int:
        """
        Record outcome for a market.

        Args:
            market_id: Market that resolved
            actual_outcome: 'YES' or 'NO'
            resolved_at: Resolution timestamp

        Returns:
            Number of predictions updated
        """
        return self.db.record_outcome(market_id, actual_outcome, resolved_at)

    def fetch_and_record_resolutions(self) -> Dict[str, str]:
        """
        Fetch resolutions for unresolved predictions and record them.

        Returns:
            Dict mapping market_id to outcome for newly resolved markets
        """
        if self._resolution_fetcher is None:
            logger.warning("No resolution fetcher configured")
            return {}

        unresolved = self.db.get_unresolved_predictions()
        if not unresolved:
            return {}

        # Group by market_id to avoid duplicate fetches
        market_ids = set(p.market_id for p in unresolved)
        logger.info("Checking resolutions for %d markets", len(market_ids))

        resolved = {}
        for market_id in market_ids:
            try:
                outcome = self._resolution_fetcher(market_id)
                if outcome and outcome in ("YES", "NO"):
                    updated = self.record_outcome(market_id, outcome)
                    if updated > 0:
                        resolved[market_id] = outcome
                        logger.info("Resolved market %s: %s (%d predictions)",
                                   market_id, outcome, updated)
            except Exception as e:
                logger.error("Error fetching resolution for %s: %s", market_id, e)

        return resolved

    def get_unresolved_count(self) -> int:
        """Get count of unresolved predictions."""
        return len(self.db.get_unresolved_predictions())

    def get_accuracy_stats(
        self,
        city: Optional[str] = None,
        weather_type: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Get accuracy statistics with optional filters.

        Args:
            city: Filter by city
            weather_type: Filter by weather type

        Returns:
            Dict with accuracy metrics
        """
        predictions = self.db.get_resolved_predictions(
            city=city,
            weather_type=weather_type
        )

        if not predictions:
            return {
                "total": 0,
                "correct": 0,
                "accuracy": 0.0,
                "avg_edge": 0.0,
                "total_pnl": 0.0
            }

        correct = sum(1 for p in predictions if p.prediction_side == p.actual_outcome)
        total_pnl = sum(p.pnl or 0 for p in predictions)
        avg_edge = sum(p.edge for p in predictions) / len(predictions)

        return {
            "total": len(predictions),
            "correct": correct,
            "accuracy": correct / len(predictions),
            "avg_edge": avg_edge,
            "total_pnl": total_pnl,
            "filters": {
                "city": city,
                "weather_type": weather_type
            }
        }

    def get_recent_outcomes(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Get recently resolved predictions for display."""
        predictions = self.db.get_resolved_predictions(limit=limit)

        return [{
            "trade_id": p.trade_id,
            "market_id": p.market_id,
            "prediction": p.prediction_side,
            "outcome": p.actual_outcome,
            "correct": p.prediction_side == p.actual_outcome,
            "edge": p.edge,
            "pnl": p.pnl,
            "resolved_at": p.resolved_at,
            "city": p.city,
            "weather_type": p.weather_type
        } for p in predictions]


def get_season(date: datetime) -> str:
    """Determine season from date."""
    month = date.month
    if month in (12, 1, 2):
        return "winter"
    elif month in (3, 4, 5):
        return "spring"
    elif month in (6, 7, 8):
        return "summer"
    else:
        return "fall"


def create_trade_context(
    trade_id: str,
    market_id: str,
    city: Optional[str] = None,
    weather_type: Optional[str] = None,
    forecast_horizon_hours: Optional[float] = None,
    hours_to_resolution: Optional[float] = None,
    date: Optional[datetime] = None
) -> TradeContext:
    """Helper to create trade context with auto-detected season."""
    season = get_season(date or datetime.now(timezone.utc))

    return TradeContext(
        trade_id=trade_id,
        market_id=market_id,
        city=city,
        weather_type=weather_type,
        season=season,
        forecast_horizon_hours=forecast_horizon_hours,
        hours_to_resolution=hours_to_resolution
    )
