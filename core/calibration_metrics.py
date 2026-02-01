# =============================================================================
# POLYMARKET BEOBACHTER - CALIBRATION METRICS
# =============================================================================
#
# Pure mathematical functions for calibration analysis.
# No I/O, no imports from trading/execution/decision modules.
#
# GOVERNANCE:
# - ANALYTICS ONLY — never influences trading or sizing
# - All functions are PURE — no side effects
# - If data is invalid → exclude, never guess
#
# =============================================================================

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any


# =============================================================================
# DATA POINT
# =============================================================================


@dataclass(frozen=True)
class CalibrationPoint:
    """
    A single resolved prediction for calibration.

    Immutable. Every field is explicit.

    Fields:
        market_id: The market this prediction was for.
        probability_at_entry: Our estimated probability at time of entry.
        actual_outcome: 1 if YES resolved, 0 if NO resolved.
        model_type: Which model produced the estimate (e.g. "baseline").
        confidence: Confidence level at entry ("LOW", "MEDIUM", "HIGH").
        entry_timestamp: ISO8601 string of when the prediction was made.
    """
    market_id: str
    probability_at_entry: float
    actual_outcome: int  # 0 or 1
    model_type: str
    confidence: Optional[str]  # "LOW", "MEDIUM", "HIGH", or None
    entry_timestamp: Optional[str] = None


# =============================================================================
# METRICS RESULT
# =============================================================================


@dataclass
class MetricsBucket:
    """
    Calibration metrics for a group of predictions.

    All fields are computed from CalibrationPoints.
    """
    brier_score: Optional[float] = None
    avg_probability: Optional[float] = None
    actual_frequency: Optional[float] = None
    calibration_gap: Optional[float] = None
    sample_size: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "brier_score": round(self.brier_score, 6) if self.brier_score is not None else None,
            "avg_probability": round(self.avg_probability, 6) if self.avg_probability is not None else None,
            "actual_frequency": round(self.actual_frequency, 6) if self.actual_frequency is not None else None,
            "calibration_gap": round(self.calibration_gap, 6) if self.calibration_gap is not None else None,
            "sample_size": self.sample_size,
        }


# =============================================================================
# VALIDATION
# =============================================================================


def is_valid_probability(p: Any) -> bool:
    """Check if a value is a valid probability in [0.0, 1.0]."""
    if p is None:
        return False
    try:
        f = float(p)
    except (TypeError, ValueError):
        return False
    return 0.0 <= f <= 1.0


def is_valid_outcome(o: Any) -> bool:
    """Check if a value is a valid binary outcome (0 or 1)."""
    return o in (0, 1)


def is_valid_point(point: CalibrationPoint) -> bool:
    """
    Validate a calibration point.

    Excludes:
    - Invalid probabilities (None, out of range)
    - Placeholder probabilities (exactly 0.5 with no model — ambiguous)
    - Invalid outcomes (not 0 or 1)
    """
    if not is_valid_probability(point.probability_at_entry):
        return False
    if not is_valid_outcome(point.actual_outcome):
        return False
    if not point.market_id:
        return False
    return True


# =============================================================================
# CORE METRICS
# =============================================================================


def brier_score(points: List[CalibrationPoint]) -> Optional[float]:
    """
    Compute Brier score: mean( (probability - outcome)^2 ).

    Lower is better. 0.0 = perfect. 0.25 = no skill (coin flip at 50%).

    Args:
        points: List of valid calibration points.

    Returns:
        Brier score or None if no valid points.
    """
    valid = [p for p in points if is_valid_point(p)]
    if not valid:
        return None

    total = sum(
        (p.probability_at_entry - p.actual_outcome) ** 2
        for p in valid
    )
    return total / len(valid)


def avg_probability(points: List[CalibrationPoint]) -> Optional[float]:
    """
    Compute average predicted probability.

    Args:
        points: List of valid calibration points.

    Returns:
        Average probability or None if no valid points.
    """
    valid = [p for p in points if is_valid_point(p)]
    if not valid:
        return None
    return sum(p.probability_at_entry for p in valid) / len(valid)


def actual_frequency(points: List[CalibrationPoint]) -> Optional[float]:
    """
    Compute actual frequency of outcome==1.

    Args:
        points: List of valid calibration points.

    Returns:
        Fraction of outcomes that were 1 (YES), or None if empty.
    """
    valid = [p for p in points if is_valid_point(p)]
    if not valid:
        return None
    return sum(p.actual_outcome for p in valid) / len(valid)


def calibration_gap(points: List[CalibrationPoint]) -> Optional[float]:
    """
    Compute calibration gap: actual_frequency - avg_probability.

    Positive gap = underconfident (outcomes happen more than predicted).
    Negative gap = overconfident (outcomes happen less than predicted).

    Args:
        points: List of valid calibration points.

    Returns:
        Calibration gap or None if no valid points.
    """
    af = actual_frequency(points)
    ap = avg_probability(points)
    if af is None or ap is None:
        return None
    return af - ap


def compute_bucket(points: List[CalibrationPoint]) -> MetricsBucket:
    """
    Compute all metrics for a group of calibration points.

    Args:
        points: List of calibration points (will be filtered for validity).

    Returns:
        MetricsBucket with all computed metrics.
    """
    valid = [p for p in points if is_valid_point(p)]
    if not valid:
        return MetricsBucket(sample_size=0)

    return MetricsBucket(
        brier_score=brier_score(valid),
        avg_probability=avg_probability(valid),
        actual_frequency=actual_frequency(valid),
        calibration_gap=calibration_gap(valid),
        sample_size=len(valid),
    )


# =============================================================================
# GROUPING
# =============================================================================


ODDS_BUCKETS = {
    "0_10": (0.0, 0.10),
    "10_30": (0.10, 0.30),
    "30_50": (0.30, 0.50),
    "50_70": (0.50, 0.70),
    "70_90": (0.70, 0.90),
    "90_100": (0.90, 1.01),  # 1.01 to include 1.0
}


def classify_odds_bucket(probability: float) -> Optional[str]:
    """
    Classify a probability into an odds bucket.

    Args:
        probability: Value in [0.0, 1.0].

    Returns:
        Bucket name string or None if invalid.
    """
    if not is_valid_probability(probability):
        return None
    for name, (low, high) in ODDS_BUCKETS.items():
        if low <= probability < high:
            return name
    return None


def group_by_model(points: List[CalibrationPoint]) -> Dict[str, List[CalibrationPoint]]:
    """Group calibration points by model_type."""
    groups: Dict[str, List[CalibrationPoint]] = {}
    for p in points:
        key = p.model_type or "UNKNOWN"
        groups.setdefault(key, []).append(p)
    return groups


def group_by_confidence(points: List[CalibrationPoint]) -> Dict[str, List[CalibrationPoint]]:
    """Group calibration points by confidence level."""
    groups: Dict[str, List[CalibrationPoint]] = {}
    for p in points:
        key = p.confidence or "UNKNOWN"
        groups.setdefault(key, []).append(p)
    return groups


def group_by_odds_bucket(points: List[CalibrationPoint]) -> Dict[str, List[CalibrationPoint]]:
    """Group calibration points by odds bucket."""
    groups: Dict[str, List[CalibrationPoint]] = {}
    for p in points:
        if not is_valid_point(p):
            continue
        bucket = classify_odds_bucket(p.probability_at_entry)
        if bucket:
            groups.setdefault(bucket, []).append(p)
    return groups
