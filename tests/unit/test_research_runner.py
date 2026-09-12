import json
import research_runner as rr

def test_run_once_writes_research_status_without_trading(monkeypatch, tmp_path):
    monkeypatch.setattr(rr, "STATUS_PATH", tmp_path / "status.json")
    monkeypatch.setattr(rr, "HEARTBEAT_PATH", tmp_path / "heartbeat.json")
    monkeypatch.setattr(rr, "LOG_PATH", tmp_path / "runner.log")
    monkeypatch.setattr("analytics.execution_scan.scan", lambda: {"status": "ok", "results": []})
    monkeypatch.setattr("analytics.implication_scan.scan", lambda: {"status": "ok", "results": []})
    monkeypatch.setattr(rr, "discover", lambda: {"partitions": 3, "candidates": 1})
    status = rr.run_once()
    assert status["status"] == "ok" and status["research_only"] and not status["profit_proven"] and not status["live_orders"] and not status["ledger_mutations"]
    assert json.loads((tmp_path / "status.json").read_text())["scan"]["candidates"] == 1
    assert json.loads((tmp_path / "heartbeat.json").read_text())["name"] == "research_runner"

def test_run_once_reports_scan_failure(monkeypatch, tmp_path):
    monkeypatch.setattr(rr, "STATUS_PATH", tmp_path / "status.json")
    monkeypatch.setattr(rr, "HEARTBEAT_PATH", tmp_path / "heartbeat.json")
    monkeypatch.setattr(rr, "LOG_PATH", tmp_path / "runner.log")
    monkeypatch.setattr("analytics.execution_scan.scan", lambda: {"status": "ok", "results": []})
    monkeypatch.setattr("analytics.implication_scan.scan", lambda: {"status": "ok", "results": []})
    monkeypatch.setattr(rr, "discover", lambda: (_ for _ in ()).throw(RuntimeError("offline")))
    status = rr.run_once()
    assert status["status"] == "scan_failed" and "offline" in status["error"]
    assert json.loads((tmp_path / "heartbeat.json").read_text())["status"] == "scan_failed"

def test_discover_uses_read_only_fallback(monkeypatch):
    import paper_trader.struct_arb as struct_arb

    class Client:
        def fetch_events(self, **kwargs):
            return [{"id": 1}]

    monkeypatch.setattr(struct_arb, "_make_client", lambda: Client())
    monkeypatch.setattr(struct_arb, "_build_partitions", lambda events: {"p": {"members": []}})
    monkeypatch.setattr(struct_arb, "_iter_binary_markets", lambda events: iter([{"market_id": "m"}]))
    monkeypatch.setattr(struct_arb, "fetch_open_events", lambda client: [{"id": 1}])
    assert rr.discover() == {
        "research_scope": "DISCOVERY INVENTORY",
        "events": 1,
        "partitions": 1,
        "binary_markets": 1,
        "candidates": None,
        "execution_edge_evaluated": False,
        "scan_mode": "discovery_inspection",
        "max_events": struct_arb.MAX_EVENTS,
    }


def test_discover_reports_real_event_fetch_failure(monkeypatch):
    import paper_trader.struct_arb as struct_arb

    class Client:
        def fetch_events(self, **kwargs):
            raise OSError("network down")

    monkeypatch.setattr(struct_arb, "_make_client", lambda: Client())
    try:
        rr.discover()
    except RuntimeError as exc:
        assert "network down" in str(exc)
    else:
        raise AssertionError("discovery failure was swallowed")


def test_single_instance_rejects_contention(tmp_path):
    lock = tmp_path / "runner.lock"
    with rr.single_instance(lock):
        try:
            with rr.single_instance(lock):
                raise AssertionError("second instance acquired lock")
        except rr.AlreadyRunningError:
            pass
