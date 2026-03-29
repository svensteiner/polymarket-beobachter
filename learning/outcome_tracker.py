from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional

from .learning_database import LearningDatabase, PredictionRecord


@dataclass
class TradeContext:
    trade_id: str
    market_id: str
    city: Optional[str] = None
    weather_type: Optional[str] = None
    market_price: Optional[float] = None
    confidence: Optional[float] = None
    hours_to_resolution: Optional[float] = None


def get_season(value: datetime | date) -> str:
    month = value.month
    if month in (12, 1, 2):
        return "winter"
    if month in (3, 4, 5):
        return "spring"
    if month in (6, 7, 8):
        return "summer"
    return "fall"


class OutcomeTracker:
    def __init__(self, db: LearningDatabase) -> None:
        self.db = db

    def record_prediction(self, prediction: PredictionRecord) -> bool:
        return self.db.record_prediction(prediction)

    def record_outcome(self, market_id: str, outcome: str) -> int:
        return self.db.record_outcome(market_id, outcome)
