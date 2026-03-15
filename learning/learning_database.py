# =============================================================================
# POLYMARKET BEOBACHTER - LEARNING DATABASE
# =============================================================================
#
# GOVERNANCE INTENT:
# Persistent SQLite storage for learning data. Stores predictions, outcomes,
# calibration history, and detected patterns. Uses WAL mode for reliability.
#
# =============================================================================

import sqlite3
import logging
import json
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any, Tuple
from dataclasses import dataclass, asdict
from contextlib import contextmanager

logger = logging.getLogger(__name__)


@dataclass
class PredictionRecord:
    """A prediction made by the bot."""
    trade_id: str
    market_id: str
    prediction_side: str  # YES or NO
    predicted_probability: float
    market_price: float
    edge: float
    confidence: float
    hours_to_resolution: float
    city: Optional[str] = None
    weather_type: Optional[str] = None
    season: Optional[str] = None
    forecast_horizon_hours: Optional[float] = None
    created_at: Optional[str] = None
    actual_outcome: Optional[str] = None
    resolved_at: Optional[str] = None
    pnl: Optional[float] = None


@dataclass
class CalibrationBucket:
    """Statistics for a confidence bucket."""
    bucket_low: float
    bucket_high: float
    total_predictions: int
    correct_predictions: int
    accuracy: float
    calibration_factor: float


@dataclass
class PatternStats:
    """Statistics for a detected pattern."""
    pattern_type: str
    pattern_value: str
    total_trades: int
    wins: int
    losses: int
    win_rate: float
    avg_edge: float
    total_pnl: float
    confidence_interval_low: float
    confidence_interval_high: float


class LearningDatabase:
    """
    SQLite database for learning system.

    Tables:
    - predictions: All predictions with outcomes
    - calibration_history: Historical calibration snapshots
    - patterns: Detected patterns and their stats
    """

    SCHEMA_VERSION = 1

    def __init__(self, db_path: Optional[Path] = None):
        """
        Initialize learning database.

        Args:
            db_path: Path to SQLite database. Defaults to data/learning.db
        """
        if db_path is None:
            db_path = Path(__file__).parent.parent / "data" / "learning.db"

        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self._init_database()
        logger.info("Learning database initialized: %s", self.db_path)

    @contextmanager
    def _get_connection(self):
        """Context manager for database connections."""
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_database(self):
        """Create tables if they don't exist."""
        with self._get_connection() as conn:
            # Predictions table
            conn.execute("""
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
                    season TEXT,
                    forecast_horizon_hours REAL,
                    created_at TEXT NOT NULL,
                    actual_outcome TEXT,
                    resolved_at TEXT,
                    pnl REAL,
                    CONSTRAINT valid_side CHECK (prediction_side IN ('YES', 'NO')),
                    CONSTRAINT valid_outcome CHECK (actual_outcome IN ('YES', 'NO') OR actual_outcome IS NULL)
                )
            """)

            # Indexes for efficient queries
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_predictions_market
                ON predictions(market_id)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_predictions_unresolved
                ON predictions(actual_outcome) WHERE actual_outcome IS NULL
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_predictions_city
                ON predictions(city)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_predictions_weather
                ON predictions(weather_type)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_predictions_confidence
                ON predictions(confidence)
            """)

            # Calibration history table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS calibration_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    bucket_low REAL NOT NULL,
                    bucket_high REAL NOT NULL,
                    total_predictions INTEGER NOT NULL,
                    correct_predictions INTEGER NOT NULL,
                    accuracy REAL NOT NULL,
                    calibration_factor REAL NOT NULL,
                    snapshot_at TEXT NOT NULL
                )
            """)

            # Patterns table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS patterns (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    pattern_type TEXT NOT NULL,
                    pattern_value TEXT NOT NULL,
                    total_trades INTEGER NOT NULL,
                    wins INTEGER NOT NULL,
                    losses INTEGER NOT NULL,
                    win_rate REAL NOT NULL,
                    avg_edge REAL NOT NULL,
                    total_pnl REAL NOT NULL,
                    confidence_interval_low REAL NOT NULL,
                    confidence_interval_high REAL NOT NULL,
                    detected_at TEXT NOT NULL,
                    is_active INTEGER DEFAULT 1,
                    UNIQUE(pattern_type, pattern_value)
                )
            """)

            # Schema version
            conn.execute("""
                CREATE TABLE IF NOT EXISTS schema_info (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            """)
            conn.execute(
                "INSERT OR REPLACE INTO schema_info (key, value) VALUES (?, ?)",
                ("version", str(self.SCHEMA_VERSION))
            )

    # =========================================================================
    # PREDICTIONS
    # =========================================================================

    def record_prediction(self, prediction: PredictionRecord) -> bool:
        """
        Record a new prediction.

        Args:
            prediction: The prediction to record

        Returns:
            True if recorded, False if duplicate
        """
        if prediction.created_at is None:
            prediction.created_at = datetime.now(timezone.utc).isoformat()

        try:
            with self._get_connection() as conn:
                conn.execute("""
                    INSERT INTO predictions (
                        trade_id, market_id, prediction_side, predicted_probability,
                        market_price, edge, confidence, hours_to_resolution,
                        city, weather_type, season, forecast_horizon_hours,
                        created_at, actual_outcome, resolved_at, pnl
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    prediction.trade_id, prediction.market_id, prediction.prediction_side,
                    prediction.predicted_probability, prediction.market_price,
                    prediction.edge, prediction.confidence, prediction.hours_to_resolution,
                    prediction.city, prediction.weather_type, prediction.season,
                    prediction.forecast_horizon_hours, prediction.created_at,
                    prediction.actual_outcome, prediction.resolved_at, prediction.pnl
                ))
            logger.debug("Recorded prediction: %s", prediction.trade_id)
            return True
        except sqlite3.IntegrityError:
            logger.warning("Duplicate prediction: %s", prediction.trade_id)
            return False

    def record_outcome(
        self,
        market_id: str,
        actual_outcome: str,
        resolved_at: Optional[str] = None
    ) -> int:
        """
        Record outcome for all predictions on a market.

        Args:
            market_id: The market that resolved
            actual_outcome: 'YES' or 'NO'
            resolved_at: Resolution timestamp (defaults to now)

        Returns:
            Number of predictions updated
        """
        if resolved_at is None:
            resolved_at = datetime.now(timezone.utc).isoformat()

        with self._get_connection() as conn:
            cursor = conn.execute("""
                UPDATE predictions
                SET actual_outcome = ?, resolved_at = ?
                WHERE market_id = ? AND actual_outcome IS NULL
            """, (actual_outcome, resolved_at, market_id))

            updated = cursor.rowcount

            # Calculate P&L for updated predictions
            if updated > 0:
                # P&L: If prediction correct, profit = (1 - entry_price) * stake
                # If incorrect, loss = entry_price * stake (simplified to edge-based)
                conn.execute("""
                    UPDATE predictions
                    SET pnl = CASE
                        WHEN prediction_side = actual_outcome THEN edge
                        ELSE -market_price
                    END
                    WHERE market_id = ? AND resolved_at = ?
                """, (market_id, resolved_at))

        if updated > 0:
            logger.info("Recorded outcome %s for market %s (%d predictions)",
                       actual_outcome, market_id, updated)
        return updated

    def get_unresolved_predictions(self) -> List[PredictionRecord]:
        """Get all predictions without outcomes."""
        with self._get_connection() as conn:
            rows = conn.execute("""
                SELECT * FROM predictions WHERE actual_outcome IS NULL
                ORDER BY created_at DESC
            """).fetchall()

        return [self._row_to_prediction(row) for row in rows]

    def get_resolved_predictions(
        self,
        limit: int = 1000,
        city: Optional[str] = None,
        weather_type: Optional[str] = None,
        min_confidence: Optional[float] = None,
        max_confidence: Optional[float] = None
    ) -> List[PredictionRecord]:
        """Get resolved predictions with optional filters."""
        query = "SELECT * FROM predictions WHERE actual_outcome IS NOT NULL"
        params: List[Any] = []

        if city:
            query += " AND city = ?"
            params.append(city)
        if weather_type:
            query += " AND weather_type = ?"
            params.append(weather_type)
        if min_confidence is not None:
            query += " AND confidence >= ?"
            params.append(min_confidence)
        if max_confidence is not None:
            query += " AND confidence < ?"
            params.append(max_confidence)

        query += " ORDER BY resolved_at DESC LIMIT ?"
        params.append(limit)

        with self._get_connection() as conn:
            rows = conn.execute(query, params).fetchall()

        return [self._row_to_prediction(row) for row in rows]

    def _row_to_prediction(self, row: sqlite3.Row) -> PredictionRecord:
        """Convert database row to PredictionRecord."""
        return PredictionRecord(
            trade_id=row["trade_id"],
            market_id=row["market_id"],
            prediction_side=row["prediction_side"],
            predicted_probability=row["predicted_probability"],
            market_price=row["market_price"],
            edge=row["edge"],
            confidence=row["confidence"],
            hours_to_resolution=row["hours_to_resolution"],
            city=row["city"],
            weather_type=row["weather_type"],
            season=row["season"],
            forecast_horizon_hours=row["forecast_horizon_hours"],
            created_at=row["created_at"],
            actual_outcome=row["actual_outcome"],
            resolved_at=row["resolved_at"],
            pnl=row["pnl"]
        )

    # =========================================================================
    # CALIBRATION
    # =========================================================================

    def get_calibration_stats(
        self,
        bucket_width: float = 0.1
    ) -> List[CalibrationBucket]:
        """
        Calculate calibration statistics by confidence bucket.

        Args:
            bucket_width: Width of each bucket (default 10%)

        Returns:
            List of calibration buckets with accuracy stats
        """
        buckets = []
        bucket_low = 0.0

        with self._get_connection() as conn:
            while bucket_low < 1.0:
                bucket_high = min(bucket_low + bucket_width, 1.0)

                row = conn.execute("""
                    SELECT
                        COUNT(*) as total,
                        SUM(CASE WHEN prediction_side = actual_outcome THEN 1 ELSE 0 END) as correct
                    FROM predictions
                    WHERE actual_outcome IS NOT NULL
                      AND confidence >= ? AND confidence < ?
                """, (bucket_low, bucket_high)).fetchone()

                total = row["total"] or 0
                correct = row["correct"] or 0

                if total > 0:
                    accuracy = correct / total
                    # Calibration factor: if we predict 70% but are right 60%, factor = 0.857
                    expected_accuracy = (bucket_low + bucket_high) / 2
                    calibration_factor = accuracy / expected_accuracy if expected_accuracy > 0 else 1.0
                else:
                    accuracy = 0.0
                    calibration_factor = 1.0

                buckets.append(CalibrationBucket(
                    bucket_low=bucket_low,
                    bucket_high=bucket_high,
                    total_predictions=total,
                    correct_predictions=correct,
                    accuracy=accuracy,
                    calibration_factor=calibration_factor
                ))

                bucket_low = bucket_high

        return buckets

    def save_calibration_snapshot(self, buckets: List[CalibrationBucket]):
        """Save current calibration state to history."""
        snapshot_at = datetime.now(timezone.utc).isoformat()

        with self._get_connection() as conn:
            for bucket in buckets:
                conn.execute("""
                    INSERT INTO calibration_history (
                        bucket_low, bucket_high, total_predictions, correct_predictions,
                        accuracy, calibration_factor, snapshot_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    bucket.bucket_low, bucket.bucket_high, bucket.total_predictions,
                    bucket.correct_predictions, bucket.accuracy, bucket.calibration_factor,
                    snapshot_at
                ))

        logger.info("Saved calibration snapshot with %d buckets", len(buckets))

    # =========================================================================
    # PATTERNS
    # =========================================================================

    def get_pattern_stats(
        self,
        pattern_type: str,
        min_samples: int = 20
    ) -> List[PatternStats]:
        """
        Get statistics grouped by pattern dimension.

        Args:
            pattern_type: 'city', 'weather_type', 'season', etc.
            min_samples: Minimum trades to include pattern

        Returns:
            List of pattern statistics
        """
        column = pattern_type
        if column not in ("city", "weather_type", "season"):
            raise ValueError(f"Invalid pattern type: {pattern_type}")

        patterns = []

        with self._get_connection() as conn:
            rows = conn.execute(f"""
                SELECT
                    {column} as pattern_value,
                    COUNT(*) as total,
                    SUM(CASE WHEN prediction_side = actual_outcome THEN 1 ELSE 0 END) as wins,
                    AVG(edge) as avg_edge,
                    SUM(pnl) as total_pnl
                FROM predictions
                WHERE actual_outcome IS NOT NULL
                  AND {column} IS NOT NULL
                GROUP BY {column}
                HAVING COUNT(*) >= ?
            """, (min_samples,)).fetchall()

            for row in rows:
                total = row["total"]
                wins = row["wins"] or 0
                losses = total - wins
                win_rate = wins / total if total > 0 else 0

                # Wilson score interval for confidence
                z = 1.96  # 95% confidence
                n = total
                p = win_rate
                ci_low = (p + z*z/(2*n) - z*((p*(1-p) + z*z/(4*n))/n)**0.5) / (1 + z*z/n) if n > 0 else 0
                ci_high = (p + z*z/(2*n) + z*((p*(1-p) + z*z/(4*n))/n)**0.5) / (1 + z*z/n) if n > 0 else 0

                patterns.append(PatternStats(
                    pattern_type=pattern_type,
                    pattern_value=row["pattern_value"],
                    total_trades=total,
                    wins=wins,
                    losses=losses,
                    win_rate=win_rate,
                    avg_edge=row["avg_edge"] or 0,
                    total_pnl=row["total_pnl"] or 0,
                    confidence_interval_low=ci_low,
                    confidence_interval_high=ci_high
                ))

        return patterns

    def save_pattern(self, pattern: PatternStats):
        """Save or update a detected pattern."""
        detected_at = datetime.now(timezone.utc).isoformat()

        with self._get_connection() as conn:
            conn.execute("""
                INSERT INTO patterns (
                    pattern_type, pattern_value, total_trades, wins, losses,
                    win_rate, avg_edge, total_pnl, confidence_interval_low,
                    confidence_interval_high, detected_at, is_active
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                ON CONFLICT(pattern_type, pattern_value) DO UPDATE SET
                    total_trades = excluded.total_trades,
                    wins = excluded.wins,
                    losses = excluded.losses,
                    win_rate = excluded.win_rate,
                    avg_edge = excluded.avg_edge,
                    total_pnl = excluded.total_pnl,
                    confidence_interval_low = excluded.confidence_interval_low,
                    confidence_interval_high = excluded.confidence_interval_high,
                    detected_at = excluded.detected_at
            """, (
                pattern.pattern_type, pattern.pattern_value, pattern.total_trades,
                pattern.wins, pattern.losses, pattern.win_rate, pattern.avg_edge,
                pattern.total_pnl, pattern.confidence_interval_low,
                pattern.confidence_interval_high, detected_at
            ))

    def get_active_patterns(self) -> List[PatternStats]:
        """Get all active patterns."""
        with self._get_connection() as conn:
            rows = conn.execute("""
                SELECT * FROM patterns WHERE is_active = 1
            """).fetchall()

        return [PatternStats(
            pattern_type=row["pattern_type"],
            pattern_value=row["pattern_value"],
            total_trades=row["total_trades"],
            wins=row["wins"],
            losses=row["losses"],
            win_rate=row["win_rate"],
            avg_edge=row["avg_edge"],
            total_pnl=row["total_pnl"],
            confidence_interval_low=row["confidence_interval_low"],
            confidence_interval_high=row["confidence_interval_high"]
        ) for row in rows]

    # =========================================================================
    # STATISTICS
    # =========================================================================

    def get_summary_stats(self) -> Dict[str, Any]:
        """Get overall learning database statistics."""
        with self._get_connection() as conn:
            total = conn.execute("SELECT COUNT(*) FROM predictions").fetchone()[0]
            resolved = conn.execute(
                "SELECT COUNT(*) FROM predictions WHERE actual_outcome IS NOT NULL"
            ).fetchone()[0]
            unresolved = total - resolved

            if resolved > 0:
                accuracy_row = conn.execute("""
                    SELECT
                        AVG(CASE WHEN prediction_side = actual_outcome THEN 1.0 ELSE 0.0 END) as accuracy,
                        SUM(pnl) as total_pnl,
                        AVG(edge) as avg_edge
                    FROM predictions WHERE actual_outcome IS NOT NULL
                """).fetchone()
                accuracy = accuracy_row["accuracy"] or 0
                total_pnl = accuracy_row["total_pnl"] or 0
                avg_edge = accuracy_row["avg_edge"] or 0
            else:
                accuracy = 0
                total_pnl = 0
                avg_edge = 0

            active_patterns = conn.execute(
                "SELECT COUNT(*) FROM patterns WHERE is_active = 1"
            ).fetchone()[0]

        return {
            "total_predictions": total,
            "resolved_predictions": resolved,
            "unresolved_predictions": unresolved,
            "accuracy": accuracy,
            "total_pnl": total_pnl,
            "avg_edge": avg_edge,
            "active_patterns": active_patterns
        }
