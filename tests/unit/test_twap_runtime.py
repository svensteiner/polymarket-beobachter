import json
import socket
from types import SimpleNamespace

import pytest

from analytics import twap_forward as mod


START = 1800000000
DECISION = (START + 210) * 1000


def live(timestamp):
    return {"type": "update", "topic": "crypto_prices_twap_sixty", "timestamp": timestamp,
            "payload": {"symbol": "btc/usd", "window_s": 60, "timestamp": timestamp,
                        "full_accuracy_value": "101000000000000000000"}}


class Clock:
    def __init__(self, value):
        self.value = value

    def now(self):
        return self.value

    def sleep(self, seconds):
        self.value += round(seconds * 1000)


@pytest.mark.parametrize("public", [False, True])
def test_runtime_fetches_after_decision_and_preserves_failed_other_leg(public):
    for fail in [False, True]:
        clock = Clock(START * 1000)
        seen = []

        def metadata(slug):
            assert clock.value == DECISION - 20000
            return {"tokens": {"Up": "1", "Down": "2"}, "conditionId": "c",
                    "active": True, "closed": False, "acceptingOrders": True,
                    "resolutionSource": mod.SOURCE, "feesEnabled": True,
                    "feeSchedule": {"rate": ".07", "exponent": 1},
                    "event": {"eventMetadata": {"priceToBeat": None if public else "100"}}}, clock.value, clock.value

        def public_anchor(start):
            assert public and start == START
            return {"request_at_ms": clock.value, "received_at_ms": clock.value,
                    "html": "retained_html", "anchor": {"ok": True, "value_decimal": "100",
                    "fetched_at_ms": clock.value, "source": "polymarket_public_page"}}

        def capture(cutoff):
            assert clock.value < cutoff == DECISION
            clock.value = cutoff
            return {"error": None, "frames": [{"raw": "evidence"}], "updates": [
                {"live": True, "value_e18": "101000000000000000000",
                 "observed_at_ms": cutoff-1000, "received_at_ms": cutoff-500}]}

        def book(token):
            seen.append(clock.value)
            if fail and token == "2":
                raise ValueError("synthetic_failure")
            return {"asset_id": token, "market": "c", "timestamp": str(clock.value),
                    "min_order_size": "5", "asks": [{"price": ".5", "size": "5"}]}, clock.value, clock.value+50

        result = mod._record_window(START, START*1000-1, now=clock.now, sleep=clock.sleep,
                                    market_fetch=metadata, capture=capture, book_fetch=book,
                                    anchor_fetch=public_anchor)
        assert seen == [DECISION+250, DECISION+250]
        assert result["requests"]["Up"]["received_at_ms"] < (START+300)*1000
        assert result["capture"]["frames"]
        if public:
            assert result["requests"]["public_anchor"]["html"] == "retained_html"
            assert result["selected_anchor"]["source"] == "polymarket_public_page"
        assert result["result"]["ok"] is not fail
        if fail:
            assert "payload" in result["requests"]["Up"]
            assert result["requests"]["Down"]["error"] == "synthetic_failure"
        else:
            assert result["result"]["chosen_leg_cost_decimal"] == "2.58750"
            assert result["result"]["breakeven_decimal"] == "0.51750"


@pytest.mark.parametrize("bad", [None, "close", "malformed", "wrong_topic"])
def test_connector_preserves_backfill_and_rejects_bad_frames(bad):
    clock = Clock(1000)
    backfill = {"type": "subscribe", "payload": {"data": [{"value": 999}]}}
    frames = [(1, ""), (1, json.dumps(backfill)), (1, json.dumps(live(3500)))]
    if bad == "close":
        frames.append((8, ""))
    elif bad == "malformed":
        frames.append((1, "{"))
    elif bad == "wrong_topic":
        frames.append((1, json.dumps({**live(4500), "topic": "wrong"})))

    class Sock:
        closed = False
        sent = []

        def send(self, value):
            self.sent.append(value)

        def settimeout(self, seconds):
            pass

        def recv_data(self, control_frame):
            clock.value += 1000
            if frames:
                return frames.pop(0)
            raise socket.timeout()

        def close(self):
            self.closed = True

    sock = Sock()
    result = mod._rtds(9000, now=clock.now, connector=lambda *a, **k: sock)
    assert sock.closed
    assert len(result["updates"]) == 1
    assert len(result["frames"]) >= 3
    assert json.loads(result["frames"][1]["raw"])["type"] == "subscribe"
    assert (result["error"] is None) == (bad is None)
    assert result["subscription"]["subscriptions"][0]["filters"] == '{"symbol":"btc/usd"}'
    if bad is None:
        assert "PING" in sock.sent


def test_metadata_failure_preserves_raw_payload():
    clock = Clock(DECISION-20000)

    def fetch(slug):
        error = ValueError("bad_rule")
        error.metadata_evidence = {"payload": [{"description": "bad"}],
                                   "request_at_ms": clock.value, "received_at_ms": clock.value+10}
        raise error

    result = mod._record_window(START, START*1000-1, now=clock.now, sleep=clock.sleep, market_fetch=fetch)
    assert result["requests"]["metadata"]["payload"] == [{"description": "bad"}]
    assert not result["result"]["ok"]


def test_cli_rejects_far_future_and_existing_output(tmp_path, monkeypatch):
    monkeypatch.setattr(mod.time, "time", lambda: START-1)
    args = SimpleNamespace(start_epoch=START+900, windows=1, output=str(tmp_path/"new"))
    with pytest.raises(SystemExit):
        mod._run(args)
    assert not (tmp_path/"new").exists()
    args.start_epoch = START
    args.output = str(tmp_path)
    with pytest.raises(SystemExit):
        mod._run(args)
