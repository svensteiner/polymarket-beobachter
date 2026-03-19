import json
from datetime import UTC, datetime, timedelta


class TestBotHealthMonitor:
    def test_critical_health_blocks_new_entries(self):
        from paper_trader.bot_health_monitor import derive_bot_health

        current_summary = {
            "drawdown_pct": 24.0,
            "high_price_open_positions": 2,
        }
        recent_runs = [
            {"summary": {"state": "OK", "edge_observations": 0}},
            {"summary": {"state": "DEGRADED", "edge_observations": 0}},
            {"summary": {"state": "FAIL", "edge_observations": 0}},
        ]
        performance_report = {
            "metrics": {"total_trades": 30, "win_rate_pct": 6.0},
            "strategy_attribution": {"stop_loss": {"count": 20}},
        }
        strategy_advice = {"mode": "protect"}
        recent_closed_positions = [
            {"realized_pnl_eur": -90.0},
            {"realized_pnl_eur": -80.0},
            {"realized_pnl_eur": -75.0},
            {"realized_pnl_eur": -60.0},
        ]

        health = derive_bot_health(
            current_summary=current_summary,
            recent_runs=recent_runs,
            performance_report=performance_report,
            strategy_advice=strategy_advice,
            recent_closed_positions=recent_closed_positions,
        )

        assert health["status"] == "CRITICAL"
        assert health["guardrails"]["block_new_entries"] is True
        assert health["guardrails"]["block_averaging_down"] is True
        assert health["guardrails"]["max_entry_price"] == 0.75

    def test_segment_guardrails_are_derived_from_strategy_advice(self):
        from paper_trader.bot_health_monitor import derive_bot_health

        health = derive_bot_health(
            current_summary={"drawdown_pct": 12.0, "high_price_open_positions": 0},
            recent_runs=[{"summary": {"state": "OK", "edge_observations": 0}} for _ in range(4)],
            performance_report={
                "metrics": {"total_trades": 20, "win_rate_pct": 38.0},
                "strategy_attribution": {"stop_loss": {"count": 8}},
            },
            strategy_advice={
                "mode": "protect",
                "segment_risk_flags": {
                    "suggested_city_cooldowns": ["Seattle", "Toronto", "Paris"],
                    "suggested_market_type_cooldowns": ["between", "exact"],
                    "suggested_price_band_blocks": ["0.00-0.10", "0.10-0.20"],
                },
            },
            recent_closed_positions=[{"realized_pnl_eur": -20.0}, {"realized_pnl_eur": -10.0}],
        )

        assert health["status"] == "ELEVATED"
        assert health["guardrails"]["blocked_cities"] == ["Seattle", "Toronto"]
        assert health["guardrails"]["blocked_market_types"] == ["between", "exact"]
        assert health["guardrails"]["blocked_price_bands"] == ["0.00-0.10", "0.10-0.20"]

    def test_elevated_health_caps_entry_price(self):
        from paper_trader.bot_health_monitor import derive_bot_health

        health = derive_bot_health(
            current_summary={"drawdown_pct": 12.0, "high_price_open_positions": 0},
            recent_runs=[{"summary": {"state": "OK", "edge_observations": 0}} for _ in range(4)],
            performance_report={
                "metrics": {"total_trades": 20, "win_rate_pct": 38.0},
                "strategy_attribution": {"stop_loss": {"count": 8}},
            },
            strategy_advice={"mode": "observe"},
            recent_closed_positions=[{"realized_pnl_eur": -20.0}, {"realized_pnl_eur": -10.0}],
        )

        assert health["status"] == "ELEVATED"
        assert health["guardrails"]["block_new_entries"] is False
        assert health["guardrails"]["block_averaging_down"] is True
        assert health["guardrails"]["max_entry_price"] == 0.85

    def test_expired_guardrails_do_not_block_entries(self, tmp_path, monkeypatch):
        from paper_trader import bot_health_monitor as bhm

        state_file = tmp_path / "bot_health.json"
        monkeypatch.setattr(bhm, "STATE_FILE", state_file)

        expired_state = {
            "status": "CRITICAL",
            "summary": "expired",
            "active_until": (datetime.now(UTC) - timedelta(hours=1)).isoformat(),
            "guardrails": {
                "block_new_entries": True,
                "block_averaging_down": True,
                "max_entry_price": 0.75,
            },
            "guardrails_active": True,
            "triggers": ["test"],
            "metrics_snapshot": {},
        }
        state_file.write_text(json.dumps(expired_state), encoding="utf-8")

        allowed, reason = bhm.check_can_open_entry(entry_price=0.95, is_addon=False)

        assert allowed is True
        assert reason == "OK"

    def test_segment_guardrails_block_city_market_type_and_price_band(self, tmp_path, monkeypatch):
        from paper_trader import bot_health_monitor as bhm

        state_file = tmp_path / "bot_health.json"
        monkeypatch.setattr(bhm, "STATE_FILE", state_file)

        state = {
            "status": "ELEVATED",
            "summary": "active",
            "active_until": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
            "guardrails": {
                "block_new_entries": False,
                "block_averaging_down": True,
                "max_entry_price": 0.85,
                "blocked_cities": ["Seattle"],
                "blocked_market_types": ["between"],
                "blocked_price_bands": ["0.00-0.10"],
            },
            "guardrails_active": True,
            "triggers": ["advisor_protect"],
            "metrics_snapshot": {},
        }
        state_file.write_text(json.dumps(state), encoding="utf-8")

        allowed_city, reason_city = bhm.check_can_open_entry(
            entry_price=0.30,
            is_addon=False,
            market_question="Will the highest temperature in Seattle be between 44-45°F on March 20?",
            market_type="between",
        )
        assert allowed_city is False
        assert "city Seattle" in reason_city

        allowed_band, reason_band = bhm.check_can_open_entry(
            entry_price=0.08,
            is_addon=False,
            market_question="Will the highest temperature in Miami be 70°F or above on March 20?",
            market_type="at_or_above",
        )
        assert allowed_band is False
        assert "price band 0.00-0.10" in reason_band

        allowed_type, reason_type = bhm.check_can_open_entry(
            entry_price=0.30,
            is_addon=False,
            market_question="Will the highest temperature in Miami be between 70-71°F on March 20?",
            market_type="between",
        )
        assert allowed_type is False
        assert "market type between" in reason_type
