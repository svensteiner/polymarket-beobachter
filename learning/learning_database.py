from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Optional


@dataclass
class PredictionRecord:
    trade_id: str
    market_id: str
    prediction_side: str
    predicted_probability: float
    market_price: float
    edge: float
    confidence: float
    hours_to_resolution: float
    city: Optional[str] = None
    weather_type: Optional[str] = None
    actual_outcome: Optional[str] = None
    resolved_at: Optional[str] = None


@dataclass
class CalibrationBucket:
    bucket_low: float
    bucket_high: float
    total_predictions: int
    correct_predictions: int
    avg_confidence: float


class LearningDatabase:
    """Tiny SQLite store used by the learning tests and orchestrator."""

    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS predictions (
                    trade_id TEXT PRIMARY KEY,
                    market_id TEXT NOT NULL,
                    prediction_side TEXT NOT NULL,
                    predicted_probability REAL NOT NULL,
                    market_price REAL NOT NULL,
                    edge REAL NOT NULL,
                    confidence REAL NOT NULL,
                    hours_to_resolution REAL NOT NULL,
                    city TEXT,
                    weather_type TEXT,
                    actual_outcome TEXT,
                    resolved_at TEXT
                )
                """
            )
            conn.commit()

    def _row_to_record(self, row: sqlite3.Row) -> PredictionRecord:
        return PredictionRecord(
            trade_id=row["trade_id"],
            market_id=row["market_id"],
            prediction_side=row["prediction_side"],
            predicted_probability=float(row["predicted_probability"]),
            market_price=float(row["market_price"]),
            edge=float(row["edge"]),
            confidence=float(row["confidence"]),
            hours_to_resolution=float(row["hours_to_resolution"]),
            city=row["city"],
            weather_type=row["weather_type"],
            actual_outcome=row["actual_outcome"],
            resolved_at=row["resolved_at"],
        )

    def record_prediction(self, prediction: PredictionRecord) -> bool:
        try:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO predictions (
                        trade_id, market_id, prediction_side, predicted_probability,
                        market_price, edge, confidence, hours_to_resolution,
                        city, weather_type, actual_outcome, resolved_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        prediction.trade_id,
                        prediction.market_id,
                        prediction.prediction_side,
                        prediction.predicted_probability,
                        prediction.market_price,
                        prediction.edge,
                        prediction.confidence,
                        prediction.hours_to_resolution,
                        prediction.city,
                        prediction.weather_type,
                        prediction.actual_outcome,
                        prediction.resolved_at,
                    ),
                )
                conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    def record_outcome(self, market_id: str, actual_outcome: str) -> int:
        resolved_at = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE predictions
                   SET actual_outcome = ?, resolved_at = ?
                 WHERE market_id = ? AND actual_outcome IS NULL
                """,
                (actual_outcome, resolved_at, market_id),
            )
            conn.commit()
            return cursor.rowcount

    def get_resolved_predictions(self) -> list[PredictionRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM predictions WHERE actual_outcome IS NOT NULL ORDER BY rowid"
            ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def get_unresolved_predictions(self) -> list[PredictionRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM predictions WHERE actual_outcome IS NULL ORDER BY rowid"
            ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def get_summary_stats(self) -> dict[str, Any]:
        with self._connect() as conn:
            total = conn.execute("SELECT COUNT(*) FROM predictions").fetchone()[0]
            resolved = conn.execute(
                "SELECT COUNT(*) FROM predictions WHERE actual_outcome IS NOT NULL"
            ).fetchone()[0]
            correct = conn.execute(
                """
                SELECT COUNT(*)
                  FROM predictions
                 WHERE actual_outcome IS NOT NULL
                   AND UPPER(prediction_side) = UPPER(actual_outcome)
                """
            ).fetchone()[0]
        accuracy = (correct / resolved) if resolved else None
        return {
            "total_predictions": total,
            "resolved_predictions": resolved,
            "accuracy": accuracy,
        }

    def get_calibration_stats(self, bucket_width: float = 0.1) -> list[CalibrationBucket]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT predicted_probability, prediction_side, actual_outcome
                  FROM predictions
                 WHERE actual_outcome IS NOT NULL
                 ORDER BY predicted_probability
                """
            ).fetchall()

        buckets: dict[float, list[sqlite3.Row]] = {}
        for row in rows:
            p = float(row["predicted_probability"])
            bucket_low = round((p // bucket_width) * bucket_width, 10)
            buckets.setdefault(bucket_low, []).append(row)

        stats: list[CalibrationBucket] = []
        for bucket_low in sorted(buckets):
            bucket_rows = buckets[bucket_low]
            total = len(bucket_rows)
            correct = sum(
                1
                for row in bucket_rows
                if str(row["prediction_side"]).upper() == str(row["actual_outcome"]).upper()
            )
            avg_conf = sum(float(r["predicted_probability"]) for r in bucket_rows) / total
            stats.append(
                CalibrationBucket(
                    bucket_low=bucket_low,
                    bucket_high=round(bucket_low + bucket_width, 10),
                    total_predictions=total,
                    correct_predictions=correct,
                    avg_confidence=avg_conf,
                )
            )
        return stats

    def close(self) -> None:
        return None

    def __del__(self) -> None:
        return None
