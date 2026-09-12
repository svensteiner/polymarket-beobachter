"""Read-only struct-arb research loop; it never records trades or closes positions."""
from __future__ import annotations
import argparse
import json
import logging
import os
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

ROOT = Path(__file__).resolve().parent
STATUS_PATH = ROOT / "output" / "research_status.json"
HEARTBEAT_PATH = ROOT / "output" / "research_runner.heartbeat.json"
LOG_PATH = ROOT / "logs" / "research_runner.log"
LOCK_PATH = ROOT / "output" / "research_runner.lock"
MAX_LOG_BYTES = 2 * 1024 * 1024


class AlreadyRunningError(RuntimeError):
    pass

def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()

def _json_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)

def _logger() -> logging.Logger:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("research_runner")
    logger.setLevel(logging.INFO)
    if logger.handlers and getattr(logger.handlers[0], "baseFilename", "") != str(LOG_PATH):
        for handler in logger.handlers:
            handler.close()
        logger.handlers.clear()
    if not logger.handlers:
        from logging.handlers import RotatingFileHandler

        handler = RotatingFileHandler(
            LOG_PATH, maxBytes=MAX_LOG_BYTES, backupCount=1, encoding="utf-8"
        )
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(handler)
    return logger

@contextmanager
def single_instance(path: Path = LOCK_PATH) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+b")
    locked = False
    try:
        try:
            if os.name == "nt":
                import msvcrt
                handle.seek(0, os.SEEK_END)
                if handle.tell() == 0:
                    handle.write(b"0")
                handle.seek(0)
                handle.flush()
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            locked = True
        except ImportError:
            handle.close()
            marker = path.with_suffix(path.suffix + ".portable")
            try:
                fd = os.open(marker, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError as exc:
                raise AlreadyRunningError("research runner is already running") from exc
            try:
                yield
            finally:
                os.close(fd)
                marker.unlink(missing_ok=True)
            return
        except OSError as exc:
            handle.close()
            raise AlreadyRunningError("research runner is already running") from exc
        yield
    finally:
        if locked:
            try:
                if os.name == "nt":
                    import msvcrt
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            finally: handle.close()

def discover() -> dict[str, Any]:
    """Inspect struct-arb discovery only; never evaluate or execute a trade."""
    import paper_trader.struct_arb as struct_arb

    class RecordingClient:
        def __init__(self, client: Any) -> None:
            self.client = client
            self.errors: list[str] = []

        def __getattr__(self, name: str) -> Any:
            return getattr(self.client, name)

        def fetch_events(self, **kwargs: Any) -> Any:
            try:
                return self.client.fetch_events(**kwargs)
            except Exception as exc:
                self.errors.append(f"{type(exc).__name__}: {exc}")
                raise

    client = RecordingClient(struct_arb._make_client())
    events = struct_arb.fetch_open_events(client=client)
    if client.errors:
        raise RuntimeError(f"event discovery failed: {client.errors[-1]}")
    partitions = struct_arb._build_partitions(events)
    binaries = list(struct_arb._iter_binary_markets(events))
    return {
        "research_scope": "DISCOVERY INVENTORY",
        "events": len(events),
        "partitions": len(partitions),
        "binary_markets": len(binaries),
        "candidates": None,
        "execution_edge_evaluated": False,
        "scan_mode": "discovery_inspection",
        "max_events": struct_arb.MAX_EVENTS,
    }

def run_once() -> dict[str, Any]:
    logger = _logger()
    status: dict[str, Any] = {"status": "ok", "research_scope": "DISCOVERY INVENTORY", "scan_validity": "discovery_only", "started_at": _utc_now(), "finished_at": None, "research_only": True, "profit_proven": False, "live_orders": False, "ledger_mutations": False}
    try:
        status["scan"] = discover()
        from analytics.execution_scan import scan as scan_execution

        status["execution_scan"] = scan_execution()
        from analytics.implication_scan import scan as scan_implication

        # Both lanes are read-only research; implication health is propagated
        # while preserving the existing binary execution snapshot.
        status["implication_scan"] = scan_implication()
        status["research_scope"] = "BINARY EXECUTION + CONDITIONAL FDV IMPLICATION SNAPSHOT"
        status["scan_validity"] = status["execution_scan"].get("status", "ok")
        if status["scan_validity"] != "ok" or status["implication_scan"].get("status") != "ok":
            status["status"] = "scan_partial"
        logger.info("research scan complete: %s", status["scan"])
    except Exception as exc:
        status["status"] = "scan_failed"
        status["scan_validity"] = "failed"
        status["error"] = f"{type(exc).__name__}: {exc}"
        logger.exception("research scan failed")
    status["finished_at"] = _utc_now()
    _json_write(STATUS_PATH, status)
    _json_write(
        HEARTBEAT_PATH,
        {
            "name": "research_runner",
            "status": status["status"],
            "updated_at": status["finished_at"],
        },
    )
    return status

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only struct-arb research runner")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--interval", type=int, default=900)
    args = parser.parse_args(argv)
    if args.interval <= 0:
        parser.error("--interval must be positive")
    try:
        with single_instance():
            while True:
                status = run_once()
                if args.once:
                    return 0 if status["status"] == "ok" else 1
                time.sleep(args.interval)
    except AlreadyRunningError:
        return 2

if __name__ == "__main__":
    sys.exit(main())
