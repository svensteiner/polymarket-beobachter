import json
import io
import os
import sys

import verify_research as verifier


def result(stdout="", returncode=0, timed_out=False):
    return {"returncode": returncode, "stdout": stdout, "stderr": "", "timed_out": timed_out}


def test_preflight_failure_skips_tests(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(verifier, "_run", lambda command, **kw: calls.append(command) or result("bad", 1))
    code, report = verifier.verify(python="fake", report=tmp_path / "r.json")
    assert code == 1 and report["status"] == "failed" and len(calls) == 1


def test_pytest_failure_and_timeout_fail_closed(tmp_path, monkeypatch):
    for second in (result("F", 1), result(timed_out=True, returncode=None)):
        calls = iter([result("3.12.8\n9.0.2\n"), second])
        monkeypatch.setattr(verifier, "_run", lambda command, **kw: next(calls))
        code, report = verifier.verify(python="fake", report=tmp_path / "r.json")
        assert code == 1 and report["status"] == "failed"


def test_sdk_omitted_is_explicitly_unchecked(tmp_path, monkeypatch):
    calls = iter([result("3.12.8\n9.0.2\n"), result("1 passed")])
    monkeypatch.setattr(verifier, "_run", lambda command, **kw: next(calls))
    code, report = verifier.verify(python="fake", report=tmp_path / "r.json")
    assert code == 0 and report["sdk"]["status"] == "not_checked"


def test_wrong_sdk_version_is_not_run(tmp_path, monkeypatch):
    calls = []
    def fake(command, **kw):
        calls.append(command)
        return result("3.12.8\n9.0.2\n") if len(calls) == 1 else (result("1 passed") if "pytest" in command else result("3.12.0\n"))
    monkeypatch.setattr(verifier, "_run", fake)
    code, report = verifier.verify(python="fake", agent_python="agent", report=tmp_path / "r.json")
    assert code == 1 and report["sdk"]["status"] == "failed" and len(calls) == 3


def test_success_is_bounded_and_atomic(tmp_path, monkeypatch):
    calls = []
    def fake(command, **kw):
        calls.append((command, kw))
        return result("3.12.8\n9.0.2\n") if len(calls) == 1 else result("1 passed")
    monkeypatch.setattr(verifier, "_run", fake)
    path = tmp_path / "nested" / "report.json"
    code, report = verifier.verify(python="fake", report=path)
    assert code == 0 and json.loads(path.read_text())["status"] == "passed"
    assert "--noconftest" in calls[1][0] and "tests/unit/test_research_agent.py" in calls[1][0]


def test_low_level_run_bounds_output_and_removes_credentials():
    old = os.environ.get("OPENAI_API_KEY")
    os.environ["OPENAI_API_KEY"] = "secret"
    try:
        out = verifier._run([sys.executable, "-c", "import os; print(os.getenv('OPENAI_API_KEY','')); print('x'*20000)"])
    finally:
        if old is None: os.environ.pop("OPENAI_API_KEY", None)
        else: os.environ["OPENAI_API_KEY"] = old
    assert out["returncode"] == 0 and "secret" not in out["stdout"]
    assert len(out["stdout"]) <= verifier.MAX_OUTPUT and out["output_truncated"]


def test_low_level_run_handles_timeout_and_missing_interpreter():
    timed = verifier._run([sys.executable, "-c", "import time; time.sleep(2)"], timeout=0.1)
    missing = verifier._run(["definitely-missing-research-python"], timeout=1)
    assert timed["timed_out"] and missing["returncode"] is None and not missing["timed_out"]


def test_sdk_zero_or_skipped_tests_do_not_pass(tmp_path, monkeypatch):
    for sdk_output in ("Ran 0 tests\nOK\n", "OK (skipped=1)\n"):
        calls = []
        def fake(command, **kw):
            calls.append(command)
            if len(calls) == 1: return result("3.12.8\n9.0.2\n")
            if len(calls) == 2: return result("121 passed\n")
            return result(sdk_output)
        monkeypatch.setattr(verifier, "_run", fake)
        code, report = verifier.verify(python="fake", agent_python="agent", report=tmp_path / (str(len(calls)) + ".json"))
        assert code == 1 and report["sdk"]["status"] == "failed"


def test_allowlist_contains_control_process_and_ownership():
    assert "tests/integration/test_research_control_process.py" in verifier.RESEARCH_TESTS
    assert "tests/unit/test_research_ownership.py" in verifier.RESEARCH_TESTS


def test_output_reader_bounds_the_file_read(monkeypatch):
    class BoundedReader(io.BytesIO):
        def read(self, size=-1):
            assert size == verifier.MAX_OUTPUT + 1
            return super().read(size)

    monkeypatch.setattr(verifier.Path, "open", lambda self, mode: BoundedReader(b"x" * 20000))
    output, truncated = verifier._read_output("unused")
    assert len(output) == verifier.MAX_OUTPUT and truncated
