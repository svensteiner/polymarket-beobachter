from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from typing import Optional

from .learning_database import LearningDatabase
from .outcome_tracker import TradeContext


def calculate_wilson_score_interval(successes: int, total: int, z: float = 1.96) -> tuple[float, float]:
    if total == 0:
        return 0.0, 0.0
    phat = successes / total
    denom = 1 + z**2 / total
    center = (phat + z**2 / (2 * total)) / denom
    margin = (z * sqrt((phat * (1 - phat) + z**2 / (4 * total)) / total)) / denom
    return max(0.0, center - margin), min(1.0, center + margin)


@dataclass
class PatternResult:
    pattern_type: str
    pattern_value: str
    total_samples: int
    win_rate: float
    lower_bound: float
    upper_bound: float
    total_adjustment: float


@dataclass
class PatternAdjustment:
    total_adjustment: float
    matched_patterns: list[PatternResult]


class PatternDetector:
    def __init__(self, db: LearningDatabase, min_samples: int = 20) -> None:
        self.db = db
        self.min_samples = min_samples
        self.patterns: list[PatternResult] = []

    def detect_patterns(self) -> list[PatternResult]:
        resolved = self.db.get_resolved_predictions()
        patterns: list[PatternResult] = []

        for field_name in ("city", "weather_type"):
            grouped: dict[str, list] = {}
            for pred in resolved:
                value = getattr(pred, field_name)
                if not value:
                    continue
                grouped.setdefault(str(value).lower(), []).append(pred)

            for value, preds in grouped.items():
                if len(preds) < self.min_samples:
                    continue
                wins = sum(
                    1
                    for pred in preds
                    if str(pred.prediction_side).upper() == str(pred.actual_outcome).upper()
                )
                win_rate = wins / len(preds)
                low, high = calculate_wilson_score_interval(wins, len(preds))
                adjustment = (win_rate - 0.5) * 0.5
                patterns.append(
                    PatternResult(
                        pattern_type=field_name,
                        pattern_value=value,
                        total_samples=len(preds),
                        win_rate=win_rate,
                        lower_bound=low,
                        upper_bound=high,
                        total_adjustment=adjustment,
                    )
                )

        self.patterns = patterns
        return patterns

    def get_pattern_adjustment(self, context: TradeContext) -> PatternAdjustment:
        if not self.patterns:
            self.detect_patterns()

        matches: list[PatternResult] = []
        total_adjustment = 0.0

        for pattern in self.patterns:
            if pattern.pattern_type == "city" and context.city:
                if pattern.pattern_value == context.city.lower():
                    matches.append(pattern)
                    total_adjustment += pattern.total_adjustment
            if pattern.pattern_type == "weather_type" and context.weather_type:
                if pattern.pattern_value == context.weather_type.lower():
                    matches.append(pattern)
                    total_adjustment += pattern.total_adjustment

        return PatternAdjustment(total_adjustment=total_adjustment, matched_patterns=matches)
