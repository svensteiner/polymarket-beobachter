# =============================================================================
# POLYMARKET BEOBACHTER - COURT RULING ANALYZER
# =============================================================================
#
# GOVERNANCE INTENT:
# This module provides a complete analysis pipeline for COURT_RULING markets.
# It validates structural tradeability WITHOUT predicting legal outcomes.
#
# CORE PRINCIPLE:
# We evaluate whether a court ruling market is STRUCTURALLY TRADEABLE.
# We do NOT predict verdicts, rulings, or legal outcomes.
#
# PIPELINE:
# 1. Court validation (6-point checklist)
# 2. If validation fails -> INSUFFICIENT_DATA (immediate return)
# 3. If validation passes -> standard analysis (timeline, resolution clarity)
#
# =============================================================================

import logging
from dataclasses import dataclass, field
from datetime import datetime, date
from typing import Optional, Dict, Any, List

from .court_validation import (
    CourtRulingValidator,
    CourtValidationChecklist,
    validate_court_ruling,
    is_court_ruling_market,
)

logger = logging.getLogger(__name__)


# =============================================================================
# DATA MODELS
# =============================================================================


@dataclass
class CourtMarketInput:
    """
    Input data for court ruling market analysis.

    GOVERNANCE:
    - No legal predictions
    - No outcome probabilities
    - Only structural/resolution information
    """
    market_question: str
    resolution_text: str
    target_date: str  # YYYY-MM-DD
    description: str = ""

    # Optional: market-implied probability (for sanity check ONLY)
    market_implied_probability: Optional[float] = None

    def __post_init__(self):
        """Validate input fields."""
        if not self.market_question:
            raise ValueError("market_question is required")
        if not self.resolution_text:
            raise ValueError("resolution_text is required")
        if not self.target_date:
            raise ValueError("target_date is required")


@dataclass
class CourtAnalysisReport:
    """
    Complete analysis report for a court ruling market.

    GOVERNANCE:
    - decision: TRADE / NO_TRADE / INSUFFICIENT_DATA
    - If court_validation fails -> decision = INSUFFICIENT_DATA
    - court_validation_summary shows exactly which criteria failed
    """
    # Input (for audit trail)
    market_input: CourtMarketInput

    # Decision outcome
    decision: str  # "TRADE" / "NO_TRADE" / "INSUFFICIENT_DATA"

    # Court-specific validation
    court_validation_summary: Dict[str, Any]

    # Blocking reasons (explicit list)
    blocking_reasons: List[str]

    # Additional analysis (only if validation passed)
    timeline_analysis: Optional[Dict[str, Any]] = None
    resolution_clarity: Optional[Dict[str, Any]] = None
    case_details: Optional[Dict[str, Any]] = None

    # Metadata
    analysis_version: str = "1.0.0"
    generated_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "decision": self.decision,
            "court_validation_summary": self.court_validation_summary,
            "blocking_reasons": self.blocking_reasons,
            "timeline_analysis": self.timeline_analysis,
            "resolution_clarity": self.resolution_clarity,
            "case_details": self.case_details,
            "analysis_version": self.analysis_version,
            "generated_at": self.generated_at,
            "market_question": self.market_input.market_question,
        }


# =============================================================================
# COURT RULING ANALYZER
# =============================================================================


class CourtRulingAnalyzer:
    """
    Analyzer for COURT_RULING markets.

    STRICT PRINCIPLES:
    - NO legal predictions
    - NO outcome probabilities
    - NO legal advice
    - ONLY structural validation

    If the 6-point checklist fails, output is INSUFFICIENT_DATA.
    This is expected and correct.
    """

    VERSION = "1.0.0"

    # Court-specific timeline expectations (days for official publication)
    COURT_PUBLICATION_LAG = {
        "SUPREME": 0,       # Published immediately
        "APPELLATE": 3,     # Few days
        "DISTRICT": 2,      # Varies
        "INTERNATIONAL": 7, # Can take longer
    }

    def __init__(self):
        """Initialize the court ruling analyzer."""
        self.court_validator = CourtRulingValidator()

    def analyze(self, market_input: CourtMarketInput) -> CourtAnalysisReport:
        """
        Analyze a court ruling market for structural tradeability.

        PIPELINE:
        1. Run 6-point court validation checklist
        2. If ANY fails -> INSUFFICIENT_DATA (stop here)
        3. If ALL pass -> check timeline feasibility
        4. Return decision with full audit trail

        Args:
            market_input: Court ruling market to analyze

        Returns:
            CourtAnalysisReport with decision and reasoning
        """
        logger.info(f"Analyzing court market: {market_input.market_question[:50]}...")

        # ---------------------------------------------------------------------
        # STEP 1: Court Validation Checklist (MANDATORY)
        # ---------------------------------------------------------------------
        validation = self.court_validator.validate(
            market_question=market_input.market_question,
            resolution_text=market_input.resolution_text,
            description=market_input.description,
            target_date=market_input.target_date,
        )

        # Build validation summary
        validation_summary = validation.to_dict()

        # ---------------------------------------------------------------------
        # STEP 2: Check if validation passed
        # ---------------------------------------------------------------------
        if not validation.is_valid:
            logger.info(
                f"Court validation FAILED: {len(validation.blocking_reasons)} issues"
            )
            return CourtAnalysisReport(
                market_input=market_input,
                decision="INSUFFICIENT_DATA",
                court_validation_summary=validation_summary,
                blocking_reasons=list(validation.blocking_reasons),
                timeline_analysis=None,
                resolution_clarity=None,
                case_details=None,
                analysis_version=self.VERSION,
            )

        # ---------------------------------------------------------------------
        # STEP 3: Timeline Analysis (only if validation passed)
        # ---------------------------------------------------------------------
        timeline_analysis = self._analyze_timeline(
            market_input, validation.court_level
        )

        # ---------------------------------------------------------------------
        # STEP 4: Resolution Clarity Check
        # ---------------------------------------------------------------------
        resolution_clarity = self._check_resolution_clarity(market_input)

        # ---------------------------------------------------------------------
        # STEP 5: Case Details
        # ---------------------------------------------------------------------
        case_details = {
            "court": validation.court_identified,
            "court_level": validation.court_level,
            "case_id": validation.case_identifier,
            "source": validation.source_identified,
            "date_type": validation.date_type,
            "expected_date": validation.expected_date,
        }

        # ---------------------------------------------------------------------
        # STEP 6: Final Decision
        # ---------------------------------------------------------------------
        blocking_reasons = list(validation.blocking_reasons)

        # Add timeline blocking reasons
        if not timeline_analysis.get("is_feasible", False):
            blocking_reasons.append(
                f"TIMELINE: {timeline_analysis.get('reason', 'Timeline not feasible')}"
            )

        # Add resolution clarity blocking reasons
        if not resolution_clarity.get("is_clear", False):
            blocking_reasons.append(
                f"RESOLUTION: {resolution_clarity.get('reason', 'Resolution unclear')}"
            )

        # Determine final decision
        if blocking_reasons:
            decision = "NO_TRADE"
        else:
            decision = "TRADE"

        logger.info(f"Court analysis complete: {decision}")

        return CourtAnalysisReport(
            market_input=market_input,
            decision=decision,
            court_validation_summary=validation_summary,
            blocking_reasons=blocking_reasons,
            timeline_analysis=timeline_analysis,
            resolution_clarity=resolution_clarity,
            case_details=case_details,
            analysis_version=self.VERSION,
        )

    def _analyze_timeline(
        self,
        market_input: CourtMarketInput,
        court_level: Optional[str]
    ) -> Dict[str, Any]:
        """
        Analyze if the timeline is feasible for resolution.

        Court rulings have variable publication timelines:
        - Supreme Court: Opinions published immediately
        - Appellate: Days to weeks
        - District: Varies widely
        - International: Can take weeks

        Args:
            market_input: Court market input
            court_level: Level of the court

        Returns:
            Timeline analysis dictionary
        """
        try:
            target = date.fromisoformat(market_input.target_date[:10])
            today = date.today()
            days_until = (target - today).days

            if days_until < 0:
                return {
                    "is_feasible": False,
                    "reason": f"Target date is {abs(days_until)} days in the past",
                    "days_until_target": days_until,
                }

            # Get expected publication lag
            pub_lag = self.COURT_PUBLICATION_LAG.get(court_level, 3)

            if days_until < pub_lag:
                return {
                    "is_feasible": False,
                    "reason": f"Insufficient time for official publication (need {pub_lag} days)",
                    "days_until_target": days_until,
                    "required_buffer": pub_lag,
                }

            return {
                "is_feasible": True,
                "reason": None,
                "days_until_target": days_until,
                "court_level": court_level,
                "expected_publication_lag": pub_lag,
                "buffer_adequate": days_until >= pub_lag * 2,
            }

        except ValueError as e:
            return {
                "is_feasible": False,
                "reason": f"Invalid target date format: {e}",
                "days_until_target": None,
            }

    def _check_resolution_clarity(
        self, market_input: CourtMarketInput
    ) -> Dict[str, Any]:
        """
        Check if the resolution criteria are clear and unambiguous.

        Args:
            market_input: Court market input

        Returns:
            Resolution clarity analysis
        """
        text = market_input.resolution_text.lower()

        # Check for problematic phrases
        problematic_phrases = [
            "at our discretion",
            "we may",
            "subject to interpretation",
            "may be adjusted",
            "approximately",
            "legal experts",
            "consensus",
        ]

        found_issues = [p for p in problematic_phrases if p in text]

        if found_issues:
            return {
                "is_clear": False,
                "reason": f"Resolution contains ambiguous language: {', '.join(found_issues)}",
                "issues": found_issues,
            }

        # Check for clear resolution source
        clear_sources = [
            "official court", "court website", "pacer",
            "published opinion", "official ruling",
        ]

        has_clear_source = any(s in text for s in clear_sources)

        if not has_clear_source:
            # Not a hard fail, but note it
            return {
                "is_clear": True,
                "reason": None,
                "issues": [],
                "warning": "No explicit official source in resolution text",
            }

        return {
            "is_clear": True,
            "reason": None,
            "issues": [],
        }


# =============================================================================
# MODULE-LEVEL FUNCTION
# =============================================================================


def analyze_court_market(
    market_question: str,
    resolution_text: str,
    target_date: str,
    description: str = "",
    market_implied_probability: Optional[float] = None,
) -> CourtAnalysisReport:
    """
    Convenience function to analyze a court ruling market.

    GOVERNANCE:
    This function does NOT:
    - Predict legal outcomes
    - Provide legal advice
    - Assess case merits

    It ONLY validates structural tradeability.

    Args:
        market_question: The market's main question
        resolution_text: The resolution criteria
        target_date: Target date (YYYY-MM-DD)
        description: Additional description
        market_implied_probability: For sanity check only

    Returns:
        CourtAnalysisReport with decision and reasoning
    """
    market_input = CourtMarketInput(
        market_question=market_question,
        resolution_text=resolution_text,
        target_date=target_date,
        description=description,
        market_implied_probability=market_implied_probability,
    )

    analyzer = CourtRulingAnalyzer()
    return analyzer.analyze(market_input)
