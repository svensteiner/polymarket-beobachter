"""
Unit tests for at_or_below-only paper lane, model/city skill, arb shadow-only.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest


class TestMarketTypeAllowlist:
    def test_at_or_below_allowed_by_default(self):
        from paper_trader.simulator import _is_market_type_allowed

        ok, reason = _is_market_type_allowed("at_or_below", weather_config={})
        assert ok is True
        assert reason == "ok"

    def test_exact_blocked_when_allowlist_is_at_or_below(self):
        from paper_trader.simulator import _is_market_type_allowed

        cfg = {"ALLOWED_MARKET_TYPES": ["at_or_below"]}
        ok, reason = _is_market_type_allowed("exact", weather_config=cfg)
        assert ok is False
        assert "market_type_not_allowed" in reason
        assert "exact" in reason

    def test_at_or_above_blocked(self):
        from paper_trader.simulator import _is_market_type_allowed

        cfg = {"ALLOWED_MARKET_TYPES": ["at_or_below"]}
        ok, _ = _is_market_type_allowed("at_or_above", weather_config=cfg)
        assert ok is False

    def test_empty_allowlist_falls_back_to_at_or_below(self):
        from paper_trader.simulator import _is_market_type_allowed

        # Empty list is falsy → helper uses default ["at_or_below"]
        ok, _ = _is_market_type_allowed(
            "at_or_below", weather_config={"ALLOWED_MARKET_TYPES": []}
        )
        assert ok is True
        ok2, _ = _is_market_type_allowed(
            "exact", weather_config={"ALLOWED_MARKET_TYPES": []}
        )
        assert ok2 is False

    def test_guardrails_reject_outside_allowlist(self):
        from paper_trader.entry_guardrails import evaluate_entry_guardrails

        proposal = MagicMock()
        proposal.implied_probability = 0.25
        proposal.market_question = "Will the high temp in Chicago be 90F or above on Aug 1?"
        proposal.market_type = "at_or_above"
        proposal.edge = 0.20
        proposal.model_probability = 0.45

        with patch(
            "paper_trader.entry_guardrails._load_weather_config",
            return_value={
                "ALLOWED_MARKET_TYPES": ["at_or_below"],
                "BLOCKED_MARKET_TYPES": ["exact", "at_or_above", "between"],
                "MAX_ODDS": 0.35,
                "MIN_ENTRY_PRICE": 0.15,
            },
        ), patch(
            "paper_trader.entry_guardrails._load_capital_config",
            return_value={"max_open_positions": 10},
        ), patch(
            "paper_trader.entry_guardrails._load_agent_policy",
            return_value={},
        ):
            allowed, reason = evaluate_entry_guardrails(
                proposal, open_positions_count=0, ignore_inventory_limit=True
            )
        assert allowed is False
        assert "market_type" in reason


class TestArbitrageShadowOnly:
    def test_scan_output_marks_shadow_and_no_capital(self, tmp_path):
        from analytics.arbitrage_detector import (
            WeatherMarketInfo,
            detect_arbitrage,
            run_arbitrage_scan,
        )

        # Force at least one opportunity via inconsistent odds
        markets = [
            WeatherMarketInfo(
                market_id="m1",
                question="Will temperature in Dallas be above 60F?",
                city="Dallas",
                threshold_f=60.0,
                direction="above",
                odds_yes=0.40,
                resolution_date="march 20",
            ),
            WeatherMarketInfo(
                market_id="m2",
                question="Will temperature in Dallas be above 65F?",
                city="Dallas",
                threshold_f=65.0,
                direction="above",
                odds_yes=0.55,
                resolution_date="march 20",
            ),
        ]
        opps = detect_arbitrage(markets, min_inconsistency=0.02)
        assert len(opps) >= 1

        out = tmp_path / "arb.json"
        candidates = [
            {
                "market_id": "m1",
                "question": "Will temperature in Dallas be above 60F on march 20?",
                "outcomePrices": json.dumps(["0.40", "0.60"]),
            },
            {
                "market_id": "m2",
                "question": "Will temperature in Dallas be above 65F on march 20?",
                "outcomePrices": json.dumps(["0.55", "0.45"]),
            },
        ]
        run_arbitrage_scan(candidates, output_file=str(out))
        assert out.exists()
        data = json.loads(out.read_text(encoding="utf-8"))
        assert data["shadow_only"] is True
        assert data["capital_allocation"] == "NONE"
        assert "ARBITRAGE_SHADOW_ONLY" in data["governance_notice"]

    def test_orchestrator_docstring_says_shadow(self):
        from app.orchestrator import Orchestrator
        import inspect

        doc = inspect.getdoc(Orchestrator._run_arbitrage_scan) or ""
        assert "SHADOW" in doc.upper()
        assert "never allocates capital" in doc.lower() or "kein kapital" in doc.lower()


class TestModelCitySkill:
    def test_agg_empty(self):
        from analytics.model_city_skill import _agg

        assert _agg([]) == {"n": 0}

    def test_agg_beats_market(self):
        from analytics.model_city_skill import _agg

        scores = [(0.04, 0.25, 1), (0.09, 0.36, 0)]
        out = _agg(scores)
        assert out["n"] == 2
        assert out["model_beats_market"] is True
        assert out["model_brier"] < out["market_brier"]

    def test_run_writes_json(self, tmp_path, monkeypatch):
        from analytics import model_city_skill as mcs

        monkeypatch.setattr(mcs, "POSITIONS_PATH", tmp_path / "positions.jsonl")
        monkeypatch.setattr(mcs, "RESOLUTIONS_PATH", tmp_path / "resolutions.jsonl")
        monkeypatch.setattr(mcs, "OBS_GLOB_DIRS", [tmp_path])
        monkeypatch.setattr(mcs, "OUT_JSON", tmp_path / "model_city_skill.json")
        monkeypatch.setattr(mcs, "OUT_MD", tmp_path / "model_city_skill.md")

        (tmp_path / "positions.jsonl").write_text("", encoding="utf-8")
        (tmp_path / "resolutions.jsonl").write_text("", encoding="utf-8")

        report = mcs.run()
        assert mcs.OUT_JSON.exists()
        assert mcs.OUT_MD.exists()
        assert "overall" in report or "n" in report or isinstance(report, dict)
