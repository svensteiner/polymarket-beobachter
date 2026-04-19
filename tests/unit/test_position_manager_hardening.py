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


def test_stop_loss_fires_at_minus_41_pct(monkeypatch):
    """SL bei -40% Threshold muss bei -41% exakt feuern.

    Regression-Test fuer den Snapshot-Bug: wenn Snapshots fehlen koennen
    SL-Exits nicht ausfuehren. Dieser Test stellt sicher dass die
    Position-Manager-Logik korrekt ist — Snapshot-Abruf separat testen.
    """
    from paper_trader import position_manager as pm

    # market_type="unknown" to bypass resolution-hold (which suppresses SL for
    # at_or_above/at_or_below/exact/between YES positions within 48h of resolution).
    # This tests the core -40% SL logic independently.
    position = PaperPosition(
        position_id="POS-SL",
        proposal_id="PROP-SL",
        market_id="MKT-SL",
        market_question="Will the highest temperature in Dallas be 71°F or below on April 20?",
        side="YES",
        status="OPEN",
        entry_time="2026-04-19T06:00:00+00:00",
        entry_price=0.50,
        entry_slippage=0.00,
        size_contracts=20.0,
        cost_basis_eur=10.0,
        exit_time=None,
        exit_price=None,
        exit_slippage=None,
        exit_reason=None,
        realized_pnl_eur=None,
        pnl_pct=None,
        hours_to_resolution=42.0,
        market_type="unknown",  # Bypasses resolution-hold (only active for known binary types)
    )

    # -41% drop: YES price at entry was 0.50, drops to 0.295
    # unrealized = (0.295 - 0.50) / 0.50 = -41% → below -40% SL threshold
    sl_snapshot = MarketSnapshot(
        market_id="MKT-SL",
        snapshot_time="2026-04-19T10:00:00Z",
        best_bid=0.28,
        best_ask=0.32,
        mid_price=0.295,  # -41% from 0.50 entry
        spread_pct=3.5,
        liquidity_bucket="HIGH",
        is_resolved=False,
        resolved_outcome=None,
    )

    fake_logger = MagicMock()
    fake_logger.get_open_positions.return_value = [position]
    monkeypatch.setattr(pm, "get_paper_logger", lambda: fake_logger)
    monkeypatch.setattr(pm, "log_trade", lambda record: None)
    monkeypatch.setattr(pm, "release_capital", lambda *args, **kwargs: None)
    monkeypatch.setattr(pm, "get_market_snapshots", lambda market_ids: {"MKT-SL": sl_snapshot})
    monkeypatch.setattr(pm, "record_sl_cooloff", lambda market_id: None)
    monkeypatch.setattr("paper_trader.position_manager._load_tp_state", lambda: {})
    monkeypatch.setattr("paper_trader.position_manager._save_tp_state", lambda state: None)
    # log_position is imported inside _full_exit_remaining — patch at source module
    import paper_trader.logger as _logger_mod
    monkeypatch.setattr(_logger_mod, "log_position", lambda pos: None)
    import paper_trader.simulator as _sim_mod
    monkeypatch.setattr(_sim_mod, "log_position", lambda pos: None)
    monkeypatch.setattr(_sim_mod, "log_trade", lambda record: None)
    monkeypatch.setattr(_sim_mod, "release_capital", lambda *args, **kwargs: None)

    manager = PositionManager()
    summary = manager.check_mid_trade_exits()

    # SL should have fired: 1 stop_loss exit
    assert summary["checked"] == 1, f"Expected 1 checked, got {summary['checked']}"
    assert summary["stop_loss"] == 1, (
        f"Expected 1 SL exit at -41% (threshold -40%), got {summary['stop_loss']}. "
        f"Summary: {summary}"
    )
    assert summary["take_profit"] == 0, f"TP should not fire, got {summary['take_profit']}"
    assert summary["pnl_eur"] < 0, f"SL exit should have negative PnL, got {summary['pnl_eur']}"


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
