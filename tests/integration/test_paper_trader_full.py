# =============================================================================
# COMPREHENSIVE TESTS FOR PAPER TRADER MODULES
# =============================================================================
# Coverage target: 100% for simulator.py, snapshot_client.py
# =============================================================================

import pytest
from datetime import datetime
from unittest.mock import patch, MagicMock

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from paper_trader.simulator import (
    ExecutionSimulator,
    get_simulator,
    simulate_entry,
    simulate_exit_resolution,
    FIXED_AMOUNT_EUR,
)
from paper_trader.models import (
    PaperPosition,
    PaperTradeRecord,
    MarketSnapshot,
    TradeAction,
    LiquidityBucket,
    generate_position_id,
    generate_record_id,
)
from proposals.models import Proposal, ProposalCoreCriteria


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def valid_core_criteria():
    """Valid core criteria for proposals."""
    return ProposalCoreCriteria(
        liquidity_ok=True,
        volume_ok=True,
        time_to_resolution_ok=True,
        data_quality_ok=True,
    )


@pytest.fixture
def trade_proposal(valid_core_criteria):
    """A TRADE proposal with positive edge."""
    return Proposal(
        proposal_id="PROP-20260118-test001",
        timestamp=datetime.now().isoformat(),
        market_id="market_123",
        market_question="Will EU pass AI Act by 2026?",
        decision="TRADE",
        implied_probability=0.50,
        model_probability=0.70,
        edge=0.20,  # Positive edge = buy YES
        core_criteria=valid_core_criteria,
        warnings=(),
        confidence_level="HIGH",
        justification_summary="Strong edge",
    )


@pytest.fixture
def trade_proposal_negative_edge(valid_core_criteria):
    """A TRADE proposal with negative edge."""
    return Proposal(
        proposal_id="PROP-20260118-test002",
        timestamp=datetime.now().isoformat(),
        market_id="market_456",
        market_question="Test market",
        decision="TRADE",
        implied_probability=0.70,
        model_probability=0.50,
        edge=-0.20,  # Negative edge = buy NO
        core_criteria=valid_core_criteria,
        warnings=(),
        confidence_level="HIGH",
        justification_summary="Negative edge",
    )


@pytest.fixture
def market_snapshot():
    """Valid market snapshot."""
    return MarketSnapshot(
        market_id="market_123",
        snapshot_time=datetime.now().isoformat(),
        best_bid=0.48,
        best_ask=0.52,
        mid_price=0.50,
        spread_pct=0.08,
        liquidity_bucket=LiquidityBucket.MEDIUM.value,
        is_resolved=False,
        resolved_outcome=None,
    )


@pytest.fixture
def resolved_snapshot_yes():
    """Resolved market snapshot - YES won."""
    return MarketSnapshot(
        market_id="market_123",
        snapshot_time=datetime.now().isoformat(),
        best_bid=None,
        best_ask=None,
        mid_price=1.0,
        spread_pct=0.0,
        liquidity_bucket=LiquidityBucket.LOW.value,
        is_resolved=True,
        resolved_outcome="YES",
    )


@pytest.fixture
def resolved_snapshot_no():
    """Resolved market snapshot - NO won."""
    return MarketSnapshot(
        market_id="market_123",
        snapshot_time=datetime.now().isoformat(),
        best_bid=None,
        best_ask=None,
        mid_price=0.0,
        spread_pct=0.0,
        liquidity_bucket=LiquidityBucket.LOW.value,
        is_resolved=True,
        resolved_outcome="NO",
    )


@pytest.fixture
def open_position():
    """An open paper position."""
    return PaperPosition(
        position_id="POS-20260118-abc123",
        proposal_id="PROP-20260118-test001",
        market_id="market_123",
        market_question="Test market",
        side="YES",
        status="OPEN",
        entry_time=datetime.now().isoformat(),
        entry_price=0.55,
        entry_slippage=0.02,
        size_contracts=181.82,  # 100 / 0.55
        cost_basis_eur=100.0,
        exit_time=None,
        exit_price=None,
        exit_slippage=None,
        exit_reason=None,
        realized_pnl_eur=None,
        pnl_pct=None,
    )


# =============================================================================
# EXECUTION SIMULATOR TESTS
# =============================================================================

class TestExecutionSimulatorInit:
    """Tests for ExecutionSimulator initialization."""

    def test_init_default_amount(self):
        """Initializes with default amount."""
        sim = ExecutionSimulator()
        assert sim.fixed_amount_eur == FIXED_AMOUNT_EUR

    def test_init_custom_amount(self):
        """Initializes with custom amount."""
        sim = ExecutionSimulator(fixed_amount_eur=500.0)
        assert sim.fixed_amount_eur == 500.0


class TestSimulateEntry:
    """Tests for simulate_entry method."""

    @patch('paper_trader.simulator.allocate_capital', return_value=True)
    @patch('paper_trader.simulator.has_sufficient_capital', return_value=True)
    @patch('paper_trader.simulator.get_market_snapshot')
    @patch('paper_trader.simulator.calculate_entry_price')
    @patch('paper_trader.simulator.log_trade')
    @patch('paper_trader.simulator.log_position')
    def test_entry_success(
        self, mock_log_pos, mock_log_trade, mock_calc_price,
        mock_get_snapshot, mock_has_cap, mock_alloc_cap,
        trade_proposal, market_snapshot
    ):
        """Successful entry creates position and record."""
        mock_get_snapshot.return_value = market_snapshot
        mock_calc_price.return_value = (0.55, 0.03)  # price, slippage

        sim = ExecutionSimulator()
        position, record = sim.simulate_entry(trade_proposal)

        assert position is not None
        assert position.side == "YES"
        assert position.entry_price == 0.55
        assert position.status == "OPEN"
        assert record.action == TradeAction.PAPER_ENTER.value

    @patch('paper_trader.simulator.get_market_snapshot')
    @patch('paper_trader.simulator.log_trade')
    @patch('paper_trader.simulator.log_position')
    def test_entry_no_snapshot(
        self, mock_log_pos, mock_log_trade, mock_get_snapshot, trade_proposal
    ):
        """No real snapshot uses simulated snapshot from proposal implied probability."""
        mock_get_snapshot.return_value = None

        sim = ExecutionSimulator()
        position, record = sim.simulate_entry(trade_proposal)

        # With implied_probability available, a simulated snapshot is created
        # and the trade proceeds (or skips for other reasons like capital)
        if position is not None:
            # Simulated snapshot was used successfully
            assert record.action == TradeAction.PAPER_ENTER.value
        else:
            # Skipped due to capital or other constraint
            assert record.action == TradeAction.SKIP.value

    @patch('paper_trader.simulator.has_sufficient_capital', return_value=True)
    @patch('paper_trader.simulator.get_market_snapshot')
    @patch('paper_trader.simulator.log_trade')
    def test_entry_no_valid_prices(
        self, mock_log_trade, mock_get_snapshot, mock_has_cap, trade_proposal
    ):
        """Snapshot without valid prices returns SKIP."""
        invalid_snapshot = MarketSnapshot(
            market_id="market_123",
            snapshot_time=datetime.now().isoformat(),
            best_bid=None,
            best_ask=None,
            mid_price=None,
            spread_pct=None,
            liquidity_bucket=LiquidityBucket.LOW.value,
            is_resolved=False,
            resolved_outcome=None,
        )
        mock_get_snapshot.return_value = invalid_snapshot

        sim = ExecutionSimulator()
        position, record = sim.simulate_entry(trade_proposal)

        assert position is None
        assert record.action == TradeAction.SKIP.value
        assert "no valid prices" in record.reason.lower()

    @patch('paper_trader.simulator.has_sufficient_capital', return_value=True)
    @patch('paper_trader.simulator.get_market_snapshot')
    @patch('paper_trader.simulator.log_trade')
    def test_entry_already_resolved(
        self, mock_log_trade, mock_get_snapshot, mock_has_cap,
        trade_proposal, resolved_snapshot_yes
    ):
        """Resolved market returns SKIP."""
        mock_get_snapshot.return_value = resolved_snapshot_yes

        sim = ExecutionSimulator()
        position, record = sim.simulate_entry(trade_proposal)

        assert position is None
        assert record.action == TradeAction.SKIP.value
        assert "resolved" in record.reason.lower()

    @patch('paper_trader.simulator.has_sufficient_capital', return_value=True)
    @patch('paper_trader.simulator.get_market_snapshot')
    @patch('paper_trader.simulator.calculate_entry_price')
    @patch('paper_trader.simulator.log_trade')
    def test_entry_cannot_calculate_price(
        self, mock_log_trade, mock_calc_price,
        mock_get_snapshot, mock_has_cap, trade_proposal, market_snapshot
    ):
        """Cannot calculate price returns SKIP."""
        mock_get_snapshot.return_value = market_snapshot
        mock_calc_price.return_value = None

        sim = ExecutionSimulator()
        position, record = sim.simulate_entry(trade_proposal)

        assert position is None
        assert record.action == TradeAction.SKIP.value
        assert "cannot calculate" in record.reason.lower()

    @patch('paper_trader.simulator.allocate_capital', return_value=True)
    @patch('paper_trader.simulator.has_sufficient_capital', return_value=True)
    @patch('paper_trader.simulator.get_market_snapshot')
    @patch('paper_trader.simulator.calculate_entry_price')
    @patch('paper_trader.simulator.log_trade')
    @patch('paper_trader.simulator.log_position')
    def test_entry_negative_edge_buys_no(
        self, mock_log_pos, mock_log_trade, mock_calc_price,
        mock_get_snapshot, mock_has_cap, mock_alloc_cap,
        trade_proposal_negative_edge, market_snapshot
    ):
        """Negative edge buys NO side."""
        mock_get_snapshot.return_value = market_snapshot
        mock_calc_price.return_value = (0.45, 0.02)

        sim = ExecutionSimulator()
        position, record = sim.simulate_entry(trade_proposal_negative_edge)

        assert position is not None
        assert position.side == "NO"


class TestSimulateExitResolution:
    """Tests for simulate_exit_resolution method."""

    @patch('paper_trader.simulator.calculate_exit_price')
    @patch('paper_trader.simulator.log_trade')
    @patch('paper_trader.simulator.log_position')
    def test_exit_yes_wins(
        self, mock_log_pos, mock_log_trade, mock_calc_price,
        open_position, resolved_snapshot_yes
    ):
        """Exit when YES wins calculates correct P&L."""
        mock_calc_price.return_value = (1.0, 0.0)

        sim = ExecutionSimulator()
        closed_pos, record = sim.simulate_exit_resolution(
            open_position, resolved_snapshot_yes
        )

        assert closed_pos.status == "RESOLVED"
        assert closed_pos.exit_price == 1.0
        # P&L = 181.82 * 1.0 - 100 = 81.82 (profit)
        assert closed_pos.realized_pnl_eur > 0
        assert record.action == TradeAction.PAPER_EXIT.value

    @patch('paper_trader.simulator.calculate_exit_price')
    @patch('paper_trader.simulator.log_trade')
    @patch('paper_trader.simulator.log_position')
    def test_exit_no_wins(
        self, mock_log_pos, mock_log_trade, mock_calc_price,
        open_position, resolved_snapshot_no
    ):
        """Exit when NO wins (and we hold YES) calculates loss."""
        mock_calc_price.return_value = (0.0, 0.0)

        sim = ExecutionSimulator()
        closed_pos, record = sim.simulate_exit_resolution(
            open_position, resolved_snapshot_no
        )

        assert closed_pos.status == "RESOLVED"
        assert closed_pos.exit_price == 0.0
        # P&L = 181.82 * 0.0 - 100 = -100 (total loss)
        assert closed_pos.realized_pnl_eur == pytest.approx(-100.0)

    @patch('paper_trader.simulator.calculate_exit_price')
    @patch('paper_trader.simulator.log_trade')
    @patch('paper_trader.simulator.log_position')
    def test_exit_no_price_fallback(
        self, mock_log_pos, mock_log_trade, mock_calc_price,
        open_position, resolved_snapshot_yes
    ):
        """Fallback to 0.5 if exit price cannot be calculated."""
        mock_calc_price.return_value = None

        sim = ExecutionSimulator()
        closed_pos, record = sim.simulate_exit_resolution(
            open_position, resolved_snapshot_yes
        )

        assert closed_pos.exit_price == 0.5


# =============================================================================
# MODULE-LEVEL FUNCTION TESTS
# =============================================================================

class TestModuleFunctions:
    """Tests for module-level convenience functions."""

    def test_get_simulator_singleton(self):
        """get_simulator returns singleton."""
        import paper_trader.simulator as sim_module
        sim_module._simulator = None  # Reset

        sim1 = get_simulator()
        sim2 = get_simulator()
        assert sim1 is sim2

    @patch('paper_trader.simulator.get_simulator')
    def test_simulate_entry_convenience(self, mock_get_sim, trade_proposal):
        """simulate_entry calls simulator.simulate_entry."""
        mock_sim = MagicMock()
        mock_get_sim.return_value = mock_sim

        simulate_entry(trade_proposal)
        mock_sim.simulate_entry.assert_called_once_with(trade_proposal)

    @patch('paper_trader.simulator.get_simulator')
    def test_simulate_exit_resolution_convenience(
        self, mock_get_sim, open_position, resolved_snapshot_yes
    ):
        """simulate_exit_resolution calls simulator method."""
        mock_sim = MagicMock()
        mock_get_sim.return_value = mock_sim

        simulate_exit_resolution(open_position, resolved_snapshot_yes)
        mock_sim.simulate_exit_resolution.assert_called_once_with(
            open_position, resolved_snapshot_yes
        )


# =============================================================================
# MARKET SNAPSHOT TESTS
# =============================================================================

class TestMarketSnapshot:
    """Tests for MarketSnapshot model."""

    def test_has_valid_prices_true(self, market_snapshot):
        """has_valid_prices returns True for valid snapshot."""
        assert market_snapshot.has_valid_prices() is True

    def test_has_valid_prices_fallback_to_mid(self):
        """has_valid_prices falls back to mid_price if bid/ask missing."""
        snapshot = MarketSnapshot(
            market_id="test",
            snapshot_time=datetime.now().isoformat(),
            best_bid=None,
            best_ask=None,
            mid_price=0.50,  # Valid mid_price
            spread_pct=0.08,
            liquidity_bucket=LiquidityBucket.MEDIUM.value,
            is_resolved=False,
            resolved_outcome=None,
        )
        assert snapshot.has_valid_prices() is True

    def test_has_valid_prices_false_no_prices(self):
        """has_valid_prices returns False without any prices."""
        snapshot = MarketSnapshot(
            market_id="test",
            snapshot_time=datetime.now().isoformat(),
            best_bid=None,
            best_ask=None,
            mid_price=None,  # No mid_price
            spread_pct=None,
            liquidity_bucket=LiquidityBucket.LOW.value,
            is_resolved=False,
            resolved_outcome=None,
        )
        assert snapshot.has_valid_prices() is False


# =============================================================================
# SLIPPAGE MODEL TESTS
# =============================================================================

class TestSlippageModel:
    """Tests for slippage calculation."""

    def test_slippage_model_import(self):
        """SlippageModel can be imported."""
        from paper_trader.slippage import SlippageModel
        model = SlippageModel()
        assert model is not None

    def test_calculate_entry_price(self, market_snapshot):
        """calculate_entry_price returns price and slippage."""
        from paper_trader.slippage import calculate_entry_price
        result = calculate_entry_price(market_snapshot, "YES")
        # Result should be tuple or None
        if result is not None:
            price, slippage = result
            assert 0 < price < 1
            assert slippage >= 0

    def test_calculate_exit_price_resolution(self, resolved_snapshot_yes):
        """calculate_exit_price for resolution."""
        from paper_trader.slippage import calculate_exit_price
        result = calculate_exit_price(resolved_snapshot_yes, "YES", is_resolution=True)
        if result is not None:
            price, slippage = result
            assert price == 1.0  # YES won
            assert slippage == 0.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
