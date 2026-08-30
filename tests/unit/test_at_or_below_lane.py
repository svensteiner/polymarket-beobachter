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


class TestSkillCommon:
    def test_extract_city_from_question(self):
        from analytics.skill_common import extract_city_from_question

        q = "Will the highest temperature in Toronto be 21°C or below on April 14?"
        assert extract_city_from_question(q) == "Toronto"
        q2 = "Will the highest temperature in New York City be 77°F or below on April 17?"
        assert extract_city_from_question(q2) == "New York"

    def test_dedupe_by_market_id_keeps_latest(self):
        from analytics.skill_common import dedupe_by_market_id

        rows = [
            {"market_id": "1", "entry_time": "2026-01-01", "v": 1},
            {"market_id": "1", "entry_time": "2026-02-01", "v": 2},
            {"market_id": "2", "entry_time": "2026-01-01", "v": 3},
        ]
        out = dedupe_by_market_id(rows)
        by = {r["market_id"]: r["v"] for r in out}
        assert by == {"1": 2, "2": 3}

    def test_gate_progress(self):
        from analytics.skill_common import gate_progress

        gp = gate_progress(7, 20)
        assert gp["n_unique"] == 7
        assert gp["target"] == 20
        assert gp["remaining"] == 13
        assert gp["ready_for_gate_eval"] is False


class TestAtOrBelowDedupe:
    def test_analyse_dedupes_and_parses_city(self, tmp_path, monkeypatch):
        from analytics import at_or_below_skill as aob

        positions = tmp_path / "positions.jsonl"
        resolutions = tmp_path / "resolutions.jsonl"
        # Same market twice → should count as n=1 unique
        rows = [
            {
                "market_id": "m1",
                "market_type": "at_or_below",
                "market_question": "Will the highest temperature in Dallas be 71°F or below on April 20?",
                "side": "YES",
                "model_probability": 0.6,
                "entry_price": 0.4,
                "entry_time": "2026-04-18T00:00:00",
                "realized_pnl_eur": 0.0,
            },
            {
                "market_id": "m1",
                "market_type": "at_or_below",
                "market_question": "Will the highest temperature in Dallas be 71°F or below on April 20?",
                "side": "YES",
                "model_probability": 0.6,
                "entry_price": 0.4,
                "entry_time": "2026-04-19T00:00:00",
                "realized_pnl_eur": 0.0,
            },
        ]
        positions.write_text(
            "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8"
        )
        resolutions.write_text(
            json.dumps(
                {"market_id": "m1", "resolved": True, "resolution": "YES"}
            )
            + "\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(aob, "POSITIONS_PATH", positions)
        monkeypatch.setattr(aob, "RESOLUTIONS_PATH", resolutions)
        monkeypatch.setattr(aob, "OUT_JSON", tmp_path / "aob.json")
        monkeypatch.setattr(aob, "OUT_MD", tmp_path / "aob.md")

        report = aob.analyse()
        assert report["n"] == 1
        assert report["n_raw_rows"] == 2
        assert report["samples"][0]["city"] == "Dallas"
        assert report["gate_progress"]["n_unique"] == 1
        assert report["model_beats_market"] is True


class TestCitySkillSoftBlock:
    def test_soft_block_rejects_losing_city(self, tmp_path, monkeypatch):
        from paper_trader import entry_guardrails as eg

        skill = {
            "cities_losing_to_market": [
                {
                    "city": "Chicago",
                    "n": 6,
                    "model_brier": 0.4,
                    "market_brier": 0.2,
                }
            ]
        }
        skill_path = tmp_path / "model_city_skill.json"
        skill_path.write_text(json.dumps(skill), encoding="utf-8")
        monkeypatch.setattr(eg, "PROJECT_ROOT", tmp_path)

        # Ensure helper reads from tmp analytics path — recreate expected layout
        (tmp_path / "analytics").mkdir(exist_ok=True)
        (tmp_path / "analytics" / "model_city_skill.json").write_text(
            json.dumps(skill), encoding="utf-8"
        )

        proposal = MagicMock()
        proposal.implied_probability = 0.25
        proposal.market_question = (
            "Will the highest temperature in Chicago be 89°F or below on July 16?"
        )
        proposal.market_type = "at_or_below"
        proposal.edge = 0.20
        proposal.model_probability = 0.45
        proposal.confidence_level = "HIGH"

        with patch.object(
            eg,
            "_load_weather_config",
            return_value={
                "ALLOWED_MARKET_TYPES": ["at_or_below"],
                "BLOCKED_MARKET_TYPES": ["exact", "at_or_above", "between"],
                "MAX_ODDS": 0.35,
                "MIN_ENTRY_PRICE": 0.15,
                "CITY_SKILL_SOFT_BLOCK": True,
                "CITY_SKILL_MIN_N": 5,
            },
        ), patch.object(
            eg, "_load_capital_config", return_value={"max_open_positions": 10}
        ), patch.object(eg, "_load_agent_policy", return_value={}):
            # Also patch city extract to Chicago if needed
            with patch.object(eg, "_extract_city", return_value="Chicago"):
                allowed, reason = eg.evaluate_entry_guardrails(
                    proposal, open_positions_count=0, ignore_inventory_limit=True
                )
        assert allowed is False
        assert "city_skill_soft_block" in reason

class TestPaperLaneEarlyFilter:
    def test_exact_rejected_in_at_or_below_only_mode(self):
        from datetime import datetime, timedelta, timezone
        from core.weather_market_filter import WeatherMarket, WeatherMarketFilter

        filt = WeatherMarketFilter(
            {
                "PAPER_LANE_MODE": "at_or_below_only",
                "MIN_LIQUIDITY": 0,
                "MIN_ODDS": 0.01,
                "MAX_ODDS": 0.99,
                "MIN_TIME_TO_RESOLUTION_HOURS": 0,
                "ALLOWED_CITIES": ["Chicago"],
            }
        )
        now = datetime.now(timezone.utc)
        market = WeatherMarket(
            market_id="x1",
            question="Will the highest temperature in Chicago be 89°F on July 16?",
            resolution_text="temp",
            description="weather",
            category="Weather",
            is_binary=True,
            liquidity_usd=1000.0,
            odds_yes=0.30,
            resolution_time=now + timedelta(hours=48),
        )
        result = filt.filter_market(market)
        assert result.passed is False
        assert any("PAPER_LANE" in r for r in result.rejection_reasons)

    def test_at_or_below_passes_lane_gate(self):
        from datetime import datetime, timedelta, timezone
        from core.weather_market_filter import WeatherMarket, WeatherMarketFilter

        filt = WeatherMarketFilter(
            {
                "PAPER_LANE_MODE": "at_or_below_only",
                "MIN_LIQUIDITY": 0,
                "MIN_ODDS": 0.01,
                "MAX_ODDS": 0.99,
                "MIN_TIME_TO_RESOLUTION_HOURS": 0,
                "ALLOWED_CITIES": ["Chicago"],
            }
        )
        now = datetime.now(timezone.utc)
        market = WeatherMarket(
            market_id="x2",
            question="Will the highest temperature in Chicago be 89°F or below on July 16?",
            resolution_text="temp",
            description="weather",
            category="Weather",
            is_binary=True,
            liquidity_usd=1000.0,
            odds_yes=0.30,
            resolution_time=now + timedelta(hours=48),
        )
        result = filt.filter_market(market)
        assert result.passed is True


class TestGateProgressVisibility:
    def test_load_gate_progress_has_required_keys(self):
        from analytics.skill_common import load_gate_progress

        gp = load_gate_progress()
        assert "n_unique" in gp
        assert "target" in gp
        assert "progress_pct" in gp


class TestProposalCityPersistence:
    def test_adapter_sets_city_and_market_type(self):
        from proposals.signal_adapter import _detect_market_type_from_question

        assert (
            _detect_market_type_from_question(
                "Will the highest temperature in Dallas be 71°F or below on April 20?"
            )
            == "at_or_below"
        )
        assert (
            _detect_market_type_from_question(
                "Will the highest temperature in Dallas be 71°F or above on April 20?"
            )
            == "at_or_above"
        )

class TestGammaBelowPrefer:
    def test_is_at_or_below_question(self):
        from collector.gamma_discovery import _is_at_or_below_question

        assert _is_at_or_below_question(
            "will the highest temperature in chicago be 89°f or below on july 16?"
        )
        assert not _is_at_or_below_question(
            "will the highest temperature in chicago be 89°f or above on july 16?"
        )
        assert not _is_at_or_below_question(
            "will the highest temperature in chicago be between 88-89°f on july 16?"
        )

    def test_discover_prefer_flag_calls_extra_pages(self, monkeypatch):
        from collector import gamma_discovery as gd
        from datetime import datetime, timedelta, timezone

        calls = []

        def fake_get(url, params=None, timeout=None, headers=None):
            calls.append(dict(params or {}))
            class R:
                def raise_for_status(self):
                    return None
                def json(self):
                    # Only return a below market on offset pages
                    offset = int((params or {}).get("offset") or 0)
                    if offset == 0 and (params or {}).get("order") == "end_date_iso":
                        end = (datetime.now(timezone.utc) + timedelta(hours=48)).isoformat()
                        return [
                            {
                                "id": f"below-{offset}",
                                "question": "Will the highest temperature in Dallas be 71°F or below on April 20?",
                                "description": "temperature",
                                "liquidity": 100,
                                "endDateIso": end,
                                "active": True,
                                "closed": False,
                            }
                        ]
                    return []
            return R()

        monkeypatch.setattr(gd.requests, "get", fake_get)
        out = gd.discover_weather_markets(
            limit=50,
            min_liquidity=10,
            prefer_at_or_below=True,
            below_pages=2,
            below_min_liquidity=10,
        )
        assert any(c.get("offset") == 500 for c in calls), calls
        assert any("or below" in (m.get("question") or "").lower() for m in out)

class TestAobEdgeFloors:
    def test_engine_uses_lower_floor_for_below_events(self):
        from core.weather_engine import WeatherEngine

        eng = WeatherEngine(
            {
                "MIN_EDGE": 0.30,
                "MIN_EDGE_ABSOLUTE": 0.10,
                "AT_OR_BELOW_MIN_EDGE": 0.15,
                "AT_OR_BELOW_MIN_EDGE_ABSOLUTE": 0.04,
                "YES_MIN_EDGE": 0.15,
                "ENSEMBLE": {"ENABLED": False},
            }
        )
        e, a = eng._edge_floors_for_event("below")
        assert e == 0.15 and a == 0.04
        e2, a2 = eng._edge_floors_for_event("exceeds")
        assert e2 == 0.30 and a2 == 0.10

    def test_guardrails_pass_aob_at_15pct_edge(self):
        from unittest.mock import MagicMock, patch
        from paper_trader import entry_guardrails as eg

        proposal = MagicMock()
        proposal.implied_probability = 0.22
        proposal.market_question = (
            "Will the highest temperature in Dallas be 71°F or below on April 20?"
        )
        proposal.market_type = "at_or_below"
        proposal.edge = 0.16
        proposal.model_probability = 0.38
        proposal.confidence_level = "HIGH"

        with patch.object(
            eg,
            "_load_weather_config",
            return_value={
                "ALLOWED_MARKET_TYPES": ["at_or_below"],
                "BLOCKED_MARKET_TYPES": ["exact", "at_or_above", "between"],
                "MAX_ODDS": 0.85,
                "MIN_ENTRY_PRICE": 0.15,
                "MIN_EDGE": 0.18,
                "MIN_EDGE_ABSOLUTE": 0.04,
                "AT_OR_BELOW_MIN_EDGE": 0.15,
                "AT_OR_BELOW_MIN_EDGE_ABSOLUTE": 0.04,
            },
        ), patch.object(
            eg, "_load_capital_config", return_value={"max_open_positions": 12}
        ), patch.object(eg, "_load_agent_policy", return_value={}):
            ok, reason = eg.evaluate_entry_guardrails(
                proposal, open_positions_count=0, ignore_inventory_limit=True
            )
        assert ok is True, reason

