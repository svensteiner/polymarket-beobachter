"""Tests for Bayesian weight update wiring and at_or_below skill report."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from core.outcome_tracker import (
    _parse_per_source_from_reasons,
    apply_bayesian_weight_update,
)


class TestPerSourceEncoding:
    def test_parse_per_source_probs(self):
        reasons = [
            "Edge: +12%",
            'PER_SOURCE_PROBS:{"ecmwf_ifs":0.42,"icon_global":0.37,"gem_global":0.33}',
        ]
        parsed = _parse_per_source_from_reasons(reasons)
        assert parsed["ecmwf_ifs"] == 0.42
        assert parsed["icon_global"] == 0.37
        assert parsed["gem_global"] == 0.33

    def test_parse_missing_returns_empty(self):
        assert _parse_per_source_from_reasons(["Edge only"]) == {}


class TestBayesianWeightUpdate:
    def test_applies_record_resolution_with_per_source(self):
        pred = MagicMock()
        pred.market_id = "m1"
        pred.timestamp_utc = "2026-08-30T00:00:00Z"
        pred.our_estimate_yes = 0.4
        pred.decision_reasons = [
            'PER_SOURCE_PROBS:{"ecmwf_ifs":0.55,"icon_global":0.45}'
        ]

        storage = MagicMock()
        storage.read_predictions.return_value = [pred]

        with patch("core.model_weights.record_resolution") as rec:
            rec.return_value = {"ecmwf_ifs": 1.4}
            ok = apply_bayesian_weight_update(storage, "m1", "YES")
            assert ok is True
            rec.assert_called_once()
            args, kwargs = rec.call_args
            assert args[0]["ecmwf_ifs"] == 0.55
            assert args[1] == 1  # YES outcome
            assert kwargs.get("market_id") == "m1" or (len(args) > 2 and args[2] == "m1")

    def test_fallback_to_ensemble_estimate(self):
        pred = MagicMock()
        pred.market_id = "m2"
        pred.timestamp_utc = "2026-08-30T00:00:00Z"
        pred.our_estimate_yes = 0.3
        pred.decision_reasons = ["Edge: +5%"]

        storage = MagicMock()
        storage.read_predictions.return_value = [pred]

        with patch("core.model_weights.record_resolution") as rec:
            rec.return_value = {}
            ok = apply_bayesian_weight_update(storage, "m2", "NO")
            assert ok is True
            forecasts = rec.call_args[0][0]
            assert forecasts == {"ensemble": 0.3}
            assert rec.call_args[0][1] == 0

    def test_skips_without_predictions(self):
        storage = MagicMock()
        storage.read_predictions.return_value = []
        assert apply_bayesian_weight_update(storage, "m3", "YES") is False


class TestAtOrBelowSkill:
    def test_run_produces_report(self, tmp_path, monkeypatch):
        from analytics import at_or_below_skill as mod

        positions = tmp_path / "positions.jsonl"
        resolutions = tmp_path / "resolutions.jsonl"
        out_json = tmp_path / "skill.json"
        out_md = tmp_path / "skill.md"

        positions.write_text(
            json.dumps(
                {
                    "market_id": "x1",
                    "market_type": "at_or_below",
                    "side": "YES",
                    "entry_price": 0.4,
                    "model_probability": 0.6,
                    "realized_pnl_eur": 1.0,
                }
            )
            + "\n",
            encoding="utf-8",
        )
        resolutions.write_text(
            json.dumps(
                {
                    "market_id": "x1",
                    "resolved": True,
                    "resolution": "YES",
                }
            )
            + "\n",
            encoding="utf-8",
        )

        monkeypatch.setattr(mod, "POSITIONS_PATH", positions)
        monkeypatch.setattr(mod, "RESOLUTIONS_PATH", resolutions)
        monkeypatch.setattr(mod, "OUT_JSON", out_json)
        monkeypatch.setattr(mod, "OUT_MD", out_md)

        report = mod.analyse()
        assert report["n"] == 1
        assert report["model_beats_market"] is True  # 0.6 closer to YES than 0.4
        assert out_json.exists()
        assert out_md.exists()
