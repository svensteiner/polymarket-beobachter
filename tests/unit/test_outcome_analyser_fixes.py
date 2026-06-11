# =============================================================================
# REGRESSION TESTS — outcome_analyser datetime + drawdown fixes
# =============================================================================
#
# Background: on 2026-04-08 the outcome_analyser was silently failing with a
# TypeError ("can't compare offset-naive and offset-aware datetimes") inside
# _compute_drawdown_from_trades, which left analytics/performance_report.json
# stale at total_trades=2 / win_rate=0% even though the position log had
# 159 closed positions. The bot_health_monitor read the stale report and
# kept the bot in ELEVATED health forever — a Catch-22.
#
# Separately, the drawdown calculation seeded the equity curve at 0 instead
# of initial_capital, producing nonsensical drawdown percentages (1151%)
# whenever an early small profit briefly inflated peak_equity above 0 and
# was followed by a loss.
# =============================================================================


from analytics.outcome_analyser import (
    _compute_drawdown_from_trades,
    _compute_monthly_performance,
)


def _pos(pnl: float, exit_time: str = "2026-04-08T10:00:00") -> dict:
    return {
        "realized_pnl_eur": pnl,
        "exit_time": exit_time,
        "entry_time": exit_time,
        "pnl_pct": -1.0 if pnl < 0 else 1.0,
    }


class TestDatetimeNormalization:
    """Mixed naive + aware datetimes from different code paths must not crash."""

    def test_drawdown_handles_mixed_tz_formats(self):
        positions = [
            _pos(10.0, "2026-04-08T10:00:00"),                  # naive
            _pos(-5.0, "2026-04-08T11:00:00Z"),                 # Z suffix
            _pos(3.0, "2026-04-08T12:00:00+00:00"),             # offset
        ]
        # Must not raise TypeError
        result = _compute_drawdown_from_trades(positions)
        assert "max_drawdown_eur" in result

    def test_monthly_performance_handles_mixed_tz_formats(self):
        positions = [
            _pos(10.0, "2026-03-15T10:00:00"),
            _pos(-5.0, "2026-04-08T11:00:00Z"),
        ]
        result = _compute_monthly_performance(positions)
        assert "Unknown" not in result, f"Expected proper month parsing, got: {result}"
        assert "2026-03" in result
        assert "2026-04" in result


class TestDrawdownCalculation:
    """Drawdown must be capped by reality. Seeding from initial_capital
    prevents the early-tiny-peak division blowup."""

    def test_drawdown_seeded_from_initial_capital(self):
        # 1 EUR win followed by -100 EUR loss should NOT show 10000% DD.
        positions = [
            _pos(1.0, "2026-01-01T10:00:00"),
            _pos(-100.0, "2026-01-02T10:00:00"),
        ]
        result = _compute_drawdown_from_trades(positions)
        # With initial_capital=5000 (default), peak is 5001, dd is 100,
        # dd_pct is 100/5001 ≈ 2%. Definitely not 10000%.
        assert result["max_drawdown_pct"] < 100.0, (
            f"Drawdown should be bounded by reality, got {result['max_drawdown_pct']}%"
        )
        assert result["max_drawdown_eur"] == 100.0
        assert result.get("initial_capital_eur") is not None

    def test_drawdown_returns_initial_capital(self):
        positions = [_pos(10.0, "2026-04-08T10:00:00")]
        result = _compute_drawdown_from_trades(positions)
        assert "initial_capital_eur" in result
        assert result["initial_capital_eur"] > 0

    def test_drawdown_realistic_scenario(self):
        # Simulate the actual production state: many trades net -823 EUR
        # against initial_capital=5000 should show ~16-18% drawdown.
        positions = []
        # 60 wins of average +5 EUR, 100 losses of average -11 EUR → net -800 EUR
        for i in range(60):
            positions.append(_pos(5.0, f"2026-03-{i % 28 + 1:02d}T10:00:00"))
        for i in range(100):
            positions.append(_pos(-11.0, f"2026-04-{i % 8 + 1:02d}T10:00:00"))
        result = _compute_drawdown_from_trades(positions)
        # Should be in single-to-low-double digit percent range
        assert 5.0 <= result["max_drawdown_pct"] <= 30.0, (
            f"Expected realistic drawdown 5-30%, got {result['max_drawdown_pct']}%"
        )


class TestStalenessRegression:
    """The combination of these fixes prevents performance_report.json
    from going stale because the analyser silently crashed."""

    def test_run_analysis_does_not_crash_on_real_data(self):
        # This test exists to make the analyser failure mode loud rather
        # than silent. If outcome_analyser crashes, the report stays stale,
        # bot_health stays in catch-22 state, and the bot never recovers.
        from analytics.outcome_analyser import run_analysis
        # If this raises, the test fails — the silent-crash regression
        # would be caught by CI before it can poison production again.
        report = run_analysis()
        assert isinstance(report, dict)
        assert "metrics" in report
        assert "drawdown" in report
