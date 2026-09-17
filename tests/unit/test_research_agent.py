import json
import subprocess
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

import research_agent as agent
from analytics.agent_run_store import RunStore


def status(path: Path):
    finished = datetime.now(timezone.utc)
    path.write_text(json.dumps({"status":"ok", "started_at": (finished - timedelta(seconds=30)).isoformat(),
        "finished_at": finished.isoformat(), "research_only": True, "live_orders": False,
        "ledger_mutations": False, "scan":{"events":1,"partitions":1,"binary_markets":1},
        "execution_scan":{"candidate_count":0,"valid_evaluations":1}}))


def test_prepare_is_offline_and_derives_key(tmp_path: Path):
    p = tmp_path / "status.json"; status(p)
    result = agent.prepare("gpt-5.6-luna", p, tmp_path / "store.json")
    assert result["state"] == "prepared_offline" and len(result["run_key"]) == 64
    assert result["live_enabled"] is False and result["dispatch_available"] is False


def test_show_missing_is_safe(tmp_path: Path):
    try: agent.show("0" * 64, tmp_path / "store.json")
    except agent.CoordinatorError as exc: assert str(exc) == "run not found"
    else: raise AssertionError("missing run accepted")


def test_unknown_reconcile_does_not_import_sdk(tmp_path: Path, monkeypatch):
    monkeypatch.setitem(sys.modules, "openai", None)
    try: agent.reconcile_known("1" * 64, tmp_path / "store.json")
    except agent.CoordinatorError as exc: assert str(exc) == "known session required"
    else: raise AssertionError("unknown run reconciled")


def test_cli_prepare_is_offline(tmp_path: Path):
    p = tmp_path / "status.json"; status(p)
    command = [sys.executable, str(agent.ROOT / "research_agent.py"), "--status", str(p), "--store", str(tmp_path / "store.json"), "prepare", "--model", "gpt-5.6-luna"]
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    assert completed.returncode == 0
    assert json.loads(completed.stdout)["dispatch_available"] is False


def test_prepare_then_show_from_other_working_directory(tmp_path: Path):
    status_path = tmp_path / "status.json"; store_path = tmp_path / "store.json"
    status(status_path)
    prepared = agent.prepare("gpt-5.6-luna", status_path, store_path)
    command = [sys.executable, str(agent.ROOT / "research_agent.py"), "--store", str(store_path),
               "show", "--run-key", prepared["run_key"]]
    completed = subprocess.run(command, cwd=tmp_path, capture_output=True, text=True, check=False)
    assert completed.returncode == 0
    assert json.loads(completed.stdout)["record"]["state"] == "prepared"


def test_repeated_prepare_preserves_existing_lifecycle(tmp_path: Path):
    status_path = tmp_path / "status.json"; store_path = tmp_path / "store.json"
    status(status_path)
    prepared = agent.prepare("gpt-5.6-luna", status_path, store_path)
    store = RunStore(store_path)
    record = store.load(prepared["run_key"]); record.update(state="session_created", session_id="sess-1")
    store.save(prepared["run_key"], record)
    agent.prepare("gpt-5.6-luna", status_path, store_path)
    assert RunStore(store_path).load(prepared["run_key"])["session_id"] == "sess-1"


def test_conflicting_immutable_record_is_rejected(tmp_path: Path):
    status_path = tmp_path / "status.json"; store_path = tmp_path / "store.json"
    status(status_path)
    prepared = agent.prepare("gpt-5.6-luna", status_path, store_path)
    store = RunStore(store_path); record = store.load(prepared["run_key"])
    record["input"] = "tampered"; store.save(prepared["run_key"], record)
    try: agent.prepare("gpt-5.6-luna", status_path, store_path)
    except agent.CoordinatorError as exc: assert str(exc) == "run key input conflict"
    else: raise AssertionError("conflicting record accepted")


def test_empty_or_incomplete_existing_record_is_not_overwritten(tmp_path: Path):
    status_path = tmp_path / "status.json"; store_path = tmp_path / "store.json"
    status(status_path)
    prepared = agent.prepare("gpt-5.6-luna", status_path, store_path)
    store = RunStore(store_path)
    for malformed in ({}, {"state": "prepared"}):
        store.save(prepared["run_key"], malformed)
        try: agent.prepare("gpt-5.6-luna", status_path, store_path)
        except agent.CoordinatorError as exc: assert str(exc) == "run key input conflict"
        else: raise AssertionError("incomplete existing record overwritten")
        assert store.load(prepared["run_key"]) == malformed


def test_cli_malformed_status_returns_structured_error(tmp_path: Path):
    status_path = tmp_path / "status.json"; status_path.write_text("{}", encoding="utf-8")
    command = [sys.executable, str(agent.ROOT / "research_agent.py"), "--status", str(status_path),
               "--store", str(tmp_path / "store.json"), "prepare", "--model", "gpt-5.6-luna"]
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    assert completed.returncode == 1
    assert json.loads(completed.stdout)["error"] == "operation failed"


class _FakeSession:
    def __init__(self, state): self.status, self.state = state, state
    def model_dump(self): return {"usage": {"input_tokens": 2, "output_tokens": 1, "total_tokens": 3}}


class _FakeTurn:
    id = "turn-1"; status = "completed"
    usage = {"input_tokens": 2, "output_tokens": 1, "total_tokens": 3}
    def model_dump(self): return {}


class _FakeItem:
    def model_dump(self):
        return {"id": "item-1", "turn_id": "turn-1", "role": "assistant",
                "content": [{"type": "output_text", "text": "ok"}]}


def _seed_session(store_path: Path):
    key = "a" * 64
    RunStore(store_path).save(key, {"model": "gpt-5.6-luna", "prompt_hash": "p", "input": "{}",
                                    "state": "session_created", "session_id": "sess-1"})
    return key


def test_reconcile_known_fake_sdk_persists_and_closes(tmp_path: Path, monkeypatch):
    store_path = tmp_path / "store.json"; key = _seed_session(store_path)
    captured = {}
    class Sessions:
        def retrieve(self, sid): return _FakeSession("idle")
        class items:
            @staticmethod
            def list(*args, **kwargs): return types.SimpleNamespace(has_more=False, data=[_FakeItem()])
        class turns:
            @staticmethod
            def list(*args, **kwargs): return types.SimpleNamespace(has_more=False, data=[_FakeTurn()])
    class FakeClient:
        beta = types.SimpleNamespace(agents=types.SimpleNamespace(sessions=Sessions()))
        def close(self): captured["closed"] = True
    def OpenAI(**kwargs): captured["kwargs"] = kwargs; return FakeClient()
    monkeypatch.setitem(sys.modules, "openai", types.SimpleNamespace(OpenAI=OpenAI))
    result = agent.reconcile_known(key, store_path, 30)
    assert result["state"] == "completed" and result["exit_code"] == 0
    assert captured == {"kwargs": {"timeout": 30, "max_retries": 0}, "closed": True}
    assert RunStore(store_path).load(key)["state"] == "completed"


def test_reconcile_in_progress_and_failed_exit_codes(tmp_path: Path, monkeypatch):
    store_path = tmp_path / "store.json"; key = _seed_session(store_path)
    mode = {"value": "running"}
    class Sessions:
        def retrieve(self, sid): return types.SimpleNamespace(status=mode["value"], model_dump=lambda: {"usage": {}})
        class items:
            list = staticmethod(lambda *a, **k: types.SimpleNamespace(has_more=False, data=[]))
        class turns:
            list = staticmethod(lambda *a, **k: types.SimpleNamespace(has_more=False, data=[]))
    class FakeClient:
        beta = types.SimpleNamespace(agents=types.SimpleNamespace(sessions=Sessions()))
        close = lambda self: None
    monkeypatch.setitem(sys.modules, "openai", types.SimpleNamespace(OpenAI=lambda **k: FakeClient()))
    assert agent.reconcile_known(key, store_path)["exit_code"] == 3
    mode["value"] = "error"
    assert agent.reconcile_known(key, store_path)["exit_code"] == 1


def test_reconcile_retrieve_error_persists_and_cli_exit(monkeypatch, tmp_path: Path):
    store_path = tmp_path / "store.json"; key = _seed_session(store_path)
    class Sessions:
        def retrieve(self, sid): raise RuntimeError("hidden")
    class FakeClient:
        beta = types.SimpleNamespace(agents=types.SimpleNamespace(sessions=Sessions()))
        close = lambda self: None
    monkeypatch.setitem(sys.modules, "openai", types.SimpleNamespace(OpenAI=lambda **k: FakeClient()))
    try: agent.reconcile_known(key, store_path)
    except agent.CoordinatorError: pass
    else: raise AssertionError("retrieve error swallowed")
    assert RunStore(store_path).load(key)["state"] == "reconcile_error"
    monkeypatch.setattr(agent, "reconcile_known", lambda *a, **k: {"state": "in_progress", "exit_code": 3})
    assert agent.main(["--store", str(store_path), "reconcile", "--run-key", key]) == 3
