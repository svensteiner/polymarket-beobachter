"""Exercise dispatch_once with the pinned OpenAI SDK against a local fixture."""
from importlib.metadata import PackageNotFoundError, version
import json
from pathlib import Path
import tempfile
import threading
import unittest
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


KEY = "a" * 64
MODEL = "gpt-5.6-luna"


def has_pinned_sdk():
    try:
        return version("openai") == "3.13.0"
    except PackageNotFoundError:
        return False


@unittest.skipUnless(has_pinned_sdk(), "run with .venv-agentic: pinned openai==3.13.0 required")
class AgentDispatchSDKAcceptance(unittest.TestCase):
    def test_happy_path_creates_agent_and_session(self):
        self._exercise("happy")

    def test_agent_error_is_uncertain_and_not_retried(self):
        self._exercise("agent500")

    def test_session_error_is_uncertain_and_not_retried(self):
        self._exercise("session500")

    def test_wrong_session_agent_is_uncertain_and_not_retried(self):
        self._exercise("sessionwrongagent")

    def _exercise(self, scenario):
        from analytics.research_coordinator import CoordinatorError, RunStore, prepare
        from tests.dispatch_harness import dispatch_once

        calls = []
        factory_calls = []

        class Handler(BaseHTTPRequestHandler):
            def _json(self, status, payload):
                body = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):
                length = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(length)
                calls.append((self.path, json.loads(raw.decode()) if raw else {}))
                if self.path == "/v1/agents":
                    if scenario == "agent500":
                        self._json(500, {"error": {"message": "agent unavailable"}})
                    else:
                        self._json(200, {"id": "agent_local", "object": "agent"})
                    return
                if self.path == "/v1/agents/sessions":
                    if scenario == "session500":
                        self._json(500, {"error": {"message": "session unavailable"}})
                    else:
                        agent_id = "agent_wrong" if scenario == "sessionwrongagent" else "agent_local"
                        self._json(200, {"id": "sess_local", "object": "agent.session",
                                         "agent": {"id": agent_id}, "status": "queued"})
                    return
                self._json(404, {"error": {"message": "unexpected path"}})

            def log_message(self, *_args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as directory:
                status_path = Path(directory) / "status.json"
                store_path = Path(directory) / "runs.json"
                now = datetime.now(timezone.utc)
                status = {
                    "status": "ok", "started_at": now.isoformat(), "finished_at": now.isoformat(),
                    "research_only": True, "live_orders": False, "ledger_mutations": False,
                    "scan": {"events": 1, "partitions": 1, "binary_markets": 2},
                    "execution_scan": {"candidate_count": 0, "valid_evaluations": 1},
                }
                status_path.write_text(json.dumps(status), encoding="utf-8")
                plan = prepare(MODEL, status_path, live_enabled=True,
                               acknowledge_no_hard_session_cost_cap=True,
                               admission_budget=1, now=now)
                created = []

                def factory(**kwargs):
                    import httpx2 as httpx
                    from openai import OpenAI
                    self.assertEqual(kwargs, {"timeout": 30, "max_retries": 0})
                    factory_calls.append(kwargs)
                    transport = httpx.Client(trust_env=False)
                    client = OpenAI(api_key=KEY,
                                    base_url=f"http://127.0.0.1:{server.server_port}/v1",
                                    http_client=transport, **kwargs)
                    created.append(client)
                    return client

                store = RunStore(store_path)
                if scenario == "happy":
                    result = dispatch_once(store, factory, plan)
                    self.assertEqual(result["state"], "session_created")
                    self.assertEqual(result["agent_id"], "agent_local")
                    self.assertEqual(result["session_id"], "sess_local")
                    self.assertEqual(len(calls), 2)
                    self.assertEqual(calls[0][0], "/v1/agents")
                    self.assertEqual(calls[1][0], "/v1/agents/sessions")
                    self.assertEqual(calls[0][1], plan["agent"])
                    self.assertEqual(calls[1][1]["agent_id"], "agent_local")
                    for field in ("environment", "input", "stream"):
                        self.assertEqual(calls[1][1][field], plan["session"][field])
                    with self.assertRaises(CoordinatorError):
                        dispatch_once(store, factory, plan)
                    self.assertEqual(len(calls), 2)
                    self.assertEqual(len(factory_calls), 1)
                else:
                    with self.assertRaises(CoordinatorError):
                        dispatch_once(store, factory, plan)
                    self.assertEqual(len(calls), 1 if scenario == "agent500" else 2)
                    self.assertEqual(len(factory_calls), 1)
                    with self.assertRaises(CoordinatorError):
                        dispatch_once(store, factory, plan)
                    self.assertEqual(len(calls), 1 if scenario == "agent500" else 2)

                saved = json.loads(store_path.read_text(encoding="utf-8"))[plan["run_key"]]
                if scenario == "happy":
                    self.assertEqual(saved["state"], "session_created")
                else:
                    self.assertEqual(saved["state"], "uncertain")
                self.assertEqual(len(created), 1)
                self.assertTrue(created[0].is_closed)
        finally:
            for client in created if "created" in locals() else ():
                if not client.is_closed:
                    client.close()
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
