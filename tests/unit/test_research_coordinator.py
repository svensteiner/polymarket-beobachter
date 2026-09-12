import json
from pathlib import Path

import pytest

from analytics.agent_run_store import RunStore
from analytics.research_coordinator import (CoordinatorError, compact_status, dispatch, dispatch_once,
                                             prepare, reconcile, request_plan)


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
    with pytest.raises(CoordinatorError): dispatch(factory, "gpt-5.6-luna", live_enabled=True,
        acknowledge_no_hard_session_cost_cap=True, admission_budget=1, status_path=p,
        store_path=tmp_path / "runs.json")
    assert [x[0] for x in calls] == ["factory", "agent", "session"]
    assert calls[-1][1]["agent_id"] == "agent-1"


def test_prepare_allowlist_and_dispatch_intent(tmp_path: Path):
    p = tmp_path / "status.json"; p.write_text(json.dumps(good_status()), encoding="utf-8")
    plan = prepare("gpt-5.6-luna", p, live_enabled=True,
                   acknowledge_no_hard_session_cost_cap=True, admission_budget=1)
    store = RunStore(tmp_path / "runs.json"); calls = []
    class Sessions:
        def create(self, **kw): calls.append(("session", kw)); return type("S", (), {"id": "s1", "status": "queued"})()
    class Agents:
        sessions = Sessions()
        def create(self, **kw): calls.append(("agent", kw)); return type("A", (), {"id": "a1"})()
    class Client: beta = type("B", (), {"agents": Agents()})()
    out = dispatch_once(store, lambda **kw: Client(), plan)
    assert out["session_id"] == "s1" and [x[0] for x in calls] == ["agent", "session"]
    with pytest.raises(CoordinatorError): dispatch_once(store, lambda **kw: Client(), plan)


def test_uncertain_create_blocks_resubmit(tmp_path: Path):
    p = tmp_path / "status.json"; p.write_text(json.dumps(good_status()), encoding="utf-8")
    plan = prepare("gpt-5.6-luna", p, live_enabled=True, acknowledge_no_hard_session_cost_cap=True, admission_budget=1)
    store = RunStore(tmp_path / "runs.json")
    def fail(**kw): raise RuntimeError("secret should not persist")
    with pytest.raises(CoordinatorError): dispatch_once(store, fail, plan)
    assert store.load(plan["run_key"])["state"] == "uncertain"
    with pytest.raises(CoordinatorError): dispatch_once(store, fail, plan)


def test_mutated_plan_is_rejected_before_factory(tmp_path: Path):
    p = tmp_path / "status.json"; p.write_text(json.dumps(good_status()), encoding="utf-8")
    plan = prepare("gpt-5.6-luna", p, live_enabled=True, acknowledge_no_hard_session_cost_cap=True, admission_budget=1)
    plan["session"]["input"] = "tampered"
    with pytest.raises(CoordinatorError): dispatch_once(RunStore(tmp_path / "runs.json"), lambda **kw: pytest.fail("factory called"), plan)


def test_reconcile_retrieve_failure_is_sanitized(tmp_path: Path):
    key = "c" * 64; store = RunStore(tmp_path / "runs.json")
    store.save(key, {"state": "session_created", "session_id": "s1", "model": "gpt-5.6-luna", "input": "{}", "prompt_hash": "x"})
    def fail(**kw):
        raise RuntimeError("secret")
    with pytest.raises(CoordinatorError): reconcile(store, fail, key)
    rec = store.load(key)
    assert rec["state"] == "reconcile_error" and "secret" not in json.dumps(rec)


def test_reconcile_requires_completed_turn_and_usage(tmp_path: Path):
    store = RunStore(tmp_path / "runs.json"); key = "b" * 64
    store.save(key, {"state": "session_created", "session_id": "s1", "model": "gpt-5.6-luna", "input": "{}", "prompt_hash": "x"})
    class Obj:
        def __init__(self, **kw): self.__dict__.update(kw)
    class Items:
        def list(self, *a, **kw): return Obj(data=[Obj(model_dump=lambda: {"id": "m1", "turn_id": "t1", "role": "assistant", "content": [{"type": "output_text", "text": "OK"}, {"type": "output_text", "text": "DONE"}]})])
    class Turns:
        def list(self, *a, **kw): return Obj(data=[Obj(id="t1", status="completed", usage=Obj(model_dump=lambda: {"input_tokens": 2, "output_tokens": 1, "total_tokens": 3}), model_dump=lambda: {"error": None})])
    class Sessions:
        items = Items(); turns = Turns()
        def retrieve(self, *a, **kw): return Obj(status="idle", model_dump=lambda: {"error": None, "usage": {"input_tokens": 2, "output_tokens": 1, "total_tokens": 3}})
    class Client: beta = Obj(agents=Obj(sessions=Sessions()))
    out = reconcile(store, lambda **kw: Client(), key)
    assert out["state"] == "completed" and out["messages"][0]["text"] == "OK"
    assert out["estimated_cost_usd"] == "0.0000016"


def test_reconcile_rejects_extra_turn(tmp_path: Path):
    store = RunStore(tmp_path / "runs.json"); key = "d" * 64
    store.save(key, {"state": "session_created", "session_id": "s1", "model": "gpt-5.6-luna", "input": "{}", "prompt_hash": "x"})
    class Obj:
        def __init__(self, **kw): self.__dict__.update(kw)
    usage = Obj(model_dump=lambda: {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2})
    class Sessions:
        class items:
            @staticmethod
            def list(*a, **kw): return Obj(data=[Obj(model_dump=lambda: {"turn_id": "t1", "role": "assistant", "content": [{"type": "output_text", "text": "OK"}]})])
        class turns:
            @staticmethod
            def list(*a, **kw): return Obj(data=[Obj(id="t1", status="completed", usage=usage, model_dump=lambda: {"error": None}), Obj(id="t2", status="failed", usage=None, model_dump=lambda: {"error": {}})])
        @staticmethod
        def retrieve(*a, **kw): return Obj(status="idle", model_dump=lambda: {"error": None, "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2}})
    out = reconcile(store, lambda **kw: Obj(beta=Obj(agents=Obj(sessions=Sessions()))), key)
    assert out["state"] == "failed"
