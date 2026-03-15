# =============================================================================
# POLYMARKET BEOBACHTER - CALIBRATION ENGINE
# =============================================================================
#
# GOVERNANCE INTENT:
# Adjusts confidence based on historical accuracy. If we predict 70% and
# are only right 60% of the time, the calibration factor is 0.857.
#
# This is NOT auto-applied. When calibration drift is significant, a proposal
# is generated for human review.
#
# =============================================================================

import logging
import json
from datetime import datetime, timezone
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import Dict, Optional, List, Any, Tuple

from .learning_database import LearningDatabase, CalibrationBucket

logger = logging.getLogger(__name__)


@dataclass
class CalibrationState:
    """Current calibration state."""
    bucket_factors: Dict[str, float]  # "0.5-0.6" -> factor
    last_updated: str
    total_samples: int
    overall_accuracy: float
    is_well_calibrated: bool
    drift_detected: bool


@dataclass
class CalibrationProposal:
    """Proposal for calibration adjustment."""
    proposal_id: str
    bucket: str
    current_factor: float
    proposed_factor: float
    sample_size: int
    accuracy: float
    expected_accuracy: float
    drift: float
    reason: str
    supporting_data: Dict[str, Any]


class CalibrationEngine:
    """
    Tracks historical accuracy and produces calibration adjustments.

    Calibration process:
    1. Group predictions by confidence bucket (e.g., 50-60%, 60-70%)
    2. For each bucket, compare predicted vs actual accuracy
    3. Calculate calibration factor: actual_accuracy / expected_accuracy
    4. Apply factor to adjust future confidence estimates

    Example:
    - Bucket 60-70%: We predict average 65% probability
    - Actual win rate in this bucket: 55%
    - Calibration factor: 55/65 = 0.846
    - Future 65% predictions become 65% * 0.846 = 55%
    """

    MIN_SAMPLES_DEFAULT = 30
    BUCKET_WIDTH_DEFAULT = 0.1
    DRIFT_THRESHOLD_DEFAULT = 0.10  # 10% drift triggers proposal

    def __init__(
        self,
        db: LearningDatabase,
        state_path: Optional[Path] = None,
        min_samples: int = MIN_SAMPLES_DEFAULT,
        bucket_width: float = BUCKET_WIDTH_DEFAULT,
        drift_threshold: float = DRIFT_THRESHOLD_DEFAULT
    ):
        """
        Initialize calibration engine.

        Args:
            db: Learning database
            state_path: Path to save calibration state
            min_samples: Minimum samples per bucket for valid calibration
            bucket_width: Width of confidence buckets (default 10%)
            drift_threshold: Drift level that triggers proposal
        """
        self.db = db
        self.state_path = state_path or Path(__file__).parent.parent / "data" / "calibration_state.json"
        self.min_samples = min_samples
        self.bucket_width = bucket_width
        self.drift_threshold = drift_threshold

        self._state: Optional[CalibrationState] = None
        self._load_state()

        logger.info("CalibrationEngine initialized (min_samples=%d, bucket_width=%.1f%%)",
                   min_samples, bucket_width * 100)

    def _load_state(self):
        """Load calibration state from disk."""
        if self.state_path.exists():
            try:
                data = json.loads(self.state_path.read_text(encoding="utf-8"))
                self._state = CalibrationState(
                    bucket_factors=data.get("bucket_factors", {}),
                    last_updated=data.get("last_updated", ""),
                    total_samples=data.get("total_samples", 0),
                    overall_accuracy=data.get("overall_accuracy", 0),
                    is_well_calibrated=data.get("is_well_calibrated", True),
                    drift_detected=data.get("drift_detected", False)
                )
                logger.info("Loaded calibration state: %d buckets", len(self._state.bucket_factors))
            except Exception as e:
                logger.warning("Failed to load calibration state: %s", e)
                self._state = None

    def _save_state(self):
        """Save calibration state to disk."""
        if self._state is None:
            return

        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            self.state_path.write_text(
                json.dumps(asdict(self._state), indent=2, ensure_ascii=False),
                encoding="utf-8"
            )
        except Exception as e:
            logger.warning("Failed to save calibration state: %s", e)

    def _get_bucket_key(self, confidence: float) -> str:
        """Get bucket key for a confidence value."""
        bucket_low = (int(confidence / self.bucket_width) * self.bucket_width)
        bucket_high = min(bucket_low + self.bucket_width, 1.0)
        return f"{bucket_low:.1f}-{bucket_high:.1f}"

    def _get_bucket_midpoint(self, bucket_key: str) -> float:
        """Get midpoint of a bucket."""
        parts = bucket_key.split("-")
        return (float(parts[0]) + float(parts[1])) / 2

    def calculate_calibration(self, raw_confidence: float) -> float:
        """
        Return calibrated confidence based on historical accuracy.

        Args:
            raw_confidence: The raw confidence estimate (0-1)

        Returns:
            Calibrated confidence
        """
        if self._state is None or not self._state.bucket_factors:
            return raw_confidence

        bucket_key = self._get_bucket_key(raw_confidence)
        factor = self._state.bucket_factors.get(bucket_key, 1.0)

        calibrated = raw_confidence * factor
        # Clamp to valid probability range
        calibrated = max(0.01, min(0.99, calibrated))

        if factor != 1.0:
            logger.debug(
                "Calibrated confidence: %.1f%% -> %.1f%% (factor=%.3f, bucket=%s)",
                raw_confidence * 100, calibrated * 100, factor, bucket_key
            )

        return calibrated

    def recalibrate(self) -> CalibrationState:
        """
        Recalculate calibration factors from historical data.

        Returns:
            Updated calibration state
        """
        buckets = self.db.get_calibration_stats(self.bucket_width)

        bucket_factors = {}
        total_samples = 0
        correct_total = 0
        drifts = []

        for bucket in buckets:
            bucket_key = f"{bucket.bucket_low:.1f}-{bucket.bucket_high:.1f}"

            if bucket.total_predictions >= self.min_samples:
                expected = (bucket.bucket_low + bucket.bucket_high) / 2
                actual = bucket.accuracy
                factor = actual / expected if expected > 0 else 1.0

                # Bound factor to reasonable range
                factor = max(0.5, min(1.5, factor))
                bucket_factors[bucket_key] = factor

                drift = abs(actual - expected)
                drifts.append(drift)

                logger.info(
                    "Bucket %s: %d samples, accuracy=%.1f%% (expected %.1f%%), factor=%.3f",
                    bucket_key, bucket.total_predictions, actual * 100, expected * 100, factor
                )
            else:
                bucket_factors[bucket_key] = 1.0  # Not enough data

            total_samples += bucket.total_predictions
            correct_total += bucket.correct_predictions

        overall_accuracy = correct_total / total_samples if total_samples > 0 else 0
        avg_drift = sum(drifts) / len(drifts) if drifts else 0
        drift_detected = avg_drift > self.drift_threshold

        self._state = CalibrationState(
            bucket_factors=bucket_factors,
            last_updated=datetime.now(timezone.utc).isoformat(),
            total_samples=total_samples,
            overall_accuracy=overall_accuracy,
            is_well_calibrated=not drift_detected,
            drift_detected=drift_detected
        )

        self._save_state()

        # Save snapshot to database
        self.db.save_calibration_snapshot(buckets)

        logger.info(
            "Recalibration complete: %d samples, accuracy=%.1f%%, drift=%s",
            total_samples, overall_accuracy * 100, "YES" if drift_detected else "NO"
        )

        return self._state

    def generate_proposals(self) -> List[CalibrationProposal]:
        """
        Generate proposals for significant calibration adjustments.

        Returns:
            List of proposals for human review
        """
        proposals = []
        buckets = self.db.get_calibration_stats(self.bucket_width)

        for bucket in buckets:
            if bucket.total_predictions < self.min_samples:
                continue

            bucket_key = f"{bucket.bucket_low:.1f}-{bucket.bucket_high:.1f}"
            expected = (bucket.bucket_low + bucket.bucket_high) / 2
            actual = bucket.accuracy
            drift = abs(actual - expected)

            if drift > self.drift_threshold:
                current_factor = self._state.bucket_factors.get(bucket_key, 1.0) if self._state else 1.0
                proposed_factor = actual / expected if expected > 0 else 1.0
                proposed_factor = max(0.5, min(1.5, proposed_factor))

                # Only propose if significant change from current
                if abs(proposed_factor - current_factor) > 0.05:
                    proposal_id = f"CAL-{bucket_key}-{datetime.now().strftime('%Y%m%d%H%M%S')}"

                    if actual < expected:
                        reason = f"Overconfident in {bucket_key} bucket: predicted {expected:.0%}, actual {actual:.0%}"
                    else:
                        reason = f"Underconfident in {bucket_key} bucket: predicted {expected:.0%}, actual {actual:.0%}"

                    proposals.append(CalibrationProposal(
                        proposal_id=proposal_id,
                        bucket=bucket_key,
                        current_factor=current_factor,
                        proposed_factor=proposed_factor,
                        sample_size=bucket.total_predictions,
                        accuracy=actual,
                        expected_accuracy=expected,
                        drift=drift,
                        reason=reason,
                        supporting_data={
                            "total_predictions": bucket.total_predictions,
                            "correct_predictions": bucket.correct_predictions,
                            "bucket_low": bucket.bucket_low,
                            "bucket_high": bucket.bucket_high
                        }
                    ))

        if proposals:
            logger.info("Generated %d calibration proposals", len(proposals))

        return proposals

    def get_state(self) -> Optional[CalibrationState]:
        """Get current calibration state."""
        return self._state

    def get_factor_for_bucket(self, bucket_key: str) -> float:
        """Get calibration factor for a specific bucket."""
        if self._state is None:
            return 1.0
        return self._state.bucket_factors.get(bucket_key, 1.0)

    def get_summary(self) -> Dict[str, Any]:
        """Get calibration summary for display."""
        if self._state is None:
            return {
                "initialized": False,
                "message": "Calibration not yet run"
            }

        return {
            "initialized": True,
            "last_updated": self._state.last_updated,
            "total_samples": self._state.total_samples,
            "overall_accuracy": f"{self._state.overall_accuracy:.1%}",
            "is_well_calibrated": self._state.is_well_calibrated,
            "drift_detected": self._state.drift_detected,
            "bucket_count": len(self._state.bucket_factors),
            "buckets": {k: f"{v:.3f}" for k, v in sorted(self._state.bucket_factors.items())}
        }

    def apply_proposal(self, proposal: CalibrationProposal) -> bool:
        """
        Apply a calibration proposal.

        This should only be called after human approval.

        Args:
            proposal: The proposal to apply

        Returns:
            True if applied successfully
        """
        if self._state is None:
            self._state = CalibrationState(
                bucket_factors={},
                last_updated="",
                total_samples=0,
                overall_accuracy=0,
                is_well_calibrated=True,
                drift_detected=False
            )

        self._state.bucket_factors[proposal.bucket] = proposal.proposed_factor
        self._state.last_updated = datetime.now(timezone.utc).isoformat()
        self._save_state()

        logger.info("Applied calibration proposal %s: bucket %s factor %.3f -> %.3f",
                   proposal.proposal_id, proposal.bucket,
                   proposal.current_factor, proposal.proposed_factor)

        return True
