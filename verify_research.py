"""Bounded, offline verification for the research-only package."""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import uuid
import re

ROOT = Path(__file__).resolve().parent
DEFAULT_REPORT = ROOT / "output" / "research_verification.json"
MAX_OUTPUT = 12_000
TIMEOUT = 120
RESEARCH_TESTS = [
    "tests/unit/test_agent_cost_report.py", "tests/unit/test_agent_run_store.py",
    "tests/unit/test_research_agent.py", "tests/unit/test_research_control.py",
    "tests/unit/test_research_coordinator.py", "tests/unit/test_research_health.py",
    "tests/unit/test_research_ownership.py", "tests/unit/test_research_runner.py",
    "tests/unit/test_research_supervisor.py", "tests/unit/test_research_verification.py",
    "tests/integration/test_agent_snapshot_cli.py", "tests/integration/test_research_control_process.py",
]


def _clip(value: str) -> str:
    return value if len(value) <= MAX_OUTPUT else value[:MAX_OUTPUT] + "...[truncated]"


def _read_output(path: str) -> tuple[str, bool]:
    with Path(path).open("rb") as handle:
        data = handle.read(MAX_OUTPUT + 1)
    truncated = len(data) > MAX_OUTPUT
    return data[:MAX_OUTPUT].decode("utf-8", "replace"), truncated


def _run(command: list[str], *, timeout: int = TIMEOUT) -> dict:
    started = time.monotonic()
    env = {k: v for k, v in os.environ.items() if k not in {"OPENAI_API_KEY", "OPENAI_ADMIN_KEY", "OPENAI_PROJECT_ID", "OPENAI_ORG_ID"}}
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    out_name = err_name = None
    try:
        with tempfile.NamedTemporaryFile(delete=False) as out, tempfile.NamedTemporaryFile(delete=False) as err:
            out_name, err_name = out.name, err.name
            completed = subprocess.run(command, cwd=ROOT, stdout=out, stderr=err,
                                       timeout=timeout, shell=False, env=env)
        stdout, stdout_truncated = _read_output(out_name)
        stderr, stderr_truncated = _read_output(err_name)
        return {"returncode": completed.returncode, "stdout": _clip(stdout),
                "stderr": _clip(stderr), "timed_out": False,
                "output_truncated": stdout_truncated or stderr_truncated,
                "duration_seconds": round(time.monotonic() - started, 3)}
    except subprocess.TimeoutExpired:
        return {"returncode": None, "stdout": "", "stderr": "", "timed_out": True, "output_truncated": False,
                "duration_seconds": round(time.monotonic() - started, 3)}
    except OSError as exc:
        return {"returncode": None, "stdout": "", "stderr": type(exc).__name__, "timed_out": False, "output_truncated": False,
                "duration_seconds": round(time.monotonic() - started, 3)}
    finally:
        for name in (out_name, err_name):
            if name:
                try: os.unlink(name)
                except OSError: pass


def _preflight(python: str) -> dict:
    probe = _run([python, "-c", "import sys,pytest; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}'); print(pytest.__version__)"], timeout=20)
    lines = probe["stdout"].splitlines()
    ok = probe["returncode"] == 0 and len(lines) >= 2 and lines[0].split(".")[:2] == ["3", "12"] and lines[1] == "9.0.2"
    probe["ok"] = ok
    probe["expected"] = {"python_major_minor": "3.12", "pytest": "9.0.2"}
    return probe


def verify(*, python: str = sys.executable, agent_python: str | None = None,
           report: Path = DEFAULT_REPORT) -> tuple[int, dict]:
    result = {"run_id": uuid.uuid4().hex, "generated_at": datetime.now(timezone.utc).isoformat(),
              "production_ready": False, "scope": "research_only" if not agent_python else "research_and_agentic_offline", "python": python,
              "preflight": {}, "pytest": None, "sdk": {"status": "not_checked"}}
    preflight = _preflight(python); result["preflight"] = preflight
    if not preflight["ok"]:
        result["status"] = "failed"; return _write(report, result), result
    test_cmd = [python, "-m", "pytest", "-q", "--noconftest", "--basetemp", str(Path(tempfile.gettempdir()) / f"research-verification-{uuid.uuid4().hex}"), *RESEARCH_TESTS]
    pytest_result = _run(test_cmd)
    result["pytest"] = pytest_result
    if pytest_result["timed_out"] or pytest_result["returncode"] != 0:
        result["status"] = "failed"; return _write(report, result), result
    if agent_python:
        sdk_probe = _run([agent_python, "-c", "from importlib.metadata import version; print(version('openai'))"], timeout=20)
        lines = sdk_probe["stdout"].splitlines()
        sdk_probe["ok"] = sdk_probe["returncode"] == 0 and lines == ["3.13.0"]
        result["sdk"]["preflight"] = sdk_probe
        if not sdk_probe["ok"]:
            result["sdk"]["status"] = "failed"; result["status"] = "failed"; return _write(report, result), result
        sdk_result = _run([agent_python, "-m", "unittest", "discover", "-s", "tests/integration", "-p", "test_research_agent_sdk.py"])
        result["sdk"]["run"] = sdk_result
        skipped = "skipped=" in (sdk_result["stdout"] + sdk_result["stderr"])
        match = re.search(r"Ran (\d+) tests?", sdk_result["stdout"] + sdk_result["stderr"])
        result["sdk"]["status"] = "passed" if sdk_result["returncode"] == 0 and not sdk_result["timed_out"] and not skipped and match and int(match.group(1)) >= 4 else "failed"
        if result["sdk"]["status"] != "passed":
            result["status"] = "failed"; return _write(report, result), result
    result["status"] = "passed"; return _write(report, result), result


def _write(path: Path, result: dict) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(result, handle, indent=2, sort_keys=True); handle.write("\n")
        os.replace(name, path)
    finally:
        if os.path.exists(name): os.unlink(name)
    return 0 if result.get("status") == "passed" else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--agent-python")
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args(argv)
    code, result = verify(python=args.python, agent_python=args.agent_python, report=args.report)
    print(json.dumps(result, indent=2, sort_keys=True)); return code


if __name__ == "__main__": raise SystemExit(main())
