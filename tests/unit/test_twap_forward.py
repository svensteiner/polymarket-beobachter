import json
from decimal import Decimal

from analytics.twap_forward import evaluate_forward_window

START = 1_800_000_000
DECISION = (START + 210) * 1000


def market(**kw):
    value = {"conditionId": "c1", "tokens": {"Up": "up", "Down": "down"},
             "feesEnabled": True, "feeSchedule": {"rate": "0.04", "exponent": 1},
             "active": True, "closed": False, "acceptingOrders": True,
             "resolutionSource": "https://data.chain.link/streams/btc-usd-twap-60s-streams"}
    value.update(kw)
    return value


def book(token, price="0.50", size="5", timestamp=DECISION):
    return {"asset_id": token, "market": "c1", "timestamp": str(timestamp),
            "min_order_size": "1", "asks": [{"price": price, "size": size}], "bids": []}


def inputs(**kw):
    value = {"window_start": START * 1000, "window_end": (START + 300) * 1000,
             "decision_ts": DECISION, "registered_at": START * 1000 - 1,
             "anchor": {"value_decimal": "100", "fetched_at_ms": DECISION - 1000},
             "updates": [{"value_e18": "101000000000000000000", "received_at_ms": DECISION - 1000,
                          "observed_at_ms": DECISION - 1000, "live": True}],
             "up_book": {**book("up"), "request_at_ms": DECISION + 250, "received_at_ms": DECISION + 300},
             "down_book": {**book("down"), "request_at_ms": DECISION + 250, "received_at_ms": DECISION + 301}, "market": market()}
    value.update(kw)
    for label in ("up_book", "down_book"):
        value[label] = {**value[label], "request_at_ms": value[label].get("request_at_ms", DECISION + 250),
                        "received_at_ms": value[label].get("received_at_ms", DECISION + 300)}
    return value


def test_lookahead_update_is_ignored_and_missing_anchor_skips():
    result = evaluate_forward_window(**inputs(updates=[{"value_e18": "101000000000000000000", "received_at_ms": DECISION + 1,
                                                        "observed_at_ms": DECISION, "live": True}]))
    assert result["skip_reason"] == "missing_or_stale_reference"
    assert evaluate_forward_window(**inputs(anchor=None))["skip_reason"] == "missing_anchor"


def test_insufficient_depth_and_identity_mismatch_skip():
    assert evaluate_forward_window(**inputs(up_book=book("up", size="4")))["skip_reason"] == "insufficient ask depth"
    assert evaluate_forward_window(**inputs(up_book=book("wrong")))["skip_reason"] == "identity_mismatch"


def test_net_fee_is_ceiling_rounded_and_up_down_labels_preserved():
    result = evaluate_forward_window(**inputs(up_book=book("up", "0.49"), down_book=book("down", "0.50")))
    assert result["ok"]
    assert result["direction"] == "Up"
    assert result["up"]["outcome"] == "Up"
    assert result["down"]["outcome"] == "Down"
    assert Decimal(result["chosen_leg_cost_decimal"]) > Decimal("2.45")
    assert result["settlement_checked"] is False


def test_tie_stale_and_registration_deadline():
    assert evaluate_forward_window(**inputs(updates=[{"value_e18": "100000000000000000000", "received_at_ms": DECISION - 1,
                                                        "observed_at_ms": DECISION - 1, "live": True}]))["skip_reason"] == "reference_tie"
    assert evaluate_forward_window(**inputs(updates=[{"value_e18": "101000000000000000000", "received_at_ms": DECISION - 5001,
                                                        "observed_at_ms": DECISION - 5001, "live": True}]))["skip_reason"] == "missing_or_stale_reference"
    assert evaluate_forward_window(**inputs(registered_at=START * 1000))["skip_reason"] == "registration_after_window_start"


def test_anchor_fetched_after_decision_is_lookahead():
    anchor = {"value_decimal": "100", "fetched_at_ms": DECISION + 1}
    assert evaluate_forward_window(**inputs(anchor=anchor))["skip_reason"] == "anchor_fetched_after_decision"


def test_books_require_ordered_request_and_receipt_after_250ms():
    bad_request = {**book("up"), "request_at_ms": DECISION + 249, "received_at_ms": DECISION + 300}
    assert evaluate_forward_window(**inputs(up_book=bad_request))["skip_reason"] == "book_before_250ms"
    bad_order = {**book("up"), "request_at_ms": DECISION + 400, "received_at_ms": DECISION + 300}
    assert evaluate_forward_window(**inputs(up_book=bad_order))["skip_reason"] == "book_receipt_before_request"


def test_observation_must_precede_receipt_and_non_live_updates_are_excluded():
    update = {"value_e18": "101000000000000000000", "observed_at_ms": DECISION + 1,
              "received_at_ms": DECISION + 2, "live": True}
    assert evaluate_forward_window(**inputs(updates=[update]))["skip_reason"] == "missing_or_stale_reference"
    non_live = {"value_e18": "101000000000000000000", "observed_at_ms": DECISION - 1000,
                "received_at_ms": DECISION - 500, "live": False}
    assert evaluate_forward_window(**inputs(updates=[non_live]))["skip_reason"] == "missing_or_stale_reference"


def test_book_source_timestamp_skew_and_exact_resolution_source():
    down = {**book("down", timestamp=DECISION - 6000), "request_at_ms": DECISION + 250,
            "received_at_ms": DECISION + 300}
    assert evaluate_forward_window(**inputs(down_book=down))["skip_reason"] == "book_timestamp_skew"
    assert evaluate_forward_window(**inputs(market=market(resolutionSource="https://example.invalid/btc-twap-60s")))["skip_reason"] == "resolution_source_invalid"


def test_minimum_size_and_fee_schedule_are_fail_closed():
    too_large = {**book("up"), "min_order_size": "6", "request_at_ms": DECISION + 250,
                 "received_at_ms": DECISION + 300}
    assert evaluate_forward_window(**inputs(up_book=too_large))["skip_reason"] == "below_minimum_order_size"
    bad_fee = market(feeSchedule={"rate": "0.04", "exponent": 2})
    assert evaluate_forward_window(**inputs(market=bad_fee))["ok"] is False


def test_old_anchor_is_valid_when_fetched_before_decision():
    old = {"value_decimal": "100", "fetched_at_ms": DECISION - 120000}
    result = evaluate_forward_window(**inputs(anchor=old))
    assert result["ok"] is True


def test_missing_book_request_or_receipt_is_rejected():
    missing_request = inputs()
    missing_request["up_book"].pop("request_at_ms")
    assert evaluate_forward_window(**missing_request)["ok"] is False
    missing_receipt = inputs()
    missing_receipt["down_book"].pop("received_at_ms")
    assert evaluate_forward_window(**missing_receipt)["ok"] is False
