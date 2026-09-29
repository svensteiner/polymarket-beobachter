"""Real offline CLI checks for untrustworthy persisted cost evidence."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]


def completed(session, cost):
    return {"state": "completed", "session_id": session,
            "model": "gpt-5.6-luna", "estimated_cost_usd": cost,
            "usage": {"input_tokens": 1, "output_tokens": 2, "total_tokens": 3},
            "session_status": "idle", "output_incomplete": False}


def run_costs(tmp_path, raw):
    store = tmp_path / "runs.json"
    store.write_bytes(raw)
    env = {key: value for key, value in os.environ.items()
           if not key.startswith("OPENAI_")}
    result = subprocess.run(
        [sys.executable, str(ROOT / "research_agent.py"), "--store", str(store), "costs"],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=20)
    assert result.stderr == ""
    assert store.read_bytes() == raw
    assert sorted(p.name for p in tmp_path.iterdir()) == ["runs.json"]
    data = json.loads(result.stdout)
    assert data["authorization"] is False
    return result.returncode, data


@pytest.mark.parametrize("bad", ["NaN", "Infinity", "1e999", '"\\ud800"'])
def test_corrupt_metadata_cannot_produce_success(tmp_path, bad):
    raw = json.dumps({"a" * 64: completed("one", "0.1")}).encode()
    raw = raw[:-2] + b', "extra": ' + bad.encode() + b'}}'
    code, data = run_costs(tmp_path, raw)
    assert code == 2
    assert data.get("total_estimated_cost_usd") is None


@pytest.mark.parametrize("contradiction", [
    {"output_incomplete": True}, {"output_incomplete": "false"},
    {"session_status": "running"}, {"session_status": None},
    {"error": {"type": "OwnershipError"}},
    {"ownership_reason": "mismatched session"},
])
def test_contradictory_completion_keeps_only_known_partial_cost(tmp_path, contradiction):
    bad = completed("bad", "9.9")
    bad.update(contradiction)
    raw = json.dumps({"a" * 64: completed("good", "0.1"), "b" * 64: bad}).encode()
    code, data = run_costs(tmp_path, raw)
    assert code == 3
    assert data["total_estimated_cost_usd"] is None
    assert data["partial_known_estimated_cost_usd"] == "0.1"
    assert data["accounted_completed"] == 1


def test_valid_completion_costs_are_still_available(tmp_path):
    raw = json.dumps({"a" * 64: completed("one", "0.1"),
                      "b" * 64: completed("two", "0.2")}).encode()
    code, data = run_costs(tmp_path, raw)
    assert code == 0 and data["total_estimated_cost_usd"] == "0.3"
