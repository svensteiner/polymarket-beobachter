import json
import subprocess
import sys
from pathlib import Path

from analytics.agent_cost_report import report


def rec(cost="0.3", session="s1", **extra):
    value = {"state": "completed", "model": "gpt-5.6-luna", "session_id": session,
             "estimated_cost_usd": cost,
             "usage": {"input_tokens": 1, "output_tokens": 2, "total_tokens": 3}}
    value.update(extra); return value


def write(path, value): path.write_text(json.dumps(value), encoding="utf-8")


def test_exact_decimal_sum_and_pending_separation(tmp_path: Path):
    path = tmp_path / "store.json"
    write(path, {"a" * 64: rec("0.1"), "b" * 64: rec("0.2", "s2"), "c" * 64: {"state": "prepared"}})
    result = report(path)
    assert result["total_estimated_cost_usd"] == "0.3"
    assert result["state_counts"]["prepared"] == 1 and result["exit_code"] == 0


def test_invalid_completed_and_duplicate_sessions_are_incomplete(tmp_path: Path):
    path = tmp_path / "store.json"
    write(path, {"a" * 64: rec("NaN"), "b" * 64: rec("0.2"), "c" * 64: rec("0.2")})
    result = report(path)
    assert result["incomplete"] and result["exit_code"] == 3
    assert result["total_estimated_cost_usd"] is None
    assert result["partial_known_estimated_cost_usd"] == "0"


def test_invalid_records_and_store_shapes_fail_closed(tmp_path: Path):
    path = tmp_path / "store.json"
    write(path, {"bad": {}, "c" * 64: {"state": []}})
    result = report(path)
    assert result["state_counts"]["unknown"] == 2 and result["exit_code"] == 2
    write(path, [])
    assert report(path)["exit_code"] == 2
    path.write_text("{", encoding="utf-8")
    assert report(path)["store_state"] == "store_corrupt"


def test_missing_and_empty_are_distinct(tmp_path: Path):
    missing = report(tmp_path / "missing.json")
    assert missing["store_state"] == "missing_store" and missing["exit_code"] == 2
    empty = tmp_path / "empty.json"; write(empty, {})
    result = report(empty)
    assert result["store_state"] == "valid_empty" and result["exit_code"] == 0


def test_oversized_store_is_rejected(tmp_path: Path):
    path = tmp_path / "store.json"; path.write_bytes(b"x" * (256 * 1024 + 1))
    assert report(path)["store_state"] == "store_too_large"


def test_each_invalid_money_form_is_unaccounted(tmp_path: Path):
    path = tmp_path / "store.json"
    for value in (True, -1, "Infinity", "1e19", "9" * 19):
        write(path, {"a" * 64: rec(value)})
        result = report(path)
        assert result["exit_code"] == 3 and result["total_estimated_cost_usd"] is None


def test_pending_with_cost_and_prepared_with_session_are_incomplete(tmp_path: Path):
    path = tmp_path / "store.json"
    write(path, {"a" * 64: {"state": "in_progress", "estimated_cost_usd": "0.1"},
                 "b" * 64: {"state": "prepared", "session_id": "sess"}})
    result = report(path)
    assert result["exit_code"] == 3 and result["total_estimated_cost_usd"] is None


def test_prepared_with_only_session_id_is_incomplete(tmp_path: Path):
    path = tmp_path / "store.json"
    write(path, {"a" * 64: {"state": "prepared", "session_id": "sess"}})
    result = report(path)
    assert result["exit_code"] == 3 and result["total_estimated_cost_usd"] is None


def test_duplicate_session_group_includes_invalid_and_pending_records(tmp_path: Path):
    path = tmp_path / "store.json"
    write(path, {"a" * 64: rec("0.1", "same"),
                 "b" * 64: rec("NaN", "same"),
                 "c" * 64: {"state": "in_progress", "session_id": "same"}})
    result = report(path)
    assert result["exit_code"] == 3 and result["partial_known_estimated_cost_usd"] == "0"


def test_exact_large_and_fractional_decimal_sum(tmp_path: Path):
    path = tmp_path / "store.json"
    write(path, {"a" * 64: rec("999999999999999999", "s1"),
                 "b" * 64: rec("0.000000000000000001", "s2")})
    result = report(path)
    assert result["total_estimated_cost_usd"] == "999999999999999999.000000000000000001"


def test_duplicate_json_keys_are_corrupt(tmp_path: Path):
    path = tmp_path / "store.json"
    path.write_text('{"' + "a" * 64 + '": {}, "' + "a" * 64 + '": {}}', encoding="utf-8")
    assert report(path)["store_state"] == "store_corrupt"


def test_session_whitespace_uses_consistent_duplicate_identity(tmp_path: Path):
    path = tmp_path / "store.json"
    write(path, {"a" * 64: rec("0.3", " s1 ")})
    assert report(path)["total_estimated_cost_usd"] == "0.3"
    write(path, {"a" * 64: rec("0.3", " s1 "), "b" * 64: rec("0.3", "s1")})
    result = report(path)
    assert result["exit_code"] == 3
    assert result["partial_known_estimated_cost_usd"] == "0"


def test_cost_cli_runs_from_foreign_cwd(tmp_path: Path):
    path = tmp_path / "store.json"; write(path, {})
    command = [sys.executable, str(Path(__file__).parents[2] / "research_agent.py"), "--store", str(path), "costs"]
    result = subprocess.run(command, cwd=tmp_path, capture_output=True, text=True, check=False)
    assert result.returncode == 0 and json.loads(result.stdout)["authorization"] is False
