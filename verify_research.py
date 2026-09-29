"""Bounded, offline verification for the research-only package."""
from __future__ import annotations

import argparse
import json
import math
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import uuid
import re
from analytics.verification_manifest import ManifestError, collect_manifest

ROOT = Path(__file__).resolve().parent
DEFAULT_REPORT = ROOT / "output" / "research_verification.json"
MAX_OUTPUT = 12_000
TIMEOUT = 120
RESEARCH_TESTS = [
    "tests/unit/test_agent_cost_report.py", "tests/unit/test_agent_run_store.py",
    "tests/unit/test_agent_dispatch.py",
    "tests/unit/test_agent_admission.py",
    "tests/unit/test_agent_result_validation.py",
    "tests/unit/test_research_agent.py", "tests/unit/test_research_control.py",
    "tests/unit/test_research_coordinator.py", "tests/unit/test_research_health.py",
    "tests/unit/test_research_ownership.py", "tests/unit/test_research_runner.py",
    "tests/unit/test_research_supervisor.py", "tests/unit/test_research_verification.py",
    "tests/integration/test_agent_snapshot_cli.py", "tests/integration/test_research_control_process.py",
    "tests/integration/test_agent_store_process.py",
    "tests/integration/test_agent_admission_cli.py",
    "tests/integration/test_research_cycle_process.py",
    "tests/integration/test_agent_setup.py",
    "tests/integration/test_verification_check_cli.py",
    "tests/unit/test_verification_manifest.py",
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
              "schema_version": 2,
              "production_ready": False, "scope": "research_only" if not agent_python else "research_and_agentic_offline", "python": python,
              "preflight": {}, "pytest": None, "sdk": {"status": "not_checked"}, "source_stable": False}
    preflight = _preflight(python); result["preflight"] = preflight
    if not preflight["ok"]:
        return _finish(report, result, "failed"), result
    try:
        result["source_manifest"] = collect_manifest(ROOT)
    except ManifestError as exc:
        result["manifest_error"] = str(exc)
        return _finish(report, result, "failed"), result
    test_cmd = [python, "-m", "pytest", "-q", "--noconftest", "--basetemp", str(Path(tempfile.gettempdir()) / f"research-verification-{uuid.uuid4().hex}"), *RESEARCH_TESTS]
    pytest_result = _run(test_cmd)
    result["pytest"] = pytest_result
    if pytest_result["timed_out"] or pytest_result["returncode"] != 0:
        return _finish(report, result, "failed"), result
    if agent_python:
        sdk_probe = _run([agent_python, "-c", "from importlib.metadata import version; print(version('openai'))"], timeout=20)
        lines = sdk_probe["stdout"].splitlines()
        sdk_probe["ok"] = sdk_probe["returncode"] == 0 and lines == ["3.13.0"]
        result["sdk"]["preflight"] = sdk_probe
        if not sdk_probe["ok"]:
            result["sdk"]["status"] = "failed"; return _finish(report, result, "failed"), result
        sdk_result = _run([agent_python, "-m", "unittest", "discover", "-s", "tests/integration", "-p", "test_*sdk.py"])
        result["sdk"]["run"] = sdk_result
        skipped = "skipped=" in (sdk_result["stdout"] + sdk_result["stderr"])
        match = re.search(r"Ran (\d+) tests?", sdk_result["stdout"] + sdk_result["stderr"])
        result["sdk"]["status"] = "passed" if sdk_result["returncode"] == 0 and not sdk_result["timed_out"] and not skipped and match and int(match.group(1)) >= 12 else "failed"
        if result["sdk"]["status"] != "passed":
            return _finish(report, result, "failed"), result
    try:
        after_manifest = collect_manifest(ROOT)
    except ManifestError as exc:
        result["manifest_error"] = str(exc)
        return _finish(report, result, "failed"), result
    result["source_stable"] = after_manifest == result["source_manifest"]
    if not result["source_stable"]:
        result["source_manifest_after"] = after_manifest
        return _finish(report, result, "failed"), result
    return _finish(report, result, "passed"), result


def _finish(path: Path, result: dict, status: str) -> int:
    result["status"] = status
    result["completed_at"] = datetime.now(timezone.utc).isoformat()
    return _write(path, result)


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


MAX_REPORT_BYTES = 1 * 1024 * 1024
MAX_JSON_DEPTH = 32


def _strict_json(path: Path) -> dict:
    class Duplicate(ValueError): pass
    def pairs(items):
        out = {}
        for key, value in items:
            if key in out: raise Duplicate("duplicate JSON key")
            out[key] = value
        return out
    with path.open("rb") as handle:
        raw = handle.read(MAX_REPORT_BYTES + 1)
    if len(raw) > MAX_REPORT_BYTES:
        raise ValueError("report exceeds 1 MiB")
    def bad_constant(value): raise ValueError("non-finite JSON value")
    def finite_float(value):
        parsed = float(value)
        if not math.isfinite(parsed):
            raise ValueError("non-finite JSON number")
        return parsed
    value = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs,
                       parse_constant=bad_constant, parse_float=finite_float)
    def depth(item, level=0):
        if level > MAX_JSON_DEPTH: raise ValueError("JSON nesting too deep")
        if isinstance(item, dict):
            for child in item.values(): depth(child, level + 1)
        elif isinstance(item, list):
            for child in item: depth(child, level + 1)
    depth(value)
    if not isinstance(value, dict): raise ValueError("report must be an object")
    return value


def _aware(value: object) -> datetime:
    if not isinstance(value, str): raise ValueError("timestamp must be a string")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None: raise ValueError("timestamp must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def check_report(*, report: Path = DEFAULT_REPORT) -> tuple[int, dict]:
    """Offline validity check; never executes report-provided commands."""
    result = {"verification_current": False, "production_ready": False, "scope": "unknown"}
    try:
        data = _strict_json(report)
        scope = data.get("scope")
        result["scope"] = scope
        reasons = []
        if type(data.get("schema_version")) is not int or data.get("schema_version") != 2:
            reasons.append("unsupported schema_version")
        if data.get("status") != "passed": reasons.append("status is not passed")
        if data.get("source_stable") is not True: reasons.append("source_stable is false")
        preflight = data.get("preflight")
        if not isinstance(preflight, dict) or preflight.get("ok") is not True: reasons.append("preflight failed")
        pytest_result = data.get("pytest")
        if (not isinstance(pytest_result, dict)
                or type(pytest_result.get("returncode")) is not int
                or pytest_result.get("returncode") != 0
                or pytest_result.get("timed_out") is not False):
            reasons.append("pytest did not pass")
        if not isinstance(data.get("source_manifest"), dict): reasons.append("missing source_manifest")
        else:
            try:
                current = collect_manifest(ROOT)
                if data["source_manifest"] != current: reasons.append("source manifest is stale")
            except ManifestError as exc: reasons.append(f"current manifest unavailable: {exc}")
        try:
            generated = _aware(data.get("generated_at")); completed = _aware(data.get("completed_at")); now = datetime.now(timezone.utc)
            if generated > completed or completed > now + timedelta(seconds=5): reasons.append("timestamps are out of order or in the future")
            if now - completed > timedelta(hours=24): reasons.append("report is older than 24 hours")
        except ValueError as exc:
            reasons.append(f"invalid timestamps: {exc}")
        sdk = data.get("sdk")
        if scope == "research_only":
            if not isinstance(sdk, dict) or sdk.get("status") != "not_checked": reasons.append("research_only sdk status invalid")
        elif scope == "research_and_agentic_offline":
            run = sdk.get("run") if isinstance(sdk, dict) else None
            pre = sdk.get("preflight") if isinstance(sdk, dict) else None
            if (not isinstance(sdk, dict) or sdk.get("status") != "passed"
                    or not isinstance(run, dict)
                    or type(run.get("returncode")) is not int
                    or run.get("returncode") != 0
                    or run.get("timed_out") is not False
                    or not isinstance(pre, dict) or pre.get("ok") is not True):
                reasons.append("SDK verification invalid")
        else: reasons.append("unknown scope")
        result["reasons"] = reasons
        result["verification_current"] = not reasons
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError, RecursionError) as exc:
        result["reasons"] = [f"invalid report: {exc}"]
        result["error"] = str(exc)
    result["status"] = "passed" if result["verification_current"] else "failed"
    return (0 if result["verification_current"] else 1), result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--agent-python")
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    if args.check:
        code, result = check_report(report=args.report)
        print(json.dumps(result, indent=2, sort_keys=True)); return code
    code, result = verify(python=args.python, agent_python=args.agent_python, report=args.report)
    print(json.dumps(result, indent=2, sort_keys=True)); return code


if __name__ == "__main__": raise SystemExit(main())
