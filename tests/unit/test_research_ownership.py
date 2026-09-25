import json
from pathlib import Path
from types import SimpleNamespace as Obj

import pytest

from analytics.agent_run_store import RunStore
from analytics.research_coordinator import CoordinatorError, reconcile


KEY = "a" * 64


def _store(path: Path, **extra):
    data = {"state": "session_created", "session_id": "sess-1", "agent_id": "agent-1", **extra}
    store = RunStore(path); store.save(KEY, data); return store


def _client(*, session_id="sess-1", agent_id="agent-1", turn=None, item=None, status="idle"):
    class Sessions:
        def retrieve(self, _sid):
            return Obj(id=session_id, agent=Obj(id=agent_id), status=status,
                       model_dump=lambda: {"id": session_id, "agent": {"id": agent_id}, "usage": {}})
        class items:
            @staticmethod
            def list(*_a, **_k): return Obj(has_more=False, data=[] if item is None else [Obj(model_dump=lambda: item)])
        class turns:
            @staticmethod
            def list(*_a, **_k): return Obj(has_more=False, data=[] if turn is None else [Obj(**turn)])
    return Obj(beta=Obj(agents=Obj(sessions=Sessions())))


@pytest.mark.parametrize("field", ["session_id", "agent_id"])
def test_missing_turn_ownership_fails_closed(tmp_path: Path, field):
    turn = {"id": "turn-1", "status": "completed", "session_id": "sess-1", "agent_id": "agent-1", "usage": None,
                "model_dump": lambda: {"session_id": "sess-1", "agent_id": "agent-1"}}
    turn.pop(field)
    turn["model_dump"] = lambda: {name: value for name, value in
        (("session_id", "sess-1"), ("agent_id", "agent-1")) if name != field}
    store = _store(tmp_path / "runs.json")
    with pytest.raises(CoordinatorError): reconcile(store, lambda **k: _client(turn=turn), KEY)
    assert store.load(KEY)["state"] == "failed"


def test_whitespace_stored_ownership_rejected_before_factory(tmp_path: Path):
    store = _store(tmp_path / "runs.json", session_id=" ")
    with pytest.raises(CoordinatorError):
        reconcile(store, lambda **k: pytest.fail("factory called"), KEY)
    assert store.load(KEY)["state"] == "failed"


def test_pending_empty_or_owned_stream_has_no_cost(tmp_path: Path):
    turn = {"id": "turn-1", "status": "running", "session_id": "sess-1", "agent_id": "agent-1",
            "usage": None, "model_dump": lambda: {"session_id": "sess-1", "agent_id": "agent-1"}}
    item = {"turn_id": "turn-1", "role": "assistant", "content": [{"type": "output_text", "text": "draft"}]}
    store = _store(tmp_path / "runs.json", estimated_cost_usd="9.99")
    result = reconcile(store, lambda **k: _client(turn=turn, item=item, status="running"), KEY)
    assert result["state"] == "in_progress" and "estimated_cost_usd" not in result
    assert result["messages"][0]["text"] == "draft"


def test_pending_empty_result_has_no_attributed_output(tmp_path: Path):
    store = _store(tmp_path / "runs.json", estimated_cost_usd="9.99")
    result = reconcile(store, lambda **k: _client(status="running"), KEY)
    assert result["state"] == "in_progress" and result["messages"] == []
    assert "estimated_cost_usd" not in result


def test_foreign_optional_message_metadata_rejected(tmp_path: Path):
    turn = {"id": "turn-1", "status": "completed", "session_id": "sess-1", "agent_id": "agent-1",
            "usage": None, "model_dump": lambda: {"session_id": "sess-1", "agent_id": "agent-1"}}
    item = {"turn_id": "turn-1", "session_id": "foreign", "agent_id": "agent-1",
            "role": "assistant", "content": [{"type": "output_text", "text": "foreign"}]}
    store = _store(tmp_path / "runs.json")
    with pytest.raises(CoordinatorError): reconcile(store, lambda **k: _client(turn=turn, item=item), KEY)
    saved = store.load(KEY)
    assert saved["state"] == "failed" and "foreign" not in json.dumps(saved)


def test_ownership_failure_then_valid_retry_clears_old_error_and_cost(tmp_path: Path):
    store = _store(tmp_path / "runs.json", estimated_cost_usd="9.99")
    with pytest.raises(CoordinatorError): reconcile(store, lambda **k: _client(session_id="foreign"), KEY)
    failed = store.load(KEY)
    assert failed["state"] == "failed" and "estimated_cost_usd" not in failed
    result = reconcile(store, lambda **k: _client(status="running"), KEY)
    assert result["state"] == "in_progress" and "error" not in result
