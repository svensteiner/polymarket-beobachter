# =============================================================================
# INTEGRATION TESTS - EDGE DASHBOARD
# =============================================================================
#
# Tests for:
# - Summary rebuild from sample snapshots
# - Deterministic output
# - Safety (no forbidden imports)
#
# =============================================================================

import json
import os
import pytest
import sys
import tempfile
from pathlib import Path
from datetime import datetime, timezone, timedelta

# Setup paths
BASE_DIR = Path(__file__).parent.parent.parent
sys.path.insert(0, str(BASE_DIR))


# =============================================================================
# SAFETY TESTS
# =============================================================================


class TestImportSafety:
    """Tests for import isolation."""

    def test_metrics_no_forbidden_imports(self):
        """Verify metrics module has no forbidden imports."""
        from core.edge_exposure_metrics import check_import_safety
        result = check_import_safety()
        assert result is True

    def test_aggregator_no_forbidden_imports(self):
        """Verify aggregator module has no forbidden imports."""
        from core.edge_exposure_aggregator import check_import_safety
        result = check_import_safety()
        assert result is True

    def test_static_analysis_metrics(self):
        """Static analysis of edge_exposure_metrics.py imports."""
        import ast

        source_file = BASE_DIR / "core" / "edge_exposure_metrics.py"
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
                    f"SAFETY VIOLATION: edge_exposure_metrics.py imports {imp}"
                )

    def test_static_analysis_aggregator(self):
        """Static analysis of edge_exposure_aggregator.py imports."""
        import ast

        source_file = BASE_DIR / "core" / "edge_exposure_aggregator.py"
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
                    f"SAFETY VIOLATION: edge_exposure_aggregator.py imports {imp}"
                )


# =============================================================================
# AGGREGATION TESTS
# =============================================================================


class TestAggregation:
    """Tests for aggregation functionality."""

    @pytest.fixture
    def temp_storage(self):
        """Create temporary storage with sample snapshots."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            edge_dir = temp_path / "data" / "edge_evolution"
            edge_dir.mkdir(parents=True)

            # Create sample snapshots
            snapshots_file = edge_dir / "edge_snapshots.jsonl"
            snapshots = self._create_sample_snapshots()

            with open(snapshots_file, "w", encoding="utf-8") as f:
                for snap in snapshots:
                    f.write(json.dumps(snap) + "\n")

            yield temp_path

    def _create_sample_snapshots(self):
        """Create sample snapshot data."""
        base_time = datetime.now(timezone.utc) - timedelta(hours=3)
        snapshots = []

        # Position 1: Consistent positive edge
        for i in range(5):
            ts = base_time + timedelta(minutes=i * 30)
            snapshots.append({
                "schema_version": 1,
                "snapshot_id": f"snap-1-{i}",
                "position_id": "pos-1",
                "market_id": "mkt-1",
                "timestamp_utc": ts.isoformat(),
                "time_since_entry_minutes": i * 30,
                "market_probability_current": 0.60,
                "fair_probability_entry": 0.80,
                "edge_relative": 0.20,  # Constant 20% edge
                "edge_delta_since_entry": 0.0,
                "source": "test",
                "record_hash": f"hash-1-{i}",
            })

        # Position 2: Declining edge
        for i in range(5):
            ts = base_time + timedelta(minutes=i * 30)
            edge = 0.30 - (i * 0.10)  # 0.30, 0.20, 0.10, 0.00, -0.10
            snapshots.append({
                "schema_version": 1,
                "snapshot_id": f"snap-2-{i}",
                "position_id": "pos-2",
                "market_id": "mkt-2",
                "timestamp_utc": ts.isoformat(),
                "time_since_entry_minutes": i * 30,
                "market_probability_current": 0.60,
                "fair_probability_entry": 0.80,
                "edge_relative": edge,
                "edge_delta_since_entry": edge - 0.30,
                "source": "test",
                "record_hash": f"hash-2-{i}",
            })

        return snapshots

    def test_summary_counts(self, temp_storage):
        """Test that summary has correct counts."""
        from core.edge_exposure_aggregator import EdgeExposureAggregator
        from core.edge_exposure_metrics import TimeWindow

        aggregator = EdgeExposureAggregator(temp_storage)
        summary = aggregator.run(TimeWindow.ALL_TIME)

        assert summary.open_positions_count == 2
        assert summary.snapshot_count == 10

    def test_positive_and_negative_exposure(self, temp_storage):
        """Test that positive and negative exposure are separated."""
        from core.edge_exposure_aggregator import EdgeExposureAggregator
        from core.edge_exposure_metrics import TimeWindow

        aggregator = EdgeExposureAggregator(temp_storage)
        summary = aggregator.run(TimeWindow.ALL_TIME)

        # Should have both positive and negative exposure
        assert summary.positive_edge_exposure_hours > 0
        # Position 2 has some negative edge
        assert summary.negative_edge_exposure_hours < 0

    def test_exposure_ratio_calculated(self, temp_storage):
        """Test that exposure ratio is calculated."""
        from core.edge_exposure_aggregator import EdgeExposureAggregator
        from core.edge_exposure_metrics import TimeWindow

        aggregator = EdgeExposureAggregator(temp_storage)
        summary = aggregator.run(TimeWindow.ALL_TIME)

        assert summary.edge_exposure_ratio is not None
        assert 0.0 <= summary.edge_exposure_ratio <= 1.0

    def test_deterministic_output(self, temp_storage):
        """Test that running twice produces same output."""
        from core.edge_exposure_aggregator import EdgeExposureAggregator
        from core.edge_exposure_metrics import TimeWindow

        aggregator = EdgeExposureAggregator(temp_storage)

        summary1 = aggregator.run(TimeWindow.ALL_TIME)
        summary2 = aggregator.run(TimeWindow.ALL_TIME)

        # Core metrics should be identical
        assert summary1.open_positions_count == summary2.open_positions_count
        assert summary1.snapshot_count == summary2.snapshot_count
        assert summary1.total_edge_exposure_hours == summary2.total_edge_exposure_hours
        assert summary1.positive_edge_exposure_hours == summary2.positive_edge_exposure_hours
        assert summary1.negative_edge_exposure_hours == summary2.negative_edge_exposure_hours

    def test_save_and_load(self, temp_storage):
        """Test summary save and load."""
        from core.edge_exposure_aggregator import EdgeExposureAggregator
        from core.edge_exposure_metrics import TimeWindow

        aggregator = EdgeExposureAggregator(temp_storage)
        summary = aggregator.run(TimeWindow.ALL_TIME)

        # Save
        saved = aggregator.save_summary(summary)
        assert saved is True

        # Load
        loaded = aggregator.load_summary()
        assert loaded is not None
        assert loaded.open_positions_count == summary.open_positions_count
        assert loaded.snapshot_count == summary.snapshot_count


# =============================================================================
# TIME WINDOW FILTERING TESTS
# =============================================================================


class TestTimeWindowFiltering:
    """Tests for time window filtering."""

    @pytest.fixture
    def temp_storage_with_old_data(self):
        """Create storage with old and new snapshots."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            edge_dir = temp_path / "data" / "edge_evolution"
            edge_dir.mkdir(parents=True)

            snapshots = []

            # Old snapshots (10 days ago)
            old_time = datetime.now(timezone.utc) - timedelta(days=10)
            for i in range(3):
                ts = old_time + timedelta(minutes=i * 30)
                snapshots.append({
                    "schema_version": 1,
                    "snapshot_id": f"old-{i}",
                    "position_id": "pos-old",
                    "market_id": "mkt-old",
                    "timestamp_utc": ts.isoformat(),
                    "edge_relative": 0.10,
                })

            # Recent snapshots (1 hour ago)
            recent_time = datetime.now(timezone.utc) - timedelta(hours=1)
            for i in range(3):
                ts = recent_time + timedelta(minutes=i * 15)
                snapshots.append({
                    "schema_version": 1,
                    "snapshot_id": f"new-{i}",
                    "position_id": "pos-new",
                    "market_id": "mkt-new",
                    "timestamp_utc": ts.isoformat(),
                    "edge_relative": 0.20,
                })

            snapshots_file = edge_dir / "edge_snapshots.jsonl"
            with open(snapshots_file, "w", encoding="utf-8") as f:
                for snap in snapshots:
                    f.write(json.dumps(snap) + "\n")

            yield temp_path

    def test_all_time_includes_all(self, temp_storage_with_old_data):
        """Test that all_time includes all snapshots."""
        from core.edge_exposure_aggregator import EdgeExposureAggregator
        from core.edge_exposure_metrics import TimeWindow

        aggregator = EdgeExposureAggregator(temp_storage_with_old_data)
        summary = aggregator.run(TimeWindow.ALL_TIME)

        assert summary.snapshot_count == 6
        assert summary.open_positions_count == 2

    def test_last_24h_excludes_old(self, temp_storage_with_old_data):
        """Test that last_24h excludes old snapshots."""
        from core.edge_exposure_aggregator import EdgeExposureAggregator
        from core.edge_exposure_metrics import TimeWindow

        aggregator = EdgeExposureAggregator(temp_storage_with_old_data)
        summary = aggregator.run(TimeWindow.LAST_24H)

        # Only recent snapshots (3 of them)
        assert summary.snapshot_count == 3
        assert summary.open_positions_count == 1

    def test_last_7d_excludes_old(self, temp_storage_with_old_data):
        """Test that last_7d excludes very old snapshots."""
        from core.edge_exposure_aggregator import EdgeExposureAggregator
        from core.edge_exposure_metrics import TimeWindow

        aggregator = EdgeExposureAggregator(temp_storage_with_old_data)
        summary = aggregator.run(TimeWindow.LAST_7D)

        # Only recent snapshots (10 days ago is excluded)
        assert summary.snapshot_count == 3
        assert summary.open_positions_count == 1


# =============================================================================
# GOVERNANCE TESTS
# =============================================================================


class TestGovernanceCompliance:
    """Tests for governance compliance."""

    def test_summary_has_governance_notice(self):
        """Test that summary includes governance notice."""
        from core.edge_exposure_metrics import EdgeExposureSummary

        summary = EdgeExposureSummary(
            schema_version=1,
            generated_at_utc="2026-01-24T15:00:00+00:00",
            time_window="all_time",
            open_positions_count=0,
            snapshot_count=0,
            total_edge_exposure_hours=0.0,
            positive_edge_exposure_hours=0.0,
            negative_edge_exposure_hours=0.0,
            edge_exposure_ratio=None,
            median_edge_duration_minutes=None,
        )

        assert "ANALYTICS" in summary.governance_notice
        assert "NOT" in summary.governance_notice

    def test_summary_dict_has_governance_notice(self):
        """Test that summary dict includes governance notice."""
        from core.edge_exposure_metrics import EdgeExposureSummary

        summary = EdgeExposureSummary(
            schema_version=1,
            generated_at_utc="2026-01-24T15:00:00+00:00",
            time_window="all_time",
            open_positions_count=0,
            snapshot_count=0,
            total_edge_exposure_hours=0.0,
            positive_edge_exposure_hours=0.0,
            negative_edge_exposure_hours=0.0,
            edge_exposure_ratio=None,
            median_edge_duration_minutes=None,
        )

        data = summary.to_dict()
        assert "governance_notice" in data
        assert "ANALYTICS" in data["governance_notice"]

    def test_position_metrics_has_governance_notice(self):
        """Test that position metrics includes governance notice."""
        from core.edge_exposure_metrics import PositionEdgeMetrics

        metrics = PositionEdgeMetrics(
            position_id="pos-1",
            market_id="mkt-1",
            snapshot_count=5,
            first_snapshot_utc="2026-01-24T15:00:00+00:00",
            last_snapshot_utc="2026-01-24T16:00:00+00:00",
            total_duration_minutes=60,
            edge_area_minutes=10.0,
            positive_edge_area_minutes=10.0,
            negative_edge_area_minutes=0.0,
            positive_edge_duration_minutes=60,
            negative_edge_duration_minutes=0,
            min_edge_relative=0.10,
            max_edge_relative=0.20,
            avg_edge_relative=0.15,
        )

        assert "ANALYTICS" in metrics.governance_notice
        data = metrics.to_dict()
        assert "governance_notice" in data


# =============================================================================
# RUN TESTS
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
