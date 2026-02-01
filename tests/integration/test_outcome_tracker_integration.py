#!/usr/bin/env python3
# =============================================================================
# OUTCOME TRACKER - INTEGRATION TESTS
# =============================================================================
#
# Tests for:
# - rebuild-index from sample jsonl
# - resolution update appends only once per market
# - corrections apply in index build
#
# =============================================================================

import json
import pytest
import tempfile
import shutil
from pathlib import Path
from datetime import datetime

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.outcome_tracker import (
    OutcomeStorage,
    IndexBuilder,
    CorrectionRecord,
    create_prediction_snapshot,
    create_resolution_record,
    generate_event_id,
    get_utc_timestamp,
    SCHEMA_VERSION,
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
def populated_storage(storage):
    """Create storage with sample data."""
    # Add several predictions
    markets = [
        ("market_1", "Will event A happen?", "TRADE"),
        ("market_2", "Will event B happen?", "NO_TRADE"),
        ("market_3", "Will event C happen?", "TRADE"),
        ("market_4", "Will event D happen?", "INSUFFICIENT_DATA"),
        ("market_5", "Will event E happen?", "TRADE"),
    ]

    for market_id, question, decision in markets:
        pred = create_prediction_snapshot(
            market_id=market_id,
            question=question,
            decision=decision,
            decision_reasons=[f"Test reason for {market_id}"],
            engine="baseline",
            mode="SHADOW",
            run_id="test_run",
            source="cli",
            market_price_yes=0.5,
        )
        storage.write_prediction(pred)

    # Add resolutions for some markets
    res1 = create_resolution_record("market_1", "YES", "test_api")
    res2 = create_resolution_record("market_2", "NO", "test_api")
    storage.write_resolution(res1)
    storage.write_resolution(res2)

    return storage


# =============================================================================
# TEST: INDEX REBUILD
# =============================================================================


class TestIndexRebuild:
    """Test index rebuilding from JSONL files."""

    def test_rebuild_creates_index_file(self, populated_storage):
        """Rebuilding should create index.json file."""
        builder = IndexBuilder(populated_storage)
        builder.rebuild()

        assert populated_storage.index_file.exists()

    def test_rebuild_contains_all_markets(self, populated_storage):
        """Index should contain all markets."""
        builder = IndexBuilder(populated_storage)
        index = builder.rebuild()

        market_ids = {e["market_id"] for e in index["entries"]}
        assert market_ids == {"market_1", "market_2", "market_3", "market_4", "market_5"}

    def test_rebuild_marks_resolved_correctly(self, populated_storage):
        """Index should mark resolved markets correctly."""
        builder = IndexBuilder(populated_storage)
        index = builder.rebuild()

        entries_by_id = {e["market_id"]: e for e in index["entries"]}

        assert entries_by_id["market_1"]["has_resolution"] is True
        assert entries_by_id["market_2"]["has_resolution"] is True
        assert entries_by_id["market_3"]["has_resolution"] is False
        assert entries_by_id["market_4"]["has_resolution"] is False
        assert entries_by_id["market_5"]["has_resolution"] is False

    def test_rebuild_includes_stats(self, populated_storage):
        """Index should include statistics."""
        builder = IndexBuilder(populated_storage)
        index = builder.rebuild()

        assert "stats" in index
        assert index["stats"]["total_predictions"] == 5
        assert index["stats"]["total_resolutions"] == 2

    def test_rebuild_includes_timestamp(self, populated_storage):
        """Index should include build timestamp."""
        builder = IndexBuilder(populated_storage)
        index = builder.rebuild()

        assert "built_at" in index
        assert "schema_version" in index

    def test_rebuild_is_deterministic(self, populated_storage):
        """Multiple rebuilds should produce same content (except timestamp)."""
        builder = IndexBuilder(populated_storage)

        index1 = builder.rebuild()
        index2 = builder.rebuild()

        # Compare entries (excluding timestamps)
        assert len(index1["entries"]) == len(index2["entries"])
        for e1, e2 in zip(index1["entries"], index2["entries"]):
            assert e1["market_id"] == e2["market_id"]
            assert e1["has_resolution"] == e2["has_resolution"]

    def test_rebuild_from_raw_jsonl(self, temp_dir):
        """Should be able to rebuild from raw JSONL files."""
        storage = OutcomeStorage(temp_dir)

        # Manually write raw JSONL
        predictions_data = [
            {
                "schema_version": 1,
                "event_id": "evt1",
                "timestamp_utc": "2026-01-15T12:00:00Z",
                "market_id": "raw_market_1",
                "question": "Raw question 1?",
                "outcomes": ["YES", "NO"],
                "market_price_yes": 0.5,
                "market_price_no": 0.5,
                "our_estimate_yes": None,
                "estimate_confidence": None,
                "decision": "TRADE",
                "decision_reasons": ["reason"],
                "engine_context": {"engine": "test", "mode": "SHADOW", "run_id": "r1"},
                "source": "cli",
                "record_hash": "abc123",
            },
            {
                "schema_version": 1,
                "event_id": "evt2",
                "timestamp_utc": "2026-01-15T12:01:00Z",
                "market_id": "raw_market_2",
                "question": "Raw question 2?",
                "outcomes": ["YES", "NO"],
                "market_price_yes": 0.7,
                "market_price_no": 0.3,
                "our_estimate_yes": None,
                "estimate_confidence": None,
                "decision": "NO_TRADE",
                "decision_reasons": ["blocked"],
                "engine_context": {"engine": "test", "mode": "SHADOW", "run_id": "r1"},
                "source": "cli",
                "record_hash": "def456",
            },
        ]

        with open(storage.predictions_file, "w") as f:
            for data in predictions_data:
                f.write(json.dumps(data) + "\n")

        # Rebuild
        builder = IndexBuilder(storage)
        index = builder.rebuild()

        assert len(index["entries"]) == 2


# =============================================================================
# TEST: RESOLUTION UPDATE
# =============================================================================


class TestResolutionUpdate:
    """Test resolution update behavior."""

    def test_resolution_appends_only_once(self, storage):
        """Resolution for same market should only be recorded once."""
        pred = create_prediction_snapshot(
            market_id="test_market",
            question="Test?",
            decision="TRADE",
            decision_reasons=[],
            engine="test",
            mode="SHADOW",
            run_id="run1",
            source="cli",
        )
        storage.write_prediction(pred)

        # First resolution
        res1 = create_resolution_record("test_market", "YES", "api")
        success1, _ = storage.write_resolution(res1)

        # Second resolution (should fail)
        res2 = create_resolution_record("test_market", "NO", "api")
        success2, msg = storage.write_resolution(res2)

        assert success1 is True
        assert success2 is False
        assert "already exists" in msg.lower()

        # Should only have one resolution
        resolutions = storage.read_resolutions()
        assert len(resolutions) == 1
        assert resolutions[0].resolution == "YES"

    def test_resolution_for_different_markets(self, storage):
        """Resolutions for different markets should both be recorded."""
        for i in range(3):
            pred = create_prediction_snapshot(
                market_id=f"market_{i}",
                question=f"Question {i}?",
                decision="TRADE",
                decision_reasons=[],
                engine="test",
                mode="SHADOW",
                run_id="run1",
                source="cli",
            )
            storage.write_prediction(pred)

        # Add resolutions for all
        for i in range(3):
            res = create_resolution_record(f"market_{i}", "YES", "api")
            success, _ = storage.write_resolution(res)
            assert success is True

        resolutions = storage.read_resolutions()
        assert len(resolutions) == 3


# =============================================================================
# TEST: CORRECTIONS
# =============================================================================


class TestCorrections:
    """Test correction application in index build."""

    def test_correction_applies_in_index(self, storage):
        """Corrections should be applied when rebuilding index."""
        # Add prediction
        pred = create_prediction_snapshot(
            market_id="market_to_correct",
            question="Original question?",
            decision="TRADE",
            decision_reasons=["Original reason"],
            engine="test",
            mode="SHADOW",
            run_id="run1",
            source="cli",
        )
        storage.write_prediction(pred)

        # Get the event_id
        predictions = storage.read_predictions()
        target_event_id = predictions[0].event_id

        # Add correction
        correction = CorrectionRecord(
            schema_version=SCHEMA_VERSION,
            event_id=generate_event_id(),
            timestamp_utc=get_utc_timestamp(),
            target_event_id=target_event_id,
            reason="Test correction",
            patch={"decision": "NO_TRADE", "decision_reasons": ["Corrected reason"]},
        )
        storage.write_correction(correction)

        # Rebuild index
        builder = IndexBuilder(storage)
        index = builder.rebuild()

        # Check correction was applied
        entry = index["entries"][0]
        pred_data = entry["predictions"][0]

        assert pred_data["decision"] == "NO_TRADE"
        assert "Corrected reason" in pred_data["decision_reasons"]

    def test_correction_does_not_modify_original(self, storage):
        """Corrections should not modify original JSONL file."""
        # Add prediction
        pred = create_prediction_snapshot(
            market_id="market_no_modify",
            question="Original?",
            decision="TRADE",
            decision_reasons=["Original"],
            engine="test",
            mode="SHADOW",
            run_id="run1",
            source="cli",
        )
        storage.write_prediction(pred)

        # Get the event_id
        predictions = storage.read_predictions()
        target_event_id = predictions[0].event_id

        # Add correction
        correction = CorrectionRecord(
            schema_version=SCHEMA_VERSION,
            event_id=generate_event_id(),
            timestamp_utc=get_utc_timestamp(),
            target_event_id=target_event_id,
            reason="Test correction",
            patch={"decision": "NO_TRADE"},
        )
        storage.write_correction(correction)

        # Rebuild index (applies correction)
        builder = IndexBuilder(storage)
        builder.rebuild()

        # Original file should still have TRADE
        with open(storage.predictions_file, "r") as f:
            original_data = json.loads(f.readline())

        assert original_data["decision"] == "TRADE"

    def test_multiple_corrections_apply_in_order(self, storage):
        """Multiple corrections should apply in chronological order."""
        # Add prediction
        pred = create_prediction_snapshot(
            market_id="market_multi_correct",
            question="Original?",
            decision="TRADE",
            decision_reasons=["Original"],
            engine="test",
            mode="SHADOW",
            run_id="run1",
            source="cli",
        )
        storage.write_prediction(pred)

        predictions = storage.read_predictions()
        target_event_id = predictions[0].event_id

        # Add first correction
        corr1 = CorrectionRecord(
            schema_version=SCHEMA_VERSION,
            event_id=generate_event_id(),
            timestamp_utc="2026-01-15T12:00:00Z",
            target_event_id=target_event_id,
            reason="First correction",
            patch={"decision": "NO_TRADE"},
        )
        storage.write_correction(corr1)

        # Add second correction (later timestamp, overrides first)
        corr2 = CorrectionRecord(
            schema_version=SCHEMA_VERSION,
            event_id=generate_event_id(),
            timestamp_utc="2026-01-15T13:00:00Z",
            target_event_id=target_event_id,
            reason="Second correction",
            patch={"decision": "INSUFFICIENT_DATA"},
        )
        storage.write_correction(corr2)

        # Rebuild index
        builder = IndexBuilder(storage)
        index = builder.rebuild()

        # Last correction should win
        entry = index["entries"][0]
        pred_data = entry["predictions"][0]

        assert pred_data["decision"] == "INSUFFICIENT_DATA"


# =============================================================================
# TEST: FULL WORKFLOW
# =============================================================================


class TestFullWorkflow:
    """Test complete workflow scenarios."""

    def test_prediction_resolution_workflow(self, storage):
        """Test full prediction -> resolution workflow."""
        # 1. Record prediction
        pred = create_prediction_snapshot(
            market_id="workflow_market",
            question="Will this test pass?",
            decision="TRADE",
            decision_reasons=["High confidence"],
            engine="baseline",
            mode="SHADOW",
            run_id="workflow_run",
            source="scheduler",
            market_price_yes=0.60,
            our_estimate_yes=0.75,
            estimate_confidence="HIGH",
        )
        success, _ = storage.write_prediction(pred)
        assert success

        # 2. Check it's unresolved
        unresolved = storage.get_unresolved_market_ids()
        assert "workflow_market" in unresolved

        # 3. Record resolution
        res = create_resolution_record(
            market_id="workflow_market",
            resolution="YES",
            resolution_source="gamma-api.polymarket.com",
            resolved_timestamp_utc="2026-01-20T00:00:00Z",
        )
        success, _ = storage.write_resolution(res)
        assert success

        # 4. Check it's now resolved
        unresolved = storage.get_unresolved_market_ids()
        assert "workflow_market" not in unresolved

        # 5. Rebuild index
        builder = IndexBuilder(storage)
        index = builder.rebuild()

        # 6. Verify index content
        entry = index["entries"][0]
        assert entry["market_id"] == "workflow_market"
        assert entry["has_resolution"] is True
        assert entry["resolution"]["resolution"] == "YES"
        assert len(entry["predictions"]) == 1
        assert entry["predictions"][0]["decision"] == "TRADE"

    def test_stats_update_through_workflow(self, storage):
        """Stats should update as records are added."""
        # Initial stats
        stats = storage.get_stats()
        assert stats["total_predictions"] == 0
        assert stats["total_resolutions"] == 0
        assert stats["coverage_pct"] == 0.0

        # Add predictions
        for i in range(5):
            pred = create_prediction_snapshot(
                market_id=f"stats_market_{i}",
                question=f"Question {i}?",
                decision="TRADE",
                decision_reasons=[],
                engine="test",
                mode="SHADOW",
                run_id="run1",
                source="cli",
            )
            storage.write_prediction(pred)

        stats = storage.get_stats()
        assert stats["total_predictions"] == 5
        assert stats["unique_markets_predicted"] == 5
        assert stats["unresolved_markets"] == 5
        assert stats["coverage_pct"] == 0.0

        # Add resolutions for 3 markets
        for i in range(3):
            res = create_resolution_record(
                f"stats_market_{i}",
                "YES",
                "api",
            )
            storage.write_resolution(res)

        stats = storage.get_stats()
        assert stats["total_resolutions"] == 3
        assert stats["resolved_markets"] == 3
        assert stats["unresolved_markets"] == 2
        assert stats["coverage_pct"] == 60.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
