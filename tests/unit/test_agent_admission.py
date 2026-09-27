import pytest

from analytics.agent_admission import AdmissionDenied, report, require_paid_admission
from analytics.research_coordinator import CoordinatorError, dispatch, dispatch_once


def test_policy_snapshot_cannot_be_mutated_to_authorize():
    snapshot = report()
    snapshot["allowed"] = True
    snapshot["reasons"].clear()
    assert report()["allowed"] is False and report()["reasons"]
    with pytest.raises(AdmissionDenied):
        require_paid_admission()


def test_legacy_flags_and_environment_cannot_unlock(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "not-a-real-key")
    monkeypatch.setenv("AGENT_BUDGET_EUR", "1000")
    monkeypatch.setenv("LIVE_ENABLED", "true")
    class Forbidden:
        def __getattribute__(self, name):
            pytest.fail("input accessed before admission denial")
    def factory(**kwargs):
        pytest.fail("client created")
    with pytest.raises(CoordinatorError, match="admission policy"):
        dispatch(factory, "gpt-5.6-luna", live_enabled=True,
                 acknowledge_no_hard_session_cost_cap=True, admission_budget=1000,
                 status_path=Forbidden(), store_path=Forbidden())
    with pytest.raises(CoordinatorError, match="admission policy"):
        dispatch_once(Forbidden(), factory, Forbidden())
