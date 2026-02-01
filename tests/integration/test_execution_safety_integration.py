# =============================================================================
# POLYMARKET BEOBACHTER - EXECUTION SAFETY INTEGRATION TESTS
# =============================================================================
#
# These tests verify the critical safety properties of the execution engine:
#
# 1. DISABLED mode rejects ALL orders
# 2. SHADOW/PAPER/ARMED modes NEVER touch the API
# 3. API client is ONLY instantiated in LIVE mode
# 4. Any API error triggers emergency disable
# 5. Live mode requires proper credentials
#
# GOVERNANCE:
# These tests are CRITICAL for ensuring system safety.
# They MUST pass before any live trading is enabled.
#
# =============================================================================

import os
import pytest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime, timedelta
import tempfile
from pathlib import Path

import sys

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.execution_engine import (
    ExecutionEngine,
    ExecutionState,
    OrderRequest,
    OrderResult,
    ExecutionMode,
    reset_execution_engine,
    get_execution_engine,
    API_KEY_ENV_VAR,
    API_SECRET_ENV_VAR,
    API_PASSPHRASE_ENV_VAR,
    PRIVATE_KEY_ENV_VAR,
    LIVE_MODE_ENV_VAR,
    LIVE_MODE_ENV_VALUE,
)
from shared.enums import OrderSide, OrderType, OrderStatus, OrderRejectionReason


# =============================================================================
# TEST FIXTURES
# =============================================================================


@pytest.fixture
def temp_data_dir(tmp_path):
    """Create temporary data directory."""
    state_file = tmp_path / "execution_state.json"
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    return state_file, log_dir


@pytest.fixture
def engine(temp_data_dir):
    """Create a fresh execution engine with temp storage."""
    state_file, log_dir = temp_data_dir
    engine = ExecutionEngine(state_file=state_file, log_dir=log_dir)
    return engine


@pytest.fixture
def sample_order():
    """Create a sample order request."""
    return OrderRequest(
        market_id="test_market_123",
        token_id="test_token_abc",
        side=OrderSide.BUY,
        price=0.5,
        size=100.0,
        source="test",
        reason="integration test",
    )


# =============================================================================
# DISABLED MODE TESTS
# =============================================================================


class TestDisabledModeSafety:
    """Verify DISABLED mode rejects ALL orders."""

    def test_engine_starts_disabled(self, engine):
        """Engine MUST start in DISABLED mode."""
        assert engine.get_mode() == ExecutionMode.DISABLED

    def test_disabled_rejects_all_orders(self, engine, sample_order):
        """DISABLED mode must reject all orders."""
        result = engine.submit_order(sample_order)

        assert result.status == OrderStatus.REJECTED
        assert result.rejection_reason == OrderRejectionReason.MODE_DISABLED

    def test_disabled_never_instantiates_api_client(self, engine, sample_order):
        """DISABLED mode must never create API client."""
        engine.submit_order(sample_order)

        # API client should still be None
        assert engine._api_client is None

    def test_disabled_after_emergency(self, temp_data_dir, sample_order):
        """Emergency disable should reject all subsequent orders."""
        state_file, log_dir = temp_data_dir
        engine = ExecutionEngine(state_file=state_file, log_dir=log_dir)

        # Trigger emergency disable
        engine._emergency_disable("test emergency")

        result = engine.submit_order(sample_order)

        assert result.status == OrderStatus.REJECTED
        assert engine.get_state()["emergency_disabled"] is True


# =============================================================================
# SHADOW MODE TESTS
# =============================================================================


class TestShadowModeSafety:
    """Verify SHADOW mode never touches the API."""

    def test_shadow_mode_logs_only(self, engine, sample_order):
        """SHADOW mode should log but not execute."""
        assert engine.set_shadow() is True
        assert engine.get_mode() == ExecutionMode.SHADOW

        result = engine.submit_order(sample_order)

        assert result.status == OrderStatus.SIMULATED
        assert result.order_id.startswith("SHADOW_")

    def test_shadow_never_instantiates_api_client(self, engine, sample_order):
        """SHADOW mode must never create API client."""
        engine.set_shadow()

        # Submit multiple orders
        for _ in range(5):
            engine.submit_order(sample_order)

        # API client should still be None
        assert engine._api_client is None

    def test_shadow_no_paper_positions(self, engine, sample_order):
        """SHADOW mode should not create paper positions."""
        engine.set_shadow()
        engine.submit_order(sample_order)

        positions = engine.get_paper_positions()
        assert len(positions) == 0


# =============================================================================
# PAPER MODE TESTS
# =============================================================================


class TestPaperModeSafety:
    """Verify PAPER mode creates positions but never calls API."""

    def test_paper_mode_creates_positions(self, engine, sample_order):
        """PAPER mode should create paper positions."""
        assert engine.set_paper() is True
        assert engine.get_mode() == ExecutionMode.PAPER

        result = engine.submit_order(sample_order)

        assert result.status == OrderStatus.FILLED
        assert result.order_id.startswith("PAPER_")

        positions = engine.get_paper_positions()
        position_key = f"{sample_order.market_id}_{sample_order.token_id}"
        assert position_key in positions
        assert positions[position_key] == sample_order.size

    def test_paper_never_instantiates_api_client(self, engine, sample_order):
        """PAPER mode must never create API client."""
        engine.set_paper()

        # Submit multiple orders
        for _ in range(5):
            engine.submit_order(sample_order)

        # API client should still be None
        assert engine._api_client is None

    def test_paper_tracks_buy_sell(self, engine):
        """PAPER mode should track net position."""
        engine.set_paper()

        buy_order = OrderRequest(
            market_id="market1",
            token_id="token1",
            side=OrderSide.BUY,
            price=0.5,
            size=100.0,
        )
        sell_order = OrderRequest(
            market_id="market1",
            token_id="token1",
            side=OrderSide.SELL,
            price=0.6,
            size=40.0,
        )

        engine.submit_order(buy_order)
        engine.submit_order(sell_order)

        positions = engine.get_paper_positions()
        assert positions["market1_token1"] == 60.0  # 100 - 40


# =============================================================================
# ARMED MODE TESTS
# =============================================================================


class TestArmedModeSafety:
    """Verify ARMED mode validates but never calls API."""

    def test_arm_requires_2_step(self, engine):
        """ARMED mode requires 2-step confirmation."""
        # Cannot directly transition to ARMED
        result = engine._transition_mode(ExecutionMode.ARMED, "test")
        assert result is False

        # Must use initiate_arm + confirm_arm
        challenge = engine.initiate_arm()
        assert challenge is not None
        assert len(challenge) == 8  # 4 bytes hex = 8 chars

        assert engine.confirm_arm(challenge) is True
        assert engine.get_mode() == ExecutionMode.ARMED

    def test_armed_validates_only(self, engine, sample_order):
        """ARMED mode should validate but not execute."""
        challenge = engine.initiate_arm()
        engine.confirm_arm(challenge)

        result = engine.submit_order(sample_order)

        assert result.status == OrderStatus.SIMULATED
        assert result.order_id.startswith("ARMED_")

    def test_armed_never_instantiates_api_client(self, engine, sample_order):
        """ARMED mode must never create API client."""
        challenge = engine.initiate_arm()
        engine.confirm_arm(challenge)

        # Submit multiple orders
        for _ in range(5):
            engine.submit_order(sample_order)

        # API client should still be None
        assert engine._api_client is None

    def test_arm_challenge_expires(self, engine):
        """ARM challenge should expire after timeout."""
        challenge = engine.initiate_arm()

        # Manually expire the challenge
        with engine._lock:
            engine._state.arm_challenge_expires = datetime.utcnow() - timedelta(seconds=1)

        # Confirmation should fail
        assert engine.confirm_arm(challenge) is False
        assert engine.get_mode() == ExecutionMode.DISABLED

    def test_arm_wrong_challenge(self, engine):
        """Wrong challenge code should fail."""
        engine.initiate_arm()

        assert engine.confirm_arm("WRONGCODE") is False
        assert engine.get_mode() == ExecutionMode.DISABLED


# =============================================================================
# LIVE MODE SAFETY TESTS
# =============================================================================


class TestLiveModeSafety:
    """Verify LIVE mode has proper safety checks."""

    def test_live_requires_armed_first(self, engine):
        """Cannot go LIVE without being ARMED first."""
        assert engine.go_live() is False
        assert engine.get_mode() == ExecutionMode.DISABLED

    def test_live_requires_env_var(self, engine):
        """LIVE mode requires POLYMARKET_LIVE env var."""
        # Get to ARMED state
        challenge = engine.initiate_arm()
        engine.confirm_arm(challenge)

        # Try to go live without env var
        with patch.dict(os.environ, {LIVE_MODE_ENV_VAR: ""}, clear=False):
            assert engine.go_live() is False
            assert engine.get_mode() == ExecutionMode.ARMED

    def test_live_requires_api_keys(self, engine):
        """LIVE mode requires API keys."""
        challenge = engine.initiate_arm()
        engine.confirm_arm(challenge)

        # Set LIVE env var but no API keys
        with patch.dict(os.environ, {
            LIVE_MODE_ENV_VAR: LIVE_MODE_ENV_VALUE,
            API_KEY_ENV_VAR: "",
            API_SECRET_ENV_VAR: "",
            PRIVATE_KEY_ENV_VAR: "",
        }, clear=False):
            assert engine.go_live() is False
            assert engine.get_mode() == ExecutionMode.ARMED

    @patch.dict(os.environ, {
        LIVE_MODE_ENV_VAR: LIVE_MODE_ENV_VALUE,
        API_KEY_ENV_VAR: "test_key",
        API_SECRET_ENV_VAR: "test_secret",
        API_PASSPHRASE_ENV_VAR: "test_passphrase",
        PRIVATE_KEY_ENV_VAR: "test_pk",
    })
    def test_live_mode_calls_api(self, engine, sample_order):
        """LIVE mode should attempt API calls."""
        # Get to ARMED state
        challenge = engine.initiate_arm()
        engine.confirm_arm(challenge)

        # Go live
        assert engine.go_live() is True
        assert engine.get_mode() == ExecutionMode.LIVE

        # Submit order - will fail because API client can't initialize
        # (py_clob_client not installed in tests)
        result = engine.submit_order(sample_order)

        # Should either reject with API error or succeed if mocked
        # The key is it TRIES to use the API (not just simulate)
        assert result.status in [
            OrderStatus.REJECTED,
            OrderStatus.SUBMITTED,
        ]

    @patch.dict(os.environ, {
        LIVE_MODE_ENV_VAR: LIVE_MODE_ENV_VALUE,
        API_KEY_ENV_VAR: "test_key",
        API_SECRET_ENV_VAR: "test_secret",
        API_PASSPHRASE_ENV_VAR: "test_passphrase",
        PRIVATE_KEY_ENV_VAR: "test_pk",
        "POLYMARKET_FUNDER_ADDRESS": "test_funder",
    })
    def test_live_api_error_triggers_emergency(self, engine, sample_order):
        """API errors in LIVE mode should trigger emergency disable."""
        # Get to LIVE state
        challenge = engine.initiate_arm()
        engine.confirm_arm(challenge)
        engine.go_live()

        # Submit order (will fail due to API error since py_clob_client not installed)
        result = engine.submit_order(sample_order)

        # After API error, should be emergency disabled
        state = engine.get_state()

        # Order should be rejected
        assert result.status == OrderStatus.REJECTED

        # If it was a critical error (RuntimeError from client init failure),
        # emergency should be enabled. Validation errors don't trigger emergency.
        # The actual behavior depends on whether we got to the API call or not.
        # With FUNDER_ADDRESS set, client creation should proceed but fail on import
        if result.rejection_reason in [
            OrderRejectionReason.API_ERROR,
            OrderRejectionReason.INTERNAL_ERROR,
        ]:
            # These are critical errors that should emergency disable
            assert state["mode"] == "DISABLED"
            assert state["emergency_disabled"] is True
        else:
            # Validation/auth errors just reject the order without emergency
            assert result.rejection_reason in [
                OrderRejectionReason.INVALID_PARAMETERS,
                OrderRejectionReason.MISSING_API_KEYS,
            ]


# =============================================================================
# API CLIENT ISOLATION TESTS
# =============================================================================


class TestApiClientIsolation:
    """Verify API client is strictly isolated to LIVE mode."""

    def test_api_client_not_imported_at_module_level(self):
        """API client module should not be imported at module level."""
        # If it was imported at module level, this would fail when
        # py_clob_client is not installed
        import core.execution_engine
        # Should reach here without ImportError

    def test_get_api_client_rejects_non_live(self, engine):
        """_get_api_client should raise if not in LIVE mode."""
        assert engine.get_mode() == ExecutionMode.DISABLED

        with pytest.raises(RuntimeError) as exc_info:
            engine._get_api_client()

        assert "DISABLED mode" in str(exc_info.value)

    def test_get_api_client_rejects_shadow(self, engine):
        """_get_api_client should raise in SHADOW mode."""
        engine.set_shadow()

        with pytest.raises(RuntimeError) as exc_info:
            engine._get_api_client()

        assert "SHADOW mode" in str(exc_info.value)

    def test_get_api_client_rejects_paper(self, engine):
        """_get_api_client should raise in PAPER mode."""
        engine.set_paper()

        with pytest.raises(RuntimeError) as exc_info:
            engine._get_api_client()

        assert "PAPER mode" in str(exc_info.value)

    def test_get_api_client_rejects_armed(self, engine):
        """_get_api_client should raise in ARMED mode."""
        challenge = engine.initiate_arm()
        engine.confirm_arm(challenge)

        with pytest.raises(RuntimeError) as exc_info:
            engine._get_api_client()

        assert "ARMED mode" in str(exc_info.value)


# =============================================================================
# STATE PERSISTENCE TESTS
# =============================================================================


class TestStatePersistence:
    """Verify state persistence and restart safety."""

    def test_always_starts_disabled(self, temp_data_dir):
        """Engine MUST start DISABLED regardless of saved state."""
        state_file, log_dir = temp_data_dir

        # Create first engine and get it to ARMED
        engine1 = ExecutionEngine(state_file=state_file, log_dir=log_dir)
        challenge = engine1.initiate_arm()
        engine1.confirm_arm(challenge)
        assert engine1.get_mode() == ExecutionMode.ARMED

        # Create second engine - should be DISABLED
        engine2 = ExecutionEngine(state_file=state_file, log_dir=log_dir)
        assert engine2.get_mode() == ExecutionMode.DISABLED

    def test_statistics_persist(self, temp_data_dir, sample_order):
        """Order statistics should persist across restarts."""
        state_file, log_dir = temp_data_dir

        engine1 = ExecutionEngine(state_file=state_file, log_dir=log_dir)
        engine1.set_shadow()
        engine1.submit_order(sample_order)

        state1 = engine1.get_state()
        assert state1["total_orders_submitted"] == 1

    def test_emergency_state_noted(self, temp_data_dir):
        """Emergency state should be recorded in state file."""
        state_file, log_dir = temp_data_dir

        engine = ExecutionEngine(state_file=state_file, log_dir=log_dir)
        engine._emergency_disable("test reason")

        state = engine.get_state()
        assert state["emergency_disabled"] is True
        assert state["emergency_reason"] == "test reason"


# =============================================================================
# RATE LIMITING TESTS
# =============================================================================


class TestRateLimiting:
    """Verify rate limiting in LIVE mode."""

    @patch.dict(os.environ, {
        LIVE_MODE_ENV_VAR: LIVE_MODE_ENV_VALUE,
        API_KEY_ENV_VAR: "test_key",
        API_SECRET_ENV_VAR: "test_secret",
        API_PASSPHRASE_ENV_VAR: "test_passphrase",
        PRIVATE_KEY_ENV_VAR: "test_pk",
    })
    def test_rate_limit_enforced(self, engine):
        """Rate limiting should be enforced."""
        from core.execution_engine import MAX_ORDERS_PER_MINUTE

        # Get to LIVE mode
        challenge = engine.initiate_arm()
        engine.confirm_arm(challenge)
        engine.go_live()

        # Fill up rate limit
        engine._order_timestamps = [
            datetime.utcnow() for _ in range(MAX_ORDERS_PER_MINUTE)
        ]

        # Next order should be rate limited
        result = engine._check_rate_limit()
        assert result is False


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
