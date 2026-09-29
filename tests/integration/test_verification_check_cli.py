"""Offline acceptance for the verification manifest checker in isolation."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone


ROOT = Path(__file__).resolve().parents[2]


class VerificationCheckCLI(unittest.TestCase):
    def test_current_report_passes_and_source_changes_are_stale(self):
        with tempfile.TemporaryDirectory() as directory:
            isolated, checker, fixture = self._isolated(Path(directory))
            from importlib.util import module_from_spec, spec_from_file_location
            spec = spec_from_file_location("isolated_verification_manifest",
                                           isolated / "analytics" / "verification_manifest.py")
            manifest_module = module_from_spec(spec)
            assert spec.loader is not None
            spec.loader.exec_module(manifest_module)
            source_manifest = manifest_module.collect(isolated)
            now = datetime.now(timezone.utc).isoformat()
            report = {
                "schema_version": 2,
                "source_manifest": source_manifest,
                "source_stable": True,
                "generated_at": now,
                "completed_at": now,
                "status": "passed",
                "scope": "research_only",
                "production_ready": False,
                "python": r"C:\sentinel\must-not-execute.exe",
                "preflight": {"ok": True, "python_major_minor": "3.12", "pytest": "9.0.2"},
                "pytest": {"returncode": 0, "timed_out": False},
                "sdk": {"status": "not_checked"},
            }
            report_path = isolated / "report.json"
            report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
            foreign = Path(directory) / "foreign"
            foreign.mkdir()
            current = self._run(checker, report_path, foreign)
            self.assertEqual(current.returncode, 0, current.stdout + current.stderr)
            self.assertEqual(current.stderr, "")
            result = json.loads(current.stdout)
            self.assertEqual(result.get("status"), "passed")
            before = report_path.read_bytes()
            fixture.write_text(fixture.read_text(encoding="utf-8") + "\nchanged = True\n", encoding="utf-8")
            stale = self._run(checker, report_path, foreign)
            self.assertEqual(stale.returncode, 1, stale.stdout + stale.stderr)
            self.assertEqual(stale.stderr, "")
            self.assertEqual(json.loads(stale.stdout).get("status"), "failed")
            self.assertEqual(report_path.read_bytes(), before)

    def test_malformed_report_is_structured_and_side_effect_free(self):
        with tempfile.TemporaryDirectory() as directory:
            isolated, checker, _fixture = self._isolated(Path(directory))
            foreign = Path(directory) / "foreign"
            foreign.mkdir()
            report_path = isolated / "report.json"
            report_path.write_text("{malformed", encoding="utf-8")
            before = report_path.read_bytes()
            completed = self._run(checker, report_path, foreign)
            self.assertEqual(completed.returncode, 1, completed.stdout + completed.stderr)
            self.assertEqual(completed.stderr, "")
            payload = json.loads(completed.stdout)
            self.assertEqual(payload.get("status"), "failed")
            self.assertIn("error", payload)
            self.assertEqual(report_path.read_bytes(), before)

    @staticmethod
    def _isolated(root):
        analytics = root / "analytics"
        analytics.mkdir(parents=True)
        shutil.copy2(ROOT / "verify_research.py", root / "verify_research.py")
        shutil.copy2(ROOT / "analytics" / "__init__.py", analytics / "__init__.py")
        shutil.copy2(ROOT / "analytics" / "verification_manifest.py", analytics / "verification_manifest.py")
        fixture = root / "fixture.py"
        fixture.write_text("SYNTHETIC_FIXTURE = True\n", encoding="utf-8")
        return root, root / "verify_research.py", fixture

    @staticmethod
    def _run(checker, report, cwd):
        environment = os.environ.copy()
        for name in ("OPENAI_API_KEY", "OPENAI_ORG_ID", "OPENAI_PROJECT_ID", "OPENAI_ADMIN_KEY"):
            environment.pop(name, None)
        environment["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
        return subprocess.run([sys.executable, str(checker), "--check", "--report", str(report)],
                              cwd=cwd, env=environment, capture_output=True, text=True, timeout=20)


if __name__ == "__main__":
    unittest.main()
