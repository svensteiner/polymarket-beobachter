# =============================================================================
# POLYMARKET BEOBACHTER - LEARNING ORCHESTRATOR
# =============================================================================
#
# GOVERNANCE INTENT:
# Central coordinator for all learning subsystems. Provides a clean interface
# for the main trading loop to access learning enhancements.
#
# All parameter change proposals are written to proposals/ for human review.
# NO automatic parameter changes.
#
# =============================================================================

import logging
import json
from datetime import datetime, timezone
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import Optional, List, Dict, Any, Callable

from .learning_database import LearningDatabase, PredictionRecord
from .outcome_tracker import OutcomeTracker, TradeContext, create_trade_context
from .calibration_engine import CalibrationEngine
from .pattern_detector import PatternDetector
from .time_urgency import TimeUrgencyCalculator, UrgencyAdjustment, create_custom_urgency_calculator

logger = logging.getLogger(__name__)


@dataclass
class LearningConfig:
    """Configuration for the learning system."""
    enabled: bool = True
    database_path: Optional[Path] = None
    calibration_enabled: bool = True
    pattern_detection_enabled: bool = True
    time_urgency_enabled: bool = True
    min_calibration_samples: int = 30
    min_pattern_samples: int = 20
    recalibrate_interval_hours: int = 24
    proposal_output_path: Optional[Path] = None

    # Time urgency thresholds
    critical_hours: float = 2.0
    urgent_hours: float = 8.0
    approaching_hours: float = 24.0


@dataclass
class EnhancedSignal:
    """A trading signal enhanced with learning insights."""
    # Original signal data
    market_id: str
    original_edge: float
    original_confidence: float
    original_size: float

    # Learning enhancements
    calibrated_confidence: float
    urgency_adjustment: Optional[UrgencyAdjustment]
    pattern_adjustment: float

    # Final values
    adjusted_edge: float
    adjusted_confidence: float
    adjusted_size: float

    # Metadata
    should_trade: bool
    reasons: List[str]
    learning_factors: Dict[str, Any]


class LearningOrchestrator:
    """
    Central coordinator for all learning subsystems.

    Provides:
    1. Signal enhancement with calibration, patterns, and time urgency
    2. Prediction recording for future learning
    3. Periodic learning cycle (recalibration, pattern detection)
    4. Proposal generation for human review
    """

    def __init__(self, config: Optional[LearningConfig] = None):
        """
        Initialize learning orchestrator.

        Args:
            config: Learning configuration (defaults provided if None)
        """
        self.config = config or LearningConfig()

        if not self.config.enabled:
            logger.info("Learning system disabled")
            self._db = None
            self._outcome_tracker = None
            self._calibration = None
            self._patterns = None
            self._time_urgency = None
            return

        # Initialize components
        self._db = LearningDatabase(self.config.database_path)

        self._outcome_tracker = OutcomeTracker(self._db)

        if self.config.calibration_enabled:
            self._calibration = CalibrationEngine(
                self._db,
                min_samples=self.config.min_calibration_samples
            )
        else:
            self._calibration = None

        if self.config.pattern_detection_enabled:
            self._patterns = PatternDetector(
                self._db,
                min_samples=self.config.min_pattern_samples
            )
        else:
            self._patterns = None

        if self.config.time_urgency_enabled:
            self._time_urgency = create_custom_urgency_calculator(
                critical_hours=self.config.critical_hours,
                urgent_hours=self.config.urgent_hours,
                approaching_hours=self.config.approaching_hours
            )
        else:
            self._time_urgency = None

        self._proposal_path = self.config.proposal_output_path or \
            Path(__file__).parent.parent / "proposals"

        self._last_recalibration: Optional[datetime] = None

        logger.info(
            "LearningOrchestrator initialized: calibration=%s, patterns=%s, time_urgency=%s",
            self.config.calibration_enabled,
            self.config.pattern_detection_enabled,
            self.config.time_urgency_enabled
        )

    @property
    def is_enabled(self) -> bool:
        """Check if learning is enabled."""
        return self.config.enabled

    def enhance_signal(
        self,
        market_id: str,
        edge: float,
        confidence: float,
        suggested_size: float,
        hours_to_resolution: float,
        context: Optional[TradeContext] = None,
        base_min_edge: float = 0.05
    ) -> EnhancedSignal:
        """
        Apply all learning enhancements to a trading signal.

        Args:
            market_id: Market identifier
            edge: Calculated edge
            confidence: Raw confidence
            suggested_size: Suggested position size
            hours_to_resolution: Hours until market resolves
            context: Optional trade context for pattern matching
            base_min_edge: Base minimum edge threshold

        Returns:
            EnhancedSignal with all adjustments applied
        """
        reasons = []
        learning_factors = {}

        # Start with original values
        adjusted_edge = edge
        adjusted_confidence = confidence
        adjusted_size = suggested_size

        # 1. Calibration adjustment
        calibrated_confidence = confidence
        if self._calibration and self.config.calibration_enabled:
            calibrated_confidence = self._calibration.calculate_calibration(confidence)
            if calibrated_confidence != confidence:
                learning_factors["calibration"] = {
                    "raw": confidence,
                    "calibrated": calibrated_confidence,
                    "factor": calibrated_confidence / confidence if confidence > 0 else 1.0
                }
                reasons.append(f"Calibrated: {confidence:.0%} -> {calibrated_confidence:.0%}")
            adjusted_confidence = calibrated_confidence

        # 2. Time urgency adjustment
        urgency_adjustment = None
        if self._time_urgency and self.config.time_urgency_enabled:
            urgency_adjustment = self._time_urgency.calculate_adjustment(
                hours_to_resolution,
                base_min_edge=base_min_edge,
                base_max_position=suggested_size * 2  # Assume suggested is ~half max
            )
            adjusted_size = suggested_size * urgency_adjustment.position_multiplier
            learning_factors["time_urgency"] = {
                "phase": urgency_adjustment.phase.value,
                "hours_remaining": hours_to_resolution,
                "edge_multiplier": urgency_adjustment.edge_multiplier,
                "position_multiplier": urgency_adjustment.position_multiplier
            }
            reasons.append(urgency_adjustment.reason)

        # 3. Pattern adjustment
        pattern_adjustment = 0.0
        if self._patterns and self.config.pattern_detection_enabled and context:
            pattern_result = self._patterns.get_pattern_adjustment(context)
            pattern_adjustment = pattern_result.total_adjustment
            if pattern_adjustment != 0:
                adjusted_edge = edge + pattern_adjustment
                learning_factors["patterns"] = {
                    "adjustment": pattern_adjustment,
                    "matches": len(pattern_result.pattern_matches),
                    "confidence": pattern_result.confidence
                }
                reasons.append(f"Pattern: {pattern_result.reason}")

        # Determine if we should trade
        should_trade = True
        effective_min_edge = base_min_edge
        if urgency_adjustment:
            effective_min_edge = urgency_adjustment.adjusted_min_edge

        if adjusted_edge < effective_min_edge:
            should_trade = False
            reasons.append(f"Edge {adjusted_edge:.1%} below threshold {effective_min_edge:.1%}")

        if urgency_adjustment and adjusted_confidence < urgency_adjustment.confidence_floor:
            should_trade = False
            reasons.append(f"Confidence {adjusted_confidence:.1%} below floor {urgency_adjustment.confidence_floor:.1%}")

        return EnhancedSignal(
            market_id=market_id,
            original_edge=edge,
            original_confidence=confidence,
            original_size=suggested_size,
            calibrated_confidence=calibrated_confidence,
            urgency_adjustment=urgency_adjustment,
            pattern_adjustment=pattern_adjustment,
            adjusted_edge=adjusted_edge,
            adjusted_confidence=adjusted_confidence,
            adjusted_size=adjusted_size,
            should_trade=should_trade,
            reasons=reasons,
            learning_factors=learning_factors
        )

    def record_prediction(
        self,
        trade_id: str,
        market_id: str,
        prediction_side: str,
        predicted_probability: float,
        market_price: float,
        edge: float,
        confidence: float,
        hours_to_resolution: float,
        context: Optional[TradeContext] = None
    ) -> bool:
        """
        Record a prediction for future learning.

        Args:
            trade_id: Unique trade identifier
            market_id: Market being traded
            prediction_side: 'YES' or 'NO'
            predicted_probability: Our probability estimate
            market_price: Market price at trade time
            edge: Calculated edge
            confidence: Confidence level
            hours_to_resolution: Hours until resolution
            context: Optional trade context

        Returns:
            True if recorded successfully
        """
        if not self._outcome_tracker:
            return False

        return self._outcome_tracker.record_prediction(
            trade_id=trade_id,
            market_id=market_id,
            prediction_side=prediction_side,
            predicted_probability=predicted_probability,
            market_price=market_price,
            edge=edge,
            confidence=confidence,
            hours_to_resolution=hours_to_resolution,
            context=context
        )

    def set_resolution_fetcher(self, fetcher: Callable[[str], Optional[str]]):
        """Set function to fetch market resolutions."""
        if self._outcome_tracker:
            self._outcome_tracker.set_resolution_fetcher(fetcher)

    def run_learning_cycle(self) -> Dict[str, Any]:
        """
        Run periodic learning cycle.

        This should be called periodically (e.g., daily) to:
        1. Fetch and record market resolutions
        2. Recalibrate confidence
        3. Detect patterns
        4. Generate proposals for significant findings

        Returns:
            Summary of learning cycle results
        """
        if not self.is_enabled:
            return {"status": "disabled"}

        results = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "resolutions": {},
            "calibration": {},
            "patterns": {},
            "proposals_generated": 0
        }

        # 1. Fetch resolutions
        if self._outcome_tracker:
            try:
                resolved = self._outcome_tracker.fetch_and_record_resolutions()
                results["resolutions"] = {
                    "markets_resolved": len(resolved),
                    "outcomes": resolved
                }
            except Exception as e:
                logger.error("Error fetching resolutions: %s", e)
                results["resolutions"] = {"error": str(e)}

        # 2. Recalibrate
        if self._calibration:
            try:
                state = self._calibration.recalibrate()
                results["calibration"] = self._calibration.get_summary()
                self._last_recalibration = datetime.now(timezone.utc)
            except Exception as e:
                logger.error("Error in recalibration: %s", e)
                results["calibration"] = {"error": str(e)}

        # 3. Detect patterns
        if self._patterns:
            try:
                patterns = self._patterns.detect_patterns()
                results["patterns"] = self._patterns.get_pattern_summary()
            except Exception as e:
                logger.error("Error in pattern detection: %s", e)
                results["patterns"] = {"error": str(e)}

        # 4. Generate proposals
        proposals = self._generate_all_proposals()
        results["proposals_generated"] = len(proposals)

        logger.info("Learning cycle complete: %d resolutions, %d proposals",
                   results["resolutions"].get("markets_resolved", 0),
                   len(proposals))

        return results

    def _generate_all_proposals(self) -> List[Dict[str, Any]]:
        """Generate and save all proposals."""
        all_proposals = []

        # Calibration proposals
        if self._calibration:
            for proposal in self._calibration.generate_proposals():
                proposal_dict = {
                    "proposal_id": proposal.proposal_id,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "source": "learning-engine-calibration",
                    "status": "OPEN",
                    "type": "calibration",
                    "parameter": {
                        "bucket": proposal.bucket,
                        "field": f"calibration.{proposal.bucket}",
                        "current_value": proposal.current_factor,
                        "proposed_value": proposal.proposed_factor
                    },
                    "reason": proposal.reason,
                    "supporting_metrics": proposal.supporting_data,
                    "risk_assessment": {
                        "level": "LOW" if proposal.sample_size > 50 else "MEDIUM",
                        "notes": f"Based on {proposal.sample_size} samples, drift={proposal.drift:.1%}"
                    }
                }
                all_proposals.append(proposal_dict)

        # Pattern proposals
        if self._patterns:
            for proposal in self._patterns.generate_proposals():
                proposal_dict = {
                    "proposal_id": proposal.proposal_id,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "source": "learning-engine-patterns",
                    "status": "OPEN",
                    "type": "pattern",
                    "parameter": {
                        "pattern_type": proposal.pattern_type,
                        "pattern_value": proposal.pattern_value,
                        "field": f"patterns.{proposal.pattern_type}.{proposal.pattern_value}",
                        "current_value": 0.0,
                        "proposed_value": proposal.suggested_edge_adjustment
                    },
                    "reason": proposal.reason,
                    "supporting_metrics": {
                        "win_rate": proposal.win_rate,
                        "sample_size": proposal.sample_size,
                        "confidence_interval": list(proposal.confidence_interval),
                        **proposal.supporting_data
                    },
                    "risk_assessment": {
                        "level": "LOW" if proposal.sample_size > 50 else "MEDIUM",
                        "notes": f"CI: [{proposal.confidence_interval[0]:.0%}-{proposal.confidence_interval[1]:.0%}]"
                    }
                }
                all_proposals.append(proposal_dict)

        # Write proposals to files
        for proposal in all_proposals:
            self._write_proposal(proposal)

        return all_proposals

    def _write_proposal(self, proposal: Dict[str, Any]):
        """Write proposal to file."""
        try:
            self._proposal_path.mkdir(parents=True, exist_ok=True)
            filename = f"proposal_{proposal['proposal_id']}.json"
            filepath = self._proposal_path / filename

            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(proposal, f, indent=2, ensure_ascii=False)

            logger.info("Wrote proposal: %s", filename)
        except Exception as e:
            logger.error("Failed to write proposal: %s", e)

    def get_status(self) -> Dict[str, Any]:
        """Get learning system status."""
        if not self.is_enabled:
            return {"enabled": False}

        status = {
            "enabled": True,
            "components": {
                "calibration": self.config.calibration_enabled,
                "patterns": self.config.pattern_detection_enabled,
                "time_urgency": self.config.time_urgency_enabled
            },
            "database": self._db.get_summary_stats() if self._db else None,
            "last_recalibration": self._last_recalibration.isoformat() if self._last_recalibration else None
        }

        if self._calibration:
            status["calibration_state"] = self._calibration.get_summary()

        if self._patterns:
            status["top_patterns"] = self._patterns.get_top_patterns(5)

        if self._time_urgency:
            status["urgency_phases"] = self._time_urgency.get_phase_summary()

        return status

    def get_accuracy_report(self) -> Dict[str, Any]:
        """Get detailed accuracy report."""
        if not self._outcome_tracker:
            return {"error": "Learning not enabled"}

        return {
            "overall": self._outcome_tracker.get_accuracy_stats(),
            "recent_outcomes": self._outcome_tracker.get_recent_outcomes(10)
        }


def create_learning_orchestrator(
    enabled: bool = True,
    critical_hours: float = 2.0,
    urgent_hours: float = 8.0
) -> LearningOrchestrator:
    """
    Factory function to create a learning orchestrator.

    Args:
        enabled: Whether learning is enabled
        critical_hours: Hours threshold for critical phase
        urgent_hours: Hours threshold for urgent phase

    Returns:
        Configured LearningOrchestrator
    """
    config = LearningConfig(
        enabled=enabled,
        critical_hours=critical_hours,
        urgent_hours=urgent_hours
    )
    return LearningOrchestrator(config)
