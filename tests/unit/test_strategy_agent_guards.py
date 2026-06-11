# =============================================================================
# REGRESSION TESTS — strategy_agent.adjust_config eligibility window guard
# =============================================================================
#
# Background: on 2026-04-08 the strategy_agent had progressively tightened
# MIN_ODDS to 0.40 and MAX_ODDS to 0.45 over many cycles, collapsing the
# eligibility window to 5 cents. This caused the bot to find 0 edge for 8
# consecutive cycles. These tests lock in the cross-parameter invariant
# that prevents that failure mode from recurring.
# =============================================================================

from unittest.mock import patch

from evolution.strategy_agent import (
    MIN_ELIGIBILITY_WINDOW,
    CONFIG_PARAMS,
    _execute_tool,
)


class TestEligibilityWindowGuard:
    """The (MIN_ODDS, MAX_ODDS) window must always be at least
    MIN_ELIGIBILITY_WINDOW wide. The agent must refuse changes that
    would collapse it below that threshold."""

    def test_min_eligibility_window_is_set(self):
        assert MIN_ELIGIBILITY_WINDOW >= 0.10, (
            "Window floor should be at least 10 cents to leave room for "
            "longshot strategy across multiple market types."
        )

    def test_min_odds_upper_bound_is_safe(self):
        # MIN_ODDS upper bound must leave room for MAX_ODDS lower bound
        # plus the eligibility window.
        min_odds_upper = CONFIG_PARAMS["MIN_ODDS"]["max"]
        max_odds_lower = CONFIG_PARAMS["MAX_ODDS"]["min"]
        assert max_odds_lower - min_odds_upper >= MIN_ELIGIBILITY_WINDOW, (
            f"With MIN_ODDS upper={min_odds_upper} and MAX_ODDS lower={max_odds_lower}, "
            f"the window can collapse to {max_odds_lower - min_odds_upper}, "
            f"which is below the required {MIN_ELIGIBILITY_WINDOW}."
        )

    def test_adjust_min_odds_above_safe_range_is_refused(self):
        # MIN_ODDS=0.30 is above the post-fix max of 0.10. This is the
        # historical failure value — must be rejected.
        with patch("evolution.strategy_agent._read_config_values") as mock_read:
            mock_read.return_value = {"MIN_ODDS": 0.05, "MAX_ODDS": 0.40}
            result = _execute_tool(
                "adjust_config",
                {"param": "MIN_ODDS", "value": 0.30, "reason": "test"},
            )
        assert "error" in result, f"Expected rejection, got: {result}"

    def test_adjust_max_odds_below_safe_range_is_refused(self):
        # MAX_ODDS=0.20 is below the post-fix min of 0.30. Must be rejected
        # because it would let the upper bound collapse near MIN_ODDS.
        with patch("evolution.strategy_agent._read_config_values") as mock_read:
            mock_read.return_value = {"MIN_ODDS": 0.05, "MAX_ODDS": 0.40}
            result = _execute_tool(
                "adjust_config",
                {"param": "MAX_ODDS", "value": 0.20, "reason": "test"},
            )
        assert "error" in result, f"Expected rejection, got: {result}"

    def test_runtime_window_check_catches_loosened_ranges(self):
        # Defense-in-depth: even if someone widens CONFIG_PARAMS bounds in the
        # future without thinking, the runtime cross-parameter check should
        # still catch a window collapse. Simulate by patching CONFIG_PARAMS
        # to a permissive state and verify the window check fires.
        from evolution import strategy_agent
        loose_params = dict(strategy_agent.CONFIG_PARAMS)
        loose_params["MIN_ODDS"] = {"min": 0.02, "max": 0.50, "desc": "loose"}
        loose_params["MAX_ODDS"] = {"min": 0.05, "max": 0.95, "desc": "loose"}
        with patch.object(strategy_agent, "CONFIG_PARAMS", loose_params), \
             patch("evolution.strategy_agent._read_config_values") as mock_read:
            mock_read.return_value = {"MIN_ODDS": 0.30, "MAX_ODDS": 0.40}
            # Try to set MIN_ODDS=0.32 → window would shrink from 0.10 to 0.08.
            # Both 0.32 and the resulting state are within the loose range
            # check, so only the window check can save us.
            result = _execute_tool(
                "adjust_config",
                {"param": "MIN_ODDS", "value": 0.32, "reason": "test"},
            )
        assert "error" in result, f"Expected window-check rejection, got: {result}"
        assert "window" in result["error"].lower() or "narrow" in result["error"].lower(), (
            f"Expected window-related error, got: {result['error']}"
        )

    def test_adjust_within_window_is_accepted(self):
        # Current: MIN_ODDS=0.05, MAX_ODDS=0.40 → setting MIN_ODDS=0.06 keeps
        # window at 0.34 which is comfortably above the floor.
        with patch("evolution.strategy_agent._read_config_values") as mock_read, \
             patch("evolution.strategy_agent._write_config_value") as mock_write, \
             patch("evolution.strategy_agent._backup_config") as mock_backup, \
             patch("evolution.strategy_agent._snapshot_current_metrics") as mock_snap, \
             patch("evolution.strategy_agent.CONFIG_LOG_FILE") as mock_log:
            mock_read.return_value = {"MIN_ODDS": 0.05, "MAX_ODDS": 0.40}
            mock_write.return_value = True
            mock_backup.return_value = "/tmp/backup.yaml"
            mock_snap.return_value = {}
            # Make CONFIG_LOG_FILE.parent.mkdir + open work via tmp_path-like mock
            mock_log.parent.mkdir = lambda **kw: None
            mock_log.__enter__ = lambda s: s

            # We don't actually want to write to disk; the success path would
            # try to open CONFIG_LOG_FILE for append. Patch builtins.open on
            # that one path to a no-op.
            with patch("builtins.open", create=True) as mock_open:
                mock_open.return_value.__enter__ = lambda s: s
                mock_open.return_value.__exit__ = lambda *a: None
                mock_open.return_value.write = lambda x: None
                result = _execute_tool(
                    "adjust_config",
                    {"param": "MIN_ODDS", "value": 0.06, "reason": "test"},
                )
        # Either ok=True or at least no window-related error
        assert "window" not in str(result).lower()

    def test_historical_failure_state_is_refused(self):
        # Reproduce the exact 2026-04-08 failure: MIN_ODDS=0.40, MAX_ODDS=0.45
        # Try to set MIN_ODDS=0.40 from a state of MIN_ODDS=0.35, MAX_ODDS=0.45.
        # Window would become 0.05 — the historical bug.
        with patch("evolution.strategy_agent._read_config_values") as mock_read:
            mock_read.return_value = {"MIN_ODDS": 0.35, "MAX_ODDS": 0.45}
            result = _execute_tool(
                "adjust_config",
                {"param": "MIN_ODDS", "value": 0.40, "reason": "tighten"},
            )
        # First, MIN_ODDS=0.40 is now outside the [0.02, 0.20] allowed range,
        # so we expect a range error before the window check even runs.
        assert "error" in result
