"""Tests for the structural-arbitrage paper lane (complete-set + binary lock)."""
from __future__ import annotations

import json
from typing import Any, Dict, List

import pytest

from paper_trader.struct_arb_math import (
    MIN_NET,
    binary_lock_net,
    completeset_no_net,
    completeset_yes_net,
    gamma_prefilter_ok,
    partition_is_complete,
    set_pnl_eur,
    taker_fee,
    tradeable_net,
)


def test_taker_fee_matches_fee_model():
    from core.fee_model import polymarket_taker_fee

    for p in (0.05, 0.10, 0.25, 0.50, 0.75, 0.90):
        assert taker_fee(p) == pytest.approx(polymarket_taker_fee(p), rel=1e-9, abs=1e-12)
    assert taker_fee(0.5) == pytest.approx(0.02)


def test_completeset_yes_net_formula():
    asks = [0.20, 0.25, 0.30]
    expected = 1.0 - sum(a + taker_fee(a) for a in asks)
    assert completeset_yes_net(asks) == pytest.approx(expected)


def test_completeset_no_net_formula():
    no_asks = [0.70, 0.65, 0.60]
    n = len(no_asks)
    expected = (n - 1) - sum(a + taker_fee(a) for a in no_asks)
    assert completeset_no_net(no_asks) == pytest.approx(expected)


def test_binary_lock_net_formula():
    yes_ask, no_ask = 0.48, 0.49
    expected = 1.0 - (yes_ask + taker_fee(yes_ask) + no_ask + taker_fee(no_ask))
    assert binary_lock_net(yes_ask, no_ask) == pytest.approx(expected)


def test_gold_cards_synthetic_extra_rejects():
    """n=8, Gamma S=0.939, +1.5c synthetic per leg → net < 0 (never trade)."""
    n = 8
    S = 0.939
    mids = [S / n] * n
    asks = [m + 0.015 for m in mids]
    net = completeset_yes_net(asks)
    assert net < 0.0
    assert tradeable_net(net) is False
    assert MIN_NET == 0.01


def test_arctic_requires_real_asks_above_min_net():
    """n=7, S=1.0955 suggests NO-set gross edge, but synthetic asks reject."""
    n = 7
    S = 1.0955
    yes_mids = [S / n] * n
    no_mids = [1.0 - y for y in yes_mids]
    # Synthetic +1.5c/leg on NO asks → cost eats the gross S-1 edge.
    no_asks_synth = [m + 0.015 for m in no_mids]
    net_synth = completeset_no_net(no_asks_synth)
    assert net_synth < MIN_NET
    assert tradeable_net(net_synth) is False

    # Real asks that clear MIN_NET must be accepted by the gate.
    # Force a known-good book: payoff n-1=6, keep cost low.
    good_asks = [0.82] * 7
    net_good = completeset_no_net(good_asks)
    # 7*0.82=5.74 + fees ≈ 5.84 → net ≈ 0.16 > MIN_NET
    assert net_good >= MIN_NET
    assert tradeable_net(net_good) is True


def test_partition_is_complete_requires_yes_in_open_interval():
    members = [
        {"closed": False, "yes_price": 0.12},
        {"closed": False, "yes_price": 0.34},
        {"closed": True, "yes_price": 0.0},  # closed may be 0/1
    ]
    assert partition_is_complete(members) is True

    incomplete = [
        {"closed": False, "yes_price": 0.12},
        {"closed": False, "yes_price": 0.0},  # open but no mid → incomplete
        {"closed": False, "yes_price": 0.34},
    ]
    assert partition_is_complete(incomplete) is False


def test_nobel_incomplete_never_tradable():
    """20 priced of 71 → incomplete partition is never tradable."""
    members: List[Dict[str, Any]] = []
    for i in range(71):
        if i < 20:
            members.append({"closed": False, "yes_price": 0.01 + (i % 9) * 0.01})
        else:
            members.append({"closed": False, "yes_price": None})
    assert partition_is_complete(members) is False


def test_gamma_prefilter_threshold():
    # |1-S| must exceed n*0.003 to probe CLOB.
    assert gamma_prefilter_ok(S=0.90, n=8) is True   # |1-0.9|=0.1 > 0.024
    assert gamma_prefilter_ok(S=0.99, n=8) is False  # 0.01 < 0.024
    assert gamma_prefilter_ok(S=1.0955, n=7) is True


def test_set_pnl_buy_yes_set():
    # notional 5, cost_per_set 0.90 → shares=5/0.90, pnl=shares*1 - 5
    pnl = set_pnl_eur(notional_eur=5.0, cost_per_set=0.90, side="BUY_YES_SET")
    assert pnl == pytest.approx(5.0 / 0.90 - 5.0)


def test_set_pnl_buy_no_set():
    # payoff = n-1 per set; shares = notional/cost; pnl = shares*(n-1) - notional
    pnl = set_pnl_eur(
        notional_eur=5.0, cost_per_set=5.5, side="BUY_NO_SET", n_legs=7
    )
    shares = 5.0 / 5.5
    assert pnl == pytest.approx(shares * 6.0 - 5.0)


def test_record_entry_and_close(monkeypatch, tmp_path):
    import paper_trader.struct_arb as sa

    ledger = tmp_path / "struct_arb.jsonl"
    out_md = tmp_path / "struct_arb.md"
    out_json = tmp_path / "struct_arb.json"
    monkeypatch.setattr(sa, "LEDGER_PATH", ledger)
    monkeypatch.setattr(sa, "OUT_MD", out_md)
    monkeypatch.setattr(sa, "OUT_JSON", out_json)
    monkeypatch.setattr(sa, "NOTIONAL_EUR", 5.0)
    monkeypatch.setattr(sa, "MAX_OPEN", 6)

    events = [
        {
            "id": "evt-1",
            "title": "Test Partition",
            "closed": False,
            "negRisk": True,
            "markets": [
                {
                    "id": f"m{i}",
                    "closed": False,
                    "negRiskMarketID": "nr-1",
                    "question": f"Bucket {i}?",
                    "outcomePrices": json.dumps([0.10, 0.90]),
                    "clobTokenIds": json.dumps([f"yes-{i}", f"no-{i}"]),
                    "outcomes": json.dumps(["Yes", "No"]),
                }
                for i in range(3)
            ],
        }
    ]

    class FakeClient:
        def fetch_events(self, **kwargs):
            offset = kwargs.get("offset", 0)
            return events if offset == 0 else []

    # Cheap YES asks so completeset_yes_net >> MIN_NET (3*0.20=0.60 + fees).
    def fake_yes_book(market_id: str):
        class B:
            def to_dict(self):
                return {
                    "ok": True,
                    "yes_best_ask": 0.20,
                    "real_spread": 0.01,
                    "ask_depth_shares": 50.0,
                    "reason": "ok",
                }

        return B()

    monkeypatch.setattr(sa, "_make_client", lambda: FakeClient())
    monkeypatch.setattr(
        "paper_trader.clob_book.fetch_yes_book_cost",
        fake_yes_book,
    )
    # Avoid binary-lock CLOB traffic in this unit test.
    monkeypatch.setattr(sa, "MAX_BOOK_FETCHES", 10)

    entered = sa.record_entries()
    assert entered == 1
    rows = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 1
    assert rows[0]["status"] == "OPEN"
    assert rows[0]["side"] == "BUY_YES_SET"
    assert rows[0]["notional_eur"] == 5.0
    assert rows[0]["governance_notice"] == "PAPER ONLY — no live order"
    assert "partition_id" in rows[0]

    # Duplicate partition_id must not re-enter.
    assert sa.record_entries() == 0

    # Close when all legs resolved (YES on m0).
    closed_events = [
        {
            "id": "evt-1",
            "closed": False,
            "negRisk": True,
            "markets": [
                {
                    "id": "m0",
                    "closed": True,
                    "negRiskMarketID": "nr-1",
                    "outcomePrices": json.dumps([1.0, 0.0]),
                },
                {
                    "id": "m1",
                    "closed": True,
                    "negRiskMarketID": "nr-1",
                    "outcomePrices": json.dumps([0.0, 1.0]),
                },
                {
                    "id": "m2",
                    "closed": True,
                    "negRiskMarketID": "nr-1",
                    "outcomePrices": json.dumps([0.0, 1.0]),
                },
            ],
        }
    ]

    class FakeClientClosed:
        def fetch_events(self, **kwargs):
            offset = kwargs.get("offset", 0)
            return closed_events if offset == 0 else []

    monkeypatch.setattr(sa, "_make_client", lambda: FakeClientClosed())
    closed = sa.close_resolved()
    assert closed == 1
    rows = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()]
    assert rows[0]["status"] == "RESOLVED"
    assert rows[0]["pnl_eur"] > 0


def test_inventory_full_blocks_entry(monkeypatch, tmp_path):
    import paper_trader.struct_arb as sa

    ledger = tmp_path / "struct_arb.jsonl"
    monkeypatch.setattr(sa, "LEDGER_PATH", ledger)
    monkeypatch.setattr(sa, "OUT_MD", tmp_path / "a.md")
    monkeypatch.setattr(sa, "OUT_JSON", tmp_path / "a.json")
    full = [
        {"partition_id": f"p-{i}", "status": "OPEN", "side": "BUY_YES_SET"}
        for i in range(sa.MAX_OPEN)
    ]
    ledger.write_text("\n".join(json.dumps(r) for r in full) + "\n", encoding="utf-8")

    class FakeClient:
        def fetch_events(self, **kwargs):
            return []

    monkeypatch.setattr(sa, "_make_client", lambda: FakeClient())
    assert sa.record_entries() == 0


def test_run_fail_open_and_writes_reports(monkeypatch, tmp_path):
    import paper_trader.struct_arb as sa

    monkeypatch.setattr(sa, "LEDGER_PATH", tmp_path / "struct_arb.jsonl")
    monkeypatch.setattr(sa, "OUT_MD", tmp_path / "struct_arb.md")
    monkeypatch.setattr(sa, "OUT_JSON", tmp_path / "struct_arb.json")

    def boom():
        raise RuntimeError("network down")

    monkeypatch.setattr(sa, "record_entries", boom)
    monkeypatch.setattr(sa, "close_resolved", boom)
    result = sa.run()
    assert isinstance(result, dict)
    assert "scanned" in result
    assert "complete" in result
    assert result.get("entered_this_cycle", 0) == 0
    assert sa.OUT_MD.exists()
    assert sa.OUT_JSON.exists()
    payload = json.loads(sa.OUT_JSON.read_text(encoding="utf-8"))
    assert "scanned" in payload
    assert "rejected_cost" in payload or "skip_counts" in payload
