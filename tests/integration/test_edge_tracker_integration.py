# =============================================================================
# INTEGRATION TESTS - EDGE EVOLUTION TRACKER
# =============================================================================
#
# Tests for:
# - Append-only storage behavior
# - Deduplication
# - Missing data handling
# - Safety (no forbidden imports)
#
# =============================================================================

import json
import os
import pytest
import sys
import tempfile
from pathlib import Path
from datetime import datetime, timezone

# Setup paths
BASE_DIR = Path(__file__).parent.parent.parent
sys.path.insert(0, str(BASE_DIR))


# =============================================================================
# SAFETY TESTS - IMPORT ISOLATION
# =============================================================================


class TestImportSafety:
    """
    Tests to verify that edge_evolution_tracker does not import
    forbidden modules (decision_engine, execution_engine, etc.)
    """

    def test_no_forbidden_imports_static_analysis(self):
        """Verify via static analysis that no forbidden modules are imported."""
        from core.edge_evolution_tracker import check_import_safety

        # This will raise ImportError if forbidden imports are detected
        result = check_import_safety()
        assert result is True

    def test_no_forbidden_imports_in_edge_snapshot(self):
        """Verify that edge_snapshot also has no forbidden imports."""
        import ast
        from pathlib import Path

        source_file = BASE_DIR / "core" / "edge_snapshot.py"
        source_code = source_file.read_text(encoding="utf-8")
        tree = ast.parse(source_code)

        forbidden = {
            "core.decision_engine",
            "core.execution_engine",
            "core.panic_contrarian_engine",
            "execution.adapter",
        }

        imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.add(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imports.add(node.module)

        for imp in imports:
            for forb in forbidden:
                assert not (imp == forb or imp.startswith(forb + ".")), (
                    f"SAFETY VIOLATION: edge_snapshot.py imports {imp}"
                )

    def test_module_can_be_removed(self):
        """
        Verify that edge_evolution_tracker can be removed without
        affecting other core modules.

        This tests the governance requirement that the tracker
        must be removable without affecting trading behavior.
        """
        # The key test is that decision_engine does NOT import edge modules
        # We verify this by checking decision_engine's imports statically
        import ast
        from pathlib import Path

        decision_engine_file = BASE_DIR / "core" / "decision_engine.py"
        if not decision_engine_file.exists():
            pytest.skip("decision_engine.py not found")

        source_code = decision_engine_file.read_text(encoding="utf-8")
        tree = ast.parse(source_code)

        edge_modules = {"core.edge_snapshot", "core.edge_evolution_tracker"}

        imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.add(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imports.add(node.module)

        for imp in imports:
            for edge_mod in edge_modules:
                assert not (imp == edge_mod or imp.startswith(edge_mod + ".")), (
                    f"DEPENDENCY VIOLATION: decision_engine.py imports {imp}. "
                    f"Edge tracker must be removable without affecting trading."
                )


# =============================================================================
# STORAGE TESTS
# =============================================================================


class TestEdgeEvolutionStorage:
    """Tests for EdgeEvolutionStorage class."""

    @pytest.fixture
    def temp_storage(self):
        """Create a temporary storage directory."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            # Create the data directory structure
            edge_dir = temp_path / "data" / "edge_evolution"
            edge_dir.mkdir(parents=True, exist_ok=True)

            from core.edge_evolution_tracker import EdgeEvolutionStorage
            storage = EdgeEvolutionStorage(temp_path)
            yield storage

    def test_append_only_storage(self, temp_storage):
        """Test that storage is append-only."""
        from core.edge_snapshot import create_edge_snapshot

        # Write first snapshot
        snapshot1 = create_edge_snapshot(
            position_id="pos-1",
            market_id="mkt-1",
            time_since_entry_minutes=60,
            market_probability_current=0.65,
            fair_probability_entry=0.80,
            market_probability_entry=0.65,
            source="cli",
        )
        success1, _ = temp_storage.write_snapshot(snapshot1)
        assert success1

        # Read and check count
        snapshots = temp_storage.read_snapshots()
        assert len(snapshots) == 1

        # Write second snapshot (different minute bucket)
        import time
        time.sleep(0.1)  # Small delay

        # Use a different timestamp to avoid dedup
        snapshot2 = create_edge_snapshot(
            position_id="pos-2",  # Different position
            market_id="mkt-1",
            time_since_entry_minutes=120,
            market_probability_current=0.70,
            fair_probability_entry=0.80,
            market_probability_entry=0.65,
            source="cli",
        )
        success2, _ = temp_storage.write_snapshot(snapshot2)
        assert success2

        # Read and check count - should be 2 (append, not overwrite)
        snapshots = temp_storage.read_snapshots()
        assert len(snapshots) == 2

    def test_deduplication_same_position_same_minute(self, temp_storage):
        """Test that duplicate snapshots for same position/minute are skipped."""
        from core.edge_snapshot import EdgeSnapshot, SCHEMA_VERSION

        # Create snapshot with fixed timestamp
        fixed_timestamp = "2026-01-24T15:30:00+00:00"

        snapshot1 = EdgeSnapshot(
            schema_version=SCHEMA_VERSION,
            snapshot_id="id-1",
            position_id="pos-1",
            market_id="mkt-1",
            timestamp_utc=fixed_timestamp,
            time_since_entry_minutes=60,
            market_probability_current=0.65,
            fair_probability_entry=0.80,
            edge_relative=0.23,
            edge_delta_since_entry=0.0,
            source="cli",
            record_hash="hash1",
        )

        # Write first
        success1, msg1 = temp_storage.write_snapshot(snapshot1)
        assert success1

        # Create second snapshot with same position_id and minute
        snapshot2 = EdgeSnapshot(
            schema_version=SCHEMA_VERSION,
            snapshot_id="id-2",  # Different ID
            position_id="pos-1",  # Same position
            market_id="mkt-1",
            timestamp_utc=fixed_timestamp,  # Same minute
            time_since_entry_minutes=61,  # Different time
            market_probability_current=0.66,  # Different value
            fair_probability_entry=0.80,
            edge_relative=0.21,
            edge_delta_since_entry=-0.02,
            source="cli",
            record_hash="hash2",
        )

        # Second write should be skipped (duplicate)
        success2, msg2 = temp_storage.write_snapshot(snapshot2)
        assert not success2
        assert "Duplicate" in msg2

        # Only one snapshot should exist
        snapshots = temp_storage.read_snapshots()
        assert len(snapshots) == 1

    def test_different_positions_same_minute_allowed(self, temp_storage):
        """Test that different positions can have snapshots in same minute."""
        from core.edge_snapshot import EdgeSnapshot, SCHEMA_VERSION

        fixed_timestamp = "2026-01-24T15:30:00+00:00"

        snapshot1 = EdgeSnapshot(
            schema_version=SCHEMA_VERSION,
            snapshot_id="id-1",
            position_id="pos-1",
            market_id="mkt-1",
            timestamp_utc=fixed_timestamp,
            time_since_entry_minutes=60,
            market_probability_current=0.65,
            fair_probability_entry=0.80,
            edge_relative=0.23,
            edge_delta_since_entry=0.0,
            source="cli",
            record_hash="hash1",
        )

        snapshot2 = EdgeSnapshot(
            schema_version=SCHEMA_VERSION,
            snapshot_id="id-2",
            position_id="pos-2",  # Different position
            market_id="mkt-1",
            timestamp_utc=fixed_timestamp,  # Same minute
            time_since_entry_minutes=60,
            market_probability_current=0.65,
            fair_probability_entry=0.80,
            edge_relative=0.23,
            edge_delta_since_entry=0.0,
            source="cli",
            record_hash="hash2",
        )

        success1, _ = temp_storage.write_snapshot(snapshot1)
        success2, _ = temp_storage.write_snapshot(snapshot2)

        assert success1
        assert success2

        snapshots = temp_storage.read_snapshots()
        assert len(snapshots) == 2

    def test_get_snapshots_by_position(self, temp_storage):
        """Test filtering snapshots by position."""
        from core.edge_snapshot import EdgeSnapshot, SCHEMA_VERSION

        # Write snapshots for different positions
        for i, pos_id in enumerate(["pos-1", "pos-1", "pos-2"]):
            snapshot = EdgeSnapshot(
                schema_version=SCHEMA_VERSION,
                snapshot_id=f"id-{i}",
                position_id=pos_id,
                market_id="mkt-1",
                timestamp_utc=f"2026-01-24T15:{30+i}:00+00:00",
                time_since_entry_minutes=60 + i * 15,
                market_probability_current=0.65,
                fair_probability_entry=0.80,
                edge_relative=0.23,
                edge_delta_since_entry=0.0,
                source="cli",
                record_hash=f"hash{i}",
            )
            temp_storage.write_snapshot(snapshot)

        # Get snapshots for pos-1
        pos1_snapshots = temp_storage.get_snapshots_by_position("pos-1")
        assert len(pos1_snapshots) == 2

        # Get snapshots for pos-2
        pos2_snapshots = temp_storage.get_snapshots_by_position("pos-2")
        assert len(pos2_snapshots) == 1


# =============================================================================
# MISSING DATA TESTS
# =============================================================================


class TestMissingDataHandling:
    """Tests for fail-closed behavior with missing data."""

    def test_tracker_handles_empty_storage(self):
        """Test that tracker storage handles empty files gracefully."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            # Create directory structure
            (temp_path / "data" / "edge_evolution").mkdir(parents=True)

            from core.edge_evolution_tracker import EdgeEvolutionStorage
            storage = EdgeEvolutionStorage(temp_path)

            # Reading empty storage should return empty list
            snapshots = storage.read_snapshots()
            assert snapshots == []

            # Stats should show zeros
            stats = storage.get_stats()
            assert stats["total_snapshots"] == 0
            assert stats["unique_positions"] == 0

    def test_tracker_run_returns_summary(self):
        """Test that tracker.run() always returns a summary dict."""
        from core.edge_evolution_tracker import get_tracker

        tracker = get_tracker()
        result = tracker.run(source="cli")

        # Should always return a dict with these keys
        assert isinstance(result, dict)
        assert "success" in result
        assert "positions_checked" in result or "error" in result


# =============================================================================
# HASH INTEGRITY TESTS
# =============================================================================


class TestHashIntegrity:
    """Tests for hash verification."""

    @pytest.fixture
    def temp_storage(self):
        """Create a temporary storage directory."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            edge_dir = temp_path / "data" / "edge_evolution"
            edge_dir.mkdir(parents=True, exist_ok=True)

            from core.edge_evolution_tracker import EdgeEvolutionStorage
            storage = EdgeEvolutionStorage(temp_path)
            yield storage

    def test_hash_verified_on_read(self, temp_storage):
        """Test that hashes can be verified on read."""
        from core.edge_snapshot import (
            create_edge_snapshot,
            compute_hash,
        )

        # Write a snapshot
        snapshot = create_edge_snapshot(
            position_id="pos-1",
            market_id="mkt-1",
            time_since_entry_minutes=60,
            market_probability_current=0.65,
            fair_probability_entry=0.80,
            market_probability_entry=0.65,
            source="cli",
        )
        temp_storage.write_snapshot(snapshot)

        # Read back and verify hash
        snapshots = temp_storage.read_snapshots()
        assert len(snapshots) == 1

        read_snapshot = snapshots[0]
        expected_hash = compute_hash(read_snapshot.to_dict())
        assert read_snapshot.record_hash == expected_hash


# =============================================================================
# GOVERNANCE TESTS
# =============================================================================


class TestGovernanceCompliance:
    """Tests for governance compliance."""

    def test_snapshot_has_governance_notice(self):
        """Test that snapshots include governance notice."""
        from core.edge_snapshot import create_edge_snapshot

        snapshot = create_edge_snapshot(
            position_id="pos-1",
            market_id="mkt-1",
            time_since_entry_minutes=60,
            market_probability_current=0.65,
            fair_probability_entry=0.80,
            market_probability_entry=0.65,
            source="cli",
        )

        assert snapshot.governance_notice is not None
        assert "ANALYTICS" in snapshot.governance_notice
        assert "NOT" in snapshot.governance_notice

    def test_snapshot_governance_in_dict(self):
        """Test that governance notice is included in dict output."""
        from core.edge_snapshot import create_edge_snapshot

        snapshot = create_edge_snapshot(
            position_id="pos-1",
            market_id="mkt-1",
            time_since_entry_minutes=60,
            market_probability_current=0.65,
            fair_probability_entry=0.80,
            market_probability_entry=0.65,
            source="cli",
        )

        data = snapshot.to_dict()
        assert "governance_notice" in data
        assert "ANALYTICS" in data["governance_notice"]


# =============================================================================
# RUN TESTS
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
