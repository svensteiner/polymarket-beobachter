import json
import math
from pathlib import Path

import pytest

from analytics.agent_run_store import RunStore, RunStoreError, validate_key


def test_atomic_store_round_trip(tmp_path: Path):
    store = RunStore(tmp_path / "runs.json")
    key = "a" * 64
    store.save(key, {"state": "prepared", "input": "{}"})
    assert store.load(key)["state"] == "prepared"
    assert not (tmp_path / "runs.json.tmp").exists()


@pytest.mark.parametrize("key", ["", "x", "A" * 64, "a" * 63])
def test_key_validation(key):
    with pytest.raises(RunStoreError):
        validate_key(key)


def test_corrupt_store_fails_closed(tmp_path: Path):
    path = tmp_path / "runs.json"
    path.write_text("[]", encoding="utf-8")
    with pytest.raises(RunStoreError):
        RunStore(path).save("a" * 64, {})


@pytest.mark.parametrize("contents", ["not-json", "[]", json.dumps({"a" * 64: []})])
def test_corrupt_shapes_fail_closed(tmp_path: Path, contents: str):
    path = tmp_path / "runs.json"; path.write_text(contents, encoding="utf-8")
    with pytest.raises(RunStoreError):
        RunStore(path).load("a" * 64)


@pytest.mark.parametrize("contents", [
    '{"' + "a" * 64 + '": {"x": 1}, "' + "a" * 64 + '": {"x": 2}}',
    '{"' + "a" * 64 + '": {"x": NaN}}',
    '{"' + "a" * 64 + '": {"x": 1e999}}',
    '{"bad": {}}',
])
def test_strict_json_corruption_fails_closed(tmp_path: Path, contents: str):
    path = tmp_path / "runs.json"; path.write_text(contents, encoding="utf-8")
    with pytest.raises(RunStoreError): RunStore(path).load("a" * 64)


def test_oversize_and_nonfinite_save_preserve_store(tmp_path: Path):
    path = tmp_path / "runs.json"; store = RunStore(path); key = "a" * 64
    store.save(key, {"state": "old"}); before = path.read_bytes()
    with pytest.raises(RunStoreError): store.save("b" * 64, {"x": math.nan})
    assert path.read_bytes() == before
    with pytest.raises(RunStoreError): store.save("b" * 64, {"nested": {1: "bad"}})
    assert path.read_bytes() == before
    with pytest.raises(RunStoreError): store.save("b" * 64, {"x": "z" * 300000})
    assert path.read_bytes() == before


def test_replace_failure_cleans_temp_and_preserves_old(tmp_path: Path, monkeypatch):
    path = tmp_path / "runs.json"; store = RunStore(path); key = "a" * 64
    store.save(key, {"state": "old"}); before = path.read_bytes()
    def fail(*args): raise OSError("replace blocked")
    monkeypatch.setattr("analytics.agent_run_store.os.replace", fail)
    with pytest.raises(RunStoreError): store.save("b" * 64, {"state": "new"})
    assert path.read_bytes() == before
    assert not list(tmp_path.glob("runs.json.*.tmp"))


def test_fsync_failure_preserves_old(tmp_path: Path, monkeypatch):
    path = tmp_path / "runs.json"; store = RunStore(path); key = "a" * 64
    store.save(key, {"state": "old"}); before = path.read_bytes()
    monkeypatch.setattr("analytics.agent_run_store.os.fsync", lambda fd: (_ for _ in ()).throw(OSError("fsync blocked")))
    with pytest.raises(RunStoreError): store.save("b" * 64, {"state": "new"})
    assert path.read_bytes() == before
    assert not list(tmp_path.glob("runs.json.*.tmp"))


def test_recursive_and_invalid_unicode_records_preserve_old(tmp_path):
    store = RunStore(tmp_path / "runs.json")
    store.save("a" * 64, {"state": "old"})
    before = store.path.read_bytes()
    cycle = {}; cycle["self"] = cycle
    for record in (cycle, {"text": "\ud800"}):
        with pytest.raises(RunStoreError):
            store.save("b" * 64, record)
        assert store.path.read_bytes() == before
