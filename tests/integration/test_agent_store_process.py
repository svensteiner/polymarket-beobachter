"""Real OS-lock contention, abrupt-owner-exit recovery, and writer preservation."""
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]


def _reap(proc):
    if proc.poll() is None:
        proc.kill()
    proc.communicate(timeout=5)


def test_operation_lock_contention_and_recovery(tmp_path):
    store = tmp_path / "runs.json"
    ready, release = tmp_path / "ready", tmp_path / "release"
    hold = """
from analytics.agent_run_store import RunStore
from pathlib import Path
import os, sys, time
with RunStore(sys.argv[1]).operation():
    Path(sys.argv[2]).touch()
    deadline = time.monotonic() + 15
    while not Path(sys.argv[3]).exists():
        if time.monotonic() > deadline: os._exit(8)
        time.sleep(.02)
    os._exit(7)
"""
    probe = """
from analytics.agent_run_store import RunStore, RunStoreError
import sys
try:
    with RunStore(sys.argv[1]).operation(): pass
except RunStoreError:
    raise SystemExit(3)
"""
    proc = subprocess.Popen([sys.executable, "-c", hold, str(store), str(ready), str(release)],
                            cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        deadline = time.monotonic() + 5
        while not ready.exists() and proc.poll() is None and time.monotonic() < deadline:
            time.sleep(.02)
        assert ready.exists() and proc.poll() is None
        command = [sys.executable, "-c", probe, str(store)]
        assert subprocess.run(command, cwd=ROOT, capture_output=True, timeout=5).returncode == 3
        release.touch()
        assert proc.wait(timeout=5) == 7
        assert subprocess.run(command, cwd=ROOT, capture_output=True, timeout=5).returncode == 0
    finally:
        _reap(proc)


def test_concurrent_different_key_writers_preserve_both(tmp_path):
    store = tmp_path / "runs.json"
    code = """
from analytics.agent_run_store import RunStore, RunStoreError
import sys, time
store = RunStore(sys.argv[1])
for _ in range(40):
    try:
        store.save(sys.argv[2], {'state': sys.argv[2]})
        break
    except RunStoreError:
        time.sleep(.05)
else:
    raise SystemExit(4)
"""
    children = []
    try:
        for key in ("a" * 64, "b" * 64):
            children.append(subprocess.Popen([sys.executable, "-c", code, str(store), key],
                            cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE))
        for child in children:
            assert child.wait(timeout=5) == 0
    finally:
        for child in children:
            _reap(child)
    data = json.loads(store.read_text(encoding="utf-8"))
    assert data == {key: {"state": key} for key in ("a" * 64, "b" * 64)}
