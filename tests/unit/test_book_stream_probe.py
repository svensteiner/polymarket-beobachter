import json

import pytest

from analytics.book_stream_probe import URL, capture


class Clock:
    def __init__(self):
        self.t = 0.0

    def mono(self):
        self.t += 0.1
        return self.t

    def wall(self):
        return 1000.0 + self.t


class Socket:
    def __init__(self, frames, clock=None):
        self.frames = list(frames)
        self.sent = []
        self.closed = False
        self.clock = clock

    def send(self, value):
        self.sent.append(value)

    def recv(self):
        if self.clock:
            self.clock.t += 0.1 if self.frames else 1.0
        if not self.frames:
            raise TimeoutError("idle")
        return self.frames.pop(0)

    def settimeout(self, value):
        self.timeout = value

    def close(self):
        self.closed = True


def book(asset, timestamp="123", asks=None, bids=None):
    return {"event_type": "book", "asset_id": asset, "market": "mkt", "timestamp": timestamp,
            "asks": asks if asks is not None else [], "bids": bids if bids is not None else []}


def test_capture_records_raw_snapshot_delta_and_pong(tmp_path):
    clock = Clock()
    sock = Socket([json.dumps(book("11")), '{"event_type":"price_change","asset_id":"11"}', "PONG"], clock)
    result = capture(["11"], tmp_path / "capture.jsonl", duration_seconds=2,
                     connector=lambda url, timeout: sock, monotonic_clock=clock.mono, wall_clock=clock.wall)
    rows = [json.loads(line) for line in (tmp_path / "capture.jsonl").read_text().splitlines()]
    assert [row["raw_frame"] for row in rows] == [json.dumps(book("11")), '{"event_type":"price_change","asset_id":"11"}', "PONG"]
    assert result["complete"] is True
    assert result["initial_timestamps"] == {"11": "123"}
    assert sock.closed
    assert json.loads((tmp_path / "capture.jsonl.summary.json").read_text())["source_url"] == URL


def test_missing_token_is_incomplete(tmp_path):
    clock = Clock()
    sock = Socket([json.dumps(book("11"))], clock)
    result = capture(["11", "22"], tmp_path / "capture.jsonl", duration_seconds=1,
                     connector=lambda *args, **kwargs: sock, monotonic_clock=clock.mono, wall_clock=clock.wall)
    assert result["complete"] is False
    assert result["seen_snapshot_tokens"] == ["11"]


def test_malformed_frame_keeps_evidence_and_marks_error(tmp_path):
    clock = Clock()
    sock = Socket(["not-json", json.dumps(book("11"))], clock)
    result = capture(["11"], tmp_path / "capture.jsonl", duration_seconds=1,
                     connector=lambda *args, **kwargs: sock, monotonic_clock=clock.mono, wall_clock=clock.wall)
    assert result["termination_reason"] == "errors"
    assert result["complete"] is False
    assert len((tmp_path / "capture.jsonl").read_text().splitlines()) == 2


def test_budget_stops_before_oversized_record(tmp_path):
    clock = Clock()
    sock = Socket([json.dumps(book("11"))], clock)
    result = capture(["11"], tmp_path / "capture.jsonl", duration_seconds=1, max_bytes=1,
                     connector=lambda *args, **kwargs: sock, monotonic_clock=clock.mono, wall_clock=clock.wall)
    assert result["termination_reason"] == "budget"
    assert result["message_count"] == 0
    assert (tmp_path / "capture.jsonl").read_text() == ""


def test_validation_rejects_duplicates_and_non_decimal(tmp_path):
    with pytest.raises(ValueError):
        capture(["1", "1"], tmp_path / "x")
    with pytest.raises(ValueError):
        capture(["١"], tmp_path / "x")


def test_idle_timeouts_do_not_end_capture_and_ping_is_sent(tmp_path):
    class ManualClock:
        t = 0.0
        def mono(self): return self.t
        def wall(self): return 1000 + self.t
    clock = ManualClock()
    class IdleSocket(Socket):
        def recv(self):
            clock.t += min(self.timeout, max(0, 12-clock.t))
            if clock.t == 2:
                return json.dumps([book("11")])
            if clock.t == 8:
                return '{"event_type":"price_change","price_changes":[]}'
            if clock.t == 10:
                return 'PONG'
            raise TimeoutError('idle')
    sock = IdleSocket([])
    result = capture(["11"], tmp_path / 'x.jsonl', duration_seconds=12,
                     connector=lambda *a, **k:sock, monotonic_clock=clock.mono, wall_clock=clock.wall)
    assert result['complete'] and clock.t == 12
    assert result['message_count'] == 3 and 'PING' in sock.sent and sock.closed


def test_disconnect_at_deadline_does_not_become_success(tmp_path):
    clock = Clock()
    class Failing(Socket):
        def recv(self):
            clock.t = 2
            raise RuntimeError('connection lost')
    result = capture(["11"], tmp_path / 'x.jsonl', duration_seconds=1,
                     connector=lambda *a, **k:Failing([]), monotonic_clock=clock.mono, wall_clock=clock.wall)
    assert not result['complete'] and result['termination_reason'] != 'timeout'


def test_budget_rejected_snapshot_is_not_counted(tmp_path):
    clock = Clock()
    result = capture(["11"], tmp_path / 'x.jsonl', duration_seconds=1, max_bytes=0,
                     connector=lambda *a, **k:Socket([json.dumps(book('11'))], clock),
                     monotonic_clock=clock.mono, wall_clock=clock.wall)
    assert result['seen_snapshot_tokens'] == [] and result['initial_timestamps'] == {}


def test_late_frame_is_not_recorded(tmp_path):
    clock = Clock()
    class Late(Socket):
        def recv(self):
            clock.t = 2
            return json.dumps(book('11'))
    result = capture(['11'], tmp_path/'x.jsonl', duration_seconds=1,
                     connector=lambda *a, **k:Late([]), monotonic_clock=clock.mono, wall_clock=clock.wall)
    assert result['message_count'] == 0 and not result['complete']
