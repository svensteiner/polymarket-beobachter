# =============================================================================
# POLYMARKET EU AI REGULATION ANALYZER
# Module: core/probability_estimator.py
# Purpose: Rule-based conservative probability estimation
# =============================================================================
#
# FUNDAMENTAL PRINCIPLE:
# This is NOT prediction. This is NOT forecasting. This is NOT ML.
#
# We produce CONSERVATIVE probability ranges based ONLY on:
# 1. Number of remaining formal steps
# 2. Historical EU implementation patterns
# 3. Status quo bias (default: things don't change)
#
# NO sentiment analysis. NO analyst opinions. NO news sentiment.
# NO price signals. NO momentum. NO "vibes."
#
# METHODOLOGY:
#
# 1. BASE RATE ANALYSIS
#    - What percentage of similar EU processes complete on time?
#    - Historical data from EU legislative tracking
#
# 2. STEP COUNT PENALTY
#    - Each remaining formal step reduces probability
#    - More steps = more chances for delay/failure
#
# 3. STATUS QUO BIAS
#    - Default assumption: things take longer than expected
#    - EU processes historically exceed initial timelines
#
# 4. UNCERTAINTY BANDS
#    - Never give point estimates
#    - Always give ranges (low, mid, high)
#    - Wider bands = less confidence
#
# OUTPUT:
# - Conservative probability range (0.0 to 1.0)
# - Explicit list of assumptions
# - Confidence level (LOW/MEDIUM/HIGH)
#
# =============================================================================

import logging
from typing import List, Dict, Tuple
from models.data_models import (
    MarketInput,
    ProcessStageAnalysis,
    TimeFeasibilityAnalysis,
    ProbabilityEstimate,
    EURegulationStage,
)

logger = logging.getLogger(__name__)


class ProbabilityEstimator:
    """
    Rule-based probability estimator.

    Produces conservative probability ranges for EU regulatory outcomes.

    DESIGN PRINCIPLE:
    Err on the side of caution. Wide bands. Status quo bias.
    No speculation. Only structural factors.
    """

    # =========================================================================
    # HISTORICAL BASE RATES
    # =========================================================================
    # These are approximate base rates derived from EU legislative history.
    # Used as starting points before adjustments.
    #
    # SOURCE: European Parliament legislative activity reports,
    #         EUR-Lex statistics, academic studies on EU legislative process
    #
    # NOTE: These are rough estimates. In production, would need regular
    #       updates based on actual outcome tracking.
    # =========================================================================

    # Base rate: What % of adopted regulations enter into force on schedule?
    # Answer: Very high (~95%) because EIF is legally mandated
    BASE_RATE_EIF_ON_SCHEDULE: float = 0.95

    # Base rate: What % of regulations have all provisions apply on time?
    # Answer: Lower (~70%) due to transitional periods, delegated acts delays
    BASE_RATE_FULL_APPLICATION_ON_TIME: float = 0.70

    # Base rate: What % of delegated acts are adopted on schedule?
    # Answer: Low (~50%) - Commission capacity is limited
    BASE_RATE_DELEGATED_ACTS_ON_TIME: float = 0.50

    # Base rate: What % of implementing acts are adopted on schedule?
    # Answer: Moderate (~60%) - committee procedure is more predictable
    BASE_RATE_IMPLEMENTING_ACTS_ON_TIME: float = 0.60

    # =========================================================================
    # STEP COUNT PENALTIES
    # =========================================================================
    # Each remaining step reduces probability of on-time completion.
    # Based on principle that more steps = more chances for delay.
    # =========================================================================

    PENALTY_PER_REMAINING_STEP: float = 0.05  # 5% penalty per step

    # Maximum penalty from step count (don't reduce below this factor)
    MAX_STEP_PENALTY: float = 0.40  # Cap at 40% reduction

    # =========================================================================
    # STATUS QUO BIAS FACTOR
    # =========================================================================
    # EU processes historically take longer than initially expected.
    # We apply a conservative adjustment downward.
    #
    # RATIONALE:
    # - Inter-institutional negotiations often extend timelines
    # - Translation requirements add delays
    # - Legal-linguistic revision is time-consuming
    # - Political priorities shift
    # =========================================================================

    STATUS_QUO_BIAS_FACTOR: float = 0.85  # Reduce estimates by 15%

    # =========================================================================
    # CONFIDENCE THRESHOLDS
    # =========================================================================
    # When to report LOW/MEDIUM/HIGH confidence
    # =========================================================================

    CONFIDENCE_HIGH_THRESHOLD: float = 0.15  # Range width < 15%
    CONFIDENCE_MEDIUM_THRESHOLD: float = 0.30  # Range width < 30%
    # Above 30% range width = LOW confidence

    def __init__(self):
        """Initialize the probability estimator."""
        pass

    def estimate(
        self,
        market_input: MarketInput,
        process_analysis: ProcessStageAnalysis,
        time_feasibility: TimeFeasibilityAnalysis
    ) -> ProbabilityEstimate:
        """
        Estimate probability based on structural factors only.

        PROCESS:
        1. Determine base rate based on market type
        2. Apply step count penalty
        3. Apply status quo bias
        4. Calculate uncertainty bands
        5. Document assumptions

        Args:
            market_input: The market input
            process_analysis: Process stage analysis
            time_feasibility: Time feasibility analysis

        Returns:
            ProbabilityEstimate with conservative range
        """
        # ---------------------------------------------------------------------
        # STEP 0: Handle timeline impossibility
        # ---------------------------------------------------------------------
        if time_feasibility.hard_fail:
            # Timeline is physically impossible - probability is 0
            return ProbabilityEstimate(
                probability_low=0.0,
                probability_high=0.05,  # Small band for "miracle" scenario
                probability_midpoint=0.025,
                assumptions=[
                    "Timeline is physically impossible based on minimum stage durations",
                    "Small non-zero band accounts for theoretical edge cases"
                ],
                historical_precedents=[
                    "No precedent for EU regulatory process completing faster than minimum procedural requirements"
                ],
                status_quo_bias_applied=True,
                confidence_level="HIGH",  # High confidence in LOW probability
                reasoning=(
                    "HARD FAIL: Timeline impossible. Market requires completion in "
                    f"{time_feasibility.days_until_target} days but minimum is "
                    f"{time_feasibility.minimum_days_required} days. "
                    "Probability range: 0-5% (effectively zero)."
                )
            )

        # ---------------------------------------------------------------------
        # STEP 1: Determine base rate
        # ---------------------------------------------------------------------
        base_rate, base_rate_reason = self._determine_base_rate(
            process_analysis.current_stage,
            process_analysis.stages_remaining
        )

        # ---------------------------------------------------------------------
        # STEP 2: Apply step count penalty
        # ---------------------------------------------------------------------
        step_penalty = self._calculate_step_penalty(
            process_analysis.stages_remaining
        )

        adjusted_rate = base_rate * (1.0 - step_penalty)

        # ---------------------------------------------------------------------
        # STEP 3: Apply status quo bias
        # ---------------------------------------------------------------------
        biased_rate = adjusted_rate * self.STATUS_QUO_BIAS_FACTOR

        # ---------------------------------------------------------------------
        # STEP 4: Calculate uncertainty bands
        # ---------------------------------------------------------------------
        uncertainty_width = self._calculate_uncertainty_width(
            process_analysis.stages_remaining,
            time_feasibility
        )

        probability_low = max(0.0, biased_rate - uncertainty_width / 2)
        probability_high = min(1.0, biased_rate + uncertainty_width / 2)
        probability_midpoint = (probability_low + probability_high) / 2

        # ---------------------------------------------------------------------
        # STEP 5: Document assumptions
        # ---------------------------------------------------------------------
        assumptions = self._build_assumptions(
            base_rate,
            base_rate_reason,
            step_penalty,
            process_analysis.stages_remaining,
            time_feasibility
        )

        historical_precedents = self._get_historical_precedents(
            market_input.referenced_regulation,
            process_analysis.current_stage
        )

        # ---------------------------------------------------------------------
        # STEP 6: Determine confidence level
        # ---------------------------------------------------------------------
        range_width = probability_high - probability_low
        if range_width < self.CONFIDENCE_HIGH_THRESHOLD:
            confidence_level = "HIGH"
        elif range_width < self.CONFIDENCE_MEDIUM_THRESHOLD:
            confidence_level = "MEDIUM"
        else:
            confidence_level = "LOW"

        # ---------------------------------------------------------------------
        # STEP 7: Build reasoning
        # ---------------------------------------------------------------------
        reasoning = self._build_reasoning(
            base_rate,
            step_penalty,
            biased_rate,
            probability_low,
            probability_high,
            confidence_level,
            process_analysis.stages_remaining
        )

        return ProbabilityEstimate(
            probability_low=round(probability_low, 3),
            probability_high=round(probability_high, 3),
            probability_midpoint=round(probability_midpoint, 3),
            assumptions=assumptions,
            historical_precedents=historical_precedents,
            status_quo_bias_applied=True,
            confidence_level=confidence_level,
            reasoning=reasoning
        )

    def _determine_base_rate(
        self,
        current_stage: EURegulationStage,
        remaining_stages: List[EURegulationStage]
    ) -> Tuple[float, str]:
        """
        Determine the appropriate base rate for this market type.

        Args:
            current_stage: Current stage of the regulation
            remaining_stages: Remaining stages to complete

        Returns:
            Tuple of (base_rate, reason_string)
        """
        remaining_set = set(remaining_stages)

        # If already in application phase
        if current_stage in {
            EURegulationStage.APPLICATION_DATE,
            EURegulationStage.TRANSITIONAL_PERIOD,
            EURegulationStage.FULLY_APPLICABLE
        }:
            return (
                0.90,
                "Regulation already in application phase - high certainty"
            )

        # If entry into force is the main remaining milestone
        if (
            EURegulationStage.ENTERED_INTO_FORCE in remaining_set and
            len(remaining_set) <= 3
        ):
            return (
                self.BASE_RATE_EIF_ON_SCHEDULE,
                f"Entry into force on schedule base rate: {self.BASE_RATE_EIF_ON_SCHEDULE}"
            )

        # If delegated acts are pending
        if EURegulationStage.DELEGATED_ACTS_PENDING in remaining_set:
            return (
                self.BASE_RATE_DELEGATED_ACTS_ON_TIME,
                f"Delegated acts on time base rate: {self.BASE_RATE_DELEGATED_ACTS_ON_TIME}"
            )

        # If implementing acts are pending
        if EURegulationStage.IMPLEMENTING_ACTS_PENDING in remaining_set:
            return (
                self.BASE_RATE_IMPLEMENTING_ACTS_ON_TIME,
                f"Implementing acts on time base rate: {self.BASE_RATE_IMPLEMENTING_ACTS_ON_TIME}"
            )

        # General case - full application target
        return (
            self.BASE_RATE_FULL_APPLICATION_ON_TIME,
            f"Full application on time base rate: {self.BASE_RATE_FULL_APPLICATION_ON_TIME}"
        )

    def _calculate_step_penalty(
        self,
        remaining_stages: List[EURegulationStage]
    ) -> float:
        """
        Calculate penalty based on number of remaining steps.

        More steps = higher penalty (more chances for delay).

        Args:
            remaining_stages: List of remaining stages

        Returns:
            Penalty factor (0.0 to MAX_STEP_PENALTY)
        """
        num_steps = len(remaining_stages)
        raw_penalty = num_steps * self.PENALTY_PER_REMAINING_STEP
        return min(raw_penalty, self.MAX_STEP_PENALTY)

    def _calculate_uncertainty_width(
        self,
        remaining_stages: List[EURegulationStage],
        time_feasibility: TimeFeasibilityAnalysis
    ) -> float:
        """
        Calculate width of uncertainty band.

        More remaining stages and tighter timelines = wider bands.

        Args:
            remaining_stages: List of remaining stages
            time_feasibility: Time feasibility analysis

        Returns:
            Width of uncertainty band (0.0 to 1.0)
        """
        # Base uncertainty from stage count
        stage_uncertainty = len(remaining_stages) * 0.03

        # Additional uncertainty from timeline pressure
        # SAFETY: Protect against division by zero and invalid data
        min_days = time_feasibility.minimum_days_required
        days_until = time_feasibility.days_until_target

        if min_days is None or min_days <= 0:
            # Invalid minimum_days - log warning and use high uncertainty
            logger.warning(f"Invalid minimum_days_required: {min_days}, using max uncertainty")
            time_buffer_ratio = 0.5  # Assume very tight timeline
        elif days_until is None or days_until < 0:
            # Invalid days_until_target - log warning and use high uncertainty
            logger.warning(f"Invalid days_until_target: {days_until}, using max uncertainty")
            time_buffer_ratio = 0.5  # Assume very tight timeline
        else:
            time_buffer_ratio = days_until / min_days

        if time_buffer_ratio < 1.5:
            # Very tight timeline - high uncertainty
            time_uncertainty = 0.20
        elif time_buffer_ratio < 2.0:
            # Moderate timeline
            time_uncertainty = 0.10
        else:
            # Comfortable timeline
            time_uncertainty = 0.05

        # Institutional constraints add uncertainty
        constraint_uncertainty = len(time_feasibility.institutional_constraints) * 0.03

        total_uncertainty = stage_uncertainty + time_uncertainty + constraint_uncertainty

        # Cap at reasonable maximum
        return min(total_uncertainty, 0.50)

    def _build_assumptions(
        self,
        base_rate: float,
        base_rate_reason: str,
        step_penalty: float,
        remaining_stages: List[EURegulationStage],
        time_feasibility: TimeFeasibilityAnalysis
    ) -> List[str]:
        """
        Build explicit list of assumptions made in estimation.

        Args:
            base_rate: The base rate used
            base_rate_reason: Why that base rate was chosen
            step_penalty: The step penalty applied
            remaining_stages: List of remaining stages
            time_feasibility: Time feasibility analysis

        Returns:
            List of assumption strings
        """
        assumptions = [
            f"Base rate: {base_rate:.0%} ({base_rate_reason})",
            f"Step penalty: {step_penalty:.0%} for {len(remaining_stages)} remaining stages",
            f"Status quo bias: {self.STATUS_QUO_BIAS_FACTOR:.0%} multiplier applied",
            "No external political shocks assumed",
            "Normal institutional capacity assumed",
            "No Member State implementation challenges assumed",
        ]

        if time_feasibility.institutional_constraints:
            assumptions.append(
                f"Institutional constraints factored: {len(time_feasibility.institutional_constraints)}"
            )

        return assumptions

    def _get_historical_precedents(
        self,
        regulation_name: str,
        current_stage: EURegulationStage
    ) -> List[str]:
        """
        Get relevant historical precedents.

        Args:
            regulation_name: Name of the regulation
            current_stage: Current stage

        Returns:
            List of historical precedent descriptions
        """
        # Hardcoded historical data
        # In production, this would be a database lookup

        precedents = []

        # General EU legislative history
        precedents.append(
            "Average EU regulation takes 18-24 months from proposal to adoption (EUR-Lex statistics)"
        )

        # Specific to major digital regulations
        if "ai" in regulation_name.lower():
            precedents.append(
                "GDPR: 4 years from proposal to entry into force (2012-2016), "
                "2 additional years to application (2018)"
            )
            precedents.append(
                "Digital Services Act: 2 years from proposal to adoption (2020-2022)"
            )
            precedents.append(
                "Digital Markets Act: 2 years from proposal to adoption (2020-2022)"
            )

        # Stage-specific precedents
        if current_stage == EURegulationStage.TRANSITIONAL_PERIOD:
            precedents.append(
                "Most major EU regulations use 24-month transitional period for main provisions"
            )

        return precedents

    def _build_reasoning(
        self,
        base_rate: float,
        step_penalty: float,
        biased_rate: float,
        probability_low: float,
        probability_high: float,
        confidence_level: str,
        remaining_stages: List[EURegulationStage]
    ) -> str:
        """
        Build human-readable reasoning for the estimate.

        Args:
            base_rate: Starting base rate
            step_penalty: Penalty applied for remaining steps
            biased_rate: Rate after status quo bias
            probability_low: Lower bound of range
            probability_high: Upper bound of range
            confidence_level: Confidence level
            remaining_stages: Remaining stages

        Returns:
            Reasoning string
        """
        parts = []

        parts.append(
            f"Starting base rate: {base_rate:.0%}."
        )

        parts.append(
            f"Applied {step_penalty:.0%} step penalty for {len(remaining_stages)} remaining stages."
        )

        parts.append(
            f"Applied {self.STATUS_QUO_BIAS_FACTOR:.0%} status quo bias factor → {biased_rate:.0%}."
        )

        parts.append(
            f"Uncertainty band: {probability_low:.0%} to {probability_high:.0%} "
            f"(midpoint: {(probability_low + probability_high) / 2:.0%})."
        )

        parts.append(
            f"Confidence level: {confidence_level} "
            f"(based on {probability_high - probability_low:.0%} range width)."
        )

        return " ".join(parts)
