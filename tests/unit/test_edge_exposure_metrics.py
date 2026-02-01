# =============================================================================
# UNIT TESTS - EDGE EXPOSURE METRICS
# =============================================================================
#
# Tests for edge area calculation, time window filtering, and exposure ratios.
#
# =============================================================================

import pytest
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta

# Setup paths
BASE_DIR = Path(__file__).parent.parent.parent
sys.path.insert(0, str(BASE_DIR))

from core.edge_exposure_metrics import (
    TimeWindow,
    get_window_start,
    calculate_edge_area,
    calculate_edge_duration,
    calculate_exposure_ratio,
    calculate_median_positive_duration,
    PositionEdgeMetrics,
    EdgeExposureSummary,
    check_import_safety,
)


# =============================================================================
# EDGE AREA CALCULATION TESTS
# =============================================================================


class TestEdgeAreaCalculation:
    """Tests for edge area (integral) calculation."""

    def test_single_snapshot_positive(self):
        """Test single snapshot with positive edge."""
        snapshots = [
            {
                "timestamp_utc": "2026-01-24T15:00:00+00:00",
                "edge_relative": 0.20,
            }
        ]
        total, positive, negative = calculate_edge_area(snapshots)

        assert total == 0.20
        assert positive == 0.20
        assert negative == 0.0

    def test_single_snapshot_negative(self):
        """Test single snapshot with negative edge."""
        snapshots = [
            {
                "timestamp_utc": "2026-01-24T15:00:00+00:00",
                "edge_relative": -0.10,
            }
        ]
        total, positive, negative = calculate_edge_area(snapshots)

        assert total == -0.10
        assert positive == 0.0
        assert negative == -0.10

    def test_two_snapshots_constant_edge(self):
        """Test two snapshots with constant positive edge."""
        snapshots = [
            {
                "timestamp_utc": "2026-01-24T15:00:00+00:00",
                "edge_relative": 0.20,
            },
            {
                "timestamp_utc": "2026-01-24T15:30:00+00:00",  # 30 minutes later
                "edge_relative": 0.20,
            }
        ]
        total, positive, negative = calculate_edge_area(snapshots)

        # Edge area = 0.20 * 30 minutes = 6.0 edge-minutes
        assert abs(total - 6.0) < 0.01
        assert abs(positive - 6.0) < 0.01
        assert negative == 0.0

    def test_two_snapshots_changing_edge(self):
        """Test two snapshots with changing edge (trapezoidal rule)."""
        snapshots = [
            {
                "timestamp_utc": "2026-01-24T15:00:00+00:00",
                "edge_relative": 0.10,
            },
            {
                "timestamp_utc": "2026-01-24T16:00:00+00:00",  # 60 minutes later
                "edge_relative": 0.30,
            }
        ]
        total, positive, negative = calculate_edge_area(snapshots)

        # Average edge = (0.10 + 0.30) / 2 = 0.20
        # Edge area = 0.20 * 60 minutes = 12.0 edge-minutes
        assert abs(total - 12.0) < 0.01
        assert abs(positive - 12.0) < 0.01
        assert negative == 0.0

    def test_three_snapshots_mixed_edge(self):
        """Test three snapshots with positive and negative edge."""
        snapshots = [
            {
                "timestamp_utc": "2026-01-24T15:00:00+00:00",
                "edge_relative": 0.20,
            },
            {
                "timestamp_utc": "2026-01-24T15:30:00+00:00",  # 30 min
                "edge_relative": 0.10,  # Average: 0.15
            },
            {
                "timestamp_utc": "2026-01-24T16:00:00+00:00",  # 30 min more
                "edge_relative": -0.10,  # Average: 0.0
            }
        ]
        total, positive, negative = calculate_edge_area(snapshots)

        # First interval: avg=0.15, dt=30 -> 4.5
        # Second interval: avg=0.0, dt=30 -> 0
        # Total positive: 4.5
        assert abs(positive - 4.5) < 0.01
        assert abs(negative - 0.0) < 0.01

    def test_multiple_snapshots_alternating(self):
        """Test snapshots alternating between positive and negative."""
        snapshots = [
            {"timestamp_utc": "2026-01-24T15:00:00+00:00", "edge_relative": 0.20},
            {"timestamp_utc": "2026-01-24T15:30:00+00:00", "edge_relative": -0.20},  # avg=0
            {"timestamp_utc": "2026-01-24T16:00:00+00:00", "edge_relative": 0.10},  # avg=-0.05
            {"timestamp_utc": "2026-01-24T16:30:00+00:00", "edge_relative": 0.10},  # avg=0.10
        ]
        total, positive, negative = calculate_edge_area(snapshots)

        # Interval 1: avg=0, dt=30 -> 0 (neither)
        # Interval 2: avg=-0.05, dt=30 -> -1.5 (negative)
        # Interval 3: avg=0.10, dt=30 -> 3.0 (positive)
        assert abs(positive - 3.0) < 0.1
        assert abs(negative - (-1.5)) < 0.1
        assert abs(total - 1.5) < 0.1

    def test_empty_snapshots(self):
        """Test with empty snapshot list."""
        total, positive, negative = calculate_edge_area([])

        assert total == 0.0
        assert positive == 0.0
        assert negative == 0.0

    def test_skips_invalid_timestamps(self):
        """Test that invalid timestamps are skipped."""
        snapshots = [
            {"timestamp_utc": "2026-01-24T15:00:00+00:00", "edge_relative": 0.20},
            {"timestamp_utc": "invalid", "edge_relative": 0.10},
            {"timestamp_utc": "2026-01-24T16:00:00+00:00", "edge_relative": 0.10},
        ]
        # Should skip intervals involving invalid timestamps
        # With sorted snapshots, invalid is in middle but can't calculate delta
        total, positive, negative = calculate_edge_area(snapshots)

        # The function processes pairs, so it tries:
        # 1. snap[0] -> snap[1]: invalid timestamp, skipped
        # 2. snap[1] -> snap[2]: invalid timestamp, skipped
        # Result: 0 edge area (no valid intervals)
        # This is correct fail-closed behavior
        assert total == 0.0


# =============================================================================
# EDGE DURATION TESTS
# =============================================================================


class TestEdgeDuration:
    """Tests for edge duration calculation."""

    def test_all_positive_duration(self):
        """Test duration with all positive edge."""
        snapshots = [
            {"timestamp_utc": "2026-01-24T15:00:00+00:00", "edge_relative": 0.20},
            {"timestamp_utc": "2026-01-24T16:00:00+00:00", "edge_relative": 0.10},
        ]
        positive, negative = calculate_edge_duration(snapshots)

        assert positive == 60
        assert negative == 0

    def test_all_negative_duration(self):
        """Test duration with all negative edge."""
        snapshots = [
            {"timestamp_utc": "2026-01-24T15:00:00+00:00", "edge_relative": -0.20},
            {"timestamp_utc": "2026-01-24T16:00:00+00:00", "edge_relative": -0.10},
        ]
        positive, negative = calculate_edge_duration(snapshots)

        assert positive == 0
        assert negative == 60

    def test_mixed_duration(self):
        """Test duration with mixed edge."""
        snapshots = [
            {"timestamp_utc": "2026-01-24T15:00:00+00:00", "edge_relative": 0.20},
            {"timestamp_utc": "2026-01-24T15:30:00+00:00", "edge_relative": 0.20},  # 30 min positive
            {"timestamp_utc": "2026-01-24T16:00:00+00:00", "edge_relative": -0.20},  # crosses zero
            {"timestamp_utc": "2026-01-24T16:30:00+00:00", "edge_relative": -0.20},  # 30 min negative
        ]
        positive, negative = calculate_edge_duration(snapshots)

        # First interval: positive (30 min)
        # Second interval: avg=0, neither (0 min each)
        # Third interval: negative (30 min)
        assert positive == 30
        assert negative == 30


# =============================================================================
# EXPOSURE RATIO TESTS
# =============================================================================


class TestExposureRatio:
    """Tests for exposure ratio calculation."""

    def test_all_positive(self):
        """Test ratio with all positive exposure."""
        ratio = calculate_exposure_ratio(100.0, 0.0)
        assert ratio == 1.0

    def test_all_negative(self):
        """Test ratio with all negative exposure."""
        ratio = calculate_exposure_ratio(0.0, -100.0)
        assert ratio == 0.0

    def test_equal_exposure(self):
        """Test ratio with equal positive and negative."""
        ratio = calculate_exposure_ratio(50.0, -50.0)
        assert ratio == 0.5

    def test_mostly_positive(self):
        """Test ratio with mostly positive exposure."""
        ratio = calculate_exposure_ratio(80.0, -20.0)
        assert ratio == 0.8

    def test_zero_total_returns_none(self):
        """Test that zero total exposure returns None."""
        ratio = calculate_exposure_ratio(0.0, 0.0)
        assert ratio is None


# =============================================================================
# MEDIAN DURATION TESTS
# =============================================================================


class TestMedianDuration:
    """Tests for median positive duration calculation."""

    def test_simple_median(self):
        """Test simple median calculation."""
        durations = [10, 20, 30, 40, 50]
        median = calculate_median_positive_duration(durations)
        assert median == 30

    def test_even_count(self):
        """Test median with even count."""
        durations = [10, 20, 30, 40]
        median = calculate_median_positive_duration(durations)
        assert median == 25  # (20 + 30) / 2

    def test_filters_zeros(self):
        """Test that zeros are filtered out."""
        durations = [0, 0, 10, 20, 30, 0]
        median = calculate_median_positive_duration(durations)
        assert median == 20

    def test_all_zeros_returns_none(self):
        """Test that all zeros returns None."""
        durations = [0, 0, 0]
        median = calculate_median_positive_duration(durations)
        assert median is None

    def test_empty_returns_none(self):
        """Test that empty list returns None."""
        median = calculate_median_positive_duration([])
        assert median is None


# =============================================================================
# TIME WINDOW TESTS
# =============================================================================


class TestTimeWindow:
    """Tests for time window parsing and filtering."""

    def test_parse_last_24h(self):
        """Test parsing last_24h."""
        window = TimeWindow.from_string("last_24h")
        assert window == TimeWindow.LAST_24H

    def test_parse_last_7d(self):
        """Test parsing last_7d."""
        window = TimeWindow.from_string("last_7d")
        assert window == TimeWindow.LAST_7D

    def test_parse_all_time(self):
        """Test parsing all_time."""
        window = TimeWindow.from_string("all_time")
        assert window == TimeWindow.ALL_TIME

    def test_parse_invalid_raises(self):
        """Test that invalid window raises ValueError."""
        with pytest.raises(ValueError, match="Unknown time window"):
            TimeWindow.from_string("invalid")

    def test_window_start_last_24h(self):
        """Test window start for last_24h."""
        start = get_window_start(TimeWindow.LAST_24H)
        now = datetime.now(timezone.utc)

        # Should be approximately 24 hours ago
        delta = now - start
        assert 23 * 3600 <= delta.total_seconds() <= 25 * 3600

    def test_window_start_all_time(self):
        """Test window start for all_time is None."""
        start = get_window_start(TimeWindow.ALL_TIME)
        assert start is None


# =============================================================================
# DATA CLASS TESTS
# =============================================================================


class TestDataClasses:
    """Tests for data class functionality."""

    def test_position_metrics_to_dict(self):
        """Test PositionEdgeMetrics serialization."""
        metrics = PositionEdgeMetrics(
            position_id="pos-1",
            market_id="mkt-1",
            snapshot_count=10,
            first_snapshot_utc="2026-01-24T15:00:00+00:00",
            last_snapshot_utc="2026-01-24T16:00:00+00:00",
            total_duration_minutes=60,
            edge_area_minutes=12.0,
            positive_edge_area_minutes=12.0,
            negative_edge_area_minutes=0.0,
            positive_edge_duration_minutes=60,
            negative_edge_duration_minutes=0,
            min_edge_relative=0.10,
            max_edge_relative=0.30,
            avg_edge_relative=0.20,
        )

        data = metrics.to_dict()
        assert data["position_id"] == "pos-1"
        assert data["edge_area_minutes"] == 12.0
        assert "governance_notice" in data

    def test_summary_to_dict(self):
        """Test EdgeExposureSummary serialization."""
        summary = EdgeExposureSummary(
            schema_version=1,
            generated_at_utc="2026-01-24T15:00:00+00:00",
            time_window="last_7d",
            open_positions_count=10,
            snapshot_count=100,
            total_edge_exposure_hours=20.5,
            positive_edge_exposure_hours=25.0,
            negative_edge_exposure_hours=-4.5,
            edge_exposure_ratio=0.847,
            median_edge_duration_minutes=45,
        )

        data = summary.to_dict()
        assert data["open_positions_count"] == 10
        assert data["edge_exposure_ratio"] == 0.847
        assert "governance_notice" in data

    def test_summary_to_json(self):
        """Test EdgeExposureSummary JSON serialization."""
        summary = EdgeExposureSummary(
            schema_version=1,
            generated_at_utc="2026-01-24T15:00:00+00:00",
            time_window="all_time",
            open_positions_count=5,
            snapshot_count=50,
            total_edge_exposure_hours=10.0,
            positive_edge_exposure_hours=10.0,
            negative_edge_exposure_hours=0.0,
            edge_exposure_ratio=1.0,
            median_edge_duration_minutes=30,
        )

        json_str = summary.to_json()
        assert '"schema_version": 1' in json_str
        assert '"governance_notice"' in json_str


# =============================================================================
# SAFETY TESTS
# =============================================================================


class TestSafety:
    """Tests for import safety."""

    def test_no_forbidden_imports(self):
        """Test that module has no forbidden imports."""
        result = check_import_safety()
        assert result is True


# =============================================================================
# RUN TESTS
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
