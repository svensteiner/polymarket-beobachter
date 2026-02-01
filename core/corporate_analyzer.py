# =============================================================================
# POLYMARKET BEOBACHTER - CORPORATE EVENT ANALYZER
# =============================================================================
#
# GOVERNANCE INTENT:
# This module provides a complete analysis pipeline for CORPORATE_EVENT markets.
# It validates structural tradeability WITHOUT predicting outcomes.
#
# CORE PRINCIPLE:
# We evaluate whether a corporate event market is STRUCTURALLY TRADEABLE.
# We do NOT predict earnings, filing outcomes, or corporate decisions.
#
# PIPELINE:
# 1. Corporate validation (6-point checklist)
# 2. If validation fails -> INSUFFICIENT_DATA (immediate return)
# 3. If validation passes -> standard analysis (timeline, resolution clarity)
#
# =============================================================================

import logging
from dataclasses import dataclass, field
from datetime import datetime, date
from typing import Optional, Dict, Any, List

from .corporate_validation import (
    CorporateEventValidator,
    CorporateValidationChecklist,
    validate_corporate_event,
    is_corporate_event_market,
)

logger = logging.getLogger(__name__)


# =============================================================================
# DATA MODELS
# =============================================================================


@dataclass
class CorporateMarketInput:
    """
    Input data for corporate event market analysis.

    GOVERNANCE:
    - No earnings predictions
    - No analyst estimates
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
class CorporateAnalysisReport:
    """
    Complete analysis report for a corporate event market.

    GOVERNANCE:
    - decision: TRADE / NO_TRADE / INSUFFICIENT_DATA
    - If corporate_validation fails -> decision = INSUFFICIENT_DATA
    - corporate_validation_summary shows exactly which criteria failed
    """
    # Input (for audit trail)
    market_input: CorporateMarketInput

    # Decision outcome
    decision: str  # "TRADE" / "NO_TRADE" / "INSUFFICIENT_DATA"

    # Corporate-specific validation
    corporate_validation_summary: Dict[str, Any]

    # Blocking reasons (explicit list)
    blocking_reasons: List[str]

    # Additional analysis (only if validation passed)
    timeline_analysis: Optional[Dict[str, Any]] = None
    resolution_clarity: Optional[Dict[str, Any]] = None
    event_details: Optional[Dict[str, Any]] = None

    # Metadata
    analysis_version: str = "1.0.0"
    generated_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "decision": self.decision,
            "corporate_validation_summary": self.corporate_validation_summary,
            "blocking_reasons": self.blocking_reasons,
            "timeline_analysis": self.timeline_analysis,
            "resolution_clarity": self.resolution_clarity,
            "event_details": self.event_details,
            "analysis_version": self.analysis_version,
            "generated_at": self.generated_at,
            "market_question": self.market_input.market_question,
        }


# =============================================================================
# CORPORATE EVENT ANALYZER
# =============================================================================


class CorporateEventAnalyzer:
    """
    Analyzer for CORPORATE_EVENT markets.

    STRICT PRINCIPLES:
    - NO earnings predictions
    - NO analyst estimates
    - NO insider information
    - ONLY structural validation

    If the 6-point checklist fails, output is INSUFFICIENT_DATA.
    This is expected and correct.
    """

    VERSION = "1.0.0"

    def __init__(self):
        """Initialize the corporate event analyzer."""
        self.corporate_validator = CorporateEventValidator()

    def analyze(self, market_input: CorporateMarketInput) -> CorporateAnalysisReport:
        """
        Analyze a corporate event market for structural tradeability.

        PIPELINE:
        1. Run 6-point corporate validation checklist
        2. If ANY fails -> INSUFFICIENT_DATA (stop here)
        3. If ALL pass -> check timeline feasibility
        4. Return decision with full audit trail

        Args:
            market_input: Corporate event market to analyze

        Returns:
            CorporateAnalysisReport with decision and reasoning
        """
        logger.info(f"Analyzing corporate market: {market_input.market_question[:50]}...")

        # ---------------------------------------------------------------------
        # STEP 1: Corporate Validation Checklist (MANDATORY)
        # ---------------------------------------------------------------------
        validation = self.corporate_validator.validate(
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
                f"Corporate validation FAILED: {len(validation.blocking_reasons)} issues"
            )
            return CorporateAnalysisReport(
                market_input=market_input,
                decision="INSUFFICIENT_DATA",
                corporate_validation_summary=validation_summary,
                blocking_reasons=list(validation.blocking_reasons),
                timeline_analysis=None,
                resolution_clarity=None,
                event_details=None,
                analysis_version=self.VERSION,
            )

        # ---------------------------------------------------------------------
        # STEP 3: Timeline Analysis (only if validation passed)
        # ---------------------------------------------------------------------
        timeline_analysis = self._analyze_timeline(market_input)

        # ---------------------------------------------------------------------
        # STEP 4: Resolution Clarity Check
        # ---------------------------------------------------------------------
        resolution_clarity = self._check_resolution_clarity(market_input)

        # ---------------------------------------------------------------------
        # STEP 5: Event Details
        # ---------------------------------------------------------------------
        event_details = {
            "company": validation.company_identified,
            "ticker": validation.ticker_symbol,
            "event_type": validation.event_type_identified,
            "source": validation.source_identified,
            "date": validation.date_identified,
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

        logger.info(f"Corporate analysis complete: {decision}")

        return CorporateAnalysisReport(
            market_input=market_input,
            decision=decision,
            corporate_validation_summary=validation_summary,
            blocking_reasons=blocking_reasons,
            timeline_analysis=timeline_analysis,
            resolution_clarity=resolution_clarity,
            event_details=event_details,
            analysis_version=self.VERSION,
        )

    def _analyze_timeline(
        self, market_input: CorporateMarketInput
    ) -> Dict[str, Any]:
        """
        Analyze if the timeline is feasible for resolution.

        Corporate events typically need:
        - Filing deadlines: 1-2 days after for SEC to process
        - Earnings: Same day or next day publication

        Args:
            market_input: Corporate market input

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

            if days_until < 1:
                return {
                    "is_feasible": False,
                    "reason": "Target date is today - insufficient time for verification",
                    "days_until_target": days_until,
                }

            # Corporate events typically resolve quickly
            return {
                "is_feasible": True,
                "reason": None,
                "days_until_target": days_until,
                "buffer_adequate": days_until >= 2,
            }

        except ValueError as e:
            return {
                "is_feasible": False,
                "reason": f"Invalid target date format: {e}",
                "days_until_target": None,
            }

    def _check_resolution_clarity(
        self, market_input: CorporateMarketInput
    ) -> Dict[str, Any]:
        """
        Check if the resolution criteria are clear and unambiguous.

        Args:
            market_input: Corporate market input

        Returns:
            Resolution clarity analysis
        """
        text = market_input.resolution_text.lower()

        # Check for problematic phrases
        problematic_phrases = [
            "at our discretion",
            "we may",
            "subject to",
            "may be adjusted",
            "approximately",
            "roughly",
            "around",
            "expected",
        ]

        found_issues = [p for p in problematic_phrases if p in text]

        if found_issues:
            return {
                "is_clear": False,
                "reason": f"Resolution contains ambiguous language: {', '.join(found_issues)}",
                "issues": found_issues,
            }

        return {
            "is_clear": True,
            "reason": None,
            "issues": [],
        }


# =============================================================================
# MODULE-LEVEL FUNCTION
# =============================================================================


def analyze_corporate_market(
    market_question: str,
    resolution_text: str,
    target_date: str,
    description: str = "",
    market_implied_probability: Optional[float] = None,
) -> CorporateAnalysisReport:
    """
    Convenience function to analyze a corporate event market.

    GOVERNANCE:
    This function does NOT:
    - Predict earnings outcomes
    - Use analyst estimates
    - Access insider information

    It ONLY validates structural tradeability.

    Args:
        market_question: The market's main question
        resolution_text: The resolution criteria
        target_date: Target date (YYYY-MM-DD)
        description: Additional description
        market_implied_probability: For sanity check only

    Returns:
        CorporateAnalysisReport with decision and reasoning
    """
    market_input = CorporateMarketInput(
        market_question=market_question,
        resolution_text=resolution_text,
        target_date=target_date,
        description=description,
        market_implied_probability=market_implied_probability,
    )

    analyzer = CorporateEventAnalyzer()
    return analyzer.analyze(market_input)
