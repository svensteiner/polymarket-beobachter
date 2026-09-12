import json

import analytics.execution_scan as scan
import paper_trader.struct_arb as struct_arb


def market(mid="m1", yes="y1", no="n1"):
    return {
        "conditionId": mid, "active": True, "closed": False,
        "acceptingOrders": True, "outcomes": json.dumps(["Yes", "No"]),
        "clobTokenIds": json.dumps([yes, no]), "feesEnabled": False,
    }


def item(mid="m1"):
    return {"market_id": mid, "title": "Test", "yes_token": "y1", "no_token": "n1",
            "market": market(mid)}


def book(token, price="0.49"):
    return {"asset_id": token, "market": "m1", "timestamp": "1700000000000",
            "min_order_size": "1",
            "asks": [{"price": price, "size": "5"}], "bids": []}


def setup(monkeypatch, tmp_path, items):
    monkeypatch.setattr(scan, "STATUS_PATH", tmp_path / "status.json")
    monkeypatch.setattr(scan, "HISTORY_PATH", tmp_path / "history.jsonl")
    monkeypatch.setattr(struct_arb, "_iter_binary_markets", lambda events: items)


def test_scan_fetches_two_books_and_evaluates(monkeypatch, tmp_path):
    setup(monkeypatch, tmp_path, [item()])
    calls = []

    def get(url):
        calls.append(url)
        return book("y1" if "y1" in url else "n1")

    result = scan.scan(events=[{"markets": []}], get=get, now_ms=1700000000000)
    assert result["discovered"] == result["eligible"] == result["evaluated"] == 1
    assert len(calls) == 2
    assert result["results"][0]["evaluation"]["ok"] is True
    assert result["hypothetical_snapshot"] is True and result["orders_created"] is False


def test_scan_counts_request_failure_and_advances_budget(monkeypatch, tmp_path):
    items = [item("m2"), item("m1"), item("m3")]
    setup(monkeypatch, tmp_path, items)
    scan.STATUS_PATH.write_text(json.dumps({"execution_scan": {"next_cursor": 1}}))

    def get(url):
        if "y1" in url:
            raise OSError("offline")
        return book("n1")

    result = scan.scan(events=[], get=get, now_ms=1700000000000)
    assert result["selected"] == 3
    assert result["request_errors"] >= 1
    assert result["unexamined_budget"] == 0
    assert result["next_cursor"] == 1
    assert len((tmp_path / "history.jsonl").read_text().splitlines()) == 1


def test_scan_excludes_ineligible_and_never_negative_budget(monkeypatch, tmp_path):
    bad = item("bad")
    bad["market"]["closed"] = True
    setup(monkeypatch, tmp_path, [bad, {"market_id": "missing"}])
    result = scan.scan(events=[], get=lambda _: book("x"), now_ms=1700000000000)
    assert result["eligible"] == 0
    assert result["selected"] == 0
    assert result["unexamined_budget"] == 0
    assert result["rejected_pre"] == 2


def test_evaluation_timestamp_is_captured_per_pair(monkeypatch, tmp_path):
    items = [item("m1"), item("m2")]
    setup(monkeypatch, tmp_path, items)
    clock = iter([1000.0, 1000.0, 1001.0])
    monkeypatch.setattr(scan.time, "time", lambda: next(clock))
    seen = []

    def evaluate(*args, **kwargs):
        seen.append(args[4])
        return {"ok": True, "reason": "ok", "net_per_share_decimal": "0"}

    monkeypatch.setattr("paper_trader.execution_cost.evaluate_binary", evaluate)
    result = scan.scan(events=[], get=lambda url: book("y1" if "y1" in url else "n1"))
    assert result["evaluated"] == 2
    assert [row["evaluation_now_ms"] for row in result["results"]] == [1000000, 1001000]
    assert seen == [1000000, 1001000]
