import copy
import json

from paper_trader.execution_cost import evaluate_binary, evaluate_buy_leg


NOW = 1_700_000_000_000


def market(**kw):
    value = {
        "conditionId": "condition-1", "active": True, "closed": False,
        "acceptingOrders": True, "outcomes": json.dumps(["Yes", "No"]),
        "clobTokenIds": json.dumps(["yes-token", "no-token"]),
        "feesEnabled": False,
    }
    value.update(kw)
    return value


def book(token, asks, timestamp=NOW, **kw):
    value = {"asset_id": token, "market": "condition-1", "timestamp": str(timestamp),
             "min_order_size": "1", "asks": [{"price": str(p), "size": str(s)} for p, s in asks],
             "bids": []}
    value.update(kw)
    return value


def test_multilevel_false_bestask_and_conservative_fee():
    yes = book("yes-token", [("0.40", 1), ("0.65", 4)])
    no = book("no-token", [("0.50", 5)])
    before = copy.deepcopy((yes, no))
    result = evaluate_binary(yes, no, market(), 5, NOW)
    assert result["ok"] is True
    assert result["yes"]["vwap"] == 0.60
    assert result["yes"]["cost_decimal"] == "3.00000"
    assert result["no"]["cost_decimal"] == "2.50000"
    assert result["payout"] == 5.0
    assert result["total_cost_decimal"] == "5.50000"
    assert result["net_profit_decimal"] == "-0.50000"
    assert result["net_per_share_decimal"] == "-0.10000"
    assert (yes, no) == before
    assert result["fee_model"].startswith("zero")


def test_insufficient_depth_and_quantity_boundary():
    assert evaluate_binary(book("yes-token", [("0.4", 4)]), book("no-token", [("0.4", 5)]), market(), 5, NOW)["ok"] is False
    assert evaluate_binary(book("yes-token", [("0.4", 5)]), book("no-token", [("0.4", 5)]), market(), 0.5, NOW)["ok"] is False


def test_fee_zero_missing_and_current_fee_schedule():
    zero = evaluate_binary(book("yes-token", [("0.5", 5)]), book("no-token", [("0.5", 5)]), market(), 5, NOW)
    assert zero["ok"] and zero["total_cost"] == 5.0
    charged = evaluate_binary(book("yes-token", [("0.5", 100)]), book("no-token", [("0.5", 100)]),
                              market(feesEnabled=True, feeSchedule={"rate": "0.04", "exponent": 1}), 100, NOW)
    assert charged["ok"] and charged["yes"]["fee"] == 1.0
    assert evaluate_binary(book("yes-token", [("0.5", 5)]), book("no-token", [("0.5", 5)]), market(feesEnabled=True), 5, NOW)["ok"] is False


def test_fee_is_ceiling_rounded_per_level():
    result = evaluate_binary(book("yes-token", [("0.5", 1)]), book("no-token", [("0.5", 1)]),
                             market(feesEnabled=True, feeSchedule={"rate": "0.00001", "exponent": 1}), 1, NOW)
    assert result["ok"]
    assert result["yes"]["fill_levels"][0]["fee_decimal"] == "0.00001"


def test_exact_net_boundary_and_just_below():
    at = evaluate_binary(book("yes-token", [("0.49", 1)]), book("no-token", [("0.50", 1)]), market(), 1, NOW)
    below = evaluate_binary(book("yes-token", [("0.49001", 1)]), book("no-token", [("0.50", 1)]), market(), 1, NOW)
    assert at["net_per_share_decimal"] == "0.01000"
    assert below["net_per_share_decimal"] == "0.00999"


def test_huge_decimal_quantity_fails_closed_without_exception():
    result = evaluate_binary(book("yes-token", [("0.5", 1)]), book("no-token", [("0.5", 1)]),
                             market(), "1e1000000", NOW)
    assert result["ok"] is False


def test_rejects_nan_stale_future_skew_and_bad_tokens_or_conditions():
    base = (book("yes-token", [("nan", 5)]), book("no-token", [("0.5", 5)]), market(), 5, NOW)
    assert evaluate_binary(*base)["ok"] is False
    assert evaluate_binary(book("yes-token", [("0.5", 5)], NOW - 30001), book("no-token", [("0.5", 5)]), market(), 5, NOW)["ok"] is False
    assert evaluate_binary(book("yes-token", [("0.5", 5)], NOW + 1001), book("no-token", [("0.5", 5)]), market(), 5, NOW)["ok"] is False
    assert evaluate_binary(book("yes-token", [("0.5", 5)]), book("no-token", [("0.5", 5)], NOW - 6000), market(), 5, NOW)["ok"] is False
    assert evaluate_binary(book("no-token", [("0.5", 5)]), book("yes-token", [("0.5", 5)]), market(), 5, NOW)["ok"] is False
    assert evaluate_binary(book("yes-token", [("0.5", 5)], market="other"), book("no-token", [("0.5", 5)]), market(), 5, NOW)["ok"] is False


def test_rejects_duplicate_mapping_and_invalid_status_or_fee_literal():
    assert evaluate_binary(book("yes-token", [("0.5", 5)]), book("no-token", [("0.5", 5)]),
                           market(clobTokenIds=["same", "same"]), 5, NOW)["ok"] is False
    assert evaluate_binary(book("yes-token", [("0.5", 5)]), book("no-token", [("0.5", 5)]),
                           market(active=False), 5, NOW)["ok"] is False
    assert evaluate_binary(book("yes-token", [("0.5", 5)]), book("no-token", [("0.5", 5)]),
                           market(feesEnabled=True, feeSchedule=False), 5, NOW)["ok"] is False


def test_buy_leg_supports_non_indexed_no_mapping_and_has_no_payout():
    m = market(outcomes=json.dumps(["No", "Yes"]), clobTokenIds=json.dumps(["no-token", "yes-token"]))
    result = evaluate_buy_leg(book("no-token", [("0.40", 2), ("0.50", 3)]), m, "no", 5, NOW)
    assert result["ok"] is True
    assert result["outcome"] == "NO"
    assert result["token"] == "no-token"
    assert result["condition_id"] == "condition-1"
    assert result["quantity_decimal"] == "5"
    assert result["gross_decimal"] == "2.30"
    assert result["fee_decimal"] == "0.00000"
    assert result["cost_decimal"] == "2.30000"
    assert "payout" not in result


def test_buy_leg_rejects_wrong_token_and_condition():
    assert not evaluate_buy_leg(book("yes-token", [("0.5", 5)]), market(), "NO", 5, NOW)["ok"]
    assert not evaluate_buy_leg(book("no-token", [("0.5", 5)], market="other"), market(), "NO", 5, NOW)["ok"]


def test_buy_leg_rejects_unknown_fees_and_insufficient_depth():
    assert not evaluate_buy_leg(book("no-token", [("0.5", 5)]), market(feesEnabled=True), "NO", 5, NOW)["ok"]
    assert not evaluate_buy_leg(book("no-token", [("0.5", 4)]), market(), "NO", 5, NOW)["ok"]


def test_buy_leg_does_not_mutate_inputs():
    m = market()
    b = book("no-token", [("0.5", 2), ("0.4", 3)])
    before = copy.deepcopy((b, m))
    result = evaluate_buy_leg(b, m, "NO", 5, NOW)
    assert result["ok"]
    assert (b, m) == before
