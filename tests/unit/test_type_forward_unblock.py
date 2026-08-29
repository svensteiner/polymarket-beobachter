"""Tests for the evidence-gated per-market-type auto-unblock in entry_guardrails.

A statically-blocked market type may only become tradeable when
forward_validation proves the model beats the market on that type (large sample,
positive skill). Missing/weak evidence must keep it blocked (fail-closed).
"""

import json

import paper_trader.entry_guardrails as eg


def _write_fv(tmp_path, monkeypatch, by_market_type):
    fv = tmp_path / "forward_validation.json"
    fv.write_text(json.dumps({"observation_test": {"by_market_type": by_market_type}}),
                  encoding="utf-8")
    monkeypatch.setattr(eg, "FORWARD_VALIDATION_JSON", fv)


def test_eligible_when_model_beats_market_large_sample(tmp_path, monkeypatch):
    _write_fv(tmp_path, monkeypatch, {
        "exact": {"n": 150, "model_brier": 0.10, "market_brier": 0.15, "model_beats_market": True},
    })
    assert eg._type_forward_eligible("exact") is True     # skill = 1 - .10/.15 = 0.33


def test_blocked_when_skill_too_small(tmp_path, monkeypatch):
    _write_fv(tmp_path, monkeypatch, {
        # model_beats_market True but skill only ~0.7% (< 2% floor)
        "exact": {"n": 150, "model_brier": 0.1490, "market_brier": 0.1500, "model_beats_market": True},
    })
    assert eg._type_forward_eligible("exact") is False


def test_blocked_when_sample_too_small(tmp_path, monkeypatch):
    _write_fv(tmp_path, monkeypatch, {
        "exact": {"n": 20, "model_brier": 0.10, "market_brier": 0.15, "model_beats_market": True},
    })
    assert eg._type_forward_eligible("exact") is False


def test_blocked_when_model_worse(tmp_path, monkeypatch):
    _write_fv(tmp_path, monkeypatch, {
        "exact": {"n": 150, "model_brier": 0.16, "market_brier": 0.15, "model_beats_market": False},
    })
    assert eg._type_forward_eligible("exact") is False


def test_blocked_when_type_absent(tmp_path, monkeypatch):
    _write_fv(tmp_path, monkeypatch, {"between": {"n": 150, "model_brier": 0.1, "market_brier": 0.15, "model_beats_market": True}})
    assert eg._type_forward_eligible("exact") is False


def test_fail_closed_when_file_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(eg, "FORWARD_VALIDATION_JSON", tmp_path / "does_not_exist.json")
    assert eg._type_forward_eligible("exact") is False


class _Proposal:
    def __init__(self, q, edge=0.5, imp=0.3, model=0.8):
        self.market_question = q
        self.market_type = None
        self.edge = edge
        self.implied_probability = imp
        self.model_probability = model
        self.confidence_level = "HIGH"


def test_guardrail_blocks_exact_without_evidence(tmp_path, monkeypatch):
    monkeypatch.setattr(eg, "FORWARD_VALIDATION_JSON", tmp_path / "missing.json")
    # "be 27C" exact-type proposal should be blocked (no forward evidence)
    p = _Proposal("Will the highest temperature in Ankara be 27C on August 31?")
    allowed, reason = eg.evaluate_entry_guardrails(p, open_positions_count=0)
    assert allowed is False
    assert "market_type_blocked" in reason


def test_guardrail_unblocks_exact_with_evidence(tmp_path, monkeypatch):
    _write_fv(tmp_path, monkeypatch, {
        "exact": {"n": 150, "model_brier": 0.10, "market_brier": 0.15, "model_beats_market": True},
    })
    p = _Proposal("Will the highest temperature in Ankara be 27C on August 31?")
    allowed, reason = eg.evaluate_entry_guardrails(p, open_positions_count=0)
    # No longer blocked on market_type; passes the type gate (other checks may
    # still apply, but the reason must NOT be market_type_blocked).
    assert "market_type_blocked" not in reason
