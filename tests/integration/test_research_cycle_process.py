"""Exercise supervisor cycle identity with a real temporary child process."""
import json
from pathlib import Path
import subprocess
import tempfile
import time
import unittest


class ResearchCycleProcessAcceptance(unittest.TestCase):
    def test_fresh_matching_cycle_is_healthy(self):
        result, report, argv = self._run_fixture(tampered=False)
        self.assertEqual(result["status"], "healthy")
        self.assertIsNone(result["child_pid"])
        self.assertEqual(report["status"], "ok")
        self.assertTrue(report["research_only"])
        self.assertFalse(report["live_orders"])
        self.assertFalse(report["ledger_mutations"])
        self.assertEqual(report["cycle_id"], argv[argv.index("--cycle-id") + 1])
        self.assertTrue(argv[argv.index("--cycle-id") + 1])
        self.assertEqual(result["cycle_id"], report["cycle_id"])

    def test_fresh_wrong_cycle_is_degraded(self):
        result, report, argv = self._run_fixture(tampered=True)
        self.assertEqual(result["status"], "degraded")
        self.assertIsNone(result["child_pid"])
        self.assertEqual(report["status"], "ok")
        self.assertEqual(result["cycle_id"], argv[argv.index("--cycle-id") + 1])
        self.assertNotEqual(report["cycle_id"], argv[argv.index("--cycle-id") + 1])

    def _run_fixture(self, tampered):
        import research_supervisor as supervisor

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "output"
            output.mkdir()
            runner = root / "research_runner.py"
            runner.write_text(
                """
import argparse, json, sys
from datetime import datetime, timezone
from pathlib import Path
parser = argparse.ArgumentParser()
parser.add_argument('--once', action='store_true')
parser.add_argument('--cycle-id', required=True)
args = parser.parse_args()
Path('output/argv.json').write_text(json.dumps(sys.argv[1:]), encoding='utf-8')
cycle_id = 'fixture-wrong-cycle' if %s else args.cycle_id
now = datetime.now(timezone.utc).isoformat()
Path('output/research_status.json').write_text(json.dumps({
    'status': 'ok', 'research_only': True, 'profit_proven': False,
    'live_orders': False, 'ledger_mutations': False, 'cycle_id': cycle_id,
    'started_at': now, 'finished_at': now}), encoding='utf-8')
""" % ("True" if tampered else "False"), encoding="utf-8")
            status_path = output / "supervisor.json"
            lock_path = output / "supervisor.lock"
            stop_path = output / "supervisor.stop"
            report_path = output / "research_status.json"
            children = []
            def process_factory(*args, **kwargs):
                child = subprocess.Popen(*args, **kwargs)
                children.append(child)
                return child
            old_root = supervisor.ROOT
            old_runner_status = supervisor.RUNNER_STATUS
            try:
                supervisor.ROOT = root
                supervisor.RUNNER_STATUS = report_path
                result = supervisor.run_supervisor(
                    interval=1, cycle_timeout=5, once=True,
                    status_path=status_path, lock_path=lock_path, stop_path=stop_path,
                    process_factory=process_factory,
                )
                self.assertTrue(status_path.exists())
                report = json.loads(report_path.read_text(encoding="utf-8"))
                argv = json.loads((output / "argv.json").read_text(encoding="utf-8"))
                state = json.loads(status_path.read_text(encoding="utf-8"))
                self.assertEqual(state, result)
                self.assertFalse((root / "research_status.json").exists())
                return result, report, argv
            finally:
                deadline = time.monotonic() + 5
                for child in children:
                    if child.poll() is None:
                        try:
                            child.terminate()
                        except OSError:
                            pass
                    remaining = max(0.0, deadline - time.monotonic())
                    try:
                        child.communicate(timeout=remaining)
                    except subprocess.TimeoutExpired:
                        child.kill()
                        child.communicate(timeout=1)
                supervisor.ROOT = old_root
                supervisor.RUNNER_STATUS = old_runner_status


if __name__ == "__main__":
    unittest.main()
