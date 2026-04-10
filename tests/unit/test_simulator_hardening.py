import types
from unittest.mock import MagicMock, patch

import pytest

from proposals.models import Proposal, ProposalCoreCriteria
from paper_trader.models import MarketSnapshot


def _make_proposal(
    *,
    decision: str = "TRADE",
    edge: float = 0.10,
    confidence_level: str = "MEDIUM",
    core_ok: bool = True,
    market_question: str = "Will the highest temperature in Seattle be 70F or above on March 20?",
) -> Proposal:
    core_criteria = ProposalCoreCriteria(
        liquidity_ok=core_ok,
        volume_ok=core_ok,
        time_to_resolution_ok=core_ok,
        data_quality_ok=core_ok,
    )
    return Proposal(
        proposal_id="PROP-1",
        timestamp="2026-04-10T00:00:00Z",
        market_id="MKT-1",
        market_question=market_question,
        decision=decision,
        implied_probability=0.40,
        model_probability=0.40 + edge,
        edge=edge,
        core_criteria=core_criteria,
        warnings=(),
        confidence_level=confidence_level,
        justification_summary="test",
    )


def _make_snapshot(*, liquidity_bucket: str = "HIGH", mid_price: float = 0.50) -> MarketSnapshot:
    return MarketSnapshot(
        market_id="MKT-1",
        snapshot_time="2026-04-10T00:00:00Z",
        best_bid=max(0.01, mid_price - 0.01),
        best_ask=min(0.99, mid_price + 0.01),
        mid_price=mid_price,
        spread_pct=2.0,
        liquidity_bucket=liquidity_bucket,
        is_resolved=False,
        resolved_outcome=None,
    )


@pytest.fixture
def simulator(monkeypatch):
    from paper_trader import simulator as sim

    fake_logger = MagicMock()
    fake_logger.get_open_positions.return_value = []

    fake_capital_manager = MagicMock()
    fake_capital_manager.get_position_size.return_value = 100.0
    fake_capital_manager.can_open_position.return_value = (True, "OK")
    fake_capital_manager.get_state.return_value = types.SimpleNamespace(available_capital_eur=10_000.0)

    monkeypatch.setattr(sim, "get_paper_logger", lambda: fake_logger)
    monkeypatch.setattr(sim, "get_capital_manager", lambda: fake_capital_manager)
    monkeypatch.setattr(sim, "check_can_open_position", lambda: (True, "OK"))
    monkeypatch.setattr(sim, "check_can_open_entry", lambda **kwargs: (True, "OK"))
    monkeypatch.setattr(sim, "evaluate_high_conviction_exception", lambda proposal, entry_price=None: (False, "no"))
    monkeypatch.setattr(sim, "assess_proposal_edge", lambda proposal, market_type=None: {"allowed": True, "bucket": "medium", "position_scale": 1.0, "reason": "ok"})
    monkeypatch.setattr(sim, "get_market_snapshot", lambda market_id: _make_snapshot())
    monkeypatch.setattr(sim, "calculate_entry_price", lambda snapshot, side: (0.51, 0.01))
    monkeypatch.setattr(sim, "allocate_capital", lambda amount, reason: True)
    monkeypatch.setattr(sim, "log_trade", lambda record: None)
    monkeypatch.setattr(sim, "log_position", lambda position: None)
    return sim.ExecutionSimulator()


def test_entry_rejects_failed_core_criteria(simulator):
    proposal = _make_proposal(core_ok=False)

    position, record = simulator.simulate_entry(proposal)

    assert position is None
    assert record.action == "SKIP"
    assert "Core criteria failed" in record.reason


def test_entry_rejects_weak_edge_even_when_quality_is_good(simulator):
    proposal = _make_proposal(edge=0.06, confidence_level="HIGH")

    position, record = simulator.simulate_entry(proposal)

    assert position is None
    assert record.action == "SKIP"
    assert "edge" in record.reason.lower()


def test_entry_rejects_unknown_market_with_too_little_edge(monkeypatch):
    from paper_trader import simulator as sim

    fake_logger = MagicMock()
    fake_logger.get_open_positions.return_value = []

    fake_capital_manager = MagicMock()
    fake_capital_manager.get_position_size.return_value = 100.0
    fake_capital_manager.can_open_position.return_value = (True, "OK")
    fake_capital_manager.get_state.return_value = types.SimpleNamespace(available_capital_eur=10_000.0)

    monkeypatch.setattr(sim, "get_paper_logger", lambda: fake_logger)
    monkeypatch.setattr(sim, "get_capital_manager", lambda: fake_capital_manager)
    monkeypatch.setattr(sim, "check_can_open_position", lambda: (True, "OK"))
    monkeypatch.setattr(sim, "check_can_open_entry", lambda **kwargs: (True, "OK"))
    monkeypatch.setattr(sim, "evaluate_high_conviction_exception", lambda proposal, entry_price=None: (False, "no"))
    monkeypatch.setattr(sim, "assess_proposal_edge", lambda proposal, market_type=None: {"allowed": True, "bucket": "medium", "position_scale": 1.0, "reason": "ok"})
    monkeypatch.setattr(sim, "get_market_snapshot", lambda market_id: _make_snapshot())
    monkeypatch.setattr(sim, "calculate_entry_price", lambda snapshot, side: (0.51, 0.01))
    monkeypatch.setattr(sim, "allocate_capital", lambda amount, reason: True)
    monkeypatch.setattr(sim, "log_trade", lambda record: None)
    monkeypatch.setattr(sim, "log_position", lambda position: None)

    simulator = sim.ExecutionSimulator()
    proposal = _make_proposal(edge=0.10, confidence_level="HIGH", market_question="Will this be a surprise outcome?")

    position, record = simulator.simulate_entry(proposal)

    assert position is None
    assert record.action == "SKIP"
    assert "unknown market type" in record.reason.lower()
