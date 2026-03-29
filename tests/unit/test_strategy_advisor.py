class TestStrategyAdvisor:
    def test_poor_performance_switches_to_protect_mode(self):
        from analytics.strategy_advisor import derive_strategy_advice

        report = {
            "metrics": {
                "total_trades": 40,
                "win_rate_pct": 12.5,
                "total_pnl_eur": -1850.0,
            },
            "strategy_attribution": {
                "stop_loss": {"count": 24},
                "resolution_loss": {"count": 8},
            },
            "performance_by_city": {
                "Seattle": {"trades": 6, "win_rate_pct": 0.0, "total_pnl_eur": -640.0},
                "Paris": {"trades": 4, "win_rate_pct": 0.0, "total_pnl_eur": -410.0},
                "London": {"trades": 2, "win_rate_pct": 50.0, "total_pnl_eur": 25.0},
            },
            "calibration": {"interpretation": "EXCELLENT"},
        }
        positions = [
            {"position_id": "open-1", "status": "OPEN", "entry_price": 0.91},
            {"position_id": "open-2", "status": "OPEN", "entry_price": 0.40},
            {"position_id": "closed-1", "status": "EXPIRED", "exit_reason": "MARKET_EXPIRED_ZOMBIE_CLEANUP"},
            {"position_id": "closed-2", "status": "EXPIRED", "exit_reason": "MARKET_EXPIRED_ZOMBIE_CLEANUP"},
            {"position_id": "closed-3", "status": "EXPIRED", "exit_reason": "MARKET_EXPIRED_ZOMBIE_CLEANUP"},
            {"position_id": "closed-4", "status": "EXPIRED", "exit_reason": "MARKET_EXPIRED_ZOMBIE_CLEANUP"},
        ]
        capital = {
            "initial_capital_eur": 5000.0,
            "allocated_capital_eur": 1800.0,
        }
        config = {
            "MIN_EDGE": 0.25,
            "MIN_EDGE_ABSOLUTE": 0.08,
            "MIN_TIME_TO_RESOLUTION_HOURS": 24.0,
            "SAFETY_BUFFER_HOURS": 24.0,
        }

        advice = derive_strategy_advice(report, positions, capital, config)

        assert advice["mode"] == "protect"
        assert "entry_quality_too_weak" in advice["issues"]
        assert "selection_execution_gap" in advice["issues"]
        assert advice["metrics_snapshot"]["high_price_open_positions"] == 1
        assert any("Entry-Preis-Guardrail" in rec["action"] for rec in advice["recommendations"])
        assert any("cooldown_cities" in rec["suggested_changes"] for rec in advice["recommendations"])

    def test_no_trade_history_stays_in_observe_mode(self):
        from analytics.strategy_advisor import derive_strategy_advice

        advice = derive_strategy_advice(
            report={"metrics": {"total_trades": 0, "win_rate_pct": 0.0, "total_pnl_eur": 0.0}},
            positions=[],
            capital={},
            config_values={},
        )

        assert advice["mode"] == "observe"
        assert len(advice["recommendations"]) == 1
        assert advice["recommendations"][0]["priority"] == "LOW"

    def test_edge_bucket_recommendations_are_exposed(self, monkeypatch):
        from analytics.strategy_advisor import derive_strategy_advice

        monkeypatch.setattr(
            "analytics.edge_memory.get_edge_summary",
            lambda **_: [
                {"bucket": "HIGH|at_or_above|YES|edge10p|time_24_72h", "avg_pnl_eur": 9.0, "trade_count": 4, "win_rate": 0.75},
                {"bucket": "MEDIUM|between|NO|edge5p|time_gt72h", "avg_pnl_eur": -6.0, "trade_count": 4, "win_rate": 0.25},
            ],
        )

        advice = derive_strategy_advice(
            report={"metrics": {"total_trades": 12, "win_rate_pct": 48.0, "total_pnl_eur": 30.0}, "strategy_attribution": {}},
            positions=[],
            capital={},
            config_values={},
        )

        assert "negative_edge_buckets" in advice["issues"]
        assert advice["metrics_snapshot"]["top_edge_bucket"] == "HIGH|at_or_above|YES|edge10p|time_24_72h"
        assert any("blocked_edge_buckets" in rec["suggested_changes"] for rec in advice["recommendations"])

    def test_attack_mode_is_selected_for_strong_profile(self, monkeypatch):
        from analytics.strategy_advisor import derive_strategy_advice

        monkeypatch.setattr(
            "analytics.edge_memory.get_edge_summary",
            lambda **_: [
                {"bucket": "HIGH|at_or_above|YES|edge10p|time_24_72h", "avg_pnl_eur": 14.0, "trade_count": 6, "win_rate": 0.83},
                {"bucket": "HIGH|below|NO|edge5p|time_24_72h", "avg_pnl_eur": 8.0, "trade_count": 4, "win_rate": 0.75},
            ],
        )
        monkeypatch.setattr(
            "analytics.strategy_advisor._load_arbitrage_opportunities",
            lambda: [
                {
                    "city": "Berlin",
                    "direction": "above",
                    "inconsistency_magnitude": 0.08,
                    "market_id_lower": "low-1",
                    "market_id_higher": "high-1",
                }
            ],
        )
        monkeypatch.setattr(
            "analytics.strategy_advisor._load_smart_money_summary",
            lambda: {
                "total_wallets_tracked": 6,
                "smart_money_wallets": 3,
                "top_performers": [
                    {"wallet": "0xabc", "signal_score": 0.91, "win_rate": 0.78, "total_profit_usd": 2500.0}
                ],
            },
        )

        advice = derive_strategy_advice(
            report={
                "metrics": {"total_trades": 48, "win_rate_pct": 67.0, "total_pnl_eur": 1450.0},
                "strategy_attribution": {"stop_loss": {"count": 5}, "resolution_loss": {"count": 1}},
                "calibration": {"interpretation": "GOOD"},
            },
            positions=[{"position_id": "open-1", "status": "OPEN", "entry_price": 0.42}],
            capital={"initial_capital_eur": 5000.0, "allocated_capital_eur": 900.0},
            config_values={},
        )

        assert advice["mode"] == "attack"
        assert advice["metrics_snapshot"]["attack_score"] >= 0.68
        assert any(rec["suggested_changes"].get("policy_mode") == "ATTACK" for rec in advice["recommendations"])

    def test_attack_mode_maps_to_policy(self, tmp_path):
        import json
        from pathlib import Path

        from agentic.policy import AgentPolicyEngine

        base_dir = Path(tmp_path)
        (base_dir / "output").mkdir(parents=True, exist_ok=True)
        (base_dir / "data").mkdir(parents=True, exist_ok=True)
        (base_dir / "data" / "agent_memory").mkdir(parents=True, exist_ok=True)

        (base_dir / "output" / "strategy_advice.json").write_text(
            json.dumps({"mode": "attack", "metrics_snapshot": {"attack_score": 0.84}}),
            encoding="utf-8",
        )
        (base_dir / "output" / "segment_analysis.json").write_text("{}", encoding="utf-8")
        (base_dir / "output" / "shadow_eligibility.json").write_text("{}", encoding="utf-8")
        (base_dir / "data" / "capital_config.json").write_text(
            json.dumps({"max_open_positions": 5}),
            encoding="utf-8",
        )

        engine = AgentPolicyEngine(base_dir)
        policy = engine.build_and_save({"bot_health_status": "OK", "drawdown_pct": 0.0})

        assert policy["mode"] == "ATTACK"
        assert policy["max_open_positions"] == 7
        assert "LOW" in policy["allowed_confidence"]
        assert policy["max_entry_price"] >= 0.88
