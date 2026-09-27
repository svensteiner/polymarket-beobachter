"""Verify the standalone admission CLI is fail-closed and side-effect free."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]


class AgentAdmissionCLI(unittest.TestCase):
    def test_missing_paths_return_stable_denial_without_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory) / "foreign"
            work.mkdir()
            store = work / "missing-store.json"
            status = work / "missing-status.json"
            completed = self._run(work, store, status)
            self.assertEqual(completed.returncode, 3, completed.stdout + completed.stderr)
            self.assertEqual(completed.stderr, "")
            payload = json.loads(completed.stdout)
            self.assertFalse(payload["allowed"])
            self.assertEqual(payload["authorized_budget_eur"], "0")
            self.assertFalse(payload["hard_session_cap_verified"])
            self.assertFalse(payload["reservation_supported"])
            self.assertFalse(payload["production_ready"])
            self.assertFalse(store.exists())
            self.assertFalse(status.exists())

    def test_corrupt_paths_return_same_denial_without_rewrite(self):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory) / "foreign"
            work.mkdir()
            store = work / "store.json"
            status = work / "status.json"
            store.write_bytes(b"corrupt store\x00")
            status.write_bytes(b"corrupt status\x00")
            before = (store.read_bytes(), status.read_bytes())
            completed = self._run(work, store, status)
            self.assertEqual(completed.returncode, 3, completed.stdout + completed.stderr)
            self.assertEqual(completed.stderr, "")
            payload = json.loads(completed.stdout)
            self.assertFalse(payload["allowed"])
            self.assertEqual(payload["authorized_budget_eur"], "0")
            self.assertFalse(payload["hard_session_cap_verified"])
            self.assertFalse(payload["reservation_supported"])
            self.assertFalse(payload["production_ready"])
            self.assertEqual((store.read_bytes(), status.read_bytes()), before)

    def test_public_dispatch_denial_has_no_factory_store_or_lock_side_effects(self):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory) / "foreign"
            work.mkdir()
            store = work / "runs.json"
            status = work / "status.json"
            sentinel = work / "factory-called"
            script = work / "probe.py"
            script.write_text(
                """
import hashlib, json, sys
from pathlib import Path
from datetime import datetime, timezone
from analytics.research_coordinator import PROMPT, RunStore, dispatch, dispatch_once

store_path, status_path, sentinel_path = map(Path, sys.argv[1:])
now = datetime.now(timezone.utc).isoformat()
canonical = json.dumps({"status":"ok", "finished_at":now, "events":1,
    "partitions":1, "binary_markets":2, "candidate_count":0,
    "valid_evaluations":1}, separators=(",", ":"))
material = json.dumps({"model":"gpt-5.6-luna", "input":canonical, "prompt":PROMPT}, sort_keys=True)
key = hashlib.sha256(material.encode()).hexdigest()
plan = {"run_key":key, "model":"gpt-5.6-luna", "prompt_hash":hashlib.sha256(PROMPT.encode()).hexdigest(),
    "input":canonical, "agent":{"model":"gpt-5.6-luna", "instructions":PROMPT,
    "multi_agent":{"enabled":False}, "tools":[]}, "session":{"environment":{"type":"none"},
    "input":canonical, "stream":False}, "admission_budget":1, "live_enabled":True,
    "acknowledge_no_hard_session_cost_cap":True}
status_path.write_text(json.dumps({"status":"ok", "started_at":now, "finished_at":now,
    "research_only":True, "live_orders":False, "ledger_mutations":False,
    "scan":{"events":1,"partitions":1,"binary_markets":2},
    "execution_scan":{"candidate_count":0,"valid_evaluations":1}}), encoding="utf-8")
before = store_path.read_bytes()
def factory(**kwargs):
    sentinel_path.write_text("called", encoding="utf-8")
    raise AssertionError("factory called")
errors = []
for operation in (
    lambda: dispatch(factory, "gpt-5.6-luna", live_enabled=True,
        acknowledge_no_hard_session_cost_cap=True, admission_budget=1,
        status_path=status_path, store_path=store_path),
    lambda: dispatch_once(RunStore(store_path), factory, plan),
):
    try:
        operation()
    except Exception as exc:
        errors.append(type(exc).__name__)
print(json.dumps({"errors":errors, "store_unchanged":store_path.read_bytes() == before,
    "lock_exists":store_path.with_suffix(store_path.suffix + ".operation.lock").exists(),
    "sentinel_exists":sentinel_path.exists()}))
""", encoding="utf-8")
            store.write_text(json.dumps({"0" * 64: {"state": "prepared"}}), encoding="utf-8")
            before = store.read_bytes()
            environment = os.environ.copy()
            environment["PYTHONPATH"] = str(ROOT) + (os.pathsep + environment["PYTHONPATH"] if environment.get("PYTHONPATH") else "")
            completed = subprocess.run([sys.executable, str(script), str(store), str(status), str(sentinel)],
                                       cwd=work, env=environment, capture_output=True, text=True, timeout=20)
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            result = json.loads(completed.stdout)
            self.assertEqual(result["errors"], ["CoordinatorError", "CoordinatorError"])
            self.assertTrue(result["store_unchanged"])
            self.assertFalse(result["lock_exists"])
            self.assertFalse(result["sentinel_exists"])
            self.assertEqual(store.read_bytes(), before)

    @staticmethod
    def _run(cwd, store, status):
        environment = os.environ.copy()
        for name in ("OPENAI_API_KEY", "OPENAI_ORG_ID", "OPENAI_PROJECT_ID", "OPENAI_ADMIN_KEY"):
            environment.pop(name, None)
        return subprocess.run(
            [sys.executable, str(ROOT / "research_agent.py"), "--store", str(store),
             "--status", str(status), "admission"],
            cwd=cwd, env=environment,
            capture_output=True, text=True, timeout=20,
        )


if __name__ == "__main__":
    unittest.main()
