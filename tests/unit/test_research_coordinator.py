import json
from pathlib import Path

import pytest

from analytics.research_coordinator import CoordinatorError, compact_status, dispatch, request_plan


def good_status():
    return {"status": "ok", "scan": {"events": 2, "partitions": 1, "binary_markets": 3},
            "execution_scan": {"candidate_count": 0, "valid_evaluations": 1}, "secret": "omit"}


def test_plan_is_sdk_compatible_and_forwards_only_compact(tmp_path: Path):
    p = tmp_path / "status.json"
    p.write_text(json.dumps(good_status()), encoding="utf-8")
    plan = request_plan("cheap-model", p)
    assert plan["agent"]["tools"] == []
    assert plan["session"]["environment"] == {"type": "none"}
    assert "secret" not in plan["session"]["input"]
    assert json.loads(plan["session"]["input"])["events"] == 2


@pytest.mark.parametrize("bad_value", [True, 1.5, -1, 1_000_000_001, float("nan"), float("inf")])
def test_bad_counter_types_fail_closed(bad_value):
    bad = good_status(); bad["scan"]["events"] = bad_value
    with pytest.raises(CoordinatorError): compact_status(bad)


def test_missing_model_and_fields_fail_closed(tmp_path: Path):
    p = tmp_path / "status.json"
    p.write_text(json.dumps(good_status()), encoding="utf-8")
    with pytest.raises(CoordinatorError): request_plan("", p)
    bad = good_status(); del bad["execution_scan"]["candidate_count"]
    with pytest.raises(CoordinatorError): compact_status(bad)
    bad = good_status(); del bad["scan"]
    with pytest.raises(CoordinatorError): compact_status(bad)


def test_oversized_status_fails_closed(tmp_path: Path):
    p = tmp_path / "status.json"
    p.write_bytes(b"{" + b"x" * (2 * 1024 * 1024) + b"}")
    with pytest.raises(CoordinatorError): request_plan("m", p)


def test_live_gates_reject_before_factory(tmp_path: Path):
    called = False
    def factory(*args):
        nonlocal called
        called = True
    with pytest.raises(CoordinatorError): dispatch(factory, "m", live_enabled=True, admission_budget=1)
    assert not called
    with pytest.raises(CoordinatorError): dispatch(factory, "m", live_enabled=True,
        acknowledge_no_hard_session_cost_cap=True, admission_budget=True)
    with pytest.raises(CoordinatorError): dispatch(factory, "m", live_enabled=True,
        acknowledge_no_hard_session_cost_cap=1, admission_budget=1)


def test_dispatch_is_single_call_and_no_retry(tmp_path: Path):
    p = tmp_path / "status.json"; p.write_text(json.dumps(good_status()), encoding="utf-8")
    calls = []
    class Sessions:
        def create(self, **kwargs):
            calls.append(("session", kwargs)); raise RuntimeError("session failure")
    class Agents:
        sessions = Sessions()
        def create(self, **kwargs):
            calls.append(("agent", kwargs)); return type("Agent", (), {"id": "agent-1"})()
    class Client:
        beta = type("Beta", (), {"agents": Agents()})()
    def factory(**kwargs):
        calls.append(("factory", kwargs)); assert kwargs == {"max_retries": 0}; return Client()
    with pytest.raises(RuntimeError): dispatch(factory, "m", live_enabled=True,
        acknowledge_no_hard_session_cost_cap=True, admission_budget=1, status_path=p)
    assert [x[0] for x in calls] == ["factory", "agent", "session"]
    assert calls[-1][1]["agent_id"] == "agent-1"
