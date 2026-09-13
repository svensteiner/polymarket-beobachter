"""Exercise the installed Hosted Agents SDK against a local HTTP fixture only.

Run with .venv-agentic/Scripts/python.exe -m unittest discover
    -s tests/integration -p test_research_agent_sdk.py
"""
from importlib.metadata import PackageNotFoundError, version
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


ROOT = Path(__file__).resolve().parents[2]
KEY = "a" * 64
SESSION = "sess_local_fixture"
USAGE = {"input_tokens": 10, "output_tokens": 2, "total_tokens": 12}


def has_pinned_sdk():
    try:
        return version("openai") == "3.13.0"
    except PackageNotFoundError:
        return False


@unittest.skipUnless(has_pinned_sdk(), "run with .venv-agentic: pinned openai==3.13.0 required")
class AgentSDKAcceptance(unittest.TestCase):
    def test_cli_reconciles_with_only_three_gets(self):
        calls = []
        session_path = f"/v1/agents/sessions/{SESSION}"
        fixtures = {
            session_path: {"id": SESSION, "object": "agent.session", "status": "idle",
                           "usage": USAGE, "error": None},
            session_path + "/items": {
                "object": "list", "has_more": False,
                "data": [{"id": "msg_local", "type": "message", "role": "assistant",
                          "turn_id": "turn_local", "status": "completed",
                          "content": [{"type": "output_text", "text": "OK"}]}]},
            session_path + "/turns": {
                "object": "list", "has_more": False,
                "data": [{"id": "turn_local", "object": "agent.session.turn",
                          "agent_id": "agent_local", "session_id": SESSION,
                          "created_at": 1, "status": "completed", "error": None,
                          "usage": USAGE}]},
        }

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                path = self.path.split("?", 1)[0]
                calls.append(("GET", path))
                value = fixtures.get(path)
                body = json.dumps(value if value is not None else {"error": "unexpected path"}).encode()
                self.send_response(200 if value is not None else 404)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):
                calls.append(("POST", self.path))
                self.send_error(405)

            def log_message(self, *_args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as directory:
                store = Path(directory) / "runs.json"
                store.write_text(json.dumps({KEY: {"state": "session_created",
                    "session_id": SESSION, "agent_id": "agent_local"}}), encoding="utf-8")
                environment = os.environ.copy()
                environment.update(OPENAI_API_KEY="local-fixture-only",
                    OPENAI_BASE_URL=f"http://127.0.0.1:{server.server_port}/v1",
                    NO_PROXY="127.0.0.1,localhost", no_proxy="127.0.0.1,localhost")
                for name in ("OPENAI_ORG_ID", "OPENAI_PROJECT_ID", "OPENAI_ADMIN_KEY"):
                    environment.pop(name, None)
                completed = subprocess.run([sys.executable, str(ROOT / "research_agent.py"),
                    "--store", str(store), "reconcile", "--run-key", KEY, "--timeout", "5"],
                    cwd=directory, env=environment, capture_output=True, text=True, timeout=25)
                self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
                result = json.loads(completed.stdout)
                self.assertEqual(result["state"], "completed")
                saved = json.loads(store.read_text(encoding="utf-8"))[KEY]
                self.assertEqual(saved["state"], "completed")
                self.assertEqual(saved["usage"], USAGE)
                self.assertEqual(saved["messages"][0]["text"], "OK")
                self.assertEqual(calls, [("GET", path) for path in fixtures])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
