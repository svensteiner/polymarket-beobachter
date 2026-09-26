import json
from pathlib import Path

import pytest

from analytics.agent_run_store import RunStore, RunStoreError
from analytics.research_coordinator import CoordinatorError, dispatch_once, prepare


def _plan(tmp_path: Path):
    from tests.unit.test_research_coordinator import good_status
    status = tmp_path / "status.json"; status.write_text(json.dumps(good_status()), encoding="utf-8")
    return prepare("gpt-5.6-luna", status, live_enabled=True,
                   acknowledge_no_hard_session_cost_cap=True, admission_budget=1)


def test_invalid_response_ids_are_uncertain_and_no_followup(tmp_path: Path):
    plan = _plan(tmp_path); store = RunStore(tmp_path / "runs.json"); calls = []
    class Sessions:
        def create(self, **kwargs): calls.append("session"); return type("S", (), {"id": "s"})()
    class Agents:
        sessions = Sessions()
        def create(self, **kwargs): calls.append("agent"); return type("A", (), {"id": None})()
    class Client: beta = type("B", (), {"agents": Agents()})(); close = lambda self: None
    with pytest.raises(CoordinatorError): dispatch_once(store, lambda **k: Client(), plan)
    assert calls == ["agent"] and store.load(plan["run_key"])["state"] == "uncertain"


def test_unsafe_existing_state_rejected_before_factory(tmp_path: Path):
    plan = _plan(tmp_path); store = RunStore(tmp_path / "runs.json")
    store.save(plan["run_key"], {"model": plan["model"], "prompt_hash": plan["prompt_hash"], "input": plan["input"], "state": "session_created", "session_id": "s", "agent_id": "a"})
    with pytest.raises(CoordinatorError): dispatch_once(store, lambda **k: pytest.fail("factory called"), plan)


def test_agent_created_resume_skips_agent_post_and_closes_client(tmp_path: Path):
    plan = _plan(tmp_path); store = RunStore(tmp_path / "runs.json")
    store.save(plan["run_key"], {"model": plan["model"], "prompt_hash": plan["prompt_hash"], "input": plan["input"], "state": "agent_created", "agent_id": "a"})
    calls = []; closed = []
    class Sessions:
        def create(self, **kwargs): calls.append(kwargs); return type("S", (), {"id": "s", "agent": type("A", (), {"id": "a"})(), "status": "queued", "model_dump": lambda self: {"id": "s", "agent": {"id": "a"}}})()
    class Client:
        beta = type("B", (), {"agents": type("A", (), {"sessions": Sessions(), "create": lambda *_a, **_k: pytest.fail("agent post")})()})()
        def close(self): closed.append(True)
    out = dispatch_once(store, lambda **k: Client(), plan)
    assert out["session_id"] == "s" and calls and closed


def test_nested_session_agent_mismatch_uncertain(tmp_path: Path):
    plan = _plan(tmp_path); store = RunStore(tmp_path / "runs.json")
    class Sessions:
        def create(self, **kwargs): return type("S", (), {"id": "s", "agent": type("A", (), {"id": "foreign"})(), "model_dump": lambda self: {"id": "s", "agent": {"id": "foreign"}}})()
    class Agents:
        sessions = Sessions()
        def create(self, **kwargs): return type("A", (), {"id": "a"})()
    class Client: beta = type("B", (), {"agents": Agents()})(); close = lambda self: None
    with pytest.raises(CoordinatorError): dispatch_once(store, lambda **k: Client(), plan)
    assert store.load(plan["run_key"])["state"] == "uncertain"


class _FailSaveStore(RunStore):
    def __init__(self, path, fail_state): super().__init__(path); self.fail_state = fail_state; self.failed = False
    def save(self, key, record):
        if not self.failed and record.get("state") == self.fail_state:
            self.failed = True; raise RunStoreError("injected save failure")
        return super().save(key, record)


def test_save_failure_before_agent_post(tmp_path: Path):
    plan = _plan(tmp_path); store = _FailSaveStore(tmp_path / "runs.json", "creating_agent")
    with pytest.raises(RunStoreError): dispatch_once(store, lambda **k: object(), plan)
    assert store.load(plan["run_key"])["state"] == "prepared"


def test_save_failure_after_agent_post_leaves_retry_blocking_intent(tmp_path: Path):
    plan = _plan(tmp_path); store = _FailSaveStore(tmp_path / "runs.json", "agent_created"); calls = []
    class Agents:
        def create(self, **k): calls.append("agent"); return type("A", (), {"id": "a"})()
    class Client: beta = type("B", (), {"agents": Agents()})(); close = lambda self: None
    with pytest.raises(RunStoreError): dispatch_once(store, lambda **k: Client(), plan)
    assert calls == ["agent"] and RunStore(tmp_path / "runs.json").load(plan["run_key"])["state"] == "creating_agent"


def test_save_failure_before_session_post_preserves_agent_created(tmp_path: Path):
    plan = _plan(tmp_path); base = RunStore(tmp_path / "runs.json")
    base.save(plan["run_key"], {"model": plan["model"], "prompt_hash": plan["prompt_hash"], "input": plan["input"], "state": "agent_created", "agent_id": "a"})
    store = _FailSaveStore(tmp_path / "runs.json", "creating_session")
    with pytest.raises(RunStoreError): dispatch_once(store, lambda **k: object(), plan)
    assert RunStore(tmp_path / "runs.json").load(plan["run_key"])["state"] == "agent_created"


def test_save_failure_after_session_post_blocks_retry(tmp_path: Path):
    plan = _plan(tmp_path); base = RunStore(tmp_path / "runs.json")
    base.save(plan["run_key"], {"model": plan["model"], "prompt_hash": plan["prompt_hash"], "input": plan["input"], "state": "agent_created", "agent_id": "a"})
    store = _FailSaveStore(tmp_path / "runs.json", "session_created")
    class Sessions:
        def create(self, **k): return type("S", (), {"id": "s", "agent": type("A", (), {"id": "a"})(), "model_dump": lambda self: {"agent": {"id": "a"}}})()
    class Client: beta = type("B", (), {"agents": type("A", (), {"sessions": Sessions()})()})(); close = lambda self: None
    with pytest.raises(RunStoreError): dispatch_once(store, lambda **k: Client(), plan)
    assert RunStore(tmp_path / "runs.json").load(plan["run_key"])["state"] == "creating_session"
    with pytest.raises(CoordinatorError): dispatch_once(RunStore(tmp_path / "runs.json"), lambda **k: pytest.fail("retry"), plan)


@pytest.mark.parametrize("bad", [None, 1, ""])
def test_malformed_agent_response_id_uncertain(tmp_path: Path, bad):
    plan = _plan(tmp_path); store = RunStore(tmp_path / "runs.json")
    class Agents:
        def create(self, **k): return type("A", (), {"id": bad})()
    class Client: beta = type("B", (), {"agents": Agents()})(); close = lambda self: None
    with pytest.raises(CoordinatorError): dispatch_once(store, lambda **k: Client(), plan)
    assert store.load(plan["run_key"])["state"] == "uncertain"


def test_close_failure_does_not_mask_success_or_original_error(tmp_path: Path):
    plan = _plan(tmp_path); store = RunStore(tmp_path / "runs.json")
    class Sessions:
        def create(self, **k): return type("S", (), {"id": "s", "agent": type("A", (), {"id": "a"})(), "model_dump": lambda self: {"agent": {"id": "a"}}})()
    class Client:
        beta = type("B", (), {"agents": type("A", (), {"create": lambda *_a, **_k: type("X", (), {"id": "a"})(), "sessions": Sessions()})()})()
        def close(self): raise RuntimeError("close")
    out = dispatch_once(store, lambda **k: Client(), plan)
    assert out["state"] == "session_created"
