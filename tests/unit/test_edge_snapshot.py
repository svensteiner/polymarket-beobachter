# =============================================================================
# UNIT TESTS - EDGE SNAPSHOT MODULE
# =============================================================================
#
# Tests for edge calculation correctness and schema validation.
#
# =============================================================================

import pytest
import sys
from pathlib import Path

# Setup paths
BASE_DIR = Path(__file__).parent.parent.parent
sys.path.insert(0, str(BASE_DIR))

from core.edge_snapshot import (
    EdgeSnapshot,
    SCHEMA_VERSION,
    calculate_edge_relative,
    calculate_edge_at_entry,
    calculate_edge_delta_since_entry,
    calculate_time_since_entry_minutes,
    create_edge_snapshot,
    compute_hash,
    canonical_json,
    generate_snapshot_id,
    get_utc_timestamp,
    get_minute_bucket,
)


# =============================================================================
# EDGE CALCULATION TESTS
# =============================================================================


class TestEdgeCalculations:
    """Tests for edge calculation functions."""

    def test_edge_relative_positive(self):
        """Test positive edge calculation (fair > market)."""
        # Fair value 80%, market at 65%
        # Edge = (0.80 - 0.65) / 0.65 = 0.2308
        edge = calculate_edge_relative(
            fair_probability_entry=0.80,
            market_probability_current=0.65,
        )
        assert abs(edge - 0.2308) < 0.001

    def test_edge_relative_negative(self):
        """Test negative edge calculation (fair < market)."""
        # Fair value 50%, market at 65%
        # Edge = (0.50 - 0.65) / 0.65 = -0.2308
        edge = calculate_edge_relative(
            fair_probability_entry=0.50,
            market_probability_current=0.65,
        )
        assert abs(edge - (-0.2308)) < 0.001

    def test_edge_relative_zero(self):
        """Test zero edge when fair equals market."""
        edge = calculate_edge_relative(
            fair_probability_entry=0.65,
            market_probability_current=0.65,
        )
        assert edge == 0.0

    def test_edge_relative_zero_market_raises(self):
        """Test that zero market probability raises ValueError."""
        with pytest.raises(ValueError, match="cannot be zero"):
            calculate_edge_relative(
                fair_probability_entry=0.50,
                market_probability_current=0.0,
            )

    def test_edge_at_entry(self):
        """Test edge at entry calculation."""
        # Fair value 80%, market at 65% at entry
        edge = calculate_edge_at_entry(
            fair_probability_entry=0.80,
            market_probability_entry=0.65,
        )
        assert abs(edge - 0.2308) < 0.001

    def test_edge_delta_convergence(self):
        """Test edge delta when market converges to fair value."""
        # Entry: fair=80%, market=65%, edge_at_entry = 0.2308
        # Now: market=80%, edge_current = 0
        # Delta = 0 - 0.2308 = -0.2308 (edge decreased)
        delta = calculate_edge_delta_since_entry(
            fair_probability_entry=0.80,
            market_probability_current=0.80,
            market_probability_entry=0.65,
        )
        assert abs(delta - (-0.2308)) < 0.001

    def test_edge_delta_divergence(self):
        """Test edge delta when market diverges from fair value."""
        # Entry: fair=80%, market=65%, edge_at_entry = 0.2308
        # Now: market=50%, edge_current = 0.60
        # Delta = 0.60 - 0.2308 = 0.3692 (edge increased)
        delta = calculate_edge_delta_since_entry(
            fair_probability_entry=0.80,
            market_probability_current=0.50,
            market_probability_entry=0.65,
        )
        assert abs(delta - 0.3692) < 0.001

    def test_edge_delta_no_change(self):
        """Test edge delta when market hasn't moved."""
        # Market stayed at 65%, edge unchanged
        delta = calculate_edge_delta_since_entry(
            fair_probability_entry=0.80,
            market_probability_current=0.65,
            market_probability_entry=0.65,
        )
        assert delta == 0.0


class TestTimeCalculations:
    """Tests for time calculation functions."""

    def test_time_since_entry_positive(self):
        """Test time calculation with valid timestamps."""
        from datetime import datetime, timezone, timedelta

        now = datetime.now(timezone.utc)
        entry = now - timedelta(minutes=120)

        minutes = calculate_time_since_entry_minutes(
            entry_time=entry.isoformat(),
            current_time=now.isoformat(),
        )
        assert minutes == 120

    def test_time_since_entry_default_now(self):
        """Test time calculation using default current time."""
        from datetime import datetime, timezone, timedelta

        entry = datetime.now(timezone.utc) - timedelta(minutes=60)

        minutes = calculate_time_since_entry_minutes(
            entry_time=entry.isoformat(),
        )
        # Should be approximately 60 minutes
        assert 59 <= minutes <= 61

    def test_time_since_entry_invalid_returns_zero(self):
        """Test that invalid timestamps return 0."""
        minutes = calculate_time_since_entry_minutes(
            entry_time="invalid-timestamp",
        )
        assert minutes == 0

    def test_minute_bucket(self):
        """Test minute bucket extraction."""
        timestamp = "2026-01-24T15:30:45.123456+00:00"
        bucket = get_minute_bucket(timestamp)
        assert bucket == "2026-01-24T15:30"


# =============================================================================
# SCHEMA VALIDATION TESTS
# =============================================================================


class TestEdgeSnapshotValidation:
    """Tests for EdgeSnapshot schema validation."""

    def test_valid_snapshot_creation(self):
        """Test creation of a valid snapshot."""
        snapshot = EdgeSnapshot(
            schema_version=SCHEMA_VERSION,
            snapshot_id="test-id-123",
            position_id="PAPER-20260124-abc123",
            market_id="market-456",
            timestamp_utc="2026-01-24T15:30:00+00:00",
            time_since_entry_minutes=60,
            market_probability_current=0.65,
            fair_probability_entry=0.80,
            edge_relative=0.2308,
            edge_delta_since_entry=-0.05,
            source="cli",
        )
        assert snapshot.snapshot_id == "test-id-123"
        assert snapshot.edge_relative == 0.2308

    def test_invalid_schema_version(self):
        """Test that wrong schema version raises error."""
        with pytest.raises(ValueError, match="schema_version"):
            EdgeSnapshot(
                schema_version=999,
                snapshot_id="test-id",
                position_id="pos-id",
                market_id="mkt-id",
                timestamp_utc="2026-01-24T15:30:00+00:00",
                time_since_entry_minutes=60,
                market_probability_current=0.65,
                fair_probability_entry=0.80,
                edge_relative=0.2308,
                edge_delta_since_entry=-0.05,
                source="cli",
            )

    def test_missing_snapshot_id(self):
        """Test that missing snapshot_id raises error."""
        with pytest.raises(ValueError, match="snapshot_id is required"):
            EdgeSnapshot(
                schema_version=SCHEMA_VERSION,
                snapshot_id="",
                position_id="pos-id",
                market_id="mkt-id",
                timestamp_utc="2026-01-24T15:30:00+00:00",
                time_since_entry_minutes=60,
                market_probability_current=0.65,
                fair_probability_entry=0.80,
                edge_relative=0.2308,
                edge_delta_since_entry=-0.05,
                source="cli",
            )

    def test_invalid_probability_range(self):
        """Test that probabilities outside 0-1 raise error."""
        with pytest.raises(ValueError, match="market_probability_current must be 0-1"):
            EdgeSnapshot(
                schema_version=SCHEMA_VERSION,
                snapshot_id="test-id",
                position_id="pos-id",
                market_id="mkt-id",
                timestamp_utc="2026-01-24T15:30:00+00:00",
                time_since_entry_minutes=60,
                market_probability_current=1.5,  # Invalid!
                fair_probability_entry=0.80,
                edge_relative=0.2308,
                edge_delta_since_entry=-0.05,
                source="cli",
            )

    def test_invalid_source(self):
        """Test that invalid source raises error."""
        with pytest.raises(ValueError, match="source must be one of"):
            EdgeSnapshot(
                schema_version=SCHEMA_VERSION,
                snapshot_id="test-id",
                position_id="pos-id",
                market_id="mkt-id",
                timestamp_utc="2026-01-24T15:30:00+00:00",
                time_since_entry_minutes=60,
                market_probability_current=0.65,
                fair_probability_entry=0.80,
                edge_relative=0.2308,
                edge_delta_since_entry=-0.05,
                source="invalid_source",
            )

    def test_negative_time_since_entry(self):
        """Test that negative time_since_entry raises error."""
        with pytest.raises(ValueError, match="time_since_entry_minutes must be >= 0"):
            EdgeSnapshot(
                schema_version=SCHEMA_VERSION,
                snapshot_id="test-id",
                position_id="pos-id",
                market_id="mkt-id",
                timestamp_utc="2026-01-24T15:30:00+00:00",
                time_since_entry_minutes=-10,  # Invalid!
                market_probability_current=0.65,
                fair_probability_entry=0.80,
                edge_relative=0.2308,
                edge_delta_since_entry=-0.05,
                source="cli",
            )


class TestSnapshotSerialization:
    """Tests for snapshot serialization."""

    def test_to_dict(self):
        """Test conversion to dictionary."""
        snapshot = EdgeSnapshot(
            schema_version=SCHEMA_VERSION,
            snapshot_id="test-id",
            position_id="pos-id",
            market_id="mkt-id",
            timestamp_utc="2026-01-24T15:30:00+00:00",
            time_since_entry_minutes=60,
            market_probability_current=0.65,
            fair_probability_entry=0.80,
            edge_relative=0.2308,
            edge_delta_since_entry=-0.05,
            source="cli",
        )
        data = snapshot.to_dict()

        assert data["snapshot_id"] == "test-id"
        assert data["position_id"] == "pos-id"
        assert data["edge_relative"] == 0.2308
        assert "governance_notice" in data

    def test_from_dict(self):
        """Test creation from dictionary."""
        data = {
            "schema_version": SCHEMA_VERSION,
            "snapshot_id": "test-id",
            "position_id": "pos-id",
            "market_id": "mkt-id",
            "timestamp_utc": "2026-01-24T15:30:00+00:00",
            "time_since_entry_minutes": 60,
            "market_probability_current": 0.65,
            "fair_probability_entry": 0.80,
            "edge_relative": 0.2308,
            "edge_delta_since_entry": -0.05,
            "source": "cli",
            "record_hash": "abc123",
        }
        snapshot = EdgeSnapshot.from_dict(data)

        assert snapshot.snapshot_id == "test-id"
        assert snapshot.edge_relative == 0.2308
        assert snapshot.record_hash == "abc123"

    def test_roundtrip(self):
        """Test that to_dict and from_dict are reversible."""
        original = EdgeSnapshot(
            schema_version=SCHEMA_VERSION,
            snapshot_id="test-id",
            position_id="pos-id",
            market_id="mkt-id",
            timestamp_utc="2026-01-24T15:30:00+00:00",
            time_since_entry_minutes=60,
            market_probability_current=0.65,
            fair_probability_entry=0.80,
            edge_relative=0.2308,
            edge_delta_since_entry=-0.05,
            source="cli",
        )
        data = original.to_dict()
        restored = EdgeSnapshot.from_dict(data)

        assert original.snapshot_id == restored.snapshot_id
        assert original.edge_relative == restored.edge_relative


# =============================================================================
# HASHING TESTS
# =============================================================================


class TestHashing:
    """Tests for canonical JSON and hashing."""

    def test_canonical_json_sorted_keys(self):
        """Test that keys are sorted in canonical JSON."""
        data = {"z": 1, "a": 2, "m": 3}
        canonical = canonical_json(data)
        assert canonical == '{"a":2,"m":3,"z":1}'

    def test_canonical_json_no_whitespace(self):
        """Test that canonical JSON has no whitespace."""
        data = {"key": "value", "number": 123}
        canonical = canonical_json(data)
        assert " " not in canonical
        assert "\n" not in canonical

    def test_compute_hash_excludes_record_hash(self):
        """Test that record_hash field is excluded from hash."""
        data_without_hash = {"key": "value"}
        data_with_hash = {"key": "value", "record_hash": "existing_hash"}

        hash1 = compute_hash(data_without_hash)
        hash2 = compute_hash(data_with_hash)

        # Should be identical since record_hash is excluded
        assert hash1 == hash2

    def test_hash_is_deterministic(self):
        """Test that same input produces same hash."""
        data = {"a": 1, "b": 2, "c": 3}
        hash1 = compute_hash(data)
        hash2 = compute_hash(data)
        assert hash1 == hash2

    def test_hash_is_sha256(self):
        """Test that hash is valid SHA256 (64 hex characters)."""
        data = {"test": "data"}
        hash_value = compute_hash(data)
        assert len(hash_value) == 64
        assert all(c in "0123456789abcdef" for c in hash_value)


# =============================================================================
# FACTORY FUNCTION TESTS
# =============================================================================


class TestCreateEdgeSnapshot:
    """Tests for create_edge_snapshot factory function."""

    def test_creates_valid_snapshot(self):
        """Test that factory creates a valid snapshot."""
        snapshot = create_edge_snapshot(
            position_id="PAPER-20260124-abc123",
            market_id="market-456",
            time_since_entry_minutes=60,
            market_probability_current=0.65,
            fair_probability_entry=0.80,
            market_probability_entry=0.65,
            source="cli",
        )

        assert snapshot.position_id == "PAPER-20260124-abc123"
        assert snapshot.market_id == "market-456"
        assert snapshot.source == "cli"

    def test_calculates_edge_correctly(self):
        """Test that factory calculates edge metrics correctly."""
        snapshot = create_edge_snapshot(
            position_id="test-pos",
            market_id="test-mkt",
            time_since_entry_minutes=60,
            market_probability_current=0.65,
            fair_probability_entry=0.80,
            market_probability_entry=0.65,
            source="scheduler",
        )

        # Edge relative = (0.80 - 0.65) / 0.65 = 0.2308
        assert abs(snapshot.edge_relative - 0.2308) < 0.001

        # Edge at entry was same since market hasn't moved
        # Delta should be 0
        assert snapshot.edge_delta_since_entry == 0.0

    def test_generates_unique_ids(self):
        """Test that factory generates unique snapshot IDs."""
        snapshot1 = create_edge_snapshot(
            position_id="test-pos",
            market_id="test-mkt",
            time_since_entry_minutes=60,
            market_probability_current=0.65,
            fair_probability_entry=0.80,
            market_probability_entry=0.65,
            source="scheduler",
        )
        snapshot2 = create_edge_snapshot(
            position_id="test-pos",
            market_id="test-mkt",
            time_since_entry_minutes=60,
            market_probability_current=0.65,
            fair_probability_entry=0.80,
            market_probability_entry=0.65,
            source="scheduler",
        )

        assert snapshot1.snapshot_id != snapshot2.snapshot_id

    def test_computes_hash(self):
        """Test that factory computes record hash."""
        snapshot = create_edge_snapshot(
            position_id="test-pos",
            market_id="test-mkt",
            time_since_entry_minutes=60,
            market_probability_current=0.65,
            fair_probability_entry=0.80,
            market_probability_entry=0.65,
            source="scheduler",
        )

        assert snapshot.record_hash != ""
        assert len(snapshot.record_hash) == 64


# =============================================================================
# RUN TESTS
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
