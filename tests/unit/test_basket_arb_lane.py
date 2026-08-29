"""Unit tests for paper_trader.basket_arb_lane entry/close/PnL logic."""

import json
from pathlib import Path

import paper_trader.basket_arb_lane as lane


def _actionable_opp():
    return {
        "family_key": "testville|lowest|may 1",
        "city": "testville", "metric": "lowest", "date": "may 1",
        "actionable": True,
        "legs": [
            {"market_id": "1", "no_ask": 0.60, "fee": 0.0},
            {"market_id": "2", "no_ask": 0.60, "fee": 0.0},
            {"market_id": "3", "no_ask": 0.60, "fee": 0.0},
        ],
    }


# --------------------------- build_entry_record --------------------------- #
def test_build_entry_record_computes_cost_and_expected_net():
    rec = lane.build_entry_record(_actionable_opp())
    assert rec is not None
    assert rec["n_buckets"] == 3
    assert abs(rec["total_cost"] - 1.8) < 1e-9      # 3 * 0.60
    assert rec["worst_case_payoff"] == 2            # n-1
    assert abs(rec["expected_net"] - 0.2) < 1e-9    # 2 - 1.8
    assert rec["status"] == "OPEN"
    assert rec["side"] == "NO_BASKET"


def test_build_entry_record_rejects_non_actionable():
    opp = _actionable_opp()
    opp["actionable"] = False
    assert lane.build_entry_record(opp) is None


def test_build_entry_record_rejects_unfillable_leg():
    opp = _actionable_opp()
    opp["legs"][1]["no_ask"] = None
    assert lane.build_entry_record(opp) is None


# --------------------------- compute_basket_pnl --------------------------- #
def test_compute_pnl_none_until_all_resolved():
    legs = [{"market_id": "1"}, {"market_id": "2"}, {"market_id": "3"}]
    res = {"1": "NO", "2": "NO"}  # leg 3 missing
    assert lane.compute_basket_pnl(legs, res, total_cost=1.8) is None


def test_compute_pnl_one_yes_pays_n_minus_1():
    legs = [{"market_id": "1"}, {"market_id": "2"}, {"market_id": "3"}]
    res = {"1": "YES", "2": "NO", "3": "NO"}   # exactly one YES
    out = lane.compute_basket_pnl(legs, res, total_cost=1.8)
    assert out["realized_payoff"] == 2.0        # two NO legs pay 1 each
    assert abs(out["realized_pnl"] - 0.2) < 1e-9
    assert out["yes_legs"] == 1


def test_compute_pnl_temperature_outside_range_pays_n():
    legs = [{"market_id": "1"}, {"market_id": "2"}, {"market_id": "3"}]
    res = {"1": "NO", "2": "NO", "3": "NO"}     # temp outside every bucket
    out = lane.compute_basket_pnl(legs, res, total_cost=1.8)
    assert out["realized_payoff"] == 3.0
    assert abs(out["realized_pnl"] - 1.2) < 1e-9


# --------------------------- record + close (isolated ledger) --------------------------- #
def test_record_and_close_end_to_end(tmp_path, monkeypatch):
    ledger = tmp_path / "basket_arb_ledger.jsonl"
    res_path = tmp_path / "resolutions.jsonl"
    monkeypatch.setattr(lane, "LEDGER_PATH", ledger)
    monkeypatch.setattr(lane, "RESOLUTIONS_PATH", res_path)

    # 1) enter
    entered = lane.record_entries([_actionable_opp()])
    assert entered == 1
    rows = [json.loads(l) for l in ledger.read_text().splitlines() if l.strip()]
    assert len(rows) == 1 and rows[0]["status"] == "OPEN"

    # 2) dedup: same family not re-entered
    assert lane.record_entries([_actionable_opp()]) == 0

    # 3) close after resolutions arrive (one bucket YES)
    res_path.write_text(
        "\n".join(json.dumps({"market_id": m, "resolved": True, "resolution": r})
                  for m, r in [("1", "YES"), ("2", "NO"), ("3", "NO")]),
        encoding="utf-8",
    )
    closed = lane.close_resolved()
    assert closed == 1
    rows = [json.loads(l) for l in ledger.read_text().splitlines() if l.strip()]
    assert rows[0]["status"] == "RESOLVED"
    assert abs(rows[0]["realized_pnl"] - 0.2) < 1e-9


def test_non_actionable_not_entered(tmp_path, monkeypatch):
    ledger = tmp_path / "basket_arb_ledger.jsonl"
    monkeypatch.setattr(lane, "LEDGER_PATH", ledger)
    opp = _actionable_opp()
    opp["actionable"] = False
    assert lane.record_entries([opp]) == 0
    assert not ledger.exists()
