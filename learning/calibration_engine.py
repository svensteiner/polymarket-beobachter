from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

from .learning_database import LearningDatabase


@dataclass
class CalibrationState:
    total_samples: int
    bucket_factors: dict[str, float]


class CalibrationEngine:
    def __init__(
        self,
        db: LearningDatabase,
        state_path: Path | str,
        min_samples: int = 25,
    ) -> None:
        self.db = db
        self.state_path = Path(state_path)
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.min_samples = min_samples
        self.state: Optional[CalibrationState] = self._load_state()

    def _load_state(self) -> Optional[CalibrationState]:
        if not self.state_path.exists():
            return None
        data = json.loads(self.state_path.read_text(encoding="utf-8"))
        return CalibrationState(
            total_samples=int(data["total_samples"]),
            bucket_factors=dict(data["bucket_factors"]),
        )

    def _save_state(self, state: CalibrationState) -> None:
        self.state_path.write_text(
            json.dumps(asdict(state), indent=2, sort_keys=True),
            encoding="utf-8",
        )

    def recalibrate(self) -> Optional[CalibrationState]:
        buckets = self.db.get_calibration_stats(bucket_width=0.1)
        total_samples = sum(bucket.total_predictions for bucket in buckets)
        if total_samples < self.min_samples:
            return None

        bucket_factors: dict[str, float] = {}
        for bucket in buckets:
            if bucket.total_predictions == 0:
                continue
            observed_rate = bucket.correct_predictions / bucket.total_predictions
            expected_rate = max(0.01, bucket.avg_confidence)
            factor = observed_rate / expected_rate
            bucket_factors[f"{bucket.bucket_low:.1f}"] = max(0.5, min(1.2, factor))

        state = CalibrationState(total_samples=total_samples, bucket_factors=bucket_factors)
        self.state = state
        self._save_state(state)
        return state

    def calculate_calibration(self, raw_confidence: float) -> float:
        if not self.state or not self.state.bucket_factors:
            return raw_confidence

        bucket_key = f"{(int(raw_confidence * 10) / 10):.1f}"
        factor = self.state.bucket_factors.get(bucket_key)
        if factor is None:
            factor = sum(self.state.bucket_factors.values()) / len(self.state.bucket_factors)
        calibrated = raw_confidence * factor
        return max(0.01, min(0.99, calibrated))
