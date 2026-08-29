"""Unit tests for paper_trader.clob_book real NO-fill cost logic."""

from paper_trader.clob_book import compute_no_cost, NoBookCost


def test_direct_no_ask_is_primary_cost():
    no_book = {
        "asks": [{"price": "0.90", "size": "100"}, {"price": "0.92", "size": "50"}],
        "bids": [{"price": "0.85", "size": "80"}],
    }
    r = compute_no_cost(no_book, market_id="m1")
    assert r.ok is True
    assert r.cost_source == "no_book"
    assert r.no_best_ask == 0.90          # lowest ask, not 0.92
    assert r.no_best_bid == 0.85
    assert r.real_spread == 0.05
    # depth counts asks within 2c of best (0.90 and 0.92 both qualify)
    assert r.ask_depth_shares == 150.0


def test_depth_excludes_far_asks():
    no_book = {
        "asks": [{"price": "0.90", "size": "10"}, {"price": "0.95", "size": "999"}],
        "bids": [],
    }
    r = compute_no_cost(no_book, market_id="m2")
    assert r.no_best_ask == 0.90
    assert r.ask_depth_shares == 10.0     # 0.95 is >2c away, excluded


def test_synthetic_no_cost_from_yes_bid_when_no_asks_empty():
    no_book = {"asks": [], "bids": [{"price": "0.01", "size": "200"}]}
    yes_book = {
        "asks": [{"price": "0.30", "size": "40"}],
        "bids": [{"price": "0.22", "size": "60"}],
    }
    r = compute_no_cost(no_book, yes_book, market_id="m3")
    assert r.ok is True
    assert r.cost_source == "synthetic_yes"
    assert r.no_best_ask == 0.78          # 1 - 0.22
    assert r.real_spread == 0.08          # yes_ask - yes_bid = 0.30 - 0.22
    assert r.ask_depth_shares == 60.0


def test_no_liquidity_when_both_sides_empty():
    r = compute_no_cost({"asks": [], "bids": []}, {"asks": [], "bids": []}, market_id="m4")
    assert r.ok is False
    assert r.reason == "no_liquidity"
    assert r.no_best_ask is None


def test_malformed_levels_are_skipped():
    no_book = {"asks": [{"price": "oops", "size": "10"}, {"price": "0.5", "size": "5"}], "bids": []}
    r = compute_no_cost(no_book, market_id="m5")
    assert r.no_best_ask == 0.5           # bad level skipped, good one used


def test_to_dict_roundtrip_has_expected_keys():
    r = NoBookCost(ok=True, reason="ok", market_id="m6", no_best_ask=0.9)
    d = r.to_dict()
    for k in ("ok", "reason", "no_best_ask", "real_spread", "ask_depth_shares", "cost_source"):
        assert k in d
