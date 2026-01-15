# =============================================================================
# POLYMARKET EU AI REGULATION ANALYZER
# Module: core/process_model.py
# Purpose: Model the EU regulatory lifecycle and determine current stage
# =============================================================================
#
# REGULATORY BACKGROUND:
# EU legislation follows the Ordinary Legislative Procedure (OLP) under
# Article 294 TFEU. The lifecycle involves:
#
# 1. LEGISLATIVE PHASE:
#    - Commission proposal
#    - European Parliament first reading
#    - Council first reading
#    - Possible second readings and conciliation
#
# 2. POST-ADOPTION PHASE:
#    - Adoption by co-legislators
#    - Publication in Official Journal (OJ)
#    - Entry into force (usually 20 days after OJ publication)
#    - Application date (may be later than entry into force)
#    - Transitional periods for specific provisions
#    - Delegated acts adoption
#    - Implementing acts adoption
#
# THE EU AI ACT (Regulation 2024/1689) EXAMPLE:
# - Adopted: June 2024
# - Published in OJ: July 12, 2024
# - Entry into force: August 1, 2024
# - Full application: August 2, 2026 (with various transitional dates)
#
# This module encodes these stages and their relationships.
#
# =============================================================================

from datetime import date
from typing import Any, Dict, List, Optional
from ..models.data_models import (
    MarketInput,
    ProcessStageAnalysis,
    EURegulationStage,
)


class EUProcessModel:
    """
    Models the EU regulatory lifecycle.

    Determines the current stage of a regulation and remaining steps.

    DESIGN NOTES:
    - Hardcoded knowledge about specific regulations (EU AI Act)
    - Extensible structure for adding new regulations
    - Deterministic stage identification
    """

    # =========================================================================
    # EU AI ACT TIMELINE (Regulation 2024/1689)
    # =========================================================================
    # These dates are from the official EU record.
    # Source: EUR-Lex, Official Journal of the European Union
    #
    # KEY DATES:
    # - Commission proposal: April 21, 2021
    # - European Parliament vote: March 13, 2024
    # - Council adoption: May 21, 2024
    # - Signed: June 13, 2024
    # - Published in OJ: July 12, 2024 (L 2024/1689)
    # - Entry into force: August 1, 2024
    # - Prohibited AI practices: February 2, 2025
    # - GPAI rules: August 2, 2025
    # - Full application: August 2, 2026
    # =========================================================================

    EU_AI_ACT_DATES: Dict[str, date] = {
        "proposal": date(2021, 4, 21),
        "ep_first_reading": date(2024, 3, 13),
        "council_adoption": date(2024, 5, 21),
        "signed": date(2024, 6, 13),
        "published_oj": date(2024, 7, 12),
        "entry_into_force": date(2024, 8, 1),
        "prohibited_practices_apply": date(2025, 2, 2),
        "gpai_rules_apply": date(2025, 8, 2),
        "full_application": date(2026, 8, 2),
    }

    # =========================================================================
    # EU AI ACT TRANSITIONAL PERIODS
    # =========================================================================
    # The EU AI Act has multiple phased application dates.
    #
    # Article 113 (Entry into force and application):
    # - 6 months: Prohibited practices (Art. 5)
    # - 12 months: GPAI rules, governance, penalties
    # - 24 months: Full application (with exceptions)
    # - 36 months: High-risk AI for Annex I products
    # =========================================================================

    EU_AI_ACT_PHASES: Dict[str, Dict[str, Any]] = {
        "prohibited_practices": {
            "application_date": date(2025, 2, 2),
            "description": "Prohibited AI practices (Article 5)",
            "months_after_eif": 6,
        },
        "gpai_obligations": {
            "application_date": date(2025, 8, 2),
            "description": "General-purpose AI rules, governance, penalties",
            "months_after_eif": 12,
        },
        "main_obligations": {
            "application_date": date(2026, 8, 2),
            "description": "Full application of high-risk AI rules",
            "months_after_eif": 24,
        },
        "annex_i_products": {
            "application_date": date(2027, 8, 2),
            "description": "High-risk AI for Annex I product legislation",
            "months_after_eif": 36,
        },
    }

    # =========================================================================
    # STAGE SEQUENCE (Ordered)
    # =========================================================================
    # The natural progression of EU regulatory stages.
    # =========================================================================

    STAGE_SEQUENCE: List[EURegulationStage] = [
        EURegulationStage.PROPOSAL,
        EURegulationStage.FIRST_READING_EP,
        EURegulationStage.FIRST_READING_COUNCIL,
        EURegulationStage.SECOND_READING_EP,
        EURegulationStage.SECOND_READING_COUNCIL,
        EURegulationStage.CONCILIATION,
        EURegulationStage.ADOPTED,
        EURegulationStage.PUBLISHED_OJ,
        EURegulationStage.ENTERED_INTO_FORCE,
        EURegulationStage.APPLICATION_DATE,
        EURegulationStage.TRANSITIONAL_PERIOD,
        EURegulationStage.DELEGATED_ACTS_PENDING,
        EURegulationStage.IMPLEMENTING_ACTS_PENDING,
        EURegulationStage.FULLY_APPLICABLE,
    ]

    def __init__(self):
        """
        Initialize the EU Process Model.

        Loads known regulation data for deterministic analysis.
        """
        # Registry of known regulations and their data
        self._regulation_registry: Dict[str, Dict] = {
            "EU AI Act": {
                "official_name": "Regulation (EU) 2024/1689",
                "short_name": "EU AI Act",
                "celex": "32024R1689",
                "dates": self.EU_AI_ACT_DATES,
                "phases": self.EU_AI_ACT_PHASES,
            }
        }

    def analyze(self, market_input: MarketInput) -> ProcessStageAnalysis:
        """
        Analyze the process stage for a given market.

        PROCESS:
        1. Identify the referenced regulation
        2. Look up known dates and stages
        3. Determine current stage based on analysis date
        4. Identify remaining stages
        5. Flag any blocking factors

        Args:
            market_input: The market to analyze

        Returns:
            ProcessStageAnalysis with stage information
        """
        regulation_name = market_input.referenced_regulation
        analysis_date = market_input.analysis_date

        # ---------------------------------------------------------------------
        # STEP 1: Look up regulation in registry
        # ---------------------------------------------------------------------
        regulation_data = self._find_regulation(regulation_name)

        if regulation_data is None:
            # Unknown regulation - return conservative analysis
            return self._unknown_regulation_analysis(market_input)

        # ---------------------------------------------------------------------
        # STEP 2: Determine current stage based on dates
        # ---------------------------------------------------------------------
        known_dates = regulation_data["dates"]
        current_stage = self._determine_current_stage(analysis_date, known_dates)

        # ---------------------------------------------------------------------
        # STEP 3: Determine completed and remaining stages
        # ---------------------------------------------------------------------
        stages_completed = self._get_completed_stages(current_stage)
        stages_remaining = self._get_remaining_stages(current_stage)

        # ---------------------------------------------------------------------
        # STEP 4: Identify blocking factors
        # ---------------------------------------------------------------------
        blocking_factors = self._identify_blocking_factors(
            regulation_data, analysis_date, market_input.target_date
        )

        # ---------------------------------------------------------------------
        # STEP 5: Build key dates dictionary
        # ---------------------------------------------------------------------
        key_dates = {
            k: v for k, v in known_dates.items()
        }

        # ---------------------------------------------------------------------
        # STEP 6: Build reasoning
        # ---------------------------------------------------------------------
        reasoning = self._build_reasoning(
            regulation_data,
            current_stage,
            analysis_date,
            stages_remaining,
            blocking_factors
        )

        return ProcessStageAnalysis(
            current_stage=current_stage,
            stages_completed=stages_completed,
            stages_remaining=stages_remaining,
            key_dates=key_dates,
            blocking_factors=blocking_factors,
            reasoning=reasoning
        )

    def _find_regulation(self, regulation_name: str) -> Optional[Dict]:
        """
        Find a regulation in the registry by name.

        Performs fuzzy matching on known names.

        Args:
            regulation_name: Name to search for

        Returns:
            Regulation data dict or None if not found
        """
        name_lower = regulation_name.lower()

        # Direct match
        for key, data in self._regulation_registry.items():
            if key.lower() == name_lower:
                return data
            if data["official_name"].lower() in name_lower:
                return data
            if name_lower in key.lower():
                return data

        # Keyword match for AI Act
        ai_keywords = ["ai act", "artificial intelligence act", "2024/1689"]
        for keyword in ai_keywords:
            if keyword in name_lower:
                return self._regulation_registry.get("EU AI Act")

        return None

    def _determine_current_stage(
        self,
        analysis_date: date,
        known_dates: Dict[str, date]
    ) -> EURegulationStage:
        """
        Determine current stage based on analysis date and known dates.

        LOGIC:
        - If analysis_date >= full_application: FULLY_APPLICABLE
        - If analysis_date >= entry_into_force: IN transitional period
        - If analysis_date >= published_oj: ENTERED_INTO_FORCE
        - If analysis_date >= council_adoption: PUBLISHED_OJ (if published)
        - etc.

        Args:
            analysis_date: Date of analysis
            known_dates: Dictionary of known regulation dates

        Returns:
            Current EURegulationStage
        """
        # Check dates in reverse order (most recent first)

        # Full application check
        full_app = known_dates.get("full_application")
        if full_app and analysis_date >= full_app:
            return EURegulationStage.FULLY_APPLICABLE

        # Entry into force check
        eif = known_dates.get("entry_into_force")
        if eif and analysis_date >= eif:
            # We're in the transitional period
            return EURegulationStage.TRANSITIONAL_PERIOD

        # Published in OJ check
        published = known_dates.get("published_oj")
        if published and analysis_date >= published:
            return EURegulationStage.ENTERED_INTO_FORCE

        # Council adoption check
        council = known_dates.get("council_adoption")
        if council and analysis_date >= council:
            return EURegulationStage.PUBLISHED_OJ

        # EP first reading check
        ep_reading = known_dates.get("ep_first_reading")
        if ep_reading and analysis_date >= ep_reading:
            return EURegulationStage.ADOPTED

        # Proposal check
        proposal = known_dates.get("proposal")
        if proposal and analysis_date >= proposal:
            return EURegulationStage.FIRST_READING_EP

        return EURegulationStage.PROPOSAL

    def _get_completed_stages(
        self,
        current_stage: EURegulationStage
    ) -> List[EURegulationStage]:
        """
        Get list of stages completed before current stage.

        Args:
            current_stage: The current stage

        Returns:
            List of completed stages
        """
        try:
            current_index = self.STAGE_SEQUENCE.index(current_stage)
            return self.STAGE_SEQUENCE[:current_index]
        except ValueError:
            return []

    def _get_remaining_stages(
        self,
        current_stage: EURegulationStage
    ) -> List[EURegulationStage]:
        """
        Get list of stages remaining after current stage.

        Args:
            current_stage: The current stage

        Returns:
            List of remaining stages (excluding current stage)
        """
        try:
            current_index = self.STAGE_SEQUENCE.index(current_stage)
            return self.STAGE_SEQUENCE[current_index + 1:]
        except ValueError:
            return self.STAGE_SEQUENCE

    def _identify_blocking_factors(
        self,
        regulation_data: Dict,
        analysis_date: date,
        target_date: date
    ) -> List[str]:
        """
        Identify factors that could block or delay progress.

        Args:
            regulation_data: Data about the regulation
            analysis_date: Date of analysis
            target_date: Market target date

        Returns:
            List of identified blocking factors
        """
        blocking_factors = []
        phases = regulation_data.get("phases", {})

        # Check if market target is before any known application dates
        for phase_name, phase_data in phases.items():
            app_date = phase_data.get("application_date")
            if app_date and target_date < app_date:
                blocking_factors.append(
                    f"Target date {target_date} is before {phase_name} "
                    f"application date {app_date}"
                )

        # Check for pending delegated/implementing acts
        # (This is a general concern for regulations in transitional period)
        eif = regulation_data["dates"].get("entry_into_force")
        full_app = regulation_data["dates"].get("full_application")

        if eif and full_app:
            if eif <= analysis_date < full_app:
                blocking_factors.append(
                    "Regulation is in transitional period - not all provisions apply yet"
                )

        return blocking_factors

    def _build_reasoning(
        self,
        regulation_data: Dict,
        current_stage: EURegulationStage,
        analysis_date: date,
        stages_remaining: List[EURegulationStage],
        blocking_factors: List[str]
    ) -> str:
        """
        Build human-readable reasoning for the analysis.

        Args:
            regulation_data: Data about the regulation
            current_stage: Determined current stage
            analysis_date: Date of analysis
            stages_remaining: Remaining stages
            blocking_factors: Identified blocking factors

        Returns:
            Reasoning string
        """
        parts = []

        parts.append(
            f"Analyzing {regulation_data['official_name']} "
            f"({regulation_data['short_name']}) as of {analysis_date}."
        )

        parts.append(f"Current stage: {current_stage.value}.")

        if stages_remaining:
            remaining_str = ", ".join(s.value for s in stages_remaining[:3])
            if len(stages_remaining) > 3:
                remaining_str += f" (+{len(stages_remaining) - 3} more)"
            parts.append(f"Remaining stages: {remaining_str}.")
        else:
            parts.append("All stages completed - regulation is fully applicable.")

        if blocking_factors:
            parts.append(f"BLOCKING FACTORS: {'; '.join(blocking_factors)}.")

        return " ".join(parts)

    def _unknown_regulation_analysis(
        self,
        market_input: MarketInput
    ) -> ProcessStageAnalysis:
        """
        Return conservative analysis for unknown regulations.

        When we don't have data about a regulation, we cannot
        reliably assess its stage. This is a FAIL CLOSED response.

        Args:
            market_input: The market input

        Returns:
            Conservative ProcessStageAnalysis
        """
        return ProcessStageAnalysis(
            current_stage=EURegulationStage.PROPOSAL,
            stages_completed=[],
            stages_remaining=self.STAGE_SEQUENCE,
            key_dates={},
            blocking_factors=[
                f"Unknown regulation: {market_input.referenced_regulation}. "
                "Cannot determine process stage without hardcoded data."
            ],
            reasoning=(
                f"CAUTION: Regulation '{market_input.referenced_regulation}' "
                "is not in the analyzer's registry. Unable to determine "
                "current stage or timeline. Manual verification required. "
                "This is a blocking factor for trading."
            )
        )

    def get_phase_info(
        self,
        regulation_name: str,
        phase_name: str
    ) -> Optional[Dict]:
        """
        Get information about a specific phase of a regulation.

        Utility method for timeline analysis.

        Args:
            regulation_name: Name of the regulation
            phase_name: Name of the phase

        Returns:
            Phase data dict or None
        """
        regulation_data = self._find_regulation(regulation_name)
        if regulation_data is None:
            return None

        return regulation_data.get("phases", {}).get(phase_name)
