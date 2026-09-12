import json

from analytics.twap_anchor import extract_anchor

START = 1_800_000_000
RECEIPT = (START + 100) * 1000


def page(*rows):
    lines = "\n".join(f"{i}:" + json.dumps(row, separators=(",", ":")) for i, row in enumerate(rows))
    return '<script>self.__next_f.push([1,' + json.dumps(lines) + '])</script>'


def row(**kw):
    query = ["crypto-prices", "price", "BTC", "2027-01-15T08:00:00Z", "fiveminute", "2027-01-15T08:05:00Z", True, 60]
    query[3] = __import__("datetime").datetime.fromtimestamp(START, __import__("datetime").timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    query[5] = __import__("datetime").datetime.fromtimestamp(START + 300, __import__("datetime").timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    data = {"openPrice": "100.25", "closePrice": None, "dataUpdatedAt": START * 1000 + 1000}
    data.update(kw.pop("data", {}))
    return {"queryKey": query, "state": {"status": "success", "data": data, **kw}}


def test_extracts_single_decimal_anchor_and_ignores_other_rows():
    result = extract_anchor(page({"unrelated": "x"}, row()), start_epoch=START, received_at_ms=RECEIPT)
    assert result["ok"] and result["value_decimal"] == "100.25"
    assert result["source"] == "polymarket_public_page"


def test_duplicate_or_wrong_query_is_rejected():
    assert extract_anchor(page(row(), row()), start_epoch=START, received_at_ms=RECEIPT)["ok"] is False
    assert extract_anchor(page(row()), start_epoch=START + 300, received_at_ms=RECEIPT)["ok"] is False


def test_flags_types_and_status_are_exact():
    bad = row()
    bad["queryKey"][6] = 1
    assert extract_anchor(page(bad), start_epoch=START, received_at_ms=RECEIPT)["ok"] is False
    assert extract_anchor(page(row(status="error")), start_epoch=START, received_at_ms=RECEIPT)["ok"] is False


def test_missing_late_and_nonfinite_anchor_fail_closed():
    assert not extract_anchor(page(row(data={"openPrice": None})), start_epoch=START, received_at_ms=RECEIPT)["ok"]
    assert not extract_anchor(page(row(data={"openPrice": "NaN"})), start_epoch=START, received_at_ms=RECEIPT)["ok"]
    assert not extract_anchor(page(row(data={"dataUpdatedAt": RECEIPT + 1})), start_epoch=START, received_at_ms=RECEIPT)["ok"]


def test_escaped_quotes_and_malicious_script_are_data_only():
    result = extract_anchor(page(row(data={"openPrice": "100.25", "note": "\\\"; eval('bad')"})), start_epoch=START, received_at_ms=RECEIPT)
    assert result["ok"]
    assert "eval" not in result["value_decimal"]


def test_size_and_node_limits():
    assert extract_anchor("x" * (3 * 1024 * 1024 + 1), start_epoch=START, received_at_ms=RECEIPT)["ok"] is False


def test_receipt_deadline_and_data_update_window_are_forward_bounded():
    assert extract_anchor(page(row()), start_epoch=START, received_at_ms=(START + 211) * 1000)["ok"] is False
    assert extract_anchor(page(row(data={"dataUpdatedAt": START * 1000 - 1})), start_epoch=START, received_at_ms=RECEIPT)["ok"] is False


def test_flight_chunks_are_joined_before_line_parsing():
    full = json.dumps(row(), separators=(",", ":"))
    first, second = full[: len(full) // 2], full[len(full) // 2:]
    html = '<script>self.__next_f.push([1,' + json.dumps("0:" + first) + '])</script>'
    html += '<script>self.__next_f.push([1,' + json.dumps(second) + '])</script>'
    assert extract_anchor(html, start_epoch=START, received_at_ms=RECEIPT)["ok"] is True


def test_query_shaped_plain_text_is_not_an_anchor():
    payload = json.dumps(row(), separators=(",", ":"))
    framed = "66:T" + format(len(payload.encode("utf-8")), "x") + "," + payload + "\n67:" + json.dumps({"other": True})
    html = '<script>self.__next_f.push([1,' + json.dumps(framed) + '])</script>'
    assert extract_anchor(html, start_epoch=START, received_at_ms=RECEIPT)["ok"] is False


def test_multiline_utf8_text_and_adjacent_structured_record():
    text = 'Grüße\n"quoted": text'
    framed = ':HL["preload"]\n66:T' + format(len(text.encode("utf-8")), "x") + ',' + text
    framed += '67:' + json.dumps(row())
    html = '<script>self.__next_f.push([1,' + json.dumps(framed) + '])</script>'
    result = extract_anchor(html, start_epoch=START, received_at_ms=RECEIPT)
    assert result["ok"] and result["value_decimal"] == "100.25"
