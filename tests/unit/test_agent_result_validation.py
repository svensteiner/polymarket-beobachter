import json
from pathlib import Path
from types import SimpleNamespace as Obj

import pytest

from analytics.agent_run_store import RunStore
from analytics.research_coordinator import CoordinatorError, reconcile

KEY = "a" * 64


def seed(path, **extra):
    s = RunStore(path); s.save(KEY, {"state": "completed", "session_id": "s", "agent_id": "a", "messages": [{"text": "old"}], "usage": {"x": 1}, "estimated_cost_usd": "1", **extra}); return s


def client(ipage, tpage, *, status="idle"):
    class Sessions:
        def retrieve(self, sid): return Obj(id="s", agent=Obj(id="a"), status=status, model_dump=lambda: {"id": "s", "agent": {"id": "a"}, "usage": {}})
        class items:
            @staticmethod
            def list(*a, **k): return ipage
        class turns:
            @staticmethod
            def list(*a, **k): return tpage
    return Obj(beta=Obj(agents=Obj(sessions=Sessions())))


def test_pagination_scrubs_old_completed_record(tmp_path: Path):
    store = seed(tmp_path / "runs.json")
    bad = Obj(has_more=True, data=[])
    with pytest.raises(CoordinatorError): reconcile(store, lambda **k: client(bad, Obj(has_more=False, data=[])), KEY)
    saved = store.load(KEY)
    assert saved["state"] == "reconcile_error" and "messages" not in saved and "estimated_cost_usd" not in saved


@pytest.mark.parametrize("page", [Obj(has_more=False, data=None), Obj(has_more=False, data=[object()]), Obj(has_more=None, data=[])])
def test_malformed_pages_fail_closed(tmp_path: Path, page):
    store = seed(tmp_path / "runs.json")
    with pytest.raises(CoordinatorError): reconcile(store, lambda **k: client(page, Obj(has_more=False, data=[])), KEY)
    assert store.load(KEY)["output_incomplete"] is True


def test_foreign_turn_in_discarded_content_fails_before_filter(tmp_path: Path):
    store = seed(tmp_path / "runs.json")
    turn = Obj(id="foreign", status="completed", session_id="foreign", agent_id="a", model_dump=lambda: {"id": "foreign", "session_id": "foreign", "agent_id": "a"})
    item = Obj(model_dump=lambda: {"id": "m", "turn_id": "foreign", "content": [{"text": "secret"}] * 20})
    with pytest.raises(CoordinatorError): reconcile(store, lambda **k: client(Obj(has_more=False, data=[item]), Obj(has_more=False, data=[turn])), KEY)
    assert "secret" not in json.dumps(store.load(KEY))


def valid_result(*, text='new', status='idle'):
    usage = {'input_tokens': 1, 'output_tokens': 1, 'total_tokens': 2}
    turn = Obj(id='t', status='completed', session_id='s', agent_id='a', usage=usage,
               model_dump=lambda: {'id': 't', 'session_id': 's', 'agent_id': 'a', 'error': None})
    message = {'id': 'm', 'turn_id': 't', 'type': 'message', 'role': 'assistant',
               'content': [{'type': 'output_text', 'text': text}]}
    items = Obj(has_more=False, data=[Obj(model_dump=lambda: message)])
    turns = Obj(has_more=False, data=[turn])
    result = client(items, turns, status=status)
    result.beta.agents.sessions.retrieve = lambda sid: Obj(id='s', agent=Obj(id='a'), status=status,
        model_dump=lambda: {'id': 's', 'agent': {'id': 'a'}, 'usage': usage})
    return result, items, turns, message


@pytest.mark.parametrize('violation', ['unicode', 'duplicate_item', 'duplicate_turn', 'turn_dump', 'missing_content', 'bad_text', 'bad_status', 'dump_raises'])
def test_malformed_result_scrubs_all_previous_evidence(tmp_path, violation):
    store = seed(tmp_path / 'runs.json')
    api, items, turns, message = valid_result()
    if violation == 'unicode': message['content'][0]['text'] = '\ud800'
    elif violation == 'duplicate_item': items.data *= 2
    elif violation == 'duplicate_turn': turns.data *= 2
    elif violation == 'turn_dump': turns.data[0].model_dump = lambda: []
    elif violation == 'missing_content': message.pop('content')
    elif violation == 'bad_text': message['content'][0]['text'] = None
    elif violation == 'bad_status':
        api.beta.agents.sessions.retrieve = lambda sid: Obj(id='s', agent=Obj(id='a'), status={}, model_dump=lambda: {})
    else:
        def fail(): raise ValueError('untrusted payload')
        items.data[0].model_dump = fail
    with pytest.raises(CoordinatorError): reconcile(store, lambda **k: api, KEY)
    saved = store.load(KEY)
    assert saved['state'] == 'reconcile_error' and saved['output_incomplete']
    for field in ('messages', 'usage', 'estimated_cost_usd', 'session_status'):
        assert field not in saved
    assert saved['session_id'] == 's' and saved['agent_id'] == 'a'
    recovered, *_ = valid_result()
    assert reconcile(store, lambda **k: recovered, KEY)['state'] == 'completed'


@pytest.mark.parametrize('status', ['running', 'error'])
def test_noncompleted_matching_usage_never_estimates_cost(tmp_path, status):
    store = seed(tmp_path / 'runs.json')
    api, *_ = valid_result(status=status)
    result = reconcile(store, lambda **k: api, KEY)
    assert result['state'] != 'completed' and 'estimated_cost_usd' not in result


def test_transport_failure_invalidates_previous_completion(tmp_path):
    store = seed(tmp_path / 'runs.json')
    def fail(**kwargs): raise RuntimeError('secret transport details')
    with pytest.raises(CoordinatorError): reconcile(store, fail, KEY)
    saved = store.load(KEY)
    assert saved['state'] == 'reconcile_error'
    assert all(field not in saved for field in ('messages', 'usage', 'estimated_cost_usd', 'session_status'))
    assert 'secret transport details' not in json.dumps(saved)


def test_foreign_item_turn_is_checked_before_oversize_filter(tmp_path):
    store = seed(tmp_path / 'runs.json')
    api, _, _, message = valid_result(text='x' * 5000)
    message['turn_id'] = 'foreign'
    with pytest.raises(CoordinatorError): reconcile(store, lambda **k: api, KEY)
    assert store.load(KEY)['state'] == 'failed'
    assert 'messages' not in store.load(KEY)
