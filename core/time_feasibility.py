# =============================================================================
# POLYMARKET EU AI REGULATION ANALYZER
# Module: core/time_feasibility.py
# Purpose: Check if market timeline is realistic given EU procedural constraints
# =============================================================================
#
# REGULATORY BACKGROUND:
# EU regulatory processes have MINIMUM durations that cannot be bypassed.
# These are procedural requirements, not just typical delays.
#
# MANDATORY WAITING PERIODS:
#
# 1. Official Journal Publication
#    - Regulation MUST be published in OJ before entering into force
#    - No specific minimum delay, but typically 1-4 weeks after signing
#
# 2. Entry Into Force
#    - Default: 20 days after OJ publication (Article 297 TFEU)
#    - Can be specified differently in the act itself
#
# 3. Application Date
#    - Often later than entry into force
#    - Allows time for implementation, guidance, etc.
#    - EU AI Act: 2 years after entry into force for most provisions
#
# 4. Transitional Periods
#    - Specific provisions may have delayed application
#    - Typically 6, 12, 24, or 36 months after entry into force
#
# INSTITUTIONAL CONSTRAINTS:
#
# 1. Parliament/Council Sessions
#    - Not in permanent session
#    - Summer recess (August)
#    - Christmas recess (late December)
#
# 2. Commission Capacity
#    - Delegated acts require Commission resources
#    - Implementing acts require committee procedures
#
# This module checks if the market's timeline is physically achievable.
#
# =============================================================================

from datetime import date, timedelta
from typing import List, Dict, Tuple
from models.data_models import (
    MarketInput,
    ProcessStageAnalysis,
    TimeFeasibilityAnalysis,
    EURegulationStage,
)


class TimeFeasibilityChecker:
    """
    Checks if a market's timeline is realistically achievable.

    Compares market target date against minimum required durations.

    DESIGN PRINCIPLE:
    If the market requires something faster than physically possible,
    this is a HARD FAIL - no trade.
    """

    # =========================================================================
    # MINIMUM STAGE DURATIONS (in days)
    # =========================================================================
    # These are ABSOLUTE MINIMUMS. Real-world usually takes longer.
    # Used to determine if a timeline is IMPOSSIBLE (not just unlikely).
    #
    # Source: Historical EU legislative procedures, Treaty provisions
    #
    # NOTES:
    # - EP First Reading: Minimum 1 month for committee + plenary
    # - Council First Reading: Minimum 1 month for COREPER + Council
    # - Conciliation: Maximum 8 weeks (can be extended by 2 weeks)
    # - OJ Publication: Typically 1-4 weeks after signing
    # - Entry into force: Usually 20 days after OJ publication
    # =========================================================================

    MINIMUM_STAGE_DURATIONS: Dict[EURegulationStage, int] = {
        EURegulationStage.PROPOSAL: 0,  # Starting point
        EURegulationStage.FIRST_READING_EP: 30,  # Minimum 1 month
        EURegulationStage.FIRST_READING_COUNCIL: 30,  # Minimum 1 month
        EURegulationStage.SECOND_READING_EP: 90,  # 3 months (Treaty limit: 4 months)
        EURegulationStage.SECOND_READING_COUNCIL: 90,  # 3 months (Treaty limit: 4 months)
        EURegulationStage.CONCILIATION: 60,  # 6-8 weeks typical
        EURegulationStage.ADOPTED: 1,  # Signing ceremony
        EURegulationStage.PUBLISHED_OJ: 14,  # 2 weeks typical
        EURegulationStage.ENTERED_INTO_FORCE: 20,  # Default under TFEU
        EURegulationStage.APPLICATION_DATE: 0,  # Varies by regulation
        EURegulationStage.TRANSITIONAL_PERIOD: 0,  # Varies
        EURegulationStage.DELEGATED_ACTS_PENDING: 90,  # 3 months minimum
        EURegulationStage.IMPLEMENTING_ACTS_PENDING: 60,  # 2 months minimum
        EURegulationStage.FULLY_APPLICABLE: 0,  # End state
    }

    # =========================================================================
    # MANDATORY WAITING PERIODS
    # =========================================================================
    # These are non-negotiable procedural requirements.
    # =========================================================================

    MANDATORY_WAITING_PERIODS: List[Tuple[str, int, str]] = [
        (
            "OJ_to_EIF",
            20,
            "Minimum 20 days from Official Journal publication to entry into force (Article 297 TFEU default)"
        ),
        (
            "Signing_to_OJ",
            7,
            "Minimum 1 week from signing to OJ publication (translation, formatting)"
        ),
        (
            "Council_to_Signing",
            7,
            "Minimum 1 week from Council adoption to formal signing ceremony"
        ),
    ]

    # =========================================================================
    # INSTITUTIONAL RECESS PERIODS (2024-2027)
    # =========================================================================
    # Parliament and Council have limited capacity during recesses.
    # These are approximate dates.
    # =========================================================================

    RECESS_PERIODS: List[Tuple[date, date, str]] = [
        (date(2024, 7, 20), date(2024, 9, 1), "Summer 2024"),
        (date(2024, 12, 20), date(2025, 1, 10), "Winter 2024/2025"),
        (date(2025, 7, 20), date(2025, 9, 1), "Summer 2025"),
        (date(2025, 12, 20), date(2026, 1, 10), "Winter 2025/2026"),
        (date(2026, 7, 20), date(2026, 9, 1), "Summer 2026"),
        (date(2026, 12, 20), date(2027, 1, 10), "Winter 2026/2027"),
    ]

    def __init__(self):
        """Initialize the feasibility checker."""
        pass

    def analyze(
        self,
        market_input: MarketInput,
        process_analysis: ProcessStageAnalysis
    ) -> TimeFeasibilityAnalysis:
        """
        Analyze if the market timeline is feasible.

        PROCESS:
        1. Calculate days until target
        2. Calculate minimum days required for remaining stages
        3. Account for mandatory waiting periods
        4. Check institutional constraints
        5. Determine if timeline is feasible

        Args:
            market_input: The market input
            process_analysis: Process stage analysis from EUProcessModel

        Returns:
            TimeFeasibilityAnalysis
        """
        analysis_date = market_input.analysis_date
        target_date = market_input.target_date

        # ---------------------------------------------------------------------
        # STEP 1: Calculate days until target
        # ---------------------------------------------------------------------
        days_until_target = (target_date - analysis_date).days

        # ---------------------------------------------------------------------
        # STEP 1a: Handle past target dates (early exit)
        # ---------------------------------------------------------------------
        # If target date is in the past, this is a special case that should
        # be flagged clearly. The market may have already resolved.
        if days_until_target < 0:
            return TimeFeasibilityAnalysis(
                days_until_target=days_until_target,
                minimum_days_required=0,
                is_timeline_feasible=False,
                mandatory_waiting_periods=[],
                institutional_constraints=[
                    f"Target date {target_date} is {-days_until_target} days in the past"
                ],
                hard_fail=True,
                reasoning=(
                    f"INVALID TIMELINE: Target date {target_date} is "
                    f"{-days_until_target} days in the past (analysis date: {analysis_date}). "
                    "The market may have already resolved. Cannot analyze future feasibility "
                    "for a past target date. HARD FAIL - NO TRADE."
                )
            )

        # ---------------------------------------------------------------------
        # STEP 2: Calculate minimum days required
        # ---------------------------------------------------------------------
        minimum_days = self._calculate_minimum_days(
            process_analysis.stages_remaining
        )

        # ---------------------------------------------------------------------
        # STEP 3: Identify applicable mandatory waiting periods
        # ---------------------------------------------------------------------
        mandatory_periods = self._get_applicable_waiting_periods(
            process_analysis.stages_remaining
        )

        # ---------------------------------------------------------------------
        # STEP 4: Identify institutional constraints
        # ---------------------------------------------------------------------
        institutional_constraints = self._identify_institutional_constraints(
            analysis_date,
            target_date,
            process_analysis.stages_remaining
        )

        # ---------------------------------------------------------------------
        # STEP 5: Adjust minimum days for constraints
        # ---------------------------------------------------------------------
        recess_days = self._calculate_recess_impact(analysis_date, target_date)
        adjusted_minimum = minimum_days + recess_days

        # ---------------------------------------------------------------------
        # STEP 6: Determine feasibility
        # ---------------------------------------------------------------------
        # Timeline is feasible if we have enough days
        is_feasible = days_until_target >= adjusted_minimum

        # Hard fail if timeline is physically impossible
        # (even with best-case scenario, not enough time)
        hard_fail = days_until_target < minimum_days

        # ---------------------------------------------------------------------
        # STEP 7: Build reasoning
        # ---------------------------------------------------------------------
        reasoning = self._build_reasoning(
            days_until_target,
            minimum_days,
            adjusted_minimum,
            is_feasible,
            hard_fail,
            process_analysis.stages_remaining,
            mandatory_periods,
            institutional_constraints
        )

        return TimeFeasibilityAnalysis(
            days_until_target=days_until_target,
            minimum_days_required=adjusted_minimum,
            is_timeline_feasible=is_feasible,
            mandatory_waiting_periods=[p[2] for p in mandatory_periods],
            institutional_constraints=institutional_constraints,
            hard_fail=hard_fail,
            reasoning=reasoning
        )

    def _calculate_minimum_days(
        self,
        remaining_stages: List[EURegulationStage]
    ) -> int:
        """
        Calculate minimum days required for remaining stages.

        Sums the minimum duration for each remaining stage.

        Args:
            remaining_stages: List of stages still to complete

        Returns:
            Total minimum days required

        Raises:
            ValueError: If a stage is not defined in MINIMUM_STAGE_DURATIONS
        """
        total_days = 0
        for stage in remaining_stages:
            if stage not in self.MINIMUM_STAGE_DURATIONS:
                # Fail explicitly for unknown stages rather than silently using 0
                raise ValueError(
                    f"Unknown stage '{stage.value}' - add to MINIMUM_STAGE_DURATIONS. "
                    f"This indicates a configuration error that must be fixed."
                )
            total_days += self.MINIMUM_STAGE_DURATIONS[stage]
        return total_days

    def _get_applicable_waiting_periods(
        self,
        remaining_stages: List[EURegulationStage]
    ) -> List[Tuple[str, int, str]]:
        """
        Get mandatory waiting periods that apply to remaining stages.

        Args:
            remaining_stages: List of stages still to complete

        Returns:
            List of applicable waiting periods
        """
        applicable = []

        # Check which waiting periods apply
        stage_set = set(remaining_stages)

        if EURegulationStage.ENTERED_INTO_FORCE in stage_set:
            applicable.append(self.MANDATORY_WAITING_PERIODS[0])  # OJ_to_EIF

        if EURegulationStage.PUBLISHED_OJ in stage_set:
            applicable.append(self.MANDATORY_WAITING_PERIODS[1])  # Signing_to_OJ

        if EURegulationStage.ADOPTED in stage_set:
            applicable.append(self.MANDATORY_WAITING_PERIODS[2])  # Council_to_Signing

        return applicable

    def _identify_institutional_constraints(
        self,
        analysis_date: date,
        target_date: date,
        remaining_stages: List[EURegulationStage]
    ) -> List[str]:
        """
        Identify institutional constraints affecting timeline.

        Args:
            analysis_date: Date of analysis
            target_date: Market target date
            remaining_stages: List of stages still to complete

        Returns:
            List of identified constraints
        """
        constraints = []

        # Check if timeline spans a recess period
        for start, end, name in self.RECESS_PERIODS:
            if analysis_date <= start <= target_date:
                # Recess falls within our timeline
                # Check if legislative stages remain
                legislative_stages = {
                    EURegulationStage.FIRST_READING_EP,
                    EURegulationStage.FIRST_READING_COUNCIL,
                    EURegulationStage.SECOND_READING_EP,
                    EURegulationStage.SECOND_READING_COUNCIL,
                    EURegulationStage.CONCILIATION,
                }

                if legislative_stages.intersection(set(remaining_stages)):
                    constraints.append(
                        f"Institutional recess ({name}) falls within timeline - "
                        f"legislative progress unlikely during {start} to {end}"
                    )

        # Check for very short timelines
        days = (target_date - analysis_date).days
        if days < 30 and len(remaining_stages) > 2:
            constraints.append(
                f"Very short timeline ({days} days) for {len(remaining_stages)} "
                "remaining stages - institutional capacity constraint"
            )

        # Check for commission capacity if delegated/implementing acts pending
        if EURegulationStage.DELEGATED_ACTS_PENDING in remaining_stages:
            constraints.append(
                "Delegated acts pending - requires Commission drafting and "
                "Parliament/Council scrutiny period"
            )

        if EURegulationStage.IMPLEMENTING_ACTS_PENDING in remaining_stages:
            constraints.append(
                "Implementing acts pending - requires committee procedure"
            )

        return constraints

    def _calculate_recess_impact(
        self,
        analysis_date: date,
        target_date: date
    ) -> int:
        """
        Calculate additional days to account for recess periods.

        During recess, legislative work effectively pauses.
        We add the recess duration to minimum timeline.

        Args:
            analysis_date: Date of analysis
            target_date: Market target date

        Returns:
            Additional days to add due to recesses
        """
        additional_days = 0

        for start, end, _ in self.RECESS_PERIODS:
            # Check if recess overlaps with our timeline
            if analysis_date <= end and target_date >= start:
                # Calculate overlap
                overlap_start = max(analysis_date, start)
                overlap_end = min(target_date, end)
                overlap_days = (overlap_end - overlap_start).days

                if overlap_days > 0:
                    additional_days += overlap_days

        return additional_days

    def _build_reasoning(
        self,
        days_until_target: int,
        minimum_days: int,
        adjusted_minimum: int,
        is_feasible: bool,
        hard_fail: bool,
        remaining_stages: List[EURegulationStage],
        mandatory_periods: List[Tuple[str, int, str]],
        institutional_constraints: List[str]
    ) -> str:
        """
        Build human-readable reasoning for the analysis.

        Args:
            days_until_target: Days until market target
            minimum_days: Base minimum days required
            adjusted_minimum: Adjusted minimum including constraints
            is_feasible: Whether timeline is feasible
            hard_fail: Whether timeline is impossible
            remaining_stages: List of remaining stages
            mandatory_periods: Applicable waiting periods
            institutional_constraints: Identified constraints

        Returns:
            Reasoning string
        """
        parts = []

        parts.append(f"Days until target: {days_until_target}.")
        parts.append(
            f"Remaining stages: {len(remaining_stages)} "
            f"({', '.join(s.value for s in remaining_stages[:3])}"
            f"{'+' + str(len(remaining_stages) - 3) + ' more' if len(remaining_stages) > 3 else ''})."
        )

        parts.append(
            f"Minimum days required (base): {minimum_days}. "
            f"Adjusted for constraints: {adjusted_minimum}."
        )

        if mandatory_periods:
            parts.append(
                f"Mandatory waiting periods apply: {len(mandatory_periods)}."
            )

        if institutional_constraints:
            parts.append(
                f"Institutional constraints identified: {len(institutional_constraints)}."
            )

        if hard_fail:
            parts.append(
                "HARD FAIL: Timeline is physically impossible. "
                f"Market requires {days_until_target} days but minimum is {minimum_days}. "
                "NO TRADE."
            )
        elif not is_feasible:
            parts.append(
                f"Timeline is NOT feasible when accounting for constraints. "
                f"Available: {days_until_target} days, Required: {adjusted_minimum} days."
            )
        else:
            parts.append(
                "Timeline is feasible (sufficient time available for remaining steps)."
            )

        return " ".join(parts)
