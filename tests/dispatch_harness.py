"""TEST ONLY: exercise private lifecycle with fakes or a local HTTP fixture.

Production callers must use the public, admission-gated entrypoints.
"""
from analytics.agent_run_store import RunStore
from analytics.research_coordinator import _dispatch_locked, prepare


def dispatch_once(store, client_factory, plan):
    with store.operation():
        return _dispatch_locked(store, client_factory, plan)


def dispatch(client_factory, model, *, store_path, **kwargs):
    return dispatch_once(RunStore(store_path), client_factory, prepare(model, **kwargs))
