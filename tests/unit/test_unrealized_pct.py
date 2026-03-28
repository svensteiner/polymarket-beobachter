"""
Unit tests for PositionManager._calc_unrealized_pct and _calc_trailing_stop_price.

These tests verify the fix for the NO-position bug where entry_price is stored
in NO terms (1 - YES_price) but snapshot.mid_price is always the YES price.
The old code compared them directly, giving nonsense results.
"""

import pytest
from unittest.mock import patch, MagicMock

from paper_trader.models import PaperPosition
from paper_trader.position_manager import PositionManager


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_position(side: str, entry_price: float) -> PaperPosition:
    """Create a minimal PaperPosition for testing."""
    return PaperPosition(
        position_id="TEST-001",
        proposal_id="PROP-001",
        market_id="MKT-001",
        market_question="Test market?",
        side=side,
        status="OPEN",
        entry_time="2026-03-28T00:00:00Z",
        entry_price=entry_price,
        entry_slippage=0.0,
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
def manager():
    """Create a PositionManager with mocked logger dependency."""
    with patch("paper_trader.position_manager.get_paper_logger"):
        return PositionManager()


# ===========================================================================
# _calc_unrealized_pct tests
# ===========================================================================

class TestCalcUnrealizedPct:
    """Tests for the unrealized P&L percentage calculation."""

    def test_yes_position_gaining(self, manager):
        """YES position: entry=0.50, current YES mid=0.60 -> +20%."""
        pos = _make_position("YES", entry_price=0.50)
        result = manager._calc_unrealized_pct(pos, current_price=0.60)
        assert result == pytest.approx(0.20, abs=1e-6)

    def test_yes_position_losing(self, manager):
        """YES position: entry=0.50, current YES mid=0.40 -> -20%."""
        pos = _make_position("YES", entry_price=0.50)
        result = manager._calc_unrealized_pct(pos, current_price=0.40)
        assert result == pytest.approx(-0.20, abs=1e-6)

    def test_no_position_gaining(self, manager):
        """NO position: entry=0.70 NO (YES was 0.30), current YES mid=0.20 (NO=0.80) -> +14.3%."""
        pos = _make_position("NO", entry_price=0.70)
        # Current YES mid = 0.20 => current NO price = 0.80
        # Unrealized = (0.80 - 0.70) / 0.70 = +0.142857...
        result = manager._calc_unrealized_pct(pos, current_price=0.20)
        assert result == pytest.approx(0.142857, abs=1e-4)

    def test_no_position_losing(self, manager):
        """NO position: entry=0.70 NO (YES was 0.30), current YES mid=0.40 (NO=0.60) -> -14.3%."""
        pos = _make_position("NO", entry_price=0.70)
        # Current YES mid = 0.40 => current NO price = 0.60
        # Unrealized = (0.60 - 0.70) / 0.70 = -0.142857...
        result = manager._calc_unrealized_pct(pos, current_price=0.40)
        assert result == pytest.approx(-0.142857, abs=1e-4)

    def test_no_position_bug_case_moderate(self, manager):
        """
        BUG case: entry=0.7725 NO, current YES mid=0.26.

        BUGGY (old code comparing YES mid directly with NO entry):
            (0.26 - 0.7725) / 0.7725 = -0.663 ... wrong sign and magnitude.
        CORRECT:
            current NO = 1.0 - 0.26 = 0.74
            (0.74 - 0.7725) / 0.7725 = -0.04207...  (~-4.2%)
        """
        pos = _make_position("NO", entry_price=0.7725)
        result = manager._calc_unrealized_pct(pos, current_price=0.26)
        expected = (0.74 - 0.7725) / 0.7725  # -0.04207...
        assert result == pytest.approx(expected, abs=1e-4)
        # Confirm it is a small loss, not the buggy +66% or -66%
        assert -0.10 < result < 0.0

    def test_no_position_bug_case_stop_loss(self, manager):
        """
        SL BUG case: entry=0.1472 NO, current YES mid=0.87.

        BUGGY (old code):
            (0.87 - 0.1472) / 0.1472 = +4.91 ... completely wrong (+491%).
        CORRECT:
            current NO = 1.0 - 0.87 = 0.13
            (0.13 - 0.1472) / 0.1472 = -0.1168...  (~-11.7%)
        """
        pos = _make_position("NO", entry_price=0.1472)
        result = manager._calc_unrealized_pct(pos, current_price=0.87)
        expected = (0.13 - 0.1472) / 0.1472  # -0.11684...
        assert result == pytest.approx(expected, abs=1e-4)
        # Confirm it is a moderate loss, not the buggy -487% or +491%
        assert -0.20 < result < 0.0

    def test_zero_entry_price_returns_zero(self, manager):
        """Edge case: entry_price=0 should return 0.0 to avoid division by zero."""
        pos = _make_position("YES", entry_price=0.0)
        result = manager._calc_unrealized_pct(pos, current_price=0.50)
        assert result == 0.0

    def test_yes_position_breakeven(self, manager):
        """YES position at break-even: entry=0.50, current=0.50 -> 0%."""
        pos = _make_position("YES", entry_price=0.50)
        result = manager._calc_unrealized_pct(pos, current_price=0.50)
        assert result == pytest.approx(0.0, abs=1e-6)

    def test_no_position_breakeven(self, manager):
        """NO position at break-even: entry=0.70 NO, current YES=0.30 -> 0%."""
        pos = _make_position("NO", entry_price=0.70)
        result = manager._calc_unrealized_pct(pos, current_price=0.30)
        assert result == pytest.approx(0.0, abs=1e-6)


# ===========================================================================
# _calc_trailing_stop_price tests
# ===========================================================================

class TestCalcTrailingStopPrice:
    """Tests for the trailing stop price calculation."""

    def test_yes_trailing_stop_breakeven(self, manager):
        """YES: entry=0.50, lock_in=0.0 -> stop=0.50 (YES must stay above 0.50)."""
        pos = _make_position("YES", entry_price=0.50)
        result = manager._calc_trailing_stop_price(pos, lock_in_pct=0.0)
        assert result == pytest.approx(0.50, abs=1e-6)

    def test_no_trailing_stop_breakeven(self, manager):
        """
        NO: entry=0.70 NO, lock_in=0.0 -> stop=0.30 (YES threshold).

        Trigger condition: YES > 0.30 means NO < 0.70, i.e., position is losing.
        At break-even: stop = 1.0 - 0.70 * 1.0 = 0.30.
        """
        pos = _make_position("NO", entry_price=0.70)
        result = manager._calc_trailing_stop_price(pos, lock_in_pct=0.0)
        assert result == pytest.approx(0.30, abs=1e-6)

    def test_no_trailing_stop_with_lockin(self, manager):
        """
        NO: entry=0.70 NO, lock_in=0.05 -> stop = 1.0 - 0.70*1.05 = 0.265.

        With 5% lock-in, the NO price must stay above 0.70*1.05=0.735,
        so YES must stay below 1.0 - 0.735 = 0.265.
        """
        pos = _make_position("NO", entry_price=0.70)
        result = manager._calc_trailing_stop_price(pos, lock_in_pct=0.05)
        expected = 1.0 - 0.70 * 1.05  # 0.265
        assert result == pytest.approx(expected, abs=1e-6)

    def test_yes_trailing_stop_with_lockin(self, manager):
        """YES: entry=0.50, lock_in=0.10 -> stop=0.55 (locks in 10% gain)."""
        pos = _make_position("YES", entry_price=0.50)
        result = manager._calc_trailing_stop_price(pos, lock_in_pct=0.10)
        assert result == pytest.approx(0.55, abs=1e-6)

    def test_no_trailing_stop_high_lockin(self, manager):
        """NO: entry=0.80, lock_in=0.10 -> stop = 1.0 - 0.80*1.10 = 0.12."""
        pos = _make_position("NO", entry_price=0.80)
        result = manager._calc_trailing_stop_price(pos, lock_in_pct=0.10)
        expected = 1.0 - 0.80 * 1.10  # 0.12
        assert result == pytest.approx(expected, abs=1e-6)

    def test_yes_stop_direction(self, manager):
        """YES stop is always below or at entry (for lock_in >= 0)."""
        pos = _make_position("YES", entry_price=0.60)
        stop = manager._calc_trailing_stop_price(pos, lock_in_pct=0.0)
        # At break-even, stop equals entry
        assert stop <= pos.entry_price + 1e-9

    def test_no_stop_direction(self, manager):
        """NO stop (YES threshold) is always at or below 1-entry for lock_in >= 0."""
        pos = _make_position("NO", entry_price=0.70)
        stop = manager._calc_trailing_stop_price(pos, lock_in_pct=0.0)
        # At break-even for NO, YES threshold = 1 - entry
        yes_at_entry = 1.0 - pos.entry_price
        assert stop <= yes_at_entry + 1e-9
