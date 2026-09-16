"""Start-handshake acceptance using an isolated real process and OS lock."""
import json
from pathlib import Path
import subprocess
import sys

import research_control as control


def test_real_process_handshake_and_duplicate_refusal(tmp_path: Path, monkeypatch):
    repository = control.ROOT
    script = tmp_path / "research_supervisor.py"
    status_path = tmp_path / "status.json"
    lock_path = tmp_path / "lock"
    stop_path = tmp_path / "stop"
    script.write_text(
        "import json, os, sys, time\n"
        f"sys.path.insert(0, {str(repository)!r})\n"
        "from pathlib import Path\n"
        "from research_supervisor import single_instance\n"
        f"with single_instance(Path({str(lock_path)!r})):\n"
        "    now=time.time()\n"
        "    state={'status':'healthy','supervisor_pid':os.getpid(),"
        "'run_id':'isolated-acceptance','updated_at':now,'next_due':now+60}\n"
        f"    Path({str(status_path)!r}).write_text(json.dumps(state), encoding='utf-8')\n"
        "    deadline=time.monotonic()+30\n"
        f"    while not Path({str(stop_path)!r}).exists() and time.monotonic()<deadline:\n"
        "        time.sleep(0.1)\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(control, "SUPERVISOR_PATH", script)
    monkeypatch.setattr(control, "ROOT", tmp_path)
    children = []

    def spawn(*args, **kwargs):
        child = subprocess.Popen(*args, **kwargs)
        children.append(child)
        return child

    try:
        first = control.start(status_path=status_path, lock_path=lock_path,
                              process_factory=spawn, wait_timeout=15)
        assert first["state"] == "started", first
        assert first["exit_code"] == 0
        second = control.start(status_path=status_path, lock_path=lock_path,
                               process_factory=spawn, wait_timeout=5)
        assert second["state"] == "already_running", second
        assert second["exit_code"] == 0
        assert len(children) == 1
        assert children[0].poll() is None
        assert json.loads(status_path.read_text())["run_id"] == "isolated-acceptance"
    finally:
        stop_path.touch()
        for child in children:
            child.wait(timeout=10)
