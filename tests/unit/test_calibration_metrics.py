# =============================================================================
# UNIT TESTS — Calibration Metrics (Pure Math)
# =============================================================================

import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from core.calibration_metrics import (
    CalibrationPoint,
    MetricsBucket,
    brier_score,
    avg_probability,
    actual_frequency,
    calibration_gap,
    compute_bucket,
    is_valid_probability,
    is_valid_outcome,
    is_valid_point,
    classify_odds_bucket,
    group_by_model,
    group_by_confidence,
    group_by_odds_bucket,
)


# =============================================================================
# HELPERS
# =============================================================================

def _pt(prob, outcome, model="baseline", confidence="HIGH", market_id=None):
    """Shorthand to create a CalibrationPoint."""
    return CalibrationPoint(
        market_id=market_id or f"m_{prob}_{outcome}",
        probability_at_entry=prob,
        actual_outcome=outcome,
        model_type=model,
        confidence=confidence,
    )


# =============================================================================
# BRIER SCORE
# =============================================================================

class TestBrierScore:

    def test_perfect_prediction_yes(self):
        """Predicting 1.0 for outcome 1 → Brier = 0."""
        pts = [_pt(1.0, 1)]
        assert brier_score(pts) == pytest.approx(0.0)

    def test_perfect_prediction_no(self):
        """Predicting 0.0 for outcome 0 → Brier = 0."""
        pts = [_pt(0.0, 0)]
        assert brier_score(pts) == pytest.approx(0.0)

    def test_worst_prediction(self):
        """Predicting 1.0 for outcome 0 → Brier = 1."""
        pts = [_pt(1.0, 0)]
        assert brier_score(pts) == pytest.approx(1.0)

    def test_coin_flip(self):
        """Predicting 0.5 always → Brier = 0.25."""
        pts = [_pt(0.5, 1), _pt(0.5, 0)]
        assert brier_score(pts) == pytest.approx(0.25)

    def test_empty_returns_none(self):
        assert brier_score([]) is None

    def test_mixed_predictions(self):
        pts = [_pt(0.8, 1), _pt(0.3, 0)]
        # (0.8-1)^2 = 0.04, (0.3-0)^2 = 0.09 → mean = 0.065
        assert brier_score(pts) == pytest.approx(0.065)


# =============================================================================
# CALIBRATION GAP
# =============================================================================

class TestCalibrationGap:

    def test_perfectly_calibrated(self):
        """avg_prob == actual_freq → gap = 0."""
        pts = [_pt(0.6, 1), _pt(0.6, 1), _pt(0.6, 0), _pt(0.6, 0), _pt(0.6, 1)]
        # actual_freq = 3/5 = 0.6, avg_prob = 0.6
        assert calibration_gap(pts) == pytest.approx(0.0)

    def test_underconfident(self):
        """Events happen more than predicted → positive gap."""
        pts = [_pt(0.3, 1), _pt(0.3, 1)]
        # actual = 1.0, avg = 0.3 → gap = 0.7
        assert calibration_gap(pts) == pytest.approx(0.7)

    def test_overconfident(self):
        """Events happen less than predicted → negative gap."""
        pts = [_pt(0.9, 0), _pt(0.9, 0)]
        # actual = 0.0, avg = 0.9 → gap = -0.9
        assert calibration_gap(pts) == pytest.approx(-0.9)

    def test_empty_returns_none(self):
        assert calibration_gap([]) is None


# =============================================================================
# VALIDATION — EXCLUSION OF INVALID DATA
# =============================================================================

class TestValidation:

    def test_reject_probability_none(self):
        assert is_valid_probability(None) is False

    def test_reject_probability_negative(self):
        assert is_valid_probability(-0.1) is False

    def test_reject_probability_above_one(self):
        assert is_valid_probability(1.1) is False

    def test_accept_probability_zero(self):
        assert is_valid_probability(0.0) is True

    def test_accept_probability_one(self):
        assert is_valid_probability(1.0) is True

    def test_reject_outcome_two(self):
        assert is_valid_outcome(2) is False

    def test_reject_outcome_none(self):
        assert is_valid_outcome(None) is False

    def test_reject_point_no_market_id(self):
        pt = CalibrationPoint("", 0.5, 1, "x", "HIGH")
        assert is_valid_point(pt) is False

    def test_reject_point_bad_prob(self):
        pt = CalibrationPoint("m1", 1.5, 1, "x", "HIGH")
        assert is_valid_point(pt) is False

    def test_reject_point_bad_outcome(self):
        pt = CalibrationPoint("m1", 0.5, 2, "x", "HIGH")
        assert is_valid_point(pt) is False

    def test_invalid_points_excluded_from_brier(self):
        """Invalid points must not affect the metric."""
        good = _pt(0.5, 1, market_id="good")
        bad = CalibrationPoint("", 999.0, 5, "x", None)  # all invalid
        assert brier_score([good, bad]) == pytest.approx(0.25)


# =============================================================================
# GROUPING & BUCKETS
# =============================================================================

class TestGrouping:

    def test_group_by_model(self):
        pts = [_pt(0.5, 1, model="A"), _pt(0.6, 0, model="B"), _pt(0.7, 1, model="A")]
        groups = group_by_model(pts)
        assert len(groups["A"]) == 2
        assert len(groups["B"]) == 1

    def test_group_by_confidence(self):
        pts = [_pt(0.5, 1, confidence="HIGH"), _pt(0.6, 0, confidence="LOW")]
        groups = group_by_confidence(pts)
        assert "HIGH" in groups
        assert "LOW" in groups

    def test_classify_odds_bucket(self):
        assert classify_odds_bucket(0.05) == "0_10"
        assert classify_odds_bucket(0.55) == "50_70"
        assert classify_odds_bucket(0.95) == "90_100"
        assert classify_odds_bucket(1.0) == "90_100"
        assert classify_odds_bucket(-0.1) is None

    def test_compute_bucket_empty(self):
        bucket = compute_bucket([])
        assert bucket.sample_size == 0
        assert bucket.brier_score is None


# =============================================================================
# METRICS BUCKET SERIALIZATION
# =============================================================================

class TestMetricsBucket:

    def test_to_dict_roundtrip(self):
        pts = [_pt(0.7, 1), _pt(0.3, 0)]
        bucket = compute_bucket(pts)
        d = bucket.to_dict()
        assert d["sample_size"] == 2
        assert isinstance(d["brier_score"], float)
        assert isinstance(d["calibration_gap"], float)
