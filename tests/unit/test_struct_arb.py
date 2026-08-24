"""Tests for the structural-arbitrage paper lane (complete-set + binary lock)."""
from __future__ import annotations

import json
from typing import Any, Dict, List

import pytest

from paper_trader.struct_arb_math import (
    MIN_ASK_COVERAGE,
    MIN_NET,
    PLACEHOLDER_TITLE_RE,
    ask_coverage_ok,
    binary_lock_net,
    completeset_no_net,
    completeset_yes_net,
    gamma_prefilter_ok,
    member_is_live,
    partition_is_complete,
    set_pnl_eur,
    skipped_inactive_ok,
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

    already_won = [
        {"closed": True, "yes_price": 1.0},
        {"closed": False, "yes_price": 0.12},
        {"closed": False, "yes_price": 0.34},
    ]
    assert partition_is_complete(already_won) is False


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

    def fake_token(token_id: str, budget):
        # 3 * 0.31 = 0.93 >= MIN_ASK_COVERAGE; net still clears MIN_NET after fees.
        return {
            "ok": True,
            "best_ask": 0.31,
            "real_spread": 0.01,
            "ask_depth_shares": 50.0,
            "reason": "ok",
        }

    monkeypatch.setattr(sa, "_make_client", lambda: FakeClient())
    monkeypatch.setattr(sa, "_fetch_token", fake_token)
    monkeypatch.setattr(sa, "MAX_BOOK_FETCHES", 10)

    entered = sa.record_entries()
    assert entered == 1
    rows = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 1
    assert rows[0]["status"] == "OPEN"
    assert rows[0]["side"] == "BUY_YES_SET"
    assert rows[0]["notional_eur"] == 5.0
    assert rows[0]["governance_notice"] == "PAPER ONLY — no live order"
    assert rows[0]["residual_risk"] == "none"
    assert "partition_id" in rows[0]

    # Duplicate partition_id must not re-enter.
    assert sa.record_entries() == 0

    closed_by_id = {
        "m0": {"id": "m0", "closed": True, "outcomePrices": json.dumps([1.0, 0.0])},
        "m1": {"id": "m1", "closed": True, "outcomePrices": json.dumps([0.0, 1.0])},
        "m2": {"id": "m2", "closed": True, "outcomePrices": json.dumps([0.0, 1.0])},
    }

    monkeypatch.setattr(sa, "_fetch_gamma_market", lambda mid: closed_by_id.get(str(mid)))
    closed = sa.close_resolved()
    assert closed == 1
    rows = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()]
    assert rows[0]["status"] == "RESOLVED"
    assert rows[0]["pnl_eur"] > 0


def test_depth_must_cover_sized_shares(monkeypatch, tmp_path):
    """5 EUR / cheap set needs more shares than a 5-share depth gate."""
    import paper_trader.struct_arb as sa

    ledger = tmp_path / "struct_arb.jsonl"
    monkeypatch.setattr(sa, "LEDGER_PATH", ledger)
    monkeypatch.setattr(sa, "OUT_MD", tmp_path / "d.md")
    monkeypatch.setattr(sa, "OUT_JSON", tmp_path / "d.json")
    monkeypatch.setattr(sa, "NOTIONAL_EUR", 5.0)

    events = [
        {
            "id": "evt-thin",
            "title": "Thin book partition",
            "closed": False,
            "negRisk": True,
            "markets": [
                {
                    "id": f"t{i}",
                    "closed": False,
                    "negRiskMarketID": "nr-thin",
                    "question": f"Bucket {i}?",
                    "outcomePrices": json.dumps([0.10, 0.90]),
                    "clobTokenIds": json.dumps([f"y{i}", f"n{i}"]),
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

    def fake_token(token_id: str, budget):
        # 3*0.31=0.93 clears coverage; cost~0.98 → need ~5.1 shares; depth 5.0 passes
        # MIN_ASK_DEPTH but fails sized-share cover.
        return {
            "ok": True,
            "best_ask": 0.31,
            "ask_depth_shares": 5.0,
            "reason": "ok",
        }

    monkeypatch.setattr(sa, "_make_client", lambda: FakeClient())
    monkeypatch.setattr(sa, "_fetch_token", fake_token)
    assert sa.record_entries() == 0
    assert not ledger.exists() or not ledger.read_text(encoding="utf-8").strip()


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


def test_binary_lock_probes_when_gamma_mids_sum_to_one(monkeypatch, tmp_path):
    """Gamma YES+NO mids always sum to 1 — that must NOT skip CLOB probes."""
    import paper_trader.struct_arb as sa

    ledger = tmp_path / "struct_arb.jsonl"
    monkeypatch.setattr(sa, "LEDGER_PATH", ledger)
    monkeypatch.setattr(sa, "OUT_MD", tmp_path / "b.md")
    monkeypatch.setattr(sa, "OUT_JSON", tmp_path / "b.json")

    events = [
        {
            "id": "bin-evt",
            "title": "Standalone binary",
            "closed": False,
            "negRisk": False,
            "volume24hr": 1000,
            "markets": [
                {
                    "id": "bin-1",
                    "closed": False,
                    "question": "Will X happen?",
                    "outcomePrices": json.dumps([0.50, 0.50]),
                    "clobTokenIds": json.dumps(["tok-yes", "tok-no"]),
                    "outcomes": json.dumps(["Yes", "No"]),
                }
            ],
        }
    ]

    class FakeClient:
        def fetch_events(self, **kwargs):
            offset = kwargs.get("offset", 0)
            return events if offset == 0 else []

    def fake_token(token_id: str, budget):
        # Asks must clear taker fees: 0.46+0.47+fees ≈ 0.97 → net > MIN_NET.
        ask = 0.46 if token_id == "tok-yes" else 0.47
        return {
            "ok": True,
            "best_ask": ask,
            "ask_depth_shares": 20.0,
            "reason": "ok",
        }

    monkeypatch.setattr(sa, "_make_client", lambda: FakeClient())
    monkeypatch.setattr(sa, "_fetch_token", fake_token)

    from paper_trader.struct_arb_math import binary_lock_net, tradeable_net

    assert tradeable_net(binary_lock_net(0.46, 0.47)) is True
    entered = sa.record_entries()
    assert entered == 1
    rows = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()]
    assert rows[0]["side"] == "BINARY_LOCK"
    assert rows[0]["partition_id"] == "binary:bin-1"
    assert rows[0]["governance_notice"] == "PAPER ONLY — no live order"


def test_run_fail_open_and_writes_reports(monkeypatch, tmp_path):
    import paper_trader.struct_arb as sa

    monkeypatch.setattr(sa, "LEDGER_PATH", tmp_path / "struct_arb.jsonl")
    monkeypatch.setattr(sa, "OUT_MD", tmp_path / "struct_arb.md")
    monkeypatch.setattr(sa, "OUT_JSON", tmp_path / "struct_arb.json")

    def boom():
        raise RuntimeError("network down")

    monkeypatch.setattr(sa, "record_entries", boom)
    monkeypatch.setattr(sa, "close_resolved", boom)

    def boom_summary():
        raise RuntimeError("corrupt ledger")

    monkeypatch.setattr(sa, "summary", boom_summary)
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


def test_member_is_live_true_and_false_cases():
    assert member_is_live({"closed": False, "active": True}) is True
    assert member_is_live({"closed": False, "liquidity": 10.0}) is True
    assert member_is_live({"closed": False, "liquidityNum": 1.5}) is True
    assert member_is_live({"closed": False, "yes_price": 0.42}) is True
    assert member_is_live({"closed": False, "bestBid": 0.01}) is True
    # Inactive placeholders: no activity signals.
    assert member_is_live({
        "closed": False,
        "active": False,
        "liquidity": 0,
        "yes_price": None,
        "bestBid": 0,
    }) is False
    assert member_is_live({"closed": True, "active": True, "yes_price": 1.0}) is False
    assert member_is_live({"closed": False, "yes_price": 0.0}) is False
    assert member_is_live({"closed": False, "yes_price": 1.0}) is False


def test_ask_coverage_ok_threshold():
    assert MIN_ASK_COVERAGE == 0.92
    assert ask_coverage_ok([0.018, 0.965]) is True  # 0.983
    assert ask_coverage_ok([0.02] * 18) is False  # 0.36 Nobel-style fake incomplete
    assert ask_coverage_ok([]) is False


def test_us_election_placeholders_treated_as_n2_complete(monkeypatch, tmp_path):
    """2 live D+R + 10 inactive Person A-J placeholders → n=2 complete set (placeholders_only)."""
    import paper_trader.struct_arb as sa

    ledger = tmp_path / "struct_arb.jsonl"
    monkeypatch.setattr(sa, "LEDGER_PATH", ledger)
    monkeypatch.setattr(sa, "OUT_MD", tmp_path / "u.md")
    monkeypatch.setattr(sa, "OUT_JSON", tmp_path / "u.json")
    monkeypatch.setattr(sa, "NOTIONAL_EUR", 5.0)

    live = [
        {
            "id": "dem",
            "closed": False,
            "active": True,
            "liquidity": 5000,
            "negRiskMarketID": "nr-sd",
            "question": "Democrat?",
            "outcomePrices": json.dumps([0.02, 0.98]),
            "bestAsk": 0.018,
            "bestBid": 0.015,
            "clobTokenIds": json.dumps(["yes-dem", "no-dem"]),
            "outcomes": json.dumps(["Yes", "No"]),
        },
        {
            "id": "rep",
            "closed": False,
            "active": True,
            "liquidity": 8000,
            "negRiskMarketID": "nr-sd",
            "question": "Republican?",
            "outcomePrices": json.dumps([0.96, 0.04]),
            "bestAsk": 0.965,
            "bestBid": 0.96,
            "clobTokenIds": json.dumps(["yes-rep", "no-rep"]),
            "outcomes": json.dumps(["Yes", "No"]),
        },
    ]
    placeholders = [
        {
            "id": f"ph{i}",
            "closed": False,
            "active": False,
            "liquidity": 0,
            "liquidityNum": 0,
            "negRiskMarketID": "nr-sd",
            "groupItemTitle": f"Person {chr(65 + i)}",
            "question": f"Person {chr(65 + i)}?",
            "outcomePrices": None,
            "bestAsk": None,
            "bestBid": 0,
            "clobTokenIds": json.dumps([f"yes-ph{i}", f"no-ph{i}"]),
            "outcomes": json.dumps(["Yes", "No"]),
        }
        for i in range(10)  # Person A-J
    ]
    events = [
        {
            "id": "evt-sd",
            "title": "South Dakota Senate Election Winner",
            "closed": False,
            "negRisk": True,
            "markets": live + placeholders,
        }
    ]

    class FakeClient:
        def fetch_events(self, **kwargs):
            offset = kwargs.get("offset", 0)
            return events if offset == 0 else []

    def fake_token(token_id: str, budget):
        ask = 0.018 if token_id == "yes-dem" else 0.965
        return {
            "ok": True,
            "best_ask": ask,
            "ask_depth_shares": 5000.0,
            "reason": "ok",
        }

    monkeypatch.setattr(sa, "_make_client", lambda: FakeClient())
    monkeypatch.setattr(sa, "_fetch_token", fake_token)

    # Math-level: placeholders not live; live+closed scan is complete n=2.
    assert member_is_live(placeholders[0]) is False
    assert member_is_live(live[0]) is True
    scan = [{"closed": False, "yes_price": 0.02}, {"closed": False, "yes_price": 0.96}]
    assert partition_is_complete(scan) is True
    assert ask_coverage_ok([0.018, 0.965]) is True

    from paper_trader.struct_arb_math import completeset_yes_net, tradeable_net

    net = completeset_yes_net([0.018, 0.965])
    assert tradeable_net(net) is True

    entered = sa.record_entries()
    assert entered == 1
    rows = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()]
    assert rows[0]["n_legs"] == 2
    assert rows[0]["skipped_inactive"] == 10
    assert rows[0]["residual_risk"] == "placeholders_only"
    assert rows[0]["coverage"] == pytest.approx(0.983, abs=1e-6)
    assert "South Dakota" in rows[0]["title"]


def test_partition_probe_order_prefers_higher_gamma_net():
    """Under tight budget, probe higher gamma-estimated YES-set net first (no network)."""
    import paper_trader.struct_arb as sa
    from paper_trader.struct_arb_math import completeset_yes_net

    def legs(asks):
        return [
            {"closed": False, "active": True, "bestAsk": a, "yes_price": a}
            for a in asks
        ]

    # Same n=2: cheap set (high est_net) must sort before expensive set.
    high = {"members": legs([0.10, 0.20])}  # S=0.30 → strong yes net
    low = {"members": legs([0.45, 0.45])}   # S=0.90 → weaker yes net
    ordered = sorted([("low", low), ("high", high)], key=sa._partition_probe_sort_key)
    assert ordered[0][0] == "high"
    assert ordered[1][0] == "low"
    assert completeset_yes_net([0.10, 0.20]) > completeset_yes_net([0.45, 0.45])

    # 2-leg preference remains primary even if a 3-leg has higher est_net.
    two = {"members": legs([0.48, 0.48])}          # weaker net
    three = {"members": legs([0.05, 0.05, 0.05])}  # much stronger net
    ordered2 = sorted([("three", three), ("two", two)], key=sa._partition_probe_sort_key)
    assert ordered2[0][0] == "two"
    assert ordered2[1][0] == "three"

    # Binary: higher gamma est_net before lower (volume secondary).
    good = {"yes_price": 0.40, "no_price": 0.40, "volume": 1.0}
    bad = {"yes_price": 0.49, "no_price": 0.49, "volume": 9999.0}
    bins = sorted([bad, good], key=sa._binary_probe_sort_key)
    assert bins[0] is good

def test_placeholder_title_re_person_option_a_to_j():
    assert PLACEHOLDER_TITLE_RE.search("Person A")
    assert PLACEHOLDER_TITLE_RE.search("person j")
    assert PLACEHOLDER_TITLE_RE.search("Option C")
    assert PLACEHOLDER_TITLE_RE.search("OPTION B?")
    assert PLACEHOLDER_TITLE_RE.search("Will Person A win?")
    assert not PLACEHOLDER_TITLE_RE.search("Other")
    assert not PLACEHOLDER_TITLE_RE.search("Other candidate")
    assert not PLACEHOLDER_TITLE_RE.search("Catch-all")
    assert not PLACEHOLDER_TITLE_RE.search("Person K")
    assert not PLACEHOLDER_TITLE_RE.search("Independent")


def test_skipped_inactive_ok_placeholders_only():
    skipped = [
        {
            "closed": False,
            "active": False,
            "liquidity": 0,
            "groupItemTitle": f"Person {chr(65 + i)}",
        }
        for i in range(10)
    ]
    assert skipped_inactive_ok(skipped) is True
    assert skipped_inactive_ok([]) is True
    assert skipped_inactive_ok(None) is True
    # Closed / live members in the list are ignored.
    mixed = skipped + [{"closed": True, "groupItemTitle": "Other", "active": False}]
    assert skipped_inactive_ok(mixed) is True


def test_skipped_inactive_ok_rejects_other():
    skipped = [
        {"closed": False, "active": False, "groupItemTitle": "Person A"},
        {"closed": False, "active": False, "groupItemTitle": "Other"},
    ]
    assert skipped_inactive_ok(skipped) is False
    assert skipped_inactive_ok([
        {"closed": False, "active": False, "question": "Any other candidate?"}
    ]) is False
    assert skipped_inactive_ok([
        {"closed": False, "active": False, "groupItemTitle": "Person K"}
    ]) is False


def test_residual_other_skip_rejects_entry_no_clob(monkeypatch, tmp_path):
    """D+R plus Person A-J plus Other is NOT a clean complete set -- no CLOB, no entry."""
    import paper_trader.struct_arb as sa

    ledger = tmp_path / "struct_arb.jsonl"
    monkeypatch.setattr(sa, "LEDGER_PATH", ledger)
    monkeypatch.setattr(sa, "OUT_MD", tmp_path / "o.md")
    monkeypatch.setattr(sa, "OUT_JSON", tmp_path / "o.json")
    monkeypatch.setattr(sa, "NOTIONAL_EUR", 5.0)

    live = [
        {
            "id": "dem",
            "closed": False,
            "active": True,
            "liquidity": 5000,
            "negRiskMarketID": "nr-sd",
            "groupItemTitle": "Democrat",
            "question": "Democrat?",
            "outcomePrices": json.dumps([0.02, 0.98]),
            "bestAsk": 0.018,
            "bestBid": 0.015,
            "clobTokenIds": json.dumps(["yes-dem", "no-dem"]),
            "outcomes": json.dumps(["Yes", "No"]),
        },
        {
            "id": "rep",
            "closed": False,
            "active": True,
            "liquidity": 8000,
            "negRiskMarketID": "nr-sd",
            "groupItemTitle": "Republican",
            "question": "Republican?",
            "outcomePrices": json.dumps([0.96, 0.04]),
            "bestAsk": 0.965,
            "bestBid": 0.96,
            "clobTokenIds": json.dumps(["yes-rep", "no-rep"]),
            "outcomes": json.dumps(["Yes", "No"]),
        },
    ]
    placeholders = [
        {
            "id": f"ph{i}",
            "closed": False,
            "active": False,
            "liquidity": 0,
            "liquidityNum": 0,
            "negRiskMarketID": "nr-sd",
            "groupItemTitle": f"Person {chr(65 + i)}",
            "question": f"Person {chr(65 + i)}?",
            "outcomePrices": None,
            "bestAsk": None,
            "bestBid": 0,
            "clobTokenIds": json.dumps([f"yes-ph{i}", f"no-ph{i}"]),
            "outcomes": json.dumps(["Yes", "No"]),
        }
        for i in range(10)
    ]
    other = {
        "id": "other",
        "closed": False,
        "active": False,
        "liquidity": 0,
        "liquidityNum": 0,
        "negRiskMarketID": "nr-sd",
        "groupItemTitle": "Other",
        "question": "Other candidate?",
        "outcomePrices": None,
        "bestAsk": None,
        "bestBid": 0,
        "clobTokenIds": json.dumps(["yes-other", "no-other"]),
        "outcomes": json.dumps(["Yes", "No"]),
    }
    events = [
        {
            "id": "evt-sd",
            "title": "South Dakota Senate Election Winner",
            "closed": False,
            "negRisk": True,
            "markets": live + placeholders + [other],
        }
    ]

    class FakeClient:
        def fetch_events(self, **kwargs):
            offset = kwargs.get("offset", 0)
            return events if offset == 0 else []

    def fake_token(token_id: str, budget):
        raise AssertionError(f"CLOB must not be probed for residual Other ({token_id})")

    monkeypatch.setattr(sa, "_make_client", lambda: FakeClient())
    monkeypatch.setattr(sa, "_fetch_token", fake_token)

    assert skipped_inactive_ok(placeholders + [other]) is False
    entered = sa.record_entries()
    assert entered == 0
    assert not ledger.exists() or not ledger.read_text(encoding="utf-8").strip()
    assert sa._LAST_SCAN["skip_counts"].get("residual_other", 0) >= 1

