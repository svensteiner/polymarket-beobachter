# =============================================================================
# POLYMARKET BEOBACHTER - LEARNING MODULE
# =============================================================================
#
# GOVERNANCE INTENT:
# This module enables the bot to learn from historical trades and improve
# decision-making over time. All learnings generate PROPOSALS for human
# review - no automatic parameter changes.
#
# Components:
# - LearningDatabase: SQLite storage for outcomes and patterns
# - OutcomeTracker: Links predictions to market resolutions
# - CalibrationEngine: Adjusts confidence based on historical accuracy
# - PatternDetector: Identifies systematic patterns by city/weather/season
# - TimeUrgencyCalculator: Intensifies trading near market close
# - LearningOrchestrator: Central coordinator
#
# =============================================================================

from .learning_database import LearningDatabase
from .outcome_tracker import OutcomeTracker
from .calibration_engine import CalibrationEngine
from .pattern_detector import PatternDetector
from .time_urgency import TimeUrgencyCalculator
from .orchestrator import LearningOrchestrator

__all__ = [
    "LearningDatabase",
    "OutcomeTracker",
    "CalibrationEngine",
    "PatternDetector",
    "TimeUrgencyCalculator",
    "LearningOrchestrator",
]
