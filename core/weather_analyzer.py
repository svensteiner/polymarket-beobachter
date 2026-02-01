# =============================================================================
# POLYMARKET BEOBACHTER - WEATHER EVENT ANALYZER
# =============================================================================
#
# GOVERNANCE INTENT:
# This module provides a complete analysis pipeline for WEATHER_EVENT markets.
# It validates structural tradeability WITHOUT forecasting.
#
# CORE PRINCIPLE:
# We evaluate whether a weather market is STRUCTURALLY TRADEABLE.
# We do NOT predict weather outcomes.
#
# PIPELINE:
# 1. Weather validation (6-point checklist)
# 2. If validation fails → INSUFFICIENT_DATA (immediate return)
# 3. If validation passes → standard analysis (timeline, resolution clarity)
#
# =============================================================================

import logging
from dataclasses import dataclass, field
from datetime import datetime, date
from typing import Optional, Dict, Any, List

from .weather_validation import (
    WeatherValidator,
    WeatherValidationChecklist,
    validate_weather_market,
    is_weather_market,
)

logger = logging.getLogger(__name__)


# =============================================================================
# DATA MODELS
# =============================================================================


@dataclass
class WeatherMarketInput:
    """
    Input data for weather market analysis.

    GOVERNANCE:
    - No weather forecasts
    - No probability estimates from external sources
    - Only structural/resolution information
    """
    market_question: str
    resolution_text: str
    target_date: str  # YYYY-MM-DD
    description: str = ""

    # Optional: market-implied probability (for sanity check ONLY)
    # Does NOT influence decision logic
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
class WeatherAnalysisReport:
    """
    Complete analysis report for a weather market.

    GOVERNANCE:
    - decision: TRADE / NO_TRADE / INSUFFICIENT_DATA
    - If weather_validation fails → decision = INSUFFICIENT_DATA
    - weather_validation_summary shows exactly which criteria failed
    """
    # Input (for audit trail)
    market_input: WeatherMarketInput

    # Decision outcome
    decision: str  # "TRADE" / "NO_TRADE" / "INSUFFICIENT_DATA"

    # Weather-specific validation
    weather_validation_summary: Dict[str, Any]

    # Blocking reasons (explicit list)
    blocking_reasons: List[str]

    # Additional analysis (only if validation passed)
    timeline_analysis: Optional[Dict[str, Any]] = None
    resolution_clarity: Optional[Dict[str, Any]] = None

    # Metadata
    analysis_version: str = "1.0.0"
    generated_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "decision": self.decision,
            "weather_validation_summary": self.weather_validation_summary,
            "blocking_reasons": self.blocking_reasons,
            "timeline_analysis": self.timeline_analysis,
            "resolution_clarity": self.resolution_clarity,
            "analysis_version": self.analysis_version,
            "generated_at": self.generated_at,
            "market_question": self.market_input.market_question,
        }


# =============================================================================
# WEATHER ANALYZER
# =============================================================================


class WeatherEventAnalyzer:
    """
    Analyzer for WEATHER_EVENT markets.

    STRICT PRINCIPLES:
    - NO forecasts
    - NO weather APIs
    - NO probability estimation from models
    - ONLY structural validation

    If the 6-point checklist fails, output is INSUFFICIENT_DATA.
    This is expected and correct.
    """

    VERSION = "1.0.0"

    def __init__(self):
        """Initialize the weather analyzer."""
        self.weather_validator = WeatherValidator()

    def analyze(self, market_input: WeatherMarketInput) -> WeatherAnalysisReport:
        """
        Analyze a weather market for structural tradeability.

        PIPELINE:
        1. Run 6-point weather validation checklist
        2. If ANY fails → INSUFFICIENT_DATA (stop here)
        3. If ALL pass → check timeline feasibility
        4. Return decision with full audit trail

        Args:
            market_input: Weather market to analyze

        Returns:
            WeatherAnalysisReport with decision and reasoning
        """
        logger.info(f"Analyzing weather market: {market_input.market_question[:50]}...")

        # ---------------------------------------------------------------------
        # STEP 1: Weather Validation Checklist (MANDATORY)
        # ---------------------------------------------------------------------
        validation = self.weather_validator.validate(
            market_question=market_input.market_question,
            resolution_text=market_input.resolution_text,
            description=market_input.description,
        )

        # Build validation summary
        validation_summary = validation.to_dict()

        # ---------------------------------------------------------------------
        # STEP 2: Check if validation passed
        # ---------------------------------------------------------------------
        if not validation.is_valid:
            logger.info(
                f"Weather validation FAILED: {len(validation.blocking_reasons)} issues"
            )
            return WeatherAnalysisReport(
                market_input=market_input,
                decision="INSUFFICIENT_DATA",
                weather_validation_summary=validation_summary,
                blocking_reasons=list(validation.blocking_reasons),
                timeline_analysis=None,
                resolution_clarity=None,
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
        # STEP 5: Final Decision
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

        logger.info(f"Weather analysis complete: {decision}")

        return WeatherAnalysisReport(
            market_input=market_input,
            decision=decision,
            weather_validation_summary=validation_summary,
            blocking_reasons=blocking_reasons,
            timeline_analysis=timeline_analysis,
            resolution_clarity=resolution_clarity,
            analysis_version=self.VERSION,
        )

    def _analyze_timeline(
        self, market_input: WeatherMarketInput
    ) -> Dict[str, Any]:
        """
        Analyze if the timeline is feasible for resolution.

        Checks:
        - Target date is in the future
        - Sufficient time for data publication

        Args:
            market_input: Weather market input

        Returns:
            Timeline analysis dictionary
        """
        try:
            target = date.fromisoformat(market_input.target_date)
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
                    "reason": "Target date is today - insufficient time for resolution",
                    "days_until_target": days_until,
                }

            return {
                "is_feasible": True,
                "reason": None,
                "days_until_target": days_until,
            }

        except ValueError as e:
            return {
                "is_feasible": False,
                "reason": f"Invalid target date format: {e}",
                "days_until_target": None,
            }

    def _check_resolution_clarity(
        self, market_input: WeatherMarketInput
    ) -> Dict[str, Any]:
        """
        Check if the resolution criteria are clear and unambiguous.

        This is a simplified check - the main validation is in WeatherValidator.

        Args:
            market_input: Weather market input

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


def analyze_weather_market(
    market_question: str,
    resolution_text: str,
    target_date: str,
    description: str = "",
    market_implied_probability: Optional[float] = None,
) -> WeatherAnalysisReport:
    """
    Convenience function to analyze a weather market.

    GOVERNANCE:
    This function does NOT:
    - Use weather forecasts
    - Call weather APIs
    - Estimate probabilities from models

    It ONLY validates structural tradeability.

    Args:
        market_question: The market's main question
        resolution_text: The resolution criteria
        target_date: Target date (YYYY-MM-DD)
        description: Additional description
        market_implied_probability: For sanity check only (does not influence decision)

    Returns:
        WeatherAnalysisReport with decision and reasoning
    """
    market_input = WeatherMarketInput(
        market_question=market_question,
        resolution_text=resolution_text,
        target_date=target_date,
        description=description,
        market_implied_probability=market_implied_probability,
    )

    analyzer = WeatherEventAnalyzer()
    return analyzer.analyze(market_input)
