# =============================================================================
# COMPREHENSIVE TESTS FOR PROPOSALS MODULE
# =============================================================================
# Coverage target: 100% for review_gate.py, generator.py, models.py
# =============================================================================

import pytest
from datetime import datetime
from unittest.mock import patch, MagicMock

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from proposals.models import (
    Proposal,
    ProposalCoreCriteria,
    ReviewResult,
    ReviewOutcome,
    ConfidenceLevel,
    generate_proposal_id,
)
from proposals.review_gate import ReviewGate, review_proposal
from proposals.generator import ProposalGenerator


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def valid_core_criteria():
    """All criteria passing."""
    return ProposalCoreCriteria(
        liquidity_ok=True,
        volume_ok=True,
        time_to_resolution_ok=True,
        data_quality_ok=True,
    )


@pytest.fixture
def failing_core_criteria():
    """Some criteria failing."""
    return ProposalCoreCriteria(
        liquidity_ok=False,
        volume_ok=True,
        time_to_resolution_ok=False,
        data_quality_ok=True,
    )


@pytest.fixture
def valid_proposal(valid_core_criteria):
    """A valid TRADE proposal that should PASS review."""
    return Proposal(
        proposal_id="PROP-20260118-test001",
        timestamp=datetime.now().isoformat(),
        market_id="market_123",
        market_question="Will EU pass AI Act by 2026?",
        decision="TRADE",
        implied_probability=0.50,
        model_probability=0.70,
        edge=0.20,  # 20% edge - well above threshold
        core_criteria=valid_core_criteria,
        warnings=(),
        confidence_level="HIGH",
        justification_summary="Strong edge with high confidence.",
    )


@pytest.fixture
def low_confidence_proposal(valid_core_criteria):
    """Proposal with LOW confidence - should REJECT."""
    return Proposal(
        proposal_id="PROP-20260118-test002",
        timestamp=datetime.now().isoformat(),
        market_id="market_456",
        market_question="Test market",
        decision="TRADE",
        implied_probability=0.50,
        model_probability=0.60,
        edge=0.10,
        core_criteria=valid_core_criteria,
        warnings=(),
        confidence_level="LOW",
        justification_summary="Low confidence test.",
    )


@pytest.fixture
def borderline_edge_proposal(valid_core_criteria):
    """Proposal with borderline edge (3-5%) - should HOLD."""
    return Proposal(
        proposal_id="PROP-20260118-test003",
        timestamp=datetime.now().isoformat(),
        market_id="market_789",
        market_question="Test market",
        decision="TRADE",
        implied_probability=0.50,
        model_probability=0.54,
        edge=0.04,  # 4% - borderline
        core_criteria=valid_core_criteria,
        warnings=(),
        confidence_level="MEDIUM",
        justification_summary="Borderline edge test.",
    )


@pytest.fixture
def low_edge_proposal(valid_core_criteria):
    """Proposal with very low edge (<3%) - should HOLD or REJECT."""
    return Proposal(
        proposal_id="PROP-20260118-test004",
        timestamp=datetime.now().isoformat(),
        market_id="market_abc",
        market_question="Test market",
        decision="TRADE",
        implied_probability=0.50,
        model_probability=0.51,
        edge=0.01,  # 1% - below borderline
        core_criteria=valid_core_criteria,
        warnings=(),
        confidence_level="MEDIUM",
        justification_summary="Low edge test.",
    )


@pytest.fixture
def critical_warning_proposal(valid_core_criteria):
    """Proposal with critical warnings - should HOLD."""
    return Proposal(
        proposal_id="PROP-20260118-test005",
        timestamp=datetime.now().isoformat(),
        market_id="market_def",
        market_question="Test market",
        decision="TRADE",
        implied_probability=0.50,
        model_probability=0.70,
        edge=0.20,
        core_criteria=valid_core_criteria,
        warnings=("CRITICAL: Data source unreliable", "Minor issue"),
        confidence_level="HIGH",
        justification_summary="Critical warning test.",
    )


@pytest.fixture
def many_warnings_proposal(valid_core_criteria):
    """Proposal with too many warnings - should HOLD."""
    return Proposal(
        proposal_id="PROP-20260118-test006",
        timestamp=datetime.now().isoformat(),
        market_id="market_ghi",
        market_question="Test market",
        decision="TRADE",
        implied_probability=0.50,
        model_probability=0.70,
        edge=0.20,
        core_criteria=valid_core_criteria,
        warnings=("Warning 1", "Warning 2", "Warning 3", "Warning 4", "Warning 5"),
        confidence_level="HIGH",
        justification_summary="Many warnings test.",
    )


@pytest.fixture
def inconsistent_proposal(failing_core_criteria):
    """TRADE decision with failing criteria - inconsistent."""
    return Proposal(
        proposal_id="PROP-20260118-test007",
        timestamp=datetime.now().isoformat(),
        market_id="market_jkl",
        market_question="Test market",
        decision="TRADE",
        implied_probability=0.50,
        model_probability=0.70,
        edge=0.20,
        core_criteria=failing_core_criteria,
        warnings=(),
        confidence_level="HIGH",
        justification_summary="Inconsistent decision test.",
    )


@pytest.fixture
def no_trade_proposal(failing_core_criteria):
    """NO_TRADE decision - always consistent."""
    return Proposal(
        proposal_id="PROP-20260118-test008",
        timestamp=datetime.now().isoformat(),
        market_id="market_mno",
        market_question="Test market",
        decision="NO_TRADE",
        implied_probability=0.50,
        model_probability=0.45,
        edge=-0.05,
        core_criteria=failing_core_criteria,
        warnings=(),
        confidence_level="MEDIUM",
        justification_summary="No trade test.",
    )


# =============================================================================
# PROPOSAL MODEL TESTS
# =============================================================================

class TestProposalCoreCriteria:
    """Tests for ProposalCoreCriteria dataclass."""

    def test_all_passed_true(self, valid_core_criteria):
        """All criteria true returns True."""
        assert valid_core_criteria.all_passed() is True

    def test_all_passed_false(self, failing_core_criteria):
        """Some criteria false returns False."""
        assert failing_core_criteria.all_passed() is False

    def test_failed_criteria_empty(self, valid_core_criteria):
        """No failures returns empty list."""
        assert valid_core_criteria.failed_criteria() == []

    def test_failed_criteria_returns_names(self, failing_core_criteria):
        """Failed criteria names are returned."""
        failed = failing_core_criteria.failed_criteria()
        assert "liquidity_ok" in failed
        assert "time_to_resolution_ok" in failed
        assert "volume_ok" not in failed

    def test_to_dict(self, valid_core_criteria):
        """to_dict returns correct dictionary."""
        d = valid_core_criteria.to_dict()
        assert d["liquidity_ok"] is True
        assert d["volume_ok"] is True
        assert d["time_to_resolution_ok"] is True
        assert d["data_quality_ok"] is True


class TestProposal:
    """Tests for Proposal dataclass."""

    def test_valid_proposal_creation(self, valid_proposal):
        """Valid proposal can be created."""
        assert valid_proposal.proposal_id == "PROP-20260118-test001"
        assert valid_proposal.decision == "TRADE"
        assert valid_proposal.edge == 0.20

    def test_invalid_decision_raises(self, valid_core_criteria):
        """Invalid decision raises ValueError."""
        with pytest.raises(ValueError, match="Invalid decision"):
            Proposal(
                proposal_id="test",
                timestamp=datetime.now().isoformat(),
                market_id="test",
                market_question="test",
                decision="INVALID",
                implied_probability=0.5,
                model_probability=0.5,
                edge=0.0,
                core_criteria=valid_core_criteria,
                warnings=(),
                confidence_level="HIGH",
                justification_summary="test",
            )

    def test_invalid_confidence_raises(self, valid_core_criteria):
        """Invalid confidence level raises ValueError."""
        with pytest.raises(ValueError, match="Invalid confidence_level"):
            Proposal(
                proposal_id="test",
                timestamp=datetime.now().isoformat(),
                market_id="test",
                market_question="test",
                decision="TRADE",
                implied_probability=0.5,
                model_probability=0.5,
                edge=0.0,
                core_criteria=valid_core_criteria,
                warnings=(),
                confidence_level="INVALID",
                justification_summary="test",
            )

    def test_probability_out_of_range_raises(self, valid_core_criteria):
        """Probability out of range raises ValueError."""
        with pytest.raises(ValueError, match="implied_probability out of range"):
            Proposal(
                proposal_id="test",
                timestamp=datetime.now().isoformat(),
                market_id="test",
                market_question="test",
                decision="TRADE",
                implied_probability=1.5,  # Out of range
                model_probability=0.5,
                edge=0.0,
                core_criteria=valid_core_criteria,
                warnings=(),
                confidence_level="HIGH",
                justification_summary="test",
            )

    def test_model_probability_out_of_range_raises(self, valid_core_criteria):
        """Model probability out of range raises ValueError."""
        with pytest.raises(ValueError, match="model_probability out of range"):
            Proposal(
                proposal_id="test",
                timestamp=datetime.now().isoformat(),
                market_id="test",
                market_question="test",
                decision="TRADE",
                implied_probability=0.5,
                model_probability=-0.1,  # Out of range
                edge=0.0,
                core_criteria=valid_core_criteria,
                warnings=(),
                confidence_level="HIGH",
                justification_summary="test",
            )

    def test_governance_notice_is_set(self, valid_proposal):
        """Governance notice is automatically set."""
        assert "informational only" in valid_proposal.governance_notice

    def test_to_dict(self, valid_proposal):
        """to_dict returns complete dictionary."""
        d = valid_proposal.to_dict()
        assert "proposal_id" in d
        assert "governance_notice" in d
        assert d["decision"] == "TRADE"

    def test_to_json(self, valid_proposal):
        """to_json returns valid JSON string."""
        import json
        json_str = valid_proposal.to_json()
        data = json.loads(json_str)
        assert data["proposal_id"] == valid_proposal.proposal_id

    def test_from_dict(self, valid_proposal):
        """from_dict recreates proposal correctly."""
        d = valid_proposal.to_dict()
        recreated = Proposal.from_dict(d)
        assert recreated.proposal_id == valid_proposal.proposal_id
        assert recreated.decision == valid_proposal.decision
        assert recreated.edge == valid_proposal.edge


class TestReviewResult:
    """Tests for ReviewResult dataclass."""

    def test_review_result_creation(self, valid_proposal):
        """ReviewResult can be created."""
        result = ReviewResult(
            proposal_id=valid_proposal.proposal_id,
            outcome=ReviewOutcome.REVIEW_PASS,
            reasons=("All checks passed",),
            checks_performed={"test_check": True},
            reviewed_at=datetime.now().isoformat(),
        )
        assert result.outcome == ReviewOutcome.REVIEW_PASS

    def test_to_dict(self, valid_proposal):
        """to_dict returns correct dictionary."""
        result = ReviewResult(
            proposal_id=valid_proposal.proposal_id,
            outcome=ReviewOutcome.REVIEW_HOLD,
            reasons=("Reason 1", "Reason 2"),
            checks_performed={"check1": True, "check2": False},
            reviewed_at=datetime.now().isoformat(),
        )
        d = result.to_dict()
        assert d["outcome"] == "REVIEW_HOLD"
        assert len(d["reasons"]) == 2

    def test_to_markdown(self, valid_proposal):
        """to_markdown generates readable output."""
        result = ReviewResult(
            proposal_id=valid_proposal.proposal_id,
            outcome=ReviewOutcome.REVIEW_PASS,
            reasons=("All checks passed",),
            checks_performed={"test_check": True},
            reviewed_at=datetime.now().isoformat(),
        )
        md = result.to_markdown(valid_proposal)
        assert "## Proposal Review" in md
        assert "REVIEW_PASS" in md
        assert "Governance Notice" in md

    def test_to_markdown_with_warnings(self, critical_warning_proposal):
        """to_markdown includes warnings section."""
        result = ReviewResult(
            proposal_id=critical_warning_proposal.proposal_id,
            outcome=ReviewOutcome.REVIEW_HOLD,
            reasons=("Critical warning",),
            checks_performed={"test": True},
            reviewed_at=datetime.now().isoformat(),
        )
        md = result.to_markdown(critical_warning_proposal)
        assert "### Warnings" in md

    def test_to_markdown_no_reasons(self, valid_proposal):
        """to_markdown handles empty reasons."""
        result = ReviewResult(
            proposal_id=valid_proposal.proposal_id,
            outcome=ReviewOutcome.REVIEW_PASS,
            reasons=(),
            checks_performed={},
            reviewed_at=datetime.now().isoformat(),
        )
        md = result.to_markdown(valid_proposal)
        assert "No specific reasons recorded" in md


class TestGenerateProposalId:
    """Tests for generate_proposal_id function."""

    def test_format(self):
        """ID has correct format."""
        id = generate_proposal_id()
        assert id.startswith("PROP-")
        parts = id.split("-")
        assert len(parts) == 3
        assert len(parts[1]) == 8  # Date part YYYYMMDD
        assert len(parts[2]) == 8  # UUID part

    def test_uniqueness(self):
        """Generated IDs are unique."""
        ids = [generate_proposal_id() for _ in range(100)]
        assert len(set(ids)) == 100


# =============================================================================
# REVIEW GATE TESTS
# =============================================================================

class TestReviewGate:
    """Tests for ReviewGate class."""

    def test_init(self):
        """ReviewGate can be initialized."""
        gate = ReviewGate()
        assert gate.MINIMUM_EDGE_THRESHOLD == 0.02
        assert gate.BORDERLINE_EDGE_THRESHOLD == 0.01

    def test_review_pass_valid_proposal(self, valid_proposal):
        """Valid proposal gets REVIEW_PASS."""
        gate = ReviewGate()
        result = gate.review(valid_proposal)
        assert result.outcome == ReviewOutcome.REVIEW_PASS
        assert result.checks_performed["confidence_not_low"] is True
        assert result.checks_performed["edge_above_minimum"] is True

    def test_review_reject_low_confidence(self, low_confidence_proposal):
        """Low confidence proposal gets REVIEW_REJECT."""
        gate = ReviewGate()
        result = gate.review(low_confidence_proposal)
        assert result.outcome == ReviewOutcome.REVIEW_REJECT
        assert result.checks_performed["confidence_not_low"] is False
        assert any("LOW" in r for r in result.reasons)

    def test_review_pass_borderline_edge(self, borderline_edge_proposal):
        """Borderline edge proposal (4%) passes with lowered threshold (2%)."""
        gate = ReviewGate()
        result = gate.review(borderline_edge_proposal)
        assert result.outcome == ReviewOutcome.REVIEW_PASS
        assert result.checks_performed["edge_above_minimum"] is True

    def test_review_hold_low_edge(self, low_edge_proposal):
        """Low edge proposal (1%) is at borderline threshold (1%) - HOLD."""
        gate = ReviewGate()
        result = gate.review(low_edge_proposal)
        assert result.outcome == ReviewOutcome.REVIEW_HOLD
        assert any("borderline" in r.lower() for r in result.reasons)

    def test_review_hold_critical_warnings(self, critical_warning_proposal):
        """Critical warnings result in REVIEW_HOLD."""
        gate = ReviewGate()
        result = gate.review(critical_warning_proposal)
        assert result.outcome == ReviewOutcome.REVIEW_HOLD
        assert result.checks_performed["no_critical_warnings"] is False

    def test_review_hold_many_warnings(self, many_warnings_proposal):
        """Many warnings result in REVIEW_HOLD."""
        gate = ReviewGate()
        result = gate.review(many_warnings_proposal)
        assert result.outcome == ReviewOutcome.REVIEW_HOLD
        assert result.checks_performed["warning_count_acceptable"] is False

    def test_review_reject_inconsistent(self, inconsistent_proposal):
        """Inconsistent TRADE decision gets REVIEW_REJECT."""
        gate = ReviewGate()
        result = gate.review(inconsistent_proposal)
        assert result.outcome == ReviewOutcome.REVIEW_REJECT
        assert result.checks_performed["decision_consistent"] is False

    def test_review_no_trade_always_consistent(self, no_trade_proposal):
        """NO_TRADE decision is always consistent."""
        gate = ReviewGate()
        result = gate.review(no_trade_proposal)
        assert result.checks_performed["decision_consistent"] is True

    def test_find_critical_warnings(self, valid_core_criteria):
        """Critical warning keywords are detected."""
        gate = ReviewGate()

        # Test each keyword
        for keyword in ["HARD FAIL", "CRITICAL", "IMPOSSIBLE", "INVALID", "BLOCKING"]:
            warnings = (f"This is a {keyword} warning",)
            critical = gate._find_critical_warnings(warnings)
            assert len(critical) == 1

    def test_find_critical_warnings_case_insensitive(self):
        """Critical keywords are case-insensitive."""
        gate = ReviewGate()
        warnings = ("this is critical warning",)
        critical = gate._find_critical_warnings(warnings)
        assert len(critical) == 1

    def test_find_critical_warnings_no_match(self):
        """Non-critical warnings return empty list."""
        gate = ReviewGate()
        warnings = ("Minor issue", "Small problem")
        critical = gate._find_critical_warnings(warnings)
        assert len(critical) == 0

    def test_check_decision_consistency_trade_passing(self, valid_proposal):
        """TRADE with passing criteria is consistent."""
        gate = ReviewGate()
        assert gate._check_decision_consistency(valid_proposal) is True

    def test_check_decision_consistency_trade_failing(self, inconsistent_proposal):
        """TRADE with failing criteria is inconsistent."""
        gate = ReviewGate()
        assert gate._check_decision_consistency(inconsistent_proposal) is False

    def test_check_decision_consistency_no_trade(self, no_trade_proposal):
        """NO_TRADE is always consistent."""
        gate = ReviewGate()
        assert gate._check_decision_consistency(no_trade_proposal) is True

    def test_classify_all_pass(self):
        """All checks passing results in REVIEW_PASS."""
        gate = ReviewGate()
        checks = {
            "confidence_not_low": True,
            "edge_above_minimum": True,
            "all_core_criteria_passed": True,
            "no_critical_warnings": True,
            "decision_consistent": True,
            "warning_count_acceptable": True,
        }
        result = gate._classify(checks, edge_borderline=False, critical_warnings=False)
        assert result == ReviewOutcome.REVIEW_PASS

    def test_classify_critical_warnings(self):
        """Critical warnings result in REVIEW_HOLD."""
        gate = ReviewGate()
        checks = {
            "confidence_not_low": True,
            "edge_above_minimum": True,
            "all_core_criteria_passed": True,
            "no_critical_warnings": False,
            "decision_consistent": True,
            "warning_count_acceptable": True,
        }
        result = gate._classify(checks, edge_borderline=False, critical_warnings=True)
        assert result == ReviewOutcome.REVIEW_HOLD

    def test_classify_edge_borderline(self):
        """Borderline edge results in REVIEW_HOLD."""
        gate = ReviewGate()
        checks = {
            "confidence_not_low": True,
            "edge_above_minimum": False,
            "all_core_criteria_passed": True,
            "no_critical_warnings": True,
            "decision_consistent": True,
            "warning_count_acceptable": True,
        }
        result = gate._classify(checks, edge_borderline=True, critical_warnings=False)
        assert result == ReviewOutcome.REVIEW_HOLD

    def test_classify_low_confidence(self):
        """Low confidence results in REVIEW_REJECT."""
        gate = ReviewGate()
        checks = {
            "confidence_not_low": False,
            "edge_above_minimum": True,
            "all_core_criteria_passed": True,
            "no_critical_warnings": True,
            "decision_consistent": True,
            "warning_count_acceptable": True,
        }
        result = gate._classify(checks, edge_borderline=False, critical_warnings=False)
        assert result == ReviewOutcome.REVIEW_REJECT

    def test_classify_decision_inconsistent(self):
        """Inconsistent decision results in REVIEW_REJECT."""
        gate = ReviewGate()
        checks = {
            "confidence_not_low": True,
            "edge_above_minimum": True,
            "all_core_criteria_passed": True,
            "no_critical_warnings": True,
            "decision_consistent": False,
            "warning_count_acceptable": True,
        }
        result = gate._classify(checks, edge_borderline=False, critical_warnings=False)
        assert result == ReviewOutcome.REVIEW_REJECT

    def test_classify_multiple_failures_reject(self):
        """Multiple core failures result in REVIEW_REJECT."""
        gate = ReviewGate()
        checks = {
            "confidence_not_low": True,
            "edge_above_minimum": False,
            "all_core_criteria_passed": False,
            "no_critical_warnings": False,
            "decision_consistent": True,
            "warning_count_acceptable": True,
        }
        result = gate._classify(checks, edge_borderline=False, critical_warnings=False)
        assert result == ReviewOutcome.REVIEW_REJECT


class TestReviewProposalFunction:
    """Tests for review_proposal convenience function."""

    def test_review_proposal_function(self, valid_proposal):
        """review_proposal function works correctly."""
        result = review_proposal(valid_proposal)
        assert result.outcome == ReviewOutcome.REVIEW_PASS


# =============================================================================
# PROPOSAL GENERATOR TESTS
# =============================================================================

class TestProposalGenerator:
    """Tests for ProposalGenerator class."""

    def test_init(self):
        """ProposalGenerator can be initialized."""
        pg = ProposalGenerator()
        assert len(pg.REQUIRED_ANALYSIS_FIELDS) == 4

    def test_can_generate_missing_fields(self):
        """Missing required fields return False."""
        pg = ProposalGenerator()

        # Empty analysis
        can, reason = pg.can_generate({})
        assert can is False
        assert "Missing required field" in reason

        # Missing market_input
        can, reason = pg.can_generate({"final_decision": {}})
        assert can is False

    def test_can_generate_no_decision_outcome(self):
        """Missing decision outcome returns False."""
        pg = ProposalGenerator()
        analysis = {
            "final_decision": {},
            "market_input": {"market_title": "Test"},
            "probability_estimate": {},
            "market_sanity": {},
        }
        can, reason = pg.can_generate(analysis)
        assert can is False
        assert "No decision outcome" in reason

    def test_can_generate_invalid_outcome(self):
        """Invalid decision outcome returns False."""
        pg = ProposalGenerator()
        analysis = {
            "final_decision": {"outcome": "INVALID"},
            "market_input": {"market_title": "Test"},
            "probability_estimate": {},
            "market_sanity": {},
        }
        can, reason = pg.can_generate(analysis)
        assert can is False
        assert "Invalid decision outcome" in reason

    def test_can_generate_insufficient_data(self):
        """INSUFFICIENT_DATA does not generate proposal."""
        pg = ProposalGenerator()
        analysis = {
            "final_decision": {"outcome": "INSUFFICIENT_DATA"},
            "market_input": {"market_title": "Test"},
            "probability_estimate": {},
            "market_sanity": {},
        }
        can, reason = pg.can_generate(analysis)
        assert can is False
        assert "INSUFFICIENT_DATA" in reason

    def test_can_generate_missing_market_title(self):
        """Missing market title returns False."""
        pg = ProposalGenerator()
        analysis = {
            "final_decision": {"outcome": "TRADE"},
            "market_input": {},  # No market_title
            "probability_estimate": {},
            "market_sanity": {},
        }
        can, reason = pg.can_generate(analysis)
        assert can is False
        assert "Missing market title" in reason

    def test_can_generate_valid_trade(self):
        """Valid TRADE analysis can generate proposal."""
        pg = ProposalGenerator()
        analysis = {
            "final_decision": {"outcome": "TRADE"},
            "market_input": {"market_title": "Test Market"},
            "probability_estimate": {},
            "market_sanity": {},
        }
        can, reason = pg.can_generate(analysis)
        assert can is True
        assert "All requirements met" in reason

    def test_can_generate_valid_no_trade(self):
        """Valid NO_TRADE analysis can generate proposal."""
        pg = ProposalGenerator()
        analysis = {
            "final_decision": {"outcome": "NO_TRADE"},
            "market_input": {"market_title": "Test Market"},
            "probability_estimate": {},
            "market_sanity": {},
        }
        can, reason = pg.can_generate(analysis)
        assert can is True

    def test_generate_returns_none_for_invalid(self):
        """generate() returns None for invalid analysis."""
        pg = ProposalGenerator()
        result = pg.generate({})
        assert result is None

    def test_generate_creates_proposal(self):
        """generate() creates valid proposal from analysis."""
        pg = ProposalGenerator()
        analysis = {
            "final_decision": {
                "outcome": "TRADE",
                "criteria_met": {"delta_meets_threshold": True},
                "reasoning": "Strong edge detected",
            },
            "market_input": {
                "market_id": "test_123",
                "market_title": "Will EU pass AI Act?",
                "market_implied_probability": 0.50,
            },
            "probability_estimate": {
                "probability_midpoint": 0.70,
                "confidence_level": "HIGH",
                "reasoning": "Historical precedent strong",
            },
            "market_sanity": {
                "direction": "MARKET_TOO_LOW",
                "reasoning": "Market underpricing event",
            },
            "time_feasibility": {
                "is_timeline_feasible": True,
            },
            "resolution_analysis": {
                "is_binary": True,
                "is_objectively_verifiable": True,
                "hard_fail": False,
            },
        }
        proposal = pg.generate(analysis)
        assert proposal is not None
        assert proposal.decision == "TRADE"
        assert proposal.market_question == "Will EU pass AI Act?"
        assert proposal.implied_probability == 0.50
        assert proposal.model_probability == 0.70
        assert proposal.edge == pytest.approx(0.20)
        assert proposal.confidence_level == "HIGH"

    def test_generate_extracts_core_criteria(self):
        """generate() correctly extracts core criteria."""
        pg = ProposalGenerator()
        analysis = {
            "final_decision": {
                "outcome": "TRADE",
                "criteria_met": {"delta_meets_threshold": True},
            },
            "market_input": {"market_title": "Test"},
            "probability_estimate": {"confidence_level": "MEDIUM"},
            "market_sanity": {"direction": "UP"},
            "time_feasibility": {"is_timeline_feasible": True},
            "resolution_analysis": {
                "is_binary": True,
                "is_objectively_verifiable": True,
                "hard_fail": False,
            },
        }
        proposal = pg.generate(analysis)
        assert proposal.core_criteria.liquidity_ok is True
        assert proposal.core_criteria.time_to_resolution_ok is True
        assert proposal.core_criteria.data_quality_ok is True

    def test_generate_collects_warnings(self):
        """generate() collects warnings from analysis."""
        pg = ProposalGenerator()
        analysis = {
            "final_decision": {
                "outcome": "TRADE",
                "risk_warnings": ["Warning 1", "Warning 2"],
            },
            "market_input": {"market_title": "Test"},
            "probability_estimate": {"confidence_level": "MEDIUM"},
            "market_sanity": {"direction": "MARKET_TOO_LOW"},
        }
        proposal = pg.generate(analysis)
        assert len(proposal.warnings) >= 2
        assert "Warning 1" in proposal.warnings
        assert any("MARKET_TOO_LOW" in w for w in proposal.warnings)

    def test_generate_builds_justification(self):
        """generate() builds justification from reasoning."""
        pg = ProposalGenerator()
        analysis = {
            "final_decision": {
                "outcome": "TRADE",
                "reasoning": "Decision reasoning here",
            },
            "market_input": {"market_title": "Test"},
            "probability_estimate": {
                "reasoning": "Probability reasoning here",
                "confidence_level": "HIGH",
            },
            "market_sanity": {
                "reasoning": "Sanity reasoning here",
            },
        }
        proposal = pg.generate(analysis)
        assert "Decision reasoning" in proposal.justification_summary
        assert "Probability reasoning" in proposal.justification_summary

    def test_generate_handles_missing_optional_fields(self):
        """generate() handles missing optional fields gracefully."""
        pg = ProposalGenerator()
        analysis = {
            "final_decision": {"outcome": "TRADE"},
            "market_input": {"market_title": "Test"},
            "probability_estimate": {},
            "market_sanity": {},
        }
        proposal = pg.generate(analysis)
        assert proposal is not None
        assert proposal.confidence_level == "LOW"  # Default
        assert proposal.implied_probability == 0.0
        assert proposal.model_probability == 0.0

    def test_extract_core_criteria_all_false(self):
        """_extract_core_criteria returns all false for minimal input."""
        pg = ProposalGenerator()
        criteria = pg._extract_core_criteria({}, {}, {})
        assert criteria.liquidity_ok is False
        assert criteria.volume_ok is False
        assert criteria.time_to_resolution_ok is False
        assert criteria.data_quality_ok is False

    def test_extract_core_criteria_partial(self):
        """_extract_core_criteria handles partial data."""
        pg = ProposalGenerator()
        analysis = {
            "final_decision": {"criteria_met": {"delta_meets_threshold": True}},
            "market_sanity": {"some_data": True},
        }
        time_feas = {"is_timeline_feasible": True}
        res_analysis = {"is_binary": True, "is_objectively_verifiable": False}

        criteria = pg._extract_core_criteria(analysis, time_feas, res_analysis)
        assert criteria.liquidity_ok is True
        assert criteria.volume_ok is True
        assert criteria.time_to_resolution_ok is True
        assert criteria.data_quality_ok is False  # Not objectively verifiable

    def test_collect_warnings_empty(self):
        """_collect_warnings returns empty list for no warnings."""
        pg = ProposalGenerator()
        warnings = pg._collect_warnings({}, {})
        assert warnings == []

    def test_collect_warnings_combines_sources(self):
        """_collect_warnings combines warnings from all sources."""
        pg = ProposalGenerator()
        final_decision = {"risk_warnings": ["Risk 1", "Risk 2"]}
        market_sanity = {"direction": "UP"}
        warnings = pg._collect_warnings(final_decision, market_sanity)
        assert "Risk 1" in warnings
        assert "Risk 2" in warnings
        assert any("UP" in w for w in warnings)

    def test_build_justification_empty(self):
        """_build_justification returns default for empty input."""
        pg = ProposalGenerator()
        justification = pg._build_justification({}, {}, {})
        assert "No detailed justification" in justification

    def test_build_justification_truncates(self):
        """_build_justification truncates long reasoning."""
        pg = ProposalGenerator()
        long_reasoning = "A" * 500
        final_decision = {"reasoning": long_reasoning}
        justification = pg._build_justification(final_decision, {}, {})
        assert len(justification) <= 250  # 200 + buffer


class TestGenerateProposalFromAnalysis:
    """Tests for generate_proposal_from_analysis convenience function."""

    def test_function_works(self):
        """Convenience function generates proposal."""
        from proposals.generator import generate_proposal_from_analysis

        analysis = {
            "final_decision": {"outcome": "TRADE"},
            "market_input": {"market_title": "Test"},
            "probability_estimate": {"confidence_level": "MEDIUM"},
            "market_sanity": {},
        }
        proposal = generate_proposal_from_analysis(analysis)
        assert proposal is not None

    def test_function_returns_none_for_invalid(self):
        """Convenience function returns None for invalid input."""
        from proposals.generator import generate_proposal_from_analysis

        result = generate_proposal_from_analysis({})
        assert result is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
