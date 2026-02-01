# =============================================================================
# INTEGRATION + SAFETY TESTS — Calibration Engine
# =============================================================================

import json
import pytest
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from core.calibration_engine import (
    CalibrationEngine,
    _build_resolution_map,
    _extract_points_from_predictions,
    REPORT_OUTPUT_PATH,
)
from core.calibration_metrics import CalibrationPoint


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def tmp_project(tmp_path):
    """Create a minimal project structure with test data."""
    outcomes = tmp_path / "data" / "outcomes"
    outcomes.mkdir(parents=True)
    calibration = tmp_path / "data" / "calibration"
    calibration.mkdir(parents=True)

    # Resolutions
    resolutions = [
        {"market_id": "m1", "resolution": "YES", "resolved": True},
        {"market_id": "m2", "resolution": "NO", "resolved": True},
        {"market_id": "m3", "resolution": "INVALID", "resolved": True},  # excluded
        {"market_id": "m4", "resolution": "YES", "resolved": False},  # not resolved
    ]
    with open(outcomes / "resolutions.jsonl", "w") as f:
        for r in resolutions:
            f.write(json.dumps(r) + "\n")

    # Predictions
    predictions = [
        {"market_id": "m1", "our_estimate_yes": 0.75, "timestamp_utc": "2026-01-15T12:00:00Z", "engine_context": {"engine": "baseline"}, "estimate_confidence": "HIGH"},
        {"market_id": "m2", "our_estimate_yes": 0.30, "timestamp_utc": "2026-01-15T12:00:00Z", "engine_context": {"engine": "baseline"}, "estimate_confidence": "MEDIUM"},
        {"market_id": "m3", "our_estimate_yes": 0.50, "timestamp_utc": "2026-01-15T12:00:00Z"},  # excluded (no definitive resolution)
        {"market_id": "m5", "our_estimate_yes": None},  # excluded (no estimate)
        {"market_id": "m6", "our_estimate_yes": 1.5},  # excluded (invalid prob)
    ]
    with open(outcomes / "predictions.jsonl", "w") as f:
        for p in predictions:
            f.write(json.dumps(p) + "\n")

    return tmp_path


# =============================================================================
# RESOLUTION MATCHING
# =============================================================================

class TestResolutionMatching:

    def test_only_definitive_resolutions(self, tmp_project):
        """Only YES/NO resolutions are included."""
        engine = CalibrationEngine(tmp_project)
        report = engine.run("all_time")
        # m1 (YES) and m2 (NO) should be matched; m3 (INVALID) and m4 (not resolved) excluded
        assert report["global"]["sample_size"] == 2

    def test_build_resolution_map(self):
        recs = [
            {"market_id": "a", "resolution": "YES", "resolved": True},
            {"market_id": "b", "resolution": "NO", "resolved": True},
            {"market_id": "c", "resolution": "CANCELLED", "resolved": True},
            {"market_id": "d", "resolution": "YES", "resolved": False},
        ]
        rmap = _build_resolution_map(recs)
        assert rmap == {"a": 1, "b": 0}


# =============================================================================
# STABLE REBUILDS
# =============================================================================

class TestStableRebuilds:

    def test_deterministic_output(self, tmp_project):
        """Running twice produces identical metrics (timestamps differ)."""
        engine = CalibrationEngine(tmp_project)
        r1 = engine.run("all_time")
        r2 = engine.run("all_time")
        assert r1["global"]["brier_score"] == r2["global"]["brier_score"]
        assert r1["global"]["sample_size"] == r2["global"]["sample_size"]
        assert r1["global"]["calibration_gap"] == r2["global"]["calibration_gap"]

    def test_run_and_save_creates_file(self, tmp_project):
        """run_and_save writes a valid JSON file."""
        engine = CalibrationEngine(tmp_project)
        report, path = engine.run_and_save("all_time")
        assert path.exists()
        with open(path) as f:
            loaded = json.load(f)
        assert loaded["global"]["sample_size"] == report["global"]["sample_size"]


# =============================================================================
# EXCLUSION RULES
# =============================================================================

class TestExclusion:

    def test_invalid_probability_excluded(self, tmp_project):
        """Predictions with prob > 1.0 or None are excluded."""
        engine = CalibrationEngine(tmp_project)
        report = engine.run("all_time")
        # Only m1 and m2 should survive
        assert report["global"]["sample_size"] == 2

    def test_empty_data(self, tmp_path):
        """No data files → empty report, no crash."""
        (tmp_path / "data" / "outcomes").mkdir(parents=True)
        (tmp_path / "data" / "calibration").mkdir(parents=True)
        engine = CalibrationEngine(tmp_path)
        report = engine.run("all_time")
        assert report["global"]["sample_size"] == 0
        assert report["global"]["brier_score"] is None


# =============================================================================
# SAFETY: NO TRADING IMPORTS
# =============================================================================

class TestSafety:

    def _check_no_trading_imports(self, filepath):
        """Check that a file has no actual import statements for trading modules."""
        code = filepath.read_text(encoding="utf-8")
        forbidden = [
            "decision_engine",
            "execution_engine",
            "panic_contrarian",
            "simulator",
            "kelly",
            "capital_manager",
            "slippage",
        ]
        for line in code.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                continue  # skip comments
            for module in forbidden:
                if f"import {module}" in stripped or f"from {module}" in stripped or f"from .{module}" in stripped:
                    pytest.fail(f"Forbidden import in {filepath.name}: {stripped}")

    def test_no_trading_imports_in_engine(self):
        """calibration_engine.py must not import trading modules."""
        src = Path(__file__).parent.parent.parent / "core" / "calibration_engine.py"
        self._check_no_trading_imports(src)

    def test_no_trading_imports_in_metrics(self):
        """calibration_metrics.py must not import trading modules."""
        src = Path(__file__).parent.parent.parent / "core" / "calibration_metrics.py"
        self._check_no_trading_imports(src)

    def test_report_contains_governance_notice(self, tmp_project):
        """Report must contain governance notice."""
        engine = CalibrationEngine(tmp_project)
        report = engine.run("all_time")
        assert "governance_notice" in report
        assert "ANALYTICS ONLY" in report["governance_notice"]
