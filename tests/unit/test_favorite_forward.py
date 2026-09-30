from decimal import Decimal

import pytest

from datetime import datetime, timezone, timedelta

from analytics.favorite_forward import (_midpoint, evaluate_books, capture_due_markets,
                                        fetch_books_batch, refresh_market, _BudgetHTTP)


def market():
    return {"conditionId": "c", "outcomes": ["Home", "Away"], "tokens": {"Home": "h", "Away": "a"},
            "market": {"feesEnabled": True, "feeSchedule": {"rate": "0.05", "exponent": 1}}}


def book(token="h", bid="0.79", ask="0.81", ts=1000):
    return {"asset_id": token, "market": "c", "timestamp": str(ts), "min_order_size": "1",
            "bids": [{"price": bid, "size": "5"}], "asks": [{"price": ask, "size": "5"}]}


def test_midpoint_and_favorite_cost_are_paper_only():
    result = evaluate_books(market=market(), books={"Home": book(), "Away": book("a", ".18", ".20")}, evaluated_at_ms=1000)
    assert result["ok"] and result["favorite"] == "Home"
    assert Decimal(result["cost_decimal"]) > Decimal("4")
    assert result["orders_created"] is False


def test_tie_and_bad_identity_fail_closed():
    assert evaluate_books(market=market(), books={"Home": book(), "Away": book("a", ".79", ".81")}, evaluated_at_ms=1000)["reason"] == "favorite_band_or_tie"
    with pytest.raises(ValueError, match="identity"):
        evaluate_books(market=market(), books={"Home": book("wrong"), "Away": book("a", ".18", ".20")}, evaluated_at_ms=1000)


def test_midpoint_rejects_crossed_or_missing_books():
    with pytest.raises(ValueError):
        _midpoint({"bids": [], "asks": []})
    with pytest.raises(ValueError):
        _midpoint({"bids": [{"price": ".9"}], "asks": [{"price": ".8"}]})
    with pytest.raises(ValueError, match="sizes"):
        _midpoint({"bids": [{"price": ".7", "size": "0"}], "asks": [{"price": ".8", "size": "5"}]})


def test_due_capture_records_late_window_without_network_and_checkpoints():
    market_data = {"conditionId": "late", "game_start": datetime.fromtimestamp(3600, timezone.utc), "market": {"id": "1"}}
    checkpoints = []
    result = capture_due_markets([market_data], registration_ms=0, clock=lambda: 100_000,
                                 sleeper=lambda _: None, checkpoint=checkpoints.append)
    assert result[0]["status"] == "missed"
    assert checkpoints and checkpoints[0]["conditionId"] == "late"


def test_due_capture_success_records_ask_cost_and_net_without_network():
    from analytics.favorite_forward import _parse_market

    raw = _raw_market("1970-01-01T02:00:00Z")
    parsed = _parse_market(raw, "event-1")
    assert parsed is not None
    due_ms = 3_600_000
    calls = []
    def fake_http(method, url, **kwargs):
        calls.append((method, url))
        if method == "GET":
            return raw, 200, due_ms
        return [book("h", ".79", ".81", due_ms), book("a", ".18", ".20", due_ms)], 200, due_ms

    result = capture_due_markets([parsed], registration_ms=0, clock=lambda: due_ms,
                                 http_get=fake_http)
    assert len(calls) == 2 and [x["status"] for x in result] == ["captured"]
    evaluation = result[0]["evaluation"]
    assert evaluation["ok"] and evaluation["favorite"] == "Home"
    assert evaluation["orders_created"] is False
    assert Decimal(evaluation["hypothetical_net_if_win_decimal"]) == Decimal("0.81152")


def test_due_capture_marks_late_after_http_as_skipped():
    from analytics.favorite_forward import _parse_market

    raw = _raw_market("1970-01-01T02:00:00Z")
    parsed = _parse_market(raw, "event-1")
    assert parsed is not None
    due_ms = 3_600_000
    clock_values = iter((due_ms, due_ms, due_ms + 30_001))
    def fake_clock():
        return next(clock_values)
    def fake_http(method, url, **kwargs):
        if method == "GET":
            return raw, 200, due_ms
        return [book("h", ".79", ".81", due_ms), book("a", ".18", ".20", due_ms)], 200, due_ms

    result = capture_due_markets([parsed], registration_ms=0, clock=fake_clock,
                                 http_get=fake_http)
    assert result[0]["status"] == "skipped"
    assert result[0]["skip_reason"] == "capture_late"


def _raw_market(start="2026-10-01T12:00:00Z"):
    return {"id": "1", "conditionId": "c", "gameStartTime": start, "createdAt": "2026-09-01T00:00:00Z",
            "sportsMarketType": "moneyline", "active": True, "closed": False, "acceptingOrders": True,
            "feesEnabled": True, "feeSchedule": {"rate": "0.05", "exponent": 1},
            "outcomes": '["Home", "Away"]', "clobTokenIds": '["h", "a"]'}


def test_books_reject_duplicate_asset_ids():
    market_data = {"tokens": {"Home": "h", "Away": "a"}}
    def fake(*args, **kwargs):
        return ([book("h"), book("h")], 200, 1000)
    with pytest.raises(ValueError, match="duplicate_book_identity"):
        fetch_books_batch(market_data, http_get=fake)


def test_refresh_rejects_start_time_change():
    original = _raw_market()
    parsed = {
        "market": original, "conditionId": "c", "tokens": {"Home": "h", "Away": "a"},
        "outcomes": ["Home", "Away"], "event_id": "e",
        "game_start": datetime.fromisoformat("2026-10-01T12:00:00+00:00"),
        "created": datetime.fromisoformat("2026-09-01T00:00:00+00:00"),
    }
    def fake(*args, **kwargs):
        return (_raw_market("2026-10-01T12:01:00Z"), 200, 1000)
    with pytest.raises(ValueError, match="market_identity_changed"):
        refresh_market(parsed, http_get=fake)


def test_budget_http_stops_at_request_cap(monkeypatch):
    import analytics.favorite_forward as ff
    monkeypatch.setattr(ff, "MAX_REQUESTS", 1)
    fake = lambda *args, **kwargs: ({"ok": True}, 200, 1000)
    budget = _BudgetHTTP(fake, started=10.0)
    budget("GET", "https://example.invalid")
    with pytest.raises(ValueError, match="request_budget"):
        budget("GET", "https://example.invalid")
