# =============================================================================
# TESTS FOR LEARNING SYSTEM
# =============================================================================

import pytest
import tempfile
from pathlib import Path
from datetime import datetime, timezone, timedelta

from learning.learning_database import LearningDatabase, PredictionRecord
from learning.outcome_tracker import OutcomeTracker, TradeContext, get_season
from learning.time_urgency import (
    TimeUrgencyCalculator,
    UrgencyPhase,
    create_custom_urgency_calculator
)
from learning.calibration_engine import CalibrationEngine
from learning.pattern_detector import PatternDetector, calculate_wilson_score_interval
from learning.orchestrator import LearningOrchestrator, LearningConfig


class TestLearningDatabase:
    """Tests for LearningDatabase."""

    @pytest.fixture
    def db(self):
        """Create a temporary database."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test_learning.db"
            yield LearningDatabase(db_path)

    def test_record_prediction(self, db):
        """Test recording a prediction."""
        prediction = PredictionRecord(
            trade_id="TEST-001",
            market_id="MARKET-001",
            prediction_side="YES",
            predicted_probability=0.7,
            market_price=0.55,
            edge=0.15,
            confidence=0.8,
            hours_to_resolution=24.0,
            city="Miami",
            weather_type="precipitation"
        )

        result = db.record_prediction(prediction)
        assert result is True

        # Duplicate should return False
        result = db.record_prediction(prediction)
        assert result is False

    def test_record_outcome(self, db):
        """Test recording outcome."""
        # First record a prediction
        prediction = PredictionRecord(
            trade_id="TEST-002",
            market_id="MARKET-002",
            prediction_side="YES",
            predicted_probability=0.7,
            market_price=0.55,
            edge=0.15,
            confidence=0.8,
            hours_to_resolution=24.0
        )
        db.record_prediction(prediction)

        # Record outcome
        updated = db.record_outcome("MARKET-002", "YES")
        assert updated == 1

        # Get resolved predictions
        resolved = db.get_resolved_predictions()
        assert len(resolved) == 1
        assert resolved[0].actual_outcome == "YES"

    def test_unresolved_predictions(self, db):
        """Test getting unresolved predictions."""
        # Record without outcome
        for i in range(3):
            prediction = PredictionRecord(
                trade_id=f"TEST-{i:03d}",
                market_id=f"MARKET-{i:03d}",
                prediction_side="YES",
                predicted_probability=0.7,
                market_price=0.55,
                edge=0.15,
                confidence=0.8,
                hours_to_resolution=24.0
            )
            db.record_prediction(prediction)

        unresolved = db.get_unresolved_predictions()
        assert len(unresolved) == 3

    def test_summary_stats(self, db):
        """Test summary statistics."""
        stats = db.get_summary_stats()
        assert "total_predictions" in stats
        assert "resolved_predictions" in stats
        assert "accuracy" in stats


class TestTimeUrgency:
    """Tests for TimeUrgencyCalculator."""

    def test_critical_phase(self):
        """Test critical phase (0-2 hours)."""
        calc = TimeUrgencyCalculator()
        phase = calc.get_phase(1.5)
        assert phase == UrgencyPhase.CRITICAL

    def test_urgent_phase(self):
        """Test urgent phase (2-8 hours)."""
        calc = TimeUrgencyCalculator()
        phase = calc.get_phase(5.0)
        assert phase == UrgencyPhase.URGENT

    def test_approaching_phase(self):
        """Test approaching phase (8-24 hours)."""
        calc = TimeUrgencyCalculator()
        phase = calc.get_phase(12.0)
        assert phase == UrgencyPhase.APPROACHING

    def test_normal_phase(self):
        """Test normal phase (24-72 hours)."""
        calc = TimeUrgencyCalculator()
        phase = calc.get_phase(48.0)
        assert phase == UrgencyPhase.NORMAL

    def test_distant_phase(self):
        """Test distant phase (72+ hours)."""
        calc = TimeUrgencyCalculator()
        phase = calc.get_phase(100.0)
        assert phase == UrgencyPhase.DISTANT

    def test_edge_adjustment(self):
        """Test edge multiplier decreases near resolution."""
        calc = TimeUrgencyCalculator()

        # Critical phase should have lower edge threshold
        critical = calc.calculate_adjustment(1.0, base_min_edge=0.05)
        normal = calc.calculate_adjustment(48.0, base_min_edge=0.05)

        assert critical.adjusted_min_edge < normal.adjusted_min_edge

    def test_position_adjustment(self):
        """Test position size increases near resolution."""
        calc = TimeUrgencyCalculator()

        # Critical phase should have larger positions
        critical = calc.calculate_adjustment(1.0, base_max_position=100)
        normal = calc.calculate_adjustment(48.0, base_max_position=100)

        assert critical.adjusted_max_position > normal.adjusted_max_position

    def test_should_trade(self):
        """Test should_trade decision."""
        calc = TimeUrgencyCalculator()

        # High edge, high confidence, critical phase - should trade
        should, reason = calc.should_trade(
            edge=0.10,
            confidence=0.75,
            hours_remaining=1.0,
            base_min_edge=0.05
        )
        assert should is True

        # Low confidence - should not trade
        should, reason = calc.should_trade(
            edge=0.10,
            confidence=0.50,
            hours_remaining=1.0,
            base_min_edge=0.05
        )
        assert should is False
        assert "below floor" in reason

    def test_custom_calculator(self):
        """Test custom urgency calculator."""
        calc = create_custom_urgency_calculator(
            critical_hours=1.0,
            urgent_hours=4.0,
            critical_edge_mult=0.3
        )

        adj = calc.calculate_adjustment(0.5, base_min_edge=0.10)
        assert adj.adjusted_min_edge == pytest.approx(0.03, rel=0.01)


class TestCalibrationEngine:
    """Tests for CalibrationEngine."""

    @pytest.fixture
    def db_with_data(self):
        """Create database with calibration data."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test_calibration.db"
            db = LearningDatabase(db_path)

            # Add predictions with outcomes
            for i in range(50):
                confidence = 0.65 + (i % 10) * 0.01  # Range 0.65-0.74
                correct = i % 2 == 0  # 50% accuracy (overconfident)

                prediction = PredictionRecord(
                    trade_id=f"CAL-{i:03d}",
                    market_id=f"MARKET-CAL-{i:03d}",
                    prediction_side="YES",
                    predicted_probability=confidence,
                    market_price=0.5,
                    edge=0.15,
                    confidence=confidence,
                    hours_to_resolution=24.0,
                    actual_outcome="YES" if correct else "NO",
                    resolved_at=datetime.now(timezone.utc).isoformat()
                )
                db.record_prediction(prediction)

            yield db

    def test_calibration_buckets(self, db_with_data):
        """Test calibration bucket calculation."""
        buckets = db_with_data.get_calibration_stats(bucket_width=0.1)

        # Should have buckets
        assert len(buckets) > 0

        # 0.6-0.7 bucket should have data
        bucket_60_70 = next((b for b in buckets if b.bucket_low == 0.6), None)
        assert bucket_60_70 is not None
        assert bucket_60_70.total_predictions > 0

    def test_recalibration(self, db_with_data):
        """Test recalibration process."""
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "calibration_state.json"
            engine = CalibrationEngine(
                db_with_data,
                state_path=state_path,
                min_samples=5
            )

            state = engine.recalibrate()

            assert state is not None
            assert state.total_samples > 0
            assert len(state.bucket_factors) > 0

    def test_calibration_adjustment(self, db_with_data):
        """Test confidence calibration."""
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "calibration_state.json"
            engine = CalibrationEngine(
                db_with_data,
                state_path=state_path,
                min_samples=5
            )
            engine.recalibrate()

            # Calibrate a confidence value
            raw = 0.70
            calibrated = engine.calculate_calibration(raw)

            # Since we're overconfident (70% predicted, 50% actual),
            # calibrated should be lower
            assert calibrated <= raw


class TestPatternDetector:
    """Tests for PatternDetector."""

    @pytest.fixture
    def db_with_patterns(self):
        """Create database with pattern data."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test_patterns.db"
            db = LearningDatabase(db_path)

            # Miami - good performance (70% win rate)
            for i in range(30):
                prediction = PredictionRecord(
                    trade_id=f"MIA-{i:03d}",
                    market_id=f"MARKET-MIA-{i:03d}",
                    prediction_side="YES",
                    predicted_probability=0.6,
                    market_price=0.5,
                    edge=0.10,
                    confidence=0.7,
                    hours_to_resolution=24.0,
                    city="miami",
                    weather_type="precipitation",
                    actual_outcome="YES" if i < 21 else "NO",  # 70%
                    resolved_at=datetime.now(timezone.utc).isoformat()
                )
                db.record_prediction(prediction)

            # Chicago - poor performance (40% win rate)
            for i in range(30):
                prediction = PredictionRecord(
                    trade_id=f"CHI-{i:03d}",
                    market_id=f"MARKET-CHI-{i:03d}",
                    prediction_side="YES",
                    predicted_probability=0.6,
                    market_price=0.5,
                    edge=0.10,
                    confidence=0.7,
                    hours_to_resolution=24.0,
                    city="chicago",
                    weather_type="temperature",
                    actual_outcome="YES" if i < 12 else "NO",  # 40%
                    resolved_at=datetime.now(timezone.utc).isoformat()
                )
                db.record_prediction(prediction)

            yield db

    def test_pattern_detection(self, db_with_patterns):
        """Test pattern detection."""
        detector = PatternDetector(db_with_patterns, min_samples=20)
        patterns = detector.detect_patterns()

        assert len(patterns) > 0

        # Should detect Miami and Chicago
        cities = [p.pattern_value for p in patterns if p.pattern_type == "city"]
        assert "miami" in cities
        assert "chicago" in cities

    def test_pattern_adjustment(self, db_with_patterns):
        """Test pattern-based edge adjustment."""
        detector = PatternDetector(db_with_patterns, min_samples=20)
        detector.detect_patterns()

        # Miami should have positive adjustment
        miami_context = TradeContext(
            trade_id="TEST",
            market_id="TEST",
            city="miami"
        )
        miami_adj = detector.get_pattern_adjustment(miami_context)
        assert miami_adj.total_adjustment >= 0

        # Chicago should have negative adjustment
        chicago_context = TradeContext(
            trade_id="TEST",
            market_id="TEST",
            city="chicago"
        )
        chicago_adj = detector.get_pattern_adjustment(chicago_context)
        assert chicago_adj.total_adjustment <= 0

    def test_wilson_score(self):
        """Test Wilson score interval calculation."""
        # 70 out of 100 successes
        low, high = calculate_wilson_score_interval(70, 100)

        assert low < 0.70
        assert high > 0.70
        assert low > 0.60  # Should be in reasonable range
        assert high < 0.80


class TestLearningOrchestrator:
    """Tests for LearningOrchestrator."""

    @pytest.fixture
    def orchestrator(self):
        """Create orchestrator with temp paths."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = LearningConfig(
                enabled=True,
                database_path=Path(tmpdir) / "test.db",
                proposal_output_path=Path(tmpdir) / "proposals",
                min_calibration_samples=5,
                min_pattern_samples=5
            )
            yield LearningOrchestrator(config)

    def test_enhance_signal(self, orchestrator):
        """Test signal enhancement."""
        enhanced = orchestrator.enhance_signal(
            market_id="TEST-001",
            edge=0.10,
            confidence=0.70,
            suggested_size=100.0,
            hours_to_resolution=5.0,  # Urgent phase
            base_min_edge=0.05
        )

        assert enhanced is not None
        assert enhanced.urgency_adjustment is not None
        assert enhanced.urgency_adjustment.phase == UrgencyPhase.URGENT
        # Position should be increased in urgent phase
        assert enhanced.adjusted_size > enhanced.original_size

    def test_record_and_track(self, orchestrator):
        """Test recording predictions."""
        success = orchestrator.record_prediction(
            trade_id="ORCH-001",
            market_id="MARKET-001",
            prediction_side="YES",
            predicted_probability=0.7,
            market_price=0.55,
            edge=0.15,
            confidence=0.8,
            hours_to_resolution=24.0
        )
        assert success is True

    def test_disabled_orchestrator(self):
        """Test disabled learning system."""
        config = LearningConfig(enabled=False)
        orch = LearningOrchestrator(config)

        assert orch.is_enabled is False

        # Should still work but return defaults
        enhanced = orch.enhance_signal(
            market_id="TEST",
            edge=0.10,
            confidence=0.70,
            suggested_size=100.0,
            hours_to_resolution=5.0
        )
        # Disabled means no enhancements
        assert enhanced.adjusted_size == enhanced.original_size

    def test_get_status(self, orchestrator):
        """Test status reporting."""
        status = orchestrator.get_status()

        assert status["enabled"] is True
        assert "components" in status
        assert "database" in status


class TestSeasonHelper:
    """Tests for season helper function."""

    def test_winter(self):
        """Test winter detection."""
        assert get_season(datetime(2024, 12, 15)) == "winter"
        assert get_season(datetime(2024, 1, 15)) == "winter"
        assert get_season(datetime(2024, 2, 15)) == "winter"

    def test_spring(self):
        """Test spring detection."""
        assert get_season(datetime(2024, 3, 15)) == "spring"
        assert get_season(datetime(2024, 4, 15)) == "spring"
        assert get_season(datetime(2024, 5, 15)) == "spring"

    def test_summer(self):
        """Test summer detection."""
        assert get_season(datetime(2024, 6, 15)) == "summer"
        assert get_season(datetime(2024, 7, 15)) == "summer"
        assert get_season(datetime(2024, 8, 15)) == "summer"

    def test_fall(self):
        """Test fall detection."""
        assert get_season(datetime(2024, 9, 15)) == "fall"
        assert get_season(datetime(2024, 10, 15)) == "fall"
        assert get_season(datetime(2024, 11, 15)) == "fall"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
