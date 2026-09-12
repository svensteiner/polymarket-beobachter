import json
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
