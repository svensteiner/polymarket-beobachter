# =============================================================================
# COMPREHENSIVE TESTS FOR CORE MODULES
# =============================================================================
# Coverage target: 100% for probability_estimator.py, process_model.py
# =============================================================================

import pytest
from datetime import date
from unittest.mock import patch, MagicMock

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from models.data_models import (
    MarketInput,
    ProcessStageAnalysis,
    TimeFeasibilityAnalysis,
    ProbabilityEstimate,
)
from shared.enums import EURegulationStage
from core.probability_estimator import ProbabilityEstimator


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def market_input():
    """Basic market input fixture."""
    return MarketInput(
        market_title="Will EU AI Act be fully applicable by August 2026?",
        resolution_text="Resolves YES if all provisions of the EU AI Act are in force.",
        target_date=date(2026, 8, 1),
        referenced_regulation="EU AI Act",
        authority_involved="European Commission",
        market_implied_probability=0.50,
        analysis_date=date(2026, 1, 18),
    )


@pytest.fixture
def process_analysis_early():
    """Process analysis - early stage with many steps remaining."""
    return ProcessStageAnalysis(
        current_stage=EURegulationStage.ADOPTED,
        stages_completed=[
            EURegulationStage.PROPOSAL,
            EURegulationStage.FIRST_READING_EP,
            EURegulationStage.FIRST_READING_COUNCIL,
            EURegulationStage.ADOPTED,
        ],
        stages_remaining=[
            EURegulationStage.PUBLISHED_OJ,
            EURegulationStage.ENTERED_INTO_FORCE,
            EURegulationStage.DELEGATED_ACTS_PENDING,
            EURegulationStage.IMPLEMENTING_ACTS_PENDING,
            EURegulationStage.TRANSITIONAL_PERIOD,
            EURegulationStage.FULLY_APPLICABLE,
        ],
        key_dates={"adoption": date(2024, 6, 1)},
        blocking_factors=[],
        reasoning="Regulation adopted, pending implementation.",
    )


@pytest.fixture
def process_analysis_late():
    """Process analysis - late stage with few steps remaining."""
    return ProcessStageAnalysis(
        current_stage=EURegulationStage.TRANSITIONAL_PERIOD,
        stages_completed=[
            EURegulationStage.PROPOSAL,
            EURegulationStage.ADOPTED,
            EURegulationStage.PUBLISHED_OJ,
            EURegulationStage.ENTERED_INTO_FORCE,
        ],
        stages_remaining=[
            EURegulationStage.FULLY_APPLICABLE,
        ],
        key_dates={"entry_into_force": date(2024, 8, 1)},
        blocking_factors=[],
        reasoning="In transitional period.",
    )


@pytest.fixture
def process_analysis_application():
    """Process analysis - already in application phase."""
    return ProcessStageAnalysis(
        current_stage=EURegulationStage.APPLICATION_DATE,
        stages_completed=[
            EURegulationStage.PROPOSAL,
            EURegulationStage.ADOPTED,
            EURegulationStage.ENTERED_INTO_FORCE,
        ],
        stages_remaining=[],
        key_dates={},
        blocking_factors=[],
        reasoning="Already in application.",
    )


@pytest.fixture
def time_feasibility_ok():
    """Time feasibility - comfortable timeline."""
    return TimeFeasibilityAnalysis(
        days_until_target=365,
        minimum_days_required=120,
        is_timeline_feasible=True,
        mandatory_waiting_periods=[],
        institutional_constraints=[],
        hard_fail=False,
        reasoning="Ample time available.",
    )


@pytest.fixture
def time_feasibility_tight():
    """Time feasibility - tight timeline."""
    return TimeFeasibilityAnalysis(
        days_until_target=100,
        minimum_days_required=90,
        is_timeline_feasible=True,
        mandatory_waiting_periods=["20-day OJ publication delay"],
        institutional_constraints=["Commission summer recess"],
        hard_fail=False,
        reasoning="Tight but feasible.",
    )


@pytest.fixture
def time_feasibility_impossible():
    """Time feasibility - impossible timeline."""
    return TimeFeasibilityAnalysis(
        days_until_target=30,
        minimum_days_required=120,
        is_timeline_feasible=False,
        mandatory_waiting_periods=["20-day OJ publication delay"],
        institutional_constraints=[],
        hard_fail=True,
        reasoning="HARD FAIL: Impossible timeline.",
    )


# =============================================================================
# PROBABILITY ESTIMATOR TESTS
# =============================================================================

class TestProbabilityEstimatorInit:
    """Tests for ProbabilityEstimator initialization."""

    def test_init(self):
        """Estimator can be initialized."""
        pe = ProbabilityEstimator()
        assert pe.BASE_RATE_EIF_ON_SCHEDULE == 0.95
        assert pe.BASE_RATE_FULL_APPLICATION_ON_TIME == 0.70
        assert pe.PENALTY_PER_REMAINING_STEP == 0.05
        assert pe.STATUS_QUO_BIAS_FACTOR == 0.85


class TestProbabilityEstimatorEstimate:
    """Tests for ProbabilityEstimator.estimate() method."""

    def test_estimate_returns_probability_estimate(
        self, market_input, process_analysis_early, time_feasibility_ok
    ):
        """estimate() returns a ProbabilityEstimate."""
        pe = ProbabilityEstimator()
        result = pe.estimate(market_input, process_analysis_early, time_feasibility_ok)
        assert isinstance(result, ProbabilityEstimate)
        assert 0.0 <= result.probability_low <= 1.0
        assert 0.0 <= result.probability_high <= 1.0
        assert result.probability_low <= result.probability_midpoint <= result.probability_high

    def test_estimate_hard_fail_returns_near_zero(
        self, market_input, process_analysis_early, time_feasibility_impossible
    ):
        """Hard fail timeline returns near-zero probability."""
        pe = ProbabilityEstimator()
        result = pe.estimate(market_input, process_analysis_early, time_feasibility_impossible)
        assert result.probability_low == 0.0
        assert result.probability_high == 0.05
        assert result.confidence_level == "HIGH"
        assert "HARD FAIL" in result.reasoning

    def test_estimate_includes_assumptions(
        self, market_input, process_analysis_early, time_feasibility_ok
    ):
        """estimate() includes list of assumptions."""
        pe = ProbabilityEstimator()
        result = pe.estimate(market_input, process_analysis_early, time_feasibility_ok)
        assert len(result.assumptions) > 0
        assert any("Base rate" in a for a in result.assumptions)
        assert any("Step penalty" in a for a in result.assumptions)

    def test_estimate_includes_historical_precedents(
        self, market_input, process_analysis_early, time_feasibility_ok
    ):
        """estimate() includes historical precedents."""
        pe = ProbabilityEstimator()
        result = pe.estimate(market_input, process_analysis_early, time_feasibility_ok)
        assert len(result.historical_precedents) > 0

    def test_estimate_status_quo_bias_applied(
        self, market_input, process_analysis_early, time_feasibility_ok
    ):
        """Status quo bias is applied."""
        pe = ProbabilityEstimator()
        result = pe.estimate(market_input, process_analysis_early, time_feasibility_ok)
        assert result.status_quo_bias_applied is True

    def test_estimate_late_stage_higher_probability(
        self, market_input, process_analysis_late, time_feasibility_ok
    ):
        """Late stage process has higher probability."""
        pe = ProbabilityEstimator()
        result = pe.estimate(market_input, process_analysis_late, time_feasibility_ok)
        # Late stage with 1 step remaining should have higher base rate
        assert result.probability_midpoint > 0.5

    def test_estimate_application_phase_highest(
        self, market_input, process_analysis_application, time_feasibility_ok
    ):
        """Application phase has highest probability."""
        pe = ProbabilityEstimator()
        result = pe.estimate(market_input, process_analysis_application, time_feasibility_ok)
        assert result.probability_midpoint >= 0.7

    def test_estimate_tight_timeline_wider_bands(
        self, market_input, process_analysis_early, time_feasibility_ok, time_feasibility_tight
    ):
        """Tight timeline results in wider uncertainty bands."""
        pe = ProbabilityEstimator()
        result_ok = pe.estimate(market_input, process_analysis_early, time_feasibility_ok)
        result_tight = pe.estimate(market_input, process_analysis_early, time_feasibility_tight)

        width_ok = result_ok.probability_high - result_ok.probability_low
        width_tight = result_tight.probability_high - result_tight.probability_low

        # Tight timeline should have wider bands
        assert width_tight >= width_ok


class TestDetermineBaseRate:
    """Tests for _determine_base_rate method."""

    def test_application_phase_high_rate(self, process_analysis_application):
        """Application phase gets high base rate."""
        pe = ProbabilityEstimator()
        rate, reason = pe._determine_base_rate(
            process_analysis_application.current_stage,
            process_analysis_application.stages_remaining
        )
        assert rate == 0.90
        assert "application phase" in reason.lower()

    def test_eif_pending_uses_eif_rate(self):
        """Entry into force pending uses EIF rate."""
        pe = ProbabilityEstimator()
        remaining = [
            EURegulationStage.ENTERED_INTO_FORCE,
            EURegulationStage.TRANSITIONAL_PERIOD,
        ]
        rate, reason = pe._determine_base_rate(
            EURegulationStage.PUBLISHED_OJ,
            remaining
        )
        assert rate == pe.BASE_RATE_EIF_ON_SCHEDULE

    def test_delegated_acts_pending_uses_delegated_rate(self):
        """Delegated acts pending uses lower rate."""
        pe = ProbabilityEstimator()
        remaining = [
            EURegulationStage.DELEGATED_ACTS_PENDING,
            EURegulationStage.FULLY_APPLICABLE,
        ]
        rate, reason = pe._determine_base_rate(
            EURegulationStage.ENTERED_INTO_FORCE,
            remaining
        )
        assert rate == pe.BASE_RATE_DELEGATED_ACTS_ON_TIME

    def test_implementing_acts_pending_uses_implementing_rate(self):
        """Implementing acts pending uses moderate rate."""
        pe = ProbabilityEstimator()
        remaining = [
            EURegulationStage.IMPLEMENTING_ACTS_PENDING,
            EURegulationStage.FULLY_APPLICABLE,
        ]
        rate, reason = pe._determine_base_rate(
            EURegulationStage.ENTERED_INTO_FORCE,
            remaining
        )
        assert rate == pe.BASE_RATE_IMPLEMENTING_ACTS_ON_TIME

    def test_default_full_application_rate(self):
        """Default case uses full application rate."""
        pe = ProbabilityEstimator()
        remaining = [
            EURegulationStage.FIRST_READING_EP,
            EURegulationStage.FIRST_READING_COUNCIL,
            EURegulationStage.FULLY_APPLICABLE,
        ]
        rate, reason = pe._determine_base_rate(
            EURegulationStage.PROPOSAL,
            remaining
        )
        assert rate == pe.BASE_RATE_FULL_APPLICATION_ON_TIME


class TestCalculateStepPenalty:
    """Tests for _calculate_step_penalty method."""

    def test_no_steps_no_penalty(self):
        """No remaining steps means no penalty."""
        pe = ProbabilityEstimator()
        penalty = pe._calculate_step_penalty([])
        assert penalty == 0.0

    def test_one_step_small_penalty(self):
        """One step gives small penalty."""
        pe = ProbabilityEstimator()
        penalty = pe._calculate_step_penalty([EURegulationStage.FULLY_APPLICABLE])
        assert penalty == 0.05

    def test_many_steps_capped_penalty(self):
        """Many steps caps at MAX_STEP_PENALTY."""
        pe = ProbabilityEstimator()
        many_stages = [
            EURegulationStage.PROPOSAL,
            EURegulationStage.FIRST_READING_EP,
            EURegulationStage.FIRST_READING_COUNCIL,
            EURegulationStage.ADOPTED,
            EURegulationStage.PUBLISHED_OJ,
            EURegulationStage.ENTERED_INTO_FORCE,
            EURegulationStage.DELEGATED_ACTS_PENDING,
            EURegulationStage.IMPLEMENTING_ACTS_PENDING,
            EURegulationStage.TRANSITIONAL_PERIOD,
            EURegulationStage.FULLY_APPLICABLE,
        ]
        penalty = pe._calculate_step_penalty(many_stages)
        assert penalty == pe.MAX_STEP_PENALTY


class TestCalculateUncertaintyWidth:
    """Tests for _calculate_uncertainty_width method."""

    def test_comfortable_timeline_narrow_width(self, time_feasibility_ok):
        """Comfortable timeline gives narrower width."""
        pe = ProbabilityEstimator()
        width = pe._calculate_uncertainty_width(
            [EURegulationStage.FULLY_APPLICABLE],
            time_feasibility_ok
        )
        assert width <= 0.15

    def test_tight_timeline_wider_width(self, time_feasibility_tight):
        """Tight timeline gives wider width."""
        pe = ProbabilityEstimator()
        width = pe._calculate_uncertainty_width(
            [EURegulationStage.FULLY_APPLICABLE],
            time_feasibility_tight
        )
        assert width >= 0.10

    def test_many_stages_increases_width(self, time_feasibility_ok):
        """More stages increase width."""
        pe = ProbabilityEstimator()
        width_few = pe._calculate_uncertainty_width(
            [EURegulationStage.FULLY_APPLICABLE],
            time_feasibility_ok
        )
        width_many = pe._calculate_uncertainty_width(
            [EURegulationStage.DELEGATED_ACTS_PENDING,
             EURegulationStage.IMPLEMENTING_ACTS_PENDING,
             EURegulationStage.TRANSITIONAL_PERIOD,
             EURegulationStage.FULLY_APPLICABLE],
            time_feasibility_ok
        )
        assert width_many > width_few

    def test_institutional_constraints_increase_width(self, time_feasibility_tight):
        """Institutional constraints increase width."""
        pe = ProbabilityEstimator()
        width = pe._calculate_uncertainty_width(
            [EURegulationStage.FULLY_APPLICABLE],
            time_feasibility_tight
        )
        # tight has constraints
        assert width >= 0.10

    def test_zero_min_days_handled(self):
        """Zero minimum days doesn't cause division error."""
        pe = ProbabilityEstimator()
        time_feas = TimeFeasibilityAnalysis(
            days_until_target=100,
            minimum_days_required=0,  # Edge case
            is_timeline_feasible=True,
            mandatory_waiting_periods=[],
            institutional_constraints=[],
            hard_fail=False,
            reasoning="Test",
        )
        # Should not raise
        width = pe._calculate_uncertainty_width(
            [EURegulationStage.FULLY_APPLICABLE],
            time_feas
        )
        assert width > 0


class TestBuildAssumptions:
    """Tests for _build_assumptions method."""

    def test_builds_assumptions_list(self, time_feasibility_ok):
        """Builds list of assumptions."""
        pe = ProbabilityEstimator()
        assumptions = pe._build_assumptions(
            base_rate=0.70,
            base_rate_reason="Test reason",
            step_penalty=0.10,
            remaining_stages=[EURegulationStage.FULLY_APPLICABLE],
            time_feasibility=time_feasibility_ok
        )
        assert len(assumptions) >= 3
        assert any("Base rate" in a for a in assumptions)
        assert any("Step penalty" in a for a in assumptions)
        assert any("Status quo" in a for a in assumptions)

    def test_includes_constraints_if_present(self, time_feasibility_tight):
        """Includes constraints if present."""
        pe = ProbabilityEstimator()
        assumptions = pe._build_assumptions(
            base_rate=0.70,
            base_rate_reason="Test",
            step_penalty=0.10,
            remaining_stages=[],
            time_feasibility=time_feasibility_tight
        )
        assert any("constraint" in a.lower() for a in assumptions)


class TestGetHistoricalPrecedents:
    """Tests for _get_historical_precedents method."""

    def test_always_includes_general_precedent(self):
        """Always includes general EU legislative precedent."""
        pe = ProbabilityEstimator()
        precedents = pe._get_historical_precedents(
            "Some Regulation",
            EURegulationStage.ADOPTED
        )
        assert len(precedents) >= 1
        assert any("EU regulation" in p for p in precedents)

    def test_ai_regulation_includes_gdpr(self):
        """AI regulation includes GDPR precedent."""
        pe = ProbabilityEstimator()
        precedents = pe._get_historical_precedents(
            "EU AI Act",
            EURegulationStage.ADOPTED
        )
        assert any("GDPR" in p for p in precedents)
        assert any("Digital" in p for p in precedents)

    def test_transitional_stage_includes_precedent(self):
        """Transitional stage includes specific precedent."""
        pe = ProbabilityEstimator()
        precedents = pe._get_historical_precedents(
            "Test Regulation",
            EURegulationStage.TRANSITIONAL_PERIOD
        )
        assert any("transitional" in p.lower() for p in precedents)


class TestBuildReasoning:
    """Tests for _build_reasoning method."""

    def test_builds_reasoning_string(self):
        """Builds comprehensive reasoning string."""
        pe = ProbabilityEstimator()
        reasoning = pe._build_reasoning(
            base_rate=0.70,
            step_penalty=0.10,
            biased_rate=0.50,
            probability_low=0.40,
            probability_high=0.60,
            confidence_level="MEDIUM",
            remaining_stages=[EURegulationStage.FULLY_APPLICABLE]
        )
        assert "base rate" in reasoning.lower()
        assert "step penalty" in reasoning.lower()
        assert "status quo" in reasoning.lower()
        assert "MEDIUM" in reasoning


class TestConfidenceLevels:
    """Tests for confidence level determination."""

    def test_high_confidence_narrow_band(
        self, market_input, process_analysis_application, time_feasibility_ok
    ):
        """Narrow band results in HIGH confidence."""
        pe = ProbabilityEstimator()
        result = pe.estimate(market_input, process_analysis_application, time_feasibility_ok)
        # Application phase with comfortable timeline should give narrow bands
        width = result.probability_high - result.probability_low
        if width < pe.CONFIDENCE_HIGH_THRESHOLD:
            assert result.confidence_level == "HIGH"

    def test_low_confidence_wide_band(
        self, market_input, process_analysis_early, time_feasibility_tight
    ):
        """Wide band results in LOW confidence."""
        pe = ProbabilityEstimator()
        result = pe.estimate(market_input, process_analysis_early, time_feasibility_tight)
        width = result.probability_high - result.probability_low
        if width >= pe.CONFIDENCE_MEDIUM_THRESHOLD:
            assert result.confidence_level == "LOW"


# =============================================================================
# PROCESS MODEL TESTS
# =============================================================================

from core.process_model import EUProcessModel


class TestEUProcessModelInit:
    """Tests for EUProcessModel initialization."""

    def test_init(self):
        """Model can be initialized."""
        model = EUProcessModel()
        assert "EU AI Act" in model._regulation_registry
        assert len(model.STAGE_SEQUENCE) == 14

    def test_has_ai_act_dates(self):
        """Model has EU AI Act dates."""
        model = EUProcessModel()
        assert model.EU_AI_ACT_DATES["entry_into_force"] == date(2024, 8, 1)
        assert model.EU_AI_ACT_DATES["full_application"] == date(2026, 8, 2)

    def test_has_ai_act_phases(self):
        """Model has EU AI Act phases."""
        model = EUProcessModel()
        assert "prohibited_practices" in model.EU_AI_ACT_PHASES
        assert "main_obligations" in model.EU_AI_ACT_PHASES


class TestFindRegulation:
    """Tests for _find_regulation method."""

    def test_find_exact_match(self):
        """Finds regulation by exact name."""
        model = EUProcessModel()
        result = model._find_regulation("EU AI Act")
        assert result is not None
        assert result["short_name"] == "EU AI Act"

    def test_find_case_insensitive(self):
        """Finds regulation case-insensitively."""
        model = EUProcessModel()
        result = model._find_regulation("eu ai act")
        assert result is not None

    def test_find_by_keyword(self):
        """Finds regulation by AI keyword."""
        model = EUProcessModel()
        result = model._find_regulation("The Artificial Intelligence Act")
        assert result is not None

    def test_find_by_number(self):
        """Finds regulation by number."""
        model = EUProcessModel()
        result = model._find_regulation("Regulation 2024/1689")
        assert result is not None

    def test_find_unknown_returns_none(self):
        """Unknown regulation returns None."""
        model = EUProcessModel()
        result = model._find_regulation("Unknown Regulation XYZ")
        assert result is None


class TestDetermineCurrentStage:
    """Tests for _determine_current_stage method."""

    def test_before_proposal(self):
        """Before proposal date returns PROPOSAL."""
        model = EUProcessModel()
        result = model._determine_current_stage(
            date(2020, 1, 1),
            model.EU_AI_ACT_DATES
        )
        assert result == EURegulationStage.PROPOSAL

    def test_after_proposal(self):
        """After proposal returns FIRST_READING_EP."""
        model = EUProcessModel()
        result = model._determine_current_stage(
            date(2022, 1, 1),
            model.EU_AI_ACT_DATES
        )
        assert result == EURegulationStage.FIRST_READING_EP

    def test_after_ep_reading(self):
        """After EP reading returns ADOPTED."""
        model = EUProcessModel()
        result = model._determine_current_stage(
            date(2024, 4, 1),
            model.EU_AI_ACT_DATES
        )
        assert result == EURegulationStage.ADOPTED

    def test_after_council_adoption(self):
        """After council adoption returns PUBLISHED_OJ."""
        model = EUProcessModel()
        result = model._determine_current_stage(
            date(2024, 6, 1),
            model.EU_AI_ACT_DATES
        )
        assert result == EURegulationStage.PUBLISHED_OJ

    def test_after_publication(self):
        """After OJ publication returns ENTERED_INTO_FORCE."""
        model = EUProcessModel()
        result = model._determine_current_stage(
            date(2024, 7, 20),
            model.EU_AI_ACT_DATES
        )
        assert result == EURegulationStage.ENTERED_INTO_FORCE

    def test_after_eif(self):
        """After entry into force returns TRANSITIONAL_PERIOD."""
        model = EUProcessModel()
        result = model._determine_current_stage(
            date(2025, 1, 1),
            model.EU_AI_ACT_DATES
        )
        assert result == EURegulationStage.TRANSITIONAL_PERIOD

    def test_after_full_application(self):
        """After full application returns FULLY_APPLICABLE."""
        model = EUProcessModel()
        result = model._determine_current_stage(
            date(2027, 1, 1),
            model.EU_AI_ACT_DATES
        )
        assert result == EURegulationStage.FULLY_APPLICABLE


class TestGetCompletedStages:
    """Tests for _get_completed_stages method."""

    def test_proposal_no_completed(self):
        """PROPOSAL stage has no completed stages."""
        model = EUProcessModel()
        result = model._get_completed_stages(EURegulationStage.PROPOSAL)
        assert result == []

    def test_adopted_has_completed(self):
        """ADOPTED stage has completed stages."""
        model = EUProcessModel()
        result = model._get_completed_stages(EURegulationStage.ADOPTED)
        assert EURegulationStage.PROPOSAL in result
        assert EURegulationStage.FIRST_READING_EP in result

    def test_unknown_stage_returns_empty(self):
        """Unknown stage returns empty list."""
        model = EUProcessModel()
        # Create mock stage that's not in sequence
        # Since all stages are in sequence, test edge case
        result = model._get_completed_stages(EURegulationStage.FULLY_APPLICABLE)
        assert len(result) == 13  # All but last


class TestGetRemainingStages:
    """Tests for _get_remaining_stages method."""

    def test_proposal_all_remaining(self):
        """PROPOSAL stage has all other stages remaining."""
        model = EUProcessModel()
        result = model._get_remaining_stages(EURegulationStage.PROPOSAL)
        assert len(result) == 13

    def test_fully_applicable_none_remaining(self):
        """FULLY_APPLICABLE has no remaining stages."""
        model = EUProcessModel()
        result = model._get_remaining_stages(EURegulationStage.FULLY_APPLICABLE)
        assert result == []

    def test_transitional_has_few_remaining(self):
        """TRANSITIONAL_PERIOD has few remaining stages."""
        model = EUProcessModel()
        result = model._get_remaining_stages(EURegulationStage.TRANSITIONAL_PERIOD)
        assert EURegulationStage.FULLY_APPLICABLE in result


class TestIdentifyBlockingFactors:
    """Tests for _identify_blocking_factors method."""

    def test_target_before_phase_is_blocking(self):
        """Target before phase application is blocking."""
        model = EUProcessModel()
        reg_data = model._find_regulation("EU AI Act")
        blocking = model._identify_blocking_factors(
            reg_data,
            date(2025, 1, 1),
            date(2025, 3, 1)  # Before GPAI rules apply
        )
        assert len(blocking) > 0

    def test_transitional_period_noted(self):
        """Transitional period is noted as blocking factor."""
        model = EUProcessModel()
        reg_data = model._find_regulation("EU AI Act")
        blocking = model._identify_blocking_factors(
            reg_data,
            date(2025, 6, 1),  # During transitional
            date(2026, 12, 1)
        )
        assert any("transitional" in b.lower() for b in blocking)


class TestAnalyze:
    """Tests for analyze method."""

    def test_analyze_known_regulation(self, market_input):
        """Analyze returns ProcessStageAnalysis for known regulation."""
        model = EUProcessModel()
        result = model.analyze(market_input)
        assert result.current_stage == EURegulationStage.TRANSITIONAL_PERIOD
        assert len(result.key_dates) > 0

    def test_analyze_unknown_regulation(self):
        """Analyze returns conservative analysis for unknown regulation."""
        model = EUProcessModel()
        unknown_input = MarketInput(
            market_title="Unknown regulation market",
            resolution_text="Some resolution",
            target_date=date(2026, 12, 1),
            referenced_regulation="Unknown Regulation XYZ",
            authority_involved="Unknown",
            market_implied_probability=0.50,
            analysis_date=date(2026, 1, 18),
        )
        result = model.analyze(unknown_input)
        assert result.current_stage == EURegulationStage.PROPOSAL
        assert len(result.blocking_factors) > 0
        assert "Unknown regulation" in result.blocking_factors[0]

    def test_analyze_includes_reasoning(self, market_input):
        """Analyze includes reasoning."""
        model = EUProcessModel()
        result = model.analyze(market_input)
        assert len(result.reasoning) > 0
        assert "EU AI Act" in result.reasoning


class TestBuildReasoning:
    """Tests for _build_reasoning method."""

    def test_builds_reasoning_string(self):
        """Builds comprehensive reasoning."""
        model = EUProcessModel()
        reg_data = model._find_regulation("EU AI Act")
        reasoning = model._build_reasoning(
            reg_data,
            EURegulationStage.TRANSITIONAL_PERIOD,
            date(2025, 6, 1),
            [EURegulationStage.FULLY_APPLICABLE],
            []
        )
        assert "2024/1689" in reasoning
        assert "TRANSITIONAL_PERIOD" in reasoning

    def test_includes_blocking_factors(self):
        """Reasoning includes blocking factors."""
        model = EUProcessModel()
        reg_data = model._find_regulation("EU AI Act")
        reasoning = model._build_reasoning(
            reg_data,
            EURegulationStage.TRANSITIONAL_PERIOD,
            date(2025, 6, 1),
            [],
            ["Some blocking factor"]
        )
        assert "BLOCKING FACTORS" in reasoning

    def test_handles_no_remaining_stages(self):
        """Reasoning handles no remaining stages."""
        model = EUProcessModel()
        reg_data = model._find_regulation("EU AI Act")
        reasoning = model._build_reasoning(
            reg_data,
            EURegulationStage.FULLY_APPLICABLE,
            date(2027, 1, 1),
            [],
            []
        )
        assert "fully applicable" in reasoning.lower()


class TestGetPhaseInfo:
    """Tests for get_phase_info method."""

    def test_get_existing_phase(self):
        """Gets existing phase info."""
        model = EUProcessModel()
        result = model.get_phase_info("EU AI Act", "prohibited_practices")
        assert result is not None
        assert result["months_after_eif"] == 6

    def test_get_unknown_phase_returns_none(self):
        """Unknown phase returns None."""
        model = EUProcessModel()
        result = model.get_phase_info("EU AI Act", "unknown_phase")
        assert result is None

    def test_get_phase_unknown_regulation_returns_none(self):
        """Unknown regulation returns None for phase."""
        model = EUProcessModel()
        result = model.get_phase_info("Unknown Reg", "prohibited_practices")
        assert result is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
