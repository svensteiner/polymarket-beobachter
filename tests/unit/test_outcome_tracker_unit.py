#!/usr/bin/env python3
# =============================================================================
# OUTCOME TRACKER - UNIT TESTS
# =============================================================================
#
# Tests for:
# - Hashing canonicalization
# - Schema validation rejects bad records
# - Append-only writer writes exactly one line
# - Dedup logic
#
# =============================================================================

import json
import pytest
import tempfile
import shutil
from pathlib import Path
from datetime import datetime, timezone

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.outcome_tracker import (
    PredictionSnapshot,
    ResolutionRecord,
    CorrectionRecord,
    EngineContext,
    OutcomeStorage,
    IndexBuilder,
    canonical_json,
    compute_hash,
    generate_event_id,
    get_utc_timestamp,
    get_minute_bucket,
    create_prediction_snapshot,
    create_resolution_record,
    SCHEMA_VERSION,
    VALID_RESOLUTIONS,
    VALID_DECISIONS,
)


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def temp_dir():
    """Create a temporary directory for tests."""
    tmpdir = tempfile.mkdtemp()
    yield Path(tmpdir)
    shutil.rmtree(tmpdir)


@pytest.fixture
def storage(temp_dir):
    """Create a storage instance with temp directory."""
    return OutcomeStorage(temp_dir)


@pytest.fixture
def valid_prediction():
    """Create a valid prediction snapshot."""
    return create_prediction_snapshot(
        market_id="test_market_123",
        question="Will test pass?",
        decision="TRADE",
        decision_reasons=["All criteria passed"],
        engine="baseline",
        mode="SHADOW",
        run_id="test_run_001",
        source="cli",
        market_price_yes=0.65,
        market_price_no=0.35,
        our_estimate_yes=0.70,
        estimate_confidence="MEDIUM",
    )


@pytest.fixture
def valid_resolution():
    """Create a valid resolution record."""
    return create_resolution_record(
        market_id="test_market_123",
        resolution="YES",
        resolution_source="gamma-api.polymarket.com/markets",
        resolved_timestamp_utc="2026-01-15T12:00:00Z",
    )


# =============================================================================
# TEST: CANONICAL JSON & HASHING
# =============================================================================


class TestCanonicalJson:
    """Test canonical JSON generation."""

    def test_keys_sorted(self):
        """Keys should be sorted alphabetically."""
        data = {"z": 1, "a": 2, "m": 3}
        result = canonical_json(data)
        assert result == '{"a":2,"m":3,"z":1}'

    def test_no_whitespace(self):
        """No whitespace in output."""
        data = {"key": "value", "number": 42}
        result = canonical_json(data)
        assert " " not in result
        assert "\n" not in result

    def test_nested_sorted(self):
        """Nested objects should also have sorted keys."""
        data = {"outer": {"z": 1, "a": 2}}
        result = canonical_json(data)
        assert result == '{"outer":{"a":2,"z":1}}'

    def test_deterministic(self):
        """Same input should always produce same output."""
        data = {"b": 2, "a": 1, "c": 3}
        result1 = canonical_json(data)
        result2 = canonical_json(data)
        assert result1 == result2


class TestHashComputation:
    """Test hash computation."""

    def test_hash_excludes_record_hash(self):
        """Hash should exclude record_hash field."""
        data = {"field1": "value1", "record_hash": "should_be_ignored"}
        hash1 = compute_hash(data)

        data2 = {"field1": "value1", "record_hash": "different_value"}
        hash2 = compute_hash(data2)

        assert hash1 == hash2

    def test_hash_is_deterministic(self):
        """Same data should produce same hash."""
        data = {"market_id": "test", "decision": "TRADE"}
        hash1 = compute_hash(data)
        hash2 = compute_hash(data)
        assert hash1 == hash2

    def test_hash_changes_with_data(self):
        """Different data should produce different hash."""
        data1 = {"market_id": "test1"}
        data2 = {"market_id": "test2"}
        assert compute_hash(data1) != compute_hash(data2)

    def test_hash_is_sha256(self):
        """Hash should be 64 character hex string (SHA256)."""
        data = {"test": "data"}
        hash_val = compute_hash(data)
        assert len(hash_val) == 64
        assert all(c in "0123456789abcdef" for c in hash_val)


# =============================================================================
# TEST: SCHEMA VALIDATION
# =============================================================================


class TestPredictionValidation:
    """Test PredictionSnapshot validation."""

    def test_valid_prediction_passes(self, valid_prediction):
        """Valid prediction should not raise errors."""
        errors = valid_prediction.validate()
        assert len(errors) == 0

    def test_invalid_schema_version(self):
        """Wrong schema version should be rejected."""
        with pytest.raises(ValueError, match="schema_version"):
            PredictionSnapshot(
                schema_version=999,  # Invalid
                event_id="test",
                timestamp_utc="2026-01-01T00:00:00Z",
                market_id="test",
                question="Test?",
                outcomes=["YES", "NO"],
                market_price_yes=0.5,
                market_price_no=0.5,
                our_estimate_yes=0.5,
                estimate_confidence="MEDIUM",
                decision="TRADE",
                decision_reasons=[],
                engine_context=EngineContext("test", "SHADOW", "run1"),
                source="cli",
            )

    def test_invalid_probability_range(self):
        """Probability outside 0-1 should be rejected."""
        with pytest.raises(ValueError, match="market_price_yes"):
            create_prediction_snapshot(
                market_id="test",
                question="Test?",
                decision="TRADE",
                decision_reasons=[],
                engine="test",
                mode="SHADOW",
                run_id="run1",
                source="cli",
                market_price_yes=1.5,  # Invalid: > 1
            )

    def test_invalid_probability_negative(self):
        """Negative probability should be rejected."""
        with pytest.raises(ValueError, match="market_price_yes"):
            create_prediction_snapshot(
                market_id="test",
                question="Test?",
                decision="TRADE",
                decision_reasons=[],
                engine="test",
                mode="SHADOW",
                run_id="run1",
                source="cli",
                market_price_yes=-0.1,  # Invalid: negative
            )

    def test_invalid_decision(self):
        """Invalid decision value should be rejected."""
        with pytest.raises(ValueError, match="decision"):
            create_prediction_snapshot(
                market_id="test",
                question="Test?",
                decision="MAYBE",  # Invalid
                decision_reasons=[],
                engine="test",
                mode="SHADOW",
                run_id="run1",
                source="cli",
            )

    def test_invalid_confidence(self):
        """Invalid confidence level should be rejected."""
        with pytest.raises(ValueError, match="estimate_confidence"):
            create_prediction_snapshot(
                market_id="test",
                question="Test?",
                decision="TRADE",
                decision_reasons=[],
                engine="test",
                mode="SHADOW",
                run_id="run1",
                source="cli",
                estimate_confidence="VERY_HIGH",  # Invalid
            )

    def test_empty_market_id(self):
        """Empty market_id should be rejected."""
        with pytest.raises(ValueError, match="market_id"):
            create_prediction_snapshot(
                market_id="",  # Empty
                question="Test?",
                decision="TRADE",
                decision_reasons=[],
                engine="test",
                mode="SHADOW",
                run_id="run1",
                source="cli",
            )


class TestResolutionValidation:
    """Test ResolutionRecord validation."""

    def test_valid_resolution_passes(self, valid_resolution):
        """Valid resolution should not raise errors."""
        errors = valid_resolution.validate()
        assert len(errors) == 0

    def test_invalid_resolution_value(self):
        """Invalid resolution value should be rejected."""
        with pytest.raises(ValueError, match="resolution"):
            create_resolution_record(
                market_id="test",
                resolution="MAYBE",  # Invalid
                resolution_source="api",
            )

    def test_all_valid_resolutions(self):
        """All valid resolution values should be accepted."""
        for res in VALID_RESOLUTIONS:
            record = create_resolution_record(
                market_id="test",
                resolution=res,
                resolution_source="api",
            )
            assert record.resolution == res


# =============================================================================
# TEST: APPEND-ONLY WRITER
# =============================================================================


class TestAppendOnlyWriter:
    """Test append-only writing behavior."""

    def test_writes_exactly_one_line(self, storage, valid_prediction):
        """Writing a prediction should add exactly one line."""
        storage.write_prediction(valid_prediction)

        with open(storage.predictions_file, "r") as f:
            lines = f.readlines()

        assert len(lines) == 1

    def test_line_is_valid_json(self, storage, valid_prediction):
        """Written line should be valid JSON."""
        storage.write_prediction(valid_prediction)

        with open(storage.predictions_file, "r") as f:
            line = f.readline()

        data = json.loads(line)
        assert data["market_id"] == valid_prediction.market_id

    def test_line_ends_with_newline(self, storage, valid_prediction):
        """Written line should end with newline."""
        storage.write_prediction(valid_prediction)

        with open(storage.predictions_file, "rb") as f:
            content = f.read()

        assert content.endswith(b"\n")

    def test_multiple_writes_append(self, storage):
        """Multiple writes should append, not overwrite."""
        pred1 = create_prediction_snapshot(
            market_id="market1",
            question="Question 1?",
            decision="TRADE",
            decision_reasons=[],
            engine="test",
            mode="SHADOW",
            run_id="run1",
            source="cli",
        )
        pred2 = create_prediction_snapshot(
            market_id="market2",
            question="Question 2?",
            decision="NO_TRADE",
            decision_reasons=["Reason"],
            engine="test",
            mode="SHADOW",
            run_id="run2",
            source="cli",
        )

        storage.write_prediction(pred1)
        storage.write_prediction(pred2)

        with open(storage.predictions_file, "r") as f:
            lines = f.readlines()

        assert len(lines) == 2

    def test_record_hash_is_set(self, storage, valid_prediction):
        """Written record should have record_hash set."""
        storage.write_prediction(valid_prediction)

        with open(storage.predictions_file, "r") as f:
            data = json.loads(f.readline())

        assert "record_hash" in data
        assert len(data["record_hash"]) == 64  # SHA256


# =============================================================================
# TEST: DEDUPLICATION
# =============================================================================


class TestDeduplication:
    """Test deduplication logic."""

    def test_duplicate_prediction_skipped(self, storage):
        """Identical prediction should be skipped."""
        # Create two predictions with same dedup key
        pred1 = create_prediction_snapshot(
            market_id="same_market",
            question="Same question?",
            decision="TRADE",
            decision_reasons=[],
            engine="baseline",
            mode="SHADOW",
            run_id="run1",
            source="cli",
        )

        # Force same timestamp for dedup
        pred2 = create_prediction_snapshot(
            market_id="same_market",
            question="Same question?",
            decision="TRADE",
            decision_reasons=[],
            engine="baseline",
            mode="SHADOW",
            run_id="run2",
            source="cli",
        )
        # Override timestamp to be in same minute bucket
        pred2.timestamp_utc = pred1.timestamp_utc

        success1, _ = storage.write_prediction(pred1)
        success2, _ = storage.write_prediction(pred2)

        assert success1 is True
        assert success2 is False  # Should be skipped as duplicate

    def test_different_market_not_duplicate(self, storage):
        """Different market_id should not be deduplicated."""
        pred1 = create_prediction_snapshot(
            market_id="market_1",
            question="Question?",
            decision="TRADE",
            decision_reasons=[],
            engine="baseline",
            mode="SHADOW",
            run_id="run1",
            source="cli",
        )
        pred2 = create_prediction_snapshot(
            market_id="market_2",
            question="Question?",
            decision="TRADE",
            decision_reasons=[],
            engine="baseline",
            mode="SHADOW",
            run_id="run1",
            source="cli",
        )

        success1, _ = storage.write_prediction(pred1)
        success2, _ = storage.write_prediction(pred2)

        assert success1 is True
        assert success2 is True

    def test_duplicate_resolution_skipped(self, storage):
        """Duplicate resolution for same market should be skipped."""
        res1 = create_resolution_record(
            market_id="market_1",
            resolution="YES",
            resolution_source="api",
        )
        res2 = create_resolution_record(
            market_id="market_1",  # Same market
            resolution="NO",  # Different resolution
            resolution_source="api",
        )

        success1, _ = storage.write_resolution(res1)
        success2, _ = storage.write_resolution(res2)

        assert success1 is True
        assert success2 is False  # Should be skipped


# =============================================================================
# TEST: UTILITY FUNCTIONS
# =============================================================================


class TestUtilityFunctions:
    """Test utility functions."""

    def test_generate_event_id_unique(self):
        """Event IDs should be unique."""
        ids = [generate_event_id() for _ in range(100)]
        assert len(ids) == len(set(ids))

    def test_generate_event_id_is_uuid(self):
        """Event ID should be valid UUID format."""
        event_id = generate_event_id()
        # UUID4 format: xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx
        assert len(event_id) == 36
        assert event_id.count("-") == 4

    def test_get_utc_timestamp_format(self):
        """Timestamp should be ISO format."""
        ts = get_utc_timestamp()
        # Should be parseable as ISO format
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        assert dt is not None

    def test_get_minute_bucket(self):
        """Minute bucket should truncate to minute."""
        ts = "2026-01-15T12:34:56.789Z"
        bucket = get_minute_bucket(ts)
        assert bucket == "2026-01-15T12:34"

    def test_get_minute_bucket_preserves_hour(self):
        """Minute bucket should preserve hour."""
        ts = "2026-01-15T23:59:59Z"
        bucket = get_minute_bucket(ts)
        assert bucket == "2026-01-15T23:59"


# =============================================================================
# TEST: STORAGE READ/WRITE
# =============================================================================


class TestStorageReadWrite:
    """Test storage read/write operations."""

    def test_read_empty_predictions(self, storage):
        """Reading non-existent file should return empty list."""
        predictions = storage.read_predictions()
        assert predictions == []

    def test_read_written_predictions(self, storage, valid_prediction):
        """Written predictions should be readable."""
        storage.write_prediction(valid_prediction)
        predictions = storage.read_predictions()

        assert len(predictions) == 1
        assert predictions[0].market_id == valid_prediction.market_id

    def test_read_written_resolutions(self, storage, valid_resolution):
        """Written resolutions should be readable."""
        storage.write_resolution(valid_resolution)
        resolutions = storage.read_resolutions()

        assert len(resolutions) == 1
        assert resolutions[0].market_id == valid_resolution.market_id

    def test_get_unresolved_market_ids(self, storage, valid_prediction, valid_resolution):
        """Should return markets with predictions but no resolution."""
        # Write prediction for market1
        storage.write_prediction(valid_prediction)

        # Write prediction for market2
        pred2 = create_prediction_snapshot(
            market_id="market_2",
            question="Another question?",
            decision="TRADE",
            decision_reasons=[],
            engine="test",
            mode="SHADOW",
            run_id="run1",
            source="cli",
        )
        storage.write_prediction(pred2)

        # Write resolution only for market1
        res1 = create_resolution_record(
            market_id=valid_prediction.market_id,
            resolution="YES",
            resolution_source="api",
        )
        storage.write_resolution(res1)

        # market_2 should be unresolved
        unresolved = storage.get_unresolved_market_ids()
        assert "market_2" in unresolved
        assert valid_prediction.market_id not in unresolved


# =============================================================================
# TEST: STATS
# =============================================================================


class TestStats:
    """Test statistics gathering."""

    def test_stats_empty(self, storage):
        """Stats on empty storage should return zeros."""
        stats = storage.get_stats()
        assert stats["total_predictions"] == 0
        assert stats["total_resolutions"] == 0
        assert stats["unique_markets_predicted"] == 0

    def test_stats_with_data(self, storage, valid_prediction, valid_resolution):
        """Stats should count records correctly."""
        storage.write_prediction(valid_prediction)
        storage.write_resolution(valid_resolution)

        stats = storage.get_stats()
        assert stats["total_predictions"] == 1
        assert stats["total_resolutions"] == 1
        assert stats["unique_markets_predicted"] == 1
        assert stats["resolved_markets"] == 1
        assert stats["coverage_pct"] == 100.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
