#!/usr/bin/env python3
# =============================================================================
# WEATHER OBSERVER - COCKPIT
# =============================================================================
#
# OBSERVER-ONLY ENTRY POINT
#
# No trading, no execution, no positions.
# Weather market observation and calibration only.
#
# Usage:
#   python cockpit.py                    # Interactive menu
#   python cockpit.py --run-once         # Run pipeline once, exit
#   python cockpit.py --status           # Show status only
#   python cockpit.py --scheduler        # Run every 15 minutes
#
# =============================================================================

import sys
import os
import atexit
import argparse
import json
import logging
import time
import traceback
from pathlib import Path
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent
sys.path.insert(0, str(BASE_DIR))

# Load .env early so all modules see environment variables
try:
    from dotenv import load_dotenv
    load_dotenv(BASE_DIR / ".env", override=False)
except ImportError:
    pass

# Initialize optimized logging and memory management
try:
    from shared.memory_optimizer import start_memory_monitoring, stop_memory_monitoring
    from shared.log_manager import shutdown_log_manager

    # Auto-cleanup on exit
    atexit.register(stop_memory_monitoring)
    atexit.register(shutdown_log_manager)
except ImportError:
    # Graceful fallback if optimization modules unavailable
    def start_memory_monitoring(): pass
    def stop_memory_monitoring(): pass
    def shutdown_log_manager(): pass

LOCKFILE = BASE_DIR / "cockpit.lock"
CRASH_LOG = BASE_DIR / "logs" / "crash.log"
BOT_STATUS_FILE = BASE_DIR / "logs" / "bot_status.json"
BOT_CONTROL_FILE = BASE_DIR / "logs" / "bot_control.json"
HEARTBEAT_TXT = BASE_DIR / "logs" / "heartbeat.txt"


def _write_heartbeat_txt():
    """Write plain-text heartbeat for watchdog.ps1 compatibility.

    BUGFIX: The watchdog checks logs/heartbeat.txt (plain ISO timestamp),
    but the scheduler only wrote logs/heartbeat.json. This caused the
    watchdog to always find a stale heartbeat and kill the bot every
    5 minutes, creating the 'stirbt staendig' pattern.
    """
    try:
        HEARTBEAT_TXT.parent.mkdir(parents=True, exist_ok=True)
        HEARTBEAT_TXT.write_text(datetime.now().isoformat(), encoding="utf-8")
    except Exception:
        pass  # Non-critical - don't crash the bot for a heartbeat

# Heartbeat-JSON fuer Dashboard (kompatibel mit aktienbot-Format)
try:
    from shared.heartbeat import write_heartbeat as _write_heartbeat_json
except Exception:
    # Graceful fallback falls shared.heartbeat nicht importierbar
    def _write_heartbeat_json(status="running", detail="", extra=None):  # type: ignore[misc]
        pass


# =============================================================================
# BOT CONTROL (MCP Integration)
# =============================================================================

def check_bot_paused() -> tuple[bool, str]:
    """Check if bot is paused via MCP control.

    Returns:
        Tuple of (is_paused, reason)
    """
    if not BOT_CONTROL_FILE.exists():
        return False, ""

    try:
        control = json.loads(BOT_CONTROL_FILE.read_text(encoding="utf-8"))
        if control.get("paused", False):
            reason = control.get("reason", "No reason provided")
            paused_at = control.get("paused_at", "Unknown")
            paused_by = control.get("paused_by", "Unknown")
            return True, f"Paused at {paused_at} by {paused_by}: {reason}"
        return False, ""
    except Exception as e:
        logger.warning("Fehler beim Lesen von bot_control.json: %s", e)
        return False, ""


# =============================================================================
# ABSTURZSICHERHEIT
# =============================================================================

def _pid_alive(pid: int) -> bool:
    """Check if a process with given PID is still running (Windows-compatible)."""
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False
        try:
            exit_code = ctypes.c_ulong(0)
            if kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return exit_code.value == STILL_ACTIVE
            return False
        finally:
            kernel32.CloseHandle(handle)
    except Exception:
        # Fallback: os.kill with signal 0 (works on Unix, raises on Windows if no process)
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False


def acquire_lock():
    """Prevent duplicate bot instances via atomic PID lockfile.

    Uses os.open(O_CREAT | O_EXCL) to avoid TOCTOU race conditions
    between checking existence and writing the lockfile.
    Returns True if lock acquired, False otherwise.
    """
    try:
        # First check if a stale lockfile exists
        if LOCKFILE.exists():
            try:
                old_pid = int(LOCKFILE.read_text().strip())
                if old_pid == os.getpid():
                    return True  # Same process, re-entry is fine
                if _pid_alive(old_pid):
                    print(f"Bot laeuft bereits! (PID {old_pid})")
                    sys.exit(1)
                # Stale lockfile from dead process - remove it
                LOCKFILE.unlink()
            except (ValueError, OSError) as e:
                logger.warning("Fehler beim Lesen des Lockfile: %s", e)
                LOCKFILE.unlink(missing_ok=True)

        # Atomic create: O_CREAT | O_EXCL fails if file already exists
        fd = os.open(str(LOCKFILE), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        atexit.register(release_lock)
        return True
    except FileExistsError:
        # Race condition: another process created the lockfile between
        # our unlink and os.open - that process wins
        print("Bot laeuft bereits! (Race condition beim Lock)")
        sys.exit(1)
    except Exception as e:
        logger.warning("Fehler beim Lock-Erwerb: %s", e)
        return False


def release_lock():
    """Remove lockfile on exit."""
    try:
        if LOCKFILE.exists():
            stored_pid = int(LOCKFILE.read_text().strip())
            if stored_pid == os.getpid():
                LOCKFILE.unlink(missing_ok=True)
    except Exception as e:
        logger.warning("Fehler beim Lockfile entfernen: %s", e)
        LOCKFILE.unlink(missing_ok=True)


def _rotate_crash_log():
    """Rotate crash.log if it exceeds 1 MB."""
    if CRASH_LOG.exists() and CRASH_LOG.stat().st_size > 1_000_000:  # 1 MB
        rotated = CRASH_LOG.with_suffix(f".{datetime.now().strftime('%Y%m%d')}.log")
        CRASH_LOG.rename(rotated)


def setup_crash_logger():
    """Install global exception hook that logs crashes to crash.log."""
    def log_crash(exc_type, exc_value, exc_tb):
        try:
            CRASH_LOG.parent.mkdir(parents=True, exist_ok=True)
            _rotate_crash_log()
            with open(CRASH_LOG, "a", encoding="utf-8") as f:
                f.write(f"\n{'='*60}\n")
                f.write(f"CRASH: {datetime.now().isoformat()}\n")
                f.write(f"PID: {os.getpid()}\n")
                traceback.print_exception(exc_type, exc_value, exc_tb, file=f)
        except Exception as e:
            logger.warning("Fehler beim Crash-Log schreiben: %s", e)
        # Still call default handler for console output
        sys.__excepthook__(exc_type, exc_value, exc_tb)
    sys.excepthook = log_crash


def _parse_last_crash() -> dict | None:
    """Parse last crash entry from crash.log (reads only last 10 KB)."""
    if not CRASH_LOG.exists():
        return None
    try:
        with open(CRASH_LOG, "rb") as f:
            f.seek(0, 2)  # Ende
            size = f.tell()
            f.seek(max(0, size - 10000))  # Letzte 10 KB
            content = f.read().decode("utf-8", errors="replace")
        blocks = content.split("=" * 60)
        for block in reversed(blocks):
            block = block.strip()
            if not block:
                continue
            lines = block.splitlines()
            ts = None
            error_lines = []
            for line in lines:
                if line.startswith(("CRASH:", "PIPELINE ERROR:", "FATAL:")):
                    ts = line.split(":", 1)[1].strip() if ":" in line else None
                elif not line.startswith(("PID:", "Consecutive:")):
                    error_lines.append(line)
            if ts:
                return {
                    "timestamp": ts,
                    "error": " ".join(error_lines[:3]).strip()[:200],
                }
    except Exception as e:
        logger.warning("Fehler beim Parsen des letzten Crashes: %s", e)
    return None


def write_bot_status(
    run_count: int,
    consecutive_errors: int,
    start_time: datetime,
    result=None,
    error: Exception | None = None,
):
    """Write machine-readable bot status JSON after each pipeline run."""
    try:
        now = datetime.now()

        # Build last_run block
        if result is not None:
            state = result.state.value  # OK / DEGRADED / FAIL
            summary = result.summary
            failed = [s.name for s in result.steps if not s.success]
            last_run = {
                "state": state,
                "duration_seconds": summary.get("duration_seconds", 0),
                "markets_fetched": summary.get("markets_fetched", 0),
                "edge_observations": summary.get("edge_observations", 0),
                "paper_positions_entered": summary.get("paper_positions_entered", 0),
                "bot_health_status": summary.get("bot_health_status", "UNKNOWN"),
                "bot_health_guardrails_active": summary.get("bot_health_guardrails_active", False),
                "failed_steps": failed,
            }
        elif error is not None:
            last_run = {
                "state": "FAIL",
                "duration_seconds": 0,
                "markets_fetched": 0,
                "edge_observations": 0,
                "paper_positions_entered": 0,
                "failed_steps": [str(error)[:200]],
            }
        else:
            last_run = None

        # Extract run_id from result summary if available
        run_id = None
        if result is not None and hasattr(result, 'summary'):
            run_id = result.summary.get("run_id")

        status = {
            "schema_version": 1,
            "timestamp": now.isoformat(),
            "pid": os.getpid(),
            "uptime_seconds": round((now - start_time).total_seconds(), 1),
            "started_at": start_time.isoformat(),
            "run_count": run_count,
            "consecutive_errors": consecutive_errors,
            "run_id": run_id,
            "last_run": last_run,
            "last_crash": _parse_last_crash(),
        }

        # Atomic write via .tmp + rename
        BOT_STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = BOT_STATUS_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(status, indent=2), encoding="utf-8")
        tmp.replace(BOT_STATUS_FILE)
    except Exception as e:
        logger.warning("Fehler beim Bot-Status schreiben: %s", e)


# =============================================================================
# TERMINAL COLORS
# =============================================================================

class C:
    """Terminal colors."""
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    CYAN = "\033[96m"
    BLUE = "\033[94m"

    @classmethod
    def disable(cls):
        for attr in dir(cls):
            if attr.isupper() and not attr.startswith('_'):
                setattr(cls, attr, "")


# Windows compatibility
if sys.platform == "win32":
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
    except Exception as e:
        logger.warning("Fehler beim Setzen des Windows-Konsolenmodus: %s", e)
        C.disable()


# =============================================================================
# OUTPUT HELPERS
# =============================================================================

def clear():
    """Clear screen."""
    print("\033[2J\033[H", end="", flush=True)


def print_header():
    """Print header."""
    print(f"\n{C.BOLD}{C.CYAN}{'='*50}{C.RESET}")
    print(f"{C.BOLD}{C.CYAN}   WEATHER OBSERVER{C.RESET}")
    print(f"{C.DIM}   Observer-only weather market analysis{C.RESET}")
    print(f"{C.BOLD}{C.CYAN}{'='*50}{C.RESET}")
    print(f"{C.DIM}   {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}{C.RESET}")
    print()


def print_step(name: str, description: str):
    """Print step start."""
    print(f"{C.CYAN}[...]{C.RESET} {C.BOLD}{description}{C.RESET}", end="", flush=True)


def print_result(success: bool, message: str):
    """Print step result."""
    status = f"{C.GREEN}OK{C.RESET}" if success else f"{C.RED}FAIL{C.RESET}"
    print(f" ... {status}")
    if message:
        print(f"      {C.DIM}{message}{C.RESET}")


def print_run_result(result):
    """Print pipeline run result."""
    state = result.state.value
    summary = result.summary

    if state == "OK":
        print(f"\n{C.GREEN}{C.BOLD}  OBSERVER RUN COMPLETE: OK  {C.RESET}")
    elif state == "DEGRADED":
        print(f"\n{C.YELLOW}{C.BOLD}  OBSERVER RUN COMPLETE: DEGRADED  {C.RESET}")
    else:
        print(f"\n{C.RED}{C.BOLD}  OBSERVER RUN COMPLETE: FAIL  {C.RESET}")

    print(f"\n{C.BOLD}Summary:{C.RESET}")
    print(f"  Markets fetched:      {summary.get('markets_fetched', 0)}")
    print(f"  Weather candidates:   {summary.get('weather_candidates', 0)}")
    print(f"  Observations:         {summary.get('observations_total', 0)}")
    print(f"  Edge detected:        {C.GREEN}{summary.get('edge_observations', 0)}{C.RESET}")
    print(f"  Resolutions updated:  {summary.get('resolutions_updated', 0)}")

    errors = [s for s in result.steps if not s.success]
    if errors:
        print(f"\n{C.YELLOW}Warnings:{C.RESET}")
        for e in errors:
            print(f"  {C.YELLOW}!{C.RESET} {e.name}: {e.error[:50] if e.error else 'Failed'}")

    print()


def print_status(status: dict):
    """Print status."""
    print(f"\n{C.BOLD}Status:{C.RESET}")
    print(f"  Last run:   {status.get('last_run', 'Never')}")
    print(f"  State:      {status.get('last_state', 'UNKNOWN')}")
    print(f"  Logs:       {status.get('logs_path', 'N/A')}")
    print()


# =============================================================================
# MAIN FUNCTIONS
# =============================================================================

def run_pipeline_with_progress():
    """Run pipeline with progress output."""
    from app.orchestrator import get_orchestrator

    orchestrator = get_orchestrator()

    print(f"{C.BOLD}Observer Pipeline{C.RESET}")
    print(f"{C.DIM}{'-' * 40}{C.RESET}\n")

    # Run the full pipeline
    result = orchestrator.run_pipeline()

    return result


def _check_live_trading_readiness() -> None:
    """Warn if LIVE_TRADING_ENABLED=true but credentials are missing."""
    import os
    if os.getenv("LIVE_TRADING_ENABLED", "false").lower() != "true":
        return
    try:
        from trading.polymarket_client import validate_live_trading_env
        ok, missing = validate_live_trading_env()
        if not ok:
            print("\n*** LIVE TRADING WARNING ***")
            print("LIVE_TRADING_ENABLED=true but missing environment variables:")
            for var in missing:
                print(f"  - {var}")
            print("Live trades will NOT execute until these are configured.\n")
        else:
            print("\n[LIVE TRADING ACTIVE] All credentials verified.\n")
    except Exception:
        pass


def run_once() -> int:
    """Run pipeline once and return exit code.

    NOTE: --run-once intentionally does NOT check the pause flag.
    The pause flag is designed to stop long-running daemon processes
    (--scheduler) that may be running stale code. Each --run-once
    invocation loads fresh code from disk, so the stale-code concern
    does not apply. Pausing the bot stops the daemon, not one-shot runs.
    """
    print_header()
    _check_live_trading_readiness()
    start_time = datetime.now()
    _write_heartbeat_txt()

    try:
        result = run_pipeline_with_progress()
        print_run_result(result)
        write_bot_status(1, 0, start_time, result=result)

        # JSON-Heartbeat fuer Dashboard schreiben
        _write_heartbeat_json(
            status="idle",
            detail=f"run_once abgeschlossen: {result.state.value}",
            extra={
                "run_count": 1,
                "consecutive_errors": 0,
                "markets_fetched": result.summary.get("markets_fetched", 0),
                "edge_observations": result.summary.get("edge_observations", 0),
            },
        )

        if result.state.value == "OK":
            return 0
        elif result.state.value == "DEGRADED":
            return 2
        else:
            return 1

    except Exception as e:
        print(f"{C.RED}Pipeline failed: {e}{C.RESET}")
        write_bot_status(1, 1, start_time, error=e)
        # Heartbeat auch bei Fehler schreiben
        _write_heartbeat_json(status="error", detail=str(e)[:200], extra={"consecutive_errors": 1})
        return 1


def _snapshot_code_mtimes() -> dict:
    """Record modification times for key strategy modules."""
    watched = [
        "paper_trader/simulator.py",
        "paper_trader/position_manager.py",
        "paper_trader/entry_guardrails.py",
        "paper_trader/capital_manager.py",
        "app/orchestrator.py",
    ]
    mtimes = {}
    for rel in watched:
        p = BASE_DIR / rel
        try:
            mtimes[rel] = p.stat().st_mtime
        except OSError:
            pass
    return mtimes


def _code_changed(baseline: dict) -> str:
    """Return path of first changed file, or '' if nothing changed."""
    for rel, old_mtime in baseline.items():
        try:
            new_mtime = (BASE_DIR / rel).stat().st_mtime
            if new_mtime != old_mtime:
                return rel
        except OSError:
            pass
    return ""


def run_scheduler(interval_seconds: int = 900, enable_self_improve: bool = False) -> int:
    """Run pipeline on a schedule with crash resilience and resource optimization."""
    run_count = 0
    consecutive_errors = 0
    start_time = datetime.now()
    # Track file mtimes at startup to detect code changes.
    # Python caches imports — if strategy files change, exit cleanly so the
    # process can be restarted fresh and pick up the new code.
    code_baseline = _snapshot_code_mtimes()

    print_header()
    print(f"{C.BOLD}Scheduler Mode{C.RESET}")
    print(f"  Interval: {interval_seconds // 60} minutes")
    print(f"  Started:  {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  PID:      {os.getpid()}")
    print(f"\n{C.DIM}Press Ctrl+C to stop{C.RESET}\n")

    # Start resource monitoring
    start_memory_monitoring()

    _write_heartbeat_json(status="running", detail="Scheduler gestartet", extra={"run_count": 0})
    _write_heartbeat_txt()

    try:
        while True:
            run_count += 1
            run_start = datetime.now()

            print(f"\n{C.BOLD}{C.CYAN}{'='*50}{C.RESET}")
            print(f"{C.BOLD}Run #{run_count}{C.RESET} - {run_start.strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"{C.BOLD}{C.CYAN}{'='*50}{C.RESET}\n")

            # Code-change detector: exit cleanly so the process restarts with
            # fresh imports. Python caches modules in sys.modules; new strategy
            # logic (guardrails, filters) won't take effect until the process
            # restarts. Exit code 3 signals "restart requested".
            changed = _code_changed(code_baseline)
            if changed:
                print(f"\n{C.YELLOW}Code change detected: {changed} — exiting for restart{C.RESET}")
                logger.info("Code change detected in %s — exiting scheduler for restart (code 3)", changed)
                _write_heartbeat_json(
                    status="restart",
                    detail=f"Code change in {changed} — restart required",
                    extra={"run_count": run_count, "changed_file": changed},
                )
                return 3

            # Check if bot is paused via MCP
            is_paused, pause_reason = check_bot_paused()
            if is_paused:
                print(f"{C.YELLOW}Bot is PAUSED - skipping run{C.RESET}")
                print(f"  {C.DIM}{pause_reason}{C.RESET}")
                _write_heartbeat_json(
                    status="paused",
                    detail=pause_reason[:150],
                    extra={"run_count": run_count, "paused": True},
                )
                _write_heartbeat_txt()
                # Still wait for next interval
                next_run = datetime.now() + timedelta(seconds=interval_seconds)
                print(f"\n{C.DIM}Next check: {next_run.strftime('%H:%M:%S')}{C.RESET}")
                time.sleep(interval_seconds)
                continue

            try:
                result = run_pipeline_with_progress()
                print_run_result(result)
                consecutive_errors = 0
                write_bot_status(run_count, consecutive_errors, start_time, result=result)
                # Goal Engine: Ziele prüfen + ggf. eskalieren (cooldown: 6h)
                try:
                    from shared.goal_engine import get_goal_engine
                    get_goal_engine().run()
                except Exception as _ge:
                    logger.debug("Goal Engine fehlgeschlagen (unkritisch): %s", _ge)
                # JSON-Heartbeat nach erfolgreichem Run schreiben
                _write_heartbeat_json(
                    status="running",
                    detail=f"Run #{run_count} abgeschlossen: {result.state.value}",
                    extra={
                        "run_count": run_count,
                        "consecutive_errors": 0,
                        "markets_fetched": result.summary.get("markets_fetched", 0),
                        "edge_observations": result.summary.get("edge_observations", 0),
                        "uptime_seconds": round((datetime.now() - start_time).total_seconds(), 1),
                    },
                )
                _write_heartbeat_txt()
            except Exception as e:
                consecutive_errors += 1
                print(f"{C.RED}Pipeline error ({consecutive_errors}x): {e}{C.RESET}")
                write_bot_status(run_count, consecutive_errors, start_time, error=e)
                # JSON-Heartbeat auch bei Fehler schreiben
                _write_heartbeat_json(
                    status="error",
                    detail=f"Run #{run_count} fehlgeschlagen: {str(e)[:150]}",
                    extra={
                        "run_count": run_count,
                        "consecutive_errors": consecutive_errors,
                        "uptime_seconds": round((datetime.now() - start_time).total_seconds(), 1),
                    },
                )
                _write_heartbeat_txt()
                # Log to crash log as well
                try:
                    CRASH_LOG.parent.mkdir(parents=True, exist_ok=True)
                    _rotate_crash_log()
                    with open(CRASH_LOG, "a", encoding="utf-8") as f:
                        f.write(f"\n{'='*60}\n")
                        f.write(f"PIPELINE ERROR: {datetime.now().isoformat()}\n")
                        f.write(f"Consecutive: {consecutive_errors}\n")
                        traceback.print_exc(file=f)
                except Exception as e:
                    logger.warning("Fehler beim Crash-Log schreiben (Scheduler): %s", e)

            # SelfImprover: alle 4 Runs einen Verbesserungszyklus ausfuehren
            if enable_self_improve:
                try:
                    from meta.self_improver import should_run, run_improvement_cycle
                    if should_run(run_count):
                        print(f"\n{C.DIM}[SelfImprover] Starte Verbesserungszyklus (Run #{run_count})...{C.RESET}")
                        improve_result = run_improvement_cycle(dry_run=False)
                        outcome = improve_result.get("outcome", "?")
                        issue = (improve_result.get("suggestion") or {}).get("issue", "")
                        print(f"{C.DIM}[SelfImprover] Ergebnis: {outcome} — {issue[:60]}{C.RESET}")
                except Exception as si_exc:
                    logger.warning("SelfImprover Fehler (ignoriert): %s", si_exc)

            # Back off if too many consecutive errors
            if consecutive_errors >= 5:
                backoff = min(consecutive_errors * 60, 600)  # Max 10 min backoff
                print(f"{C.YELLOW}Viele Fehler, warte {backoff}s extra...{C.RESET}")
                time.sleep(backoff)

            # Wait for next run using monotonic clock (robust against system time changes)
            next_run = datetime.now() + timedelta(seconds=interval_seconds)
            print(f"\n{C.DIM}Next run: {next_run.strftime('%H:%M:%S')}{C.RESET}")
            print(f"{C.DIM}Press Ctrl+C to stop{C.RESET}")

            try:
                wait_until = time.monotonic() + interval_seconds
                while time.monotonic() < wait_until:
                    remaining = int(wait_until - time.monotonic())
                    if remaining > 0 and remaining % 60 == 0:
                        mins, secs = divmod(remaining, 60)
                        print(f"\r{C.DIM}Waiting: {mins:02d}:{secs:02d}{C.RESET}  ", end="", flush=True)
                        # BUGFIX: Refresh heartbeat.txt during wait so watchdog
                        # doesn't kill the bot during the 15-minute interval.
                        _write_heartbeat_txt()
                print(f"\r{C.DIM}Waiting: 00:00{C.RESET}  ", end="", flush=True)
            except Exception as e:
                # Even sleep errors shouldn't kill the scheduler
                logger.warning("Fehler beim Warte-Countdown: %s", e)
                time.sleep(interval_seconds)

    except KeyboardInterrupt:
        print(f"\n\n{C.YELLOW}Scheduler stopped{C.RESET}")
        print(f"  Total runs: {run_count}")
        print(f"  Duration:   {str(datetime.now() - start_time).split('.')[0]}")

        # Cleanup resources
        stop_memory_monitoring()
        shutdown_log_manager()

        return 0
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else 1
    except BaseException as e:
        # Last resort: log and re-raise so BAT wrapper can restart
        print(f"{C.RED}Fatal error: {e}{C.RESET}")
        try:
            _rotate_crash_log()
            with open(CRASH_LOG, "a", encoding="utf-8") as f:
                f.write(f"\n{'='*60}\n")
                f.write(f"FATAL: {datetime.now().isoformat()}\n")
                traceback.print_exc(file=f)
        except Exception as e:
            logger.warning("Fehler beim Fatal-Crash-Log schreiben: %s", e)
        return 1


def show_status() -> int:
    """Show status."""
    from app.orchestrator import get_status

    print_header()

    try:
        status = get_status()
        print_status(status)
        return 0
    except Exception as e:
        print(f"{C.RED}Error: {e}{C.RESET}")
        return 1


def interactive_mode():
    """Run interactive menu."""
    from app.orchestrator import get_status

    menu = f"""
{C.BOLD}Menu:{C.RESET}
  {C.CYAN}1{C.RESET}) Run observer now
  {C.CYAN}2{C.RESET}) Start scheduler (15 min)
  {C.CYAN}3{C.RESET}) Show status
  {C.CYAN}4{C.RESET}) Exit
"""

    while True:
        clear()
        print_header()

        try:
            status = get_status()
            print(f"  {C.DIM}Last run:{C.RESET} {status.get('last_run', 'Never')[:16]}")
            print(f"  {C.DIM}State:{C.RESET} {status.get('last_state', 'UNKNOWN')}")
        except Exception as e:
            logger.warning("Fehler beim Status abrufen (Menue): %s", e)

        print(menu)

        try:
            choice = input(f"{C.BOLD}Select [1-4]: {C.RESET}").strip()
        except (KeyboardInterrupt, EOFError):
            print(f"\n{C.DIM}Goodbye!{C.RESET}\n")
            break

        if choice == '1':
            clear()
            print_header()
            try:
                result = run_pipeline_with_progress()
                print_run_result(result)
            except Exception as e:
                print(f"{C.RED}Error: {e}{C.RESET}")
            input(f"{C.DIM}Press Enter to continue...{C.RESET}")

        elif choice == '2':
            clear()
            print(f"\n{C.BOLD}{C.GREEN}Starting Scheduler{C.RESET}")
            try:
                run_scheduler(900)
            except KeyboardInterrupt:
                pass
            input(f"{C.DIM}Press Enter to continue...{C.RESET}")

        elif choice == '3':
            clear()
            print_header()
            try:
                status = get_status()
                print_status(status)
            except Exception as e:
                print(f"{C.RED}Error: {e}{C.RESET}")
            input(f"{C.DIM}Press Enter to continue...{C.RESET}")

        elif choice == '4':
            print(f"\n{C.DIM}Goodbye!{C.RESET}\n")
            break


# =============================================================================
# MAIN
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Weather Observer - Cockpit",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python cockpit.py                    Interactive menu
  python cockpit.py --run-once         Run pipeline once, exit
  python cockpit.py --status           Show status only
  python cockpit.py --scheduler        Run every 15 minutes
"""
    )

    parser.add_argument('--run-once', action='store_true',
                        help='Run pipeline once and exit')
    parser.add_argument('--status', action='store_true',
                        help='Show status only')
    parser.add_argument('--scheduler', action='store_true',
                        help='Run pipeline on a schedule')
    parser.add_argument('--interval', type=int, default=900,
                        help='Interval between runs in seconds (default: 900)')
    parser.add_argument('--no-color', action='store_true',
                        help='Disable colors')
    parser.add_argument('--self-improve', action='store_true',
                        help='Aktiviere autonomen Code-Verbesserungs-Agent (alle 4 Runs)')

    args = parser.parse_args()

    if args.interval < 60:
        parser.error("Interval muss mindestens 60 Sekunden sein")

    if args.no_color:
        C.disable()

    # Ensure logs directory exists
    (BASE_DIR / "logs").mkdir(exist_ok=True)

    # Activate file-based logging (Python logger → logs/observer_*.log)
    from shared.logging_config import setup_logging
    setup_logging(console_output=not args.no_color, file_output=True)

    # Install crash logger for all modes
    setup_crash_logger()

    # Start Bot Monitor (System Tray) falls nicht bereits aktiv
    try:
        sys.path.insert(0, str(BASE_DIR.parent.parent))
        from bot_monitor import ensure_running
        ensure_running()
    except Exception:
        pass  # Monitor ist optional

    # Lockfile only for long-running modes (scheduler, interactive)
    if args.scheduler or not (args.run_once or args.status):
        acquire_lock()

    if args.scheduler:
        sys.exit(run_scheduler(args.interval, enable_self_improve=getattr(args, 'self_improve', False)))
    elif args.run_once:
        sys.exit(run_once())
    elif args.status:
        sys.exit(show_status())
    else:
        interactive_mode()


if __name__ == "__main__":
    main()
