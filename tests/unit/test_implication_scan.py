import json
import pytest

import analytics.implication_scan as scan


def market(mid, question, description, *, end="2026-10-01T00:00:00Z", source="official"):
    return {"id": mid, "conditionId": "c-" + mid, "question": question,
            "description": description, "active": True, "closed": False,
            "acceptingOrders": True, "endDate": end, "resolutionSource": source,
            "outcomes": json.dumps(["Yes", "No"]),
            "clobTokenIds": json.dumps(["y-" + mid, "n-" + mid]),
            "feesEnabled": False}


def event(*markets):
    return [{"id": "e1", "markets": list(markets)}]


def test_identifies_only_same_event_fdv_implication():
    low = market("low", "MetaMask FDV above $500M one day after launch?", scan.AUDITED_RULES["metamask"])
    high = market("high", "MetaMask FDV above $1B one day after launch?", scan.AUDITED_RULES["metamask"])
    pairs, rejects = scan.identify_pairs(event(low, high))
    assert len(pairs) == 1
    assert pairs[0]["low"]["market_id"] == "low"
    assert rejects == {}


def test_rejects_deadline_source_and_non_fdv_description_mismatches():
    low = market("low", "MetaMask FDV above $500M one day after launch?", scan.AUDITED_RULES["metamask"])
    high_deadline = market("high", "MetaMask FDV above $1B one day after launch?", scan.AUDITED_RULES["metamask"], end="later")
    assert not scan.identify_pairs(event(low, high_deadline))[0]
    high_source = market("high", "MetaMask FDV above $1B one day after launch?", "Resolution source B")
    assert not scan.identify_pairs(event(low, high_source))[0]
    high_other = market("high", "MetaMask FDV above $1B one day after launch?", "Resolution source A; $500M unrelated")
    assert not scan.identify_pairs(event(low, high_other))[0]


def test_scan_uses_two_books_and_decimal_leg_costs(monkeypatch, tmp_path):
    monkeypatch.setattr(scan, "STATUS_PATH", tmp_path / "status.json")
    monkeypatch.setattr(scan, "HISTORY_PATH", tmp_path / "history.jsonl")
    low = market("low", "MetaMask FDV above $500M one day after launch?", scan.AUDITED_RULES["metamask"])
    high = market("high", "MetaMask FDV above $1B one day after launch?", scan.AUDITED_RULES["metamask"])
    now = 1_700_000_000_000

    def get(url):
        token = "y-low" if "y-low" in url else "n-high"
        return {"asset_id": token, "market": "c-" + ("low" if token == "y-low" else "high"),
                "timestamp": str(now), "min_order_size": "1", "asks": [{"price": "0.40", "size": "5"}], "bids": []}

    result = scan.scan(event(low, high), get=get, now_ms=now)
    row = result["results"][0]
    assert result["book_requests"] == 2
    assert row["ok"] and row["total_cost_decimal"] == "4.00000"
    assert row["min_model_payout_decimal"] == "5.0"
    assert row["profit_proven"] is False and len(row["evidence_hash"]) == 64


def test_wrong_direction_and_same_threshold_do_not_match():
    a = market("a", "MetaMask FDV above $1B one day after launch?", scan.AUDITED_RULES["metamask"])
    b = market("b", "MetaMask FDV above $500M one day after launch?", scan.AUDITED_RULES["metamask"])
    c = market("c", "MetaMask FDV above $1B one day after launch?", scan.AUDITED_RULES["metamask"])
    pairs, _ = scan.identify_pairs(event(a, b, c))
    assert {(p["low"]["market_id"], p["high"]["market_id"]) for p in pairs} == {("b", "a"), ("b", "c")}


@pytest.mark.parametrize("entity", ["metamask", "hyperbeat"])
def test_only_audited_complete_rules_accepted(entity):
    low = market("a", f"{entity} FDV above $500M one day after launch?", scan.AUDITED_RULES[entity])
    high = market("b", f"{entity} FDV above $1B one day after launch?", scan.AUDITED_RULES[entity])
    assert len(scan.identify_pairs(event(low, high))[0]) == 1
    for bad in ["Both resolve Yes if price falls below title", scan.AUDITED_RULES[entity].replace("greater than", "less than"), scan.AUDITED_RULES[entity] + " Exception: reverse the outcome."]:
        low["description"] = high["description"] = bad
        assert not scan.identify_pairs(event(low, high))[0]


def test_swallowed_discovery_failure_is_partial(monkeypatch, tmp_path):
    import paper_trader.struct_arb as arb
    class Broken:
        def fetch_events(self, **kwargs):
            raise OSError("offline")
    def swallowed(client, **kwargs):
        try:
            client.fetch_events()
        except OSError:
            return []
    monkeypatch.setattr(arb, "_make_client", Broken)
    monkeypatch.setattr(arb, "fetch_open_events", swallowed)
    monkeypatch.setattr(scan, "HISTORY_PATH", tmp_path / "history.jsonl")
    result = scan.scan()
    assert result["status"] == "partial" and "offline" in result["discovery_error"]


def test_net_threshold_skew_and_fee_evidence(monkeypatch, tmp_path):
    monkeypatch.setattr(scan, "STATUS_PATH", tmp_path / "status.json")
    monkeypatch.setattr(scan, "HISTORY_PATH", tmp_path / "history.jsonl")
    low = market("low", "MetaMask FDV above $500M one day after launch?", scan.AUDITED_RULES["metamask"])
    high = market("high", "MetaMask FDV above $1B one day after launch?", scan.AUDITED_RULES["metamask"])
    now = 1700000000000
    price, skew = "0.499", 0
    def get(url):
        is_low = "y-low" in url
        return {"asset_id": "y-low" if is_low else "n-high", "market": "c-low" if is_low else "c-high", "timestamp": str(now - (0 if is_low else skew)), "min_order_size": "1", "asks": [{"price": price, "size": "5"}]}
    result = scan.scan(event(low, high), get=get, now_ms=now)
    assert result["positive_model_net_count"] == 1 and result["candidate_count"] == 0
    price = "0.495"
    assert scan.scan(event(low, high), get=get, now_ms=now)["candidate_count"] == 1
    skew = 5001
    result = scan.scan(event(low, high), get=get, now_ms=now)
    assert result["status"] == "insufficient_data"
    assert result["results"][0]["books"]["high_no"]["timestamp"] == str(now-skew)
    assert result["rejection_reasons"] == {"book timestamp skew": 1}
