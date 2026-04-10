from unittest.mock import MagicMock, patch

import pytest

from paper_trader.models import MarketSnapshot, PaperPosition
from paper_trader.position_manager import PositionManager


def _make_position() -> PaperPosition:
    return PaperPosition(
        position_id="POS-1",
        proposal_id="PROP-1",
        market_id="MKT-1",
        market_question="Will the highest temperature in Seattle be 70F or above on March 20?",
        side="YES",
        status="OPEN",
        entry_time="2026-04-10T00:00:00Z",
        entry_price=0.50,
        entry_slippage=0.00,
        size_contracts=100.0,
        cost_basis_eur=50.0,
        exit_time=None,
        exit_price=None,
        exit_slippage=None,
        exit_reason=None,
        realized_pnl_eur=None,
        pnl_pct=None,
    )


@pytest.fixture
def manager(monkeypatch):
    from paper_trader import position_manager as pm

    fake_logger = MagicMock()
    fake_logger.get_open_positions.return_value = [_make_position()]
    monkeypatch.setattr(pm, "get_paper_logger", lambda: fake_logger)
    monkeypatch.setattr(pm, "log_trade", lambda record: None)
    monkeypatch.setattr(pm, "release_capital", lambda *args, **kwargs: None)
    return PositionManager()


def test_mid_trade_exits_skip_low_liquidity(manager, monkeypatch):
    from paper_trader import position_manager as pm

    low_liquidity_snapshot = MarketSnapshot(
        market_id="MKT-1",
        snapshot_time="2026-04-10T00:00:00Z",
        best_bid=0.49,
        best_ask=0.51,
        mid_price=0.60,
        spread_pct=8.0,
        liquidity_bucket="LOW",
        is_resolved=False,
        resolved_outcome=None,
    )

    monkeypatch.setattr(pm, "get_market_snapshots", lambda market_ids: {"MKT-1": low_liquidity_snapshot})

    summary = manager.check_mid_trade_exits()

    assert summary["checked"] == 1
    assert summary["take_profit"] == 0
    assert summary["stop_loss"] == 0


def test_mid_trade_exits_skip_boundary_prices(manager, monkeypatch):
    from paper_trader import position_manager as pm

    boundary_snapshot = MarketSnapshot(
        market_id="MKT-1",
        snapshot_time="2026-04-10T00:00:00Z",
        best_bid=0.97,
        best_ask=0.99,
        mid_price=0.98,
        spread_pct=2.0,
        liquidity_bucket="HIGH",
        is_resolved=False,
        resolved_outcome=None,
    )

    monkeypatch.setattr(pm, "get_market_snapshots", lambda market_ids: {"MKT-1": boundary_snapshot})

    summary = manager.check_mid_trade_exits()

    assert summary["checked"] == 1
    assert summary["take_profit"] == 0
    assert summary["stop_loss"] == 0
