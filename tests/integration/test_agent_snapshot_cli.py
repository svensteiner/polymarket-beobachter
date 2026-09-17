"""Offline CLI acceptance for snapshot identity and stale-data rejection."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]


def test_snapshot_identity_and_stale_rejection_across_processes(tmp_path):
    source = tmp_path / "status.json"
    store = tmp_path / "runs.json"
    now = datetime.now(timezone.utc)
    payload = {
        "status": "ok", "research_only": True, "live_orders": False,
        "ledger_mutations": False, "started_at": (now - timedelta(seconds=20)).isoformat(),
        "finished_at": (now - timedelta(seconds=10)).isoformat(),
        "scan": {"events": 1, "partitions": 1, "binary_markets": 2},
        "execution_scan": {"candidate_count": 0, "valid_evaluations": 1},
        "untrusted_note": "must never enter an agent prompt",
    }

    def prepare():
        source.write_text(json.dumps(payload), encoding="utf-8")
        return subprocess.run([sys.executable, str(ROOT / "research_agent.py"),
            "--status", str(source), "--store", str(store), "prepare", "--model", "gpt-5.6-luna"],
            cwd=tmp_path, capture_output=True, text=True, timeout=10)

    first = prepare()
    assert first.returncode == 0, first.stdout + first.stderr
    first_key = json.loads(first.stdout)["run_key"]
    assert "untrusted_note" not in store.read_text(encoding="utf-8")
    assert "must never enter" not in store.read_text(encoding="utf-8")
    again = prepare()
    assert again.returncode == 0
    assert json.loads(again.stdout)["run_key"] == first_key
    payload["finished_at"] = (now - timedelta(seconds=9)).isoformat()
    second = prepare()
    assert second.returncode == 0
    assert json.loads(second.stdout)["run_key"] != first_key
    before_rejection = store.read_bytes()
    payload["started_at"] = (now - timedelta(hours=2)).isoformat()
    payload["finished_at"] = (now - timedelta(hours=1)).isoformat()
    rejected = prepare()
    assert rejected.returncode != 0
    assert "error" in json.loads(rejected.stdout)
    assert store.read_bytes() == before_rejection
