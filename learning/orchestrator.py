from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .calibration_engine import CalibrationEngine
from .learning_database import LearningDatabase, PredictionRecord
from .outcome_tracker import TradeContext
from .pattern_detector import PatternDetector, PatternAdjustment
from .time_urgency import TimeUrgencyCalculator, UrgencyAdjustment


@dataclass
class LearningConfig:
    enabled: bool = True
    database_path: Path = Path("data/learning.db")
    proposal_output_path: Path = Path("output/learning_proposals")
    min_calibration_samples: int = 25
    min_pattern_samples: int = 20


@dataclass
class EnhancedSignal:
    market_id: str
    original_size: float
    adjusted_size: float
    calibrated_confidence: float
    urgency_adjustment: Optional[UrgencyAdjustment]
    pattern_adjustment: Optional[PatternAdjustment]


class LearningOrchestrator:
    def __init__(self, config: LearningConfig) -> None:
        self.config = config
        self.is_enabled = config.enabled
        self.db = LearningDatabase(config.database_path)
        self.calibration = CalibrationEngine(
            self.db,
            state_path=Path(config.proposal_output_path) / "calibration_state.json",
            min_samples=config.min_calibration_samples,
        )
        self.pattern_detector = PatternDetector(self.db, min_samples=config.min_pattern_samples)
        self.urgency = TimeUrgencyCalculator()

    def enhance_signal(
        self,
        market_id: str,
        edge: float,
        confidence: float,
        suggested_size: float,
        hours_to_resolution: float,
        base_min_edge: float = 0.05,
        city: Optional[str] = None,
        weather_type: Optional[str] = None,
    ) -> EnhancedSignal:
        if not self.is_enabled:
            return EnhancedSignal(
                market_id=market_id,
                original_size=suggested_size,
                adjusted_size=suggested_size,
                calibrated_confidence=confidence,
                urgency_adjustment=None,
                pattern_adjustment=None,
            )

        urgency_adjustment = self.urgency.calculate_adjustment(
            hours_to_resolution, base_min_edge=base_min_edge, base_max_position=suggested_size
        )
        pattern_adjustment = self.pattern_detector.get_pattern_adjustment(
            TradeContext(
                trade_id=market_id,
                market_id=market_id,
                city=city,
                weather_type=weather_type,
            )
        )
        calibrated_confidence = self.calibration.calculate_calibration(confidence)
        adjusted_size = max(
            0.0,
            suggested_size
            * (urgency_adjustment.adjusted_max_position / suggested_size if suggested_size else 1.0)
            * (1.0 + pattern_adjustment.total_adjustment),
        )

        return EnhancedSignal(
            market_id=market_id,
            original_size=suggested_size,
            adjusted_size=adjusted_size,
            calibrated_confidence=calibrated_confidence,
            urgency_adjustment=urgency_adjustment,
            pattern_adjustment=pattern_adjustment,
        )

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
        city: Optional[str] = None,
        weather_type: Optional[str] = None,
    ) -> bool:
        return self.db.record_prediction(
            PredictionRecord(
                trade_id=trade_id,
                market_id=market_id,
                prediction_side=prediction_side,
                predicted_probability=predicted_probability,
                market_price=market_price,
                edge=edge,
                confidence=confidence,
                hours_to_resolution=hours_to_resolution,
                city=city,
                weather_type=weather_type,
            )
        )

    def get_status(self) -> dict:
        return {
            "enabled": self.is_enabled,
            "components": {
                "database": str(self.config.database_path),
                "calibration_state": str(Path(self.config.proposal_output_path) / "calibration_state.json"),
                "pattern_detector": "ready",
                "urgency": "ready",
            },
            "database": self.db.get_summary_stats(),
        }
