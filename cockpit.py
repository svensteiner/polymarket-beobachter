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

LOCKFILE = BASE_DIR / "cockpit.lock"
HEARTBEAT_FILE = BASE_DIR / "logs" / "heartbeat.txt"
CRASH_LOG = BASE_DIR / "logs" / "crash.log"
BOT_STATUS_FILE = BASE_DIR / "logs" / "bot_status.json"


# =============================================================================
# ABSTURZSICHERHEIT
# =============================================================================

def _pid_alive(pid: int) -> bool:
    """Check if a process with given PID is still running (Windows-compatible)."""
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if handle:
            kernel32.CloseHandle(handle)
            return True
        return False
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


def write_heartbeat():
    """Write current timestamp to heartbeat file after each pipeline run."""
    try:
        HEARTBEAT_FILE.parent.mkdir(parents=True, exist_ok=True)
        HEARTBEAT_FILE.write_text(datetime.now().isoformat())
    except Exception as e:
        logger.warning("Fehler beim Heartbeat schreiben: %s", e)


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


def run_once() -> int:
    """Run pipeline once and return exit code."""
    print_header()
    start_time = datetime.now()

    try:
        result = run_pipeline_with_progress()
        print_run_result(result)
        write_heartbeat()
        write_bot_status(1, 0, start_time, result=result)

        if result.state.value == "OK":
            return 0
        elif result.state.value == "DEGRADED":
            return 2
        else:
            return 1

    except Exception as e:
        print(f"{C.RED}Pipeline failed: {e}{C.RESET}")
        write_bot_status(1, 1, start_time, error=e)
        return 1


def run_scheduler(interval_seconds: int = 900) -> int:
    """Run pipeline on a schedule with crash resilience."""
    run_count = 0
    consecutive_errors = 0
    start_time = datetime.now()

    print_header()
    print(f"{C.BOLD}Scheduler Mode{C.RESET}")
    print(f"  Interval: {interval_seconds // 60} minutes")
    print(f"  Started:  {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  PID:      {os.getpid()}")
    print(f"\n{C.DIM}Press Ctrl+C to stop{C.RESET}\n")

    write_heartbeat()  # Initial heartbeat

    try:
        while True:
            run_count += 1
            run_start = datetime.now()

            print(f"\n{C.BOLD}{C.CYAN}{'='*50}{C.RESET}")
            print(f"{C.BOLD}Run #{run_count}{C.RESET} - {run_start.strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"{C.BOLD}{C.CYAN}{'='*50}{C.RESET}\n")

            try:
                result = run_pipeline_with_progress()
                print_run_result(result)
                consecutive_errors = 0
                write_bot_status(run_count, consecutive_errors, start_time, result=result)
            except Exception as e:
                consecutive_errors += 1
                print(f"{C.RED}Pipeline error ({consecutive_errors}x): {e}{C.RESET}")
                write_bot_status(run_count, consecutive_errors, start_time, error=e)
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

            # Always write heartbeat - proves the scheduler loop is alive
            write_heartbeat()

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
                    time.sleep(min(10, max(1, remaining)))
                print(f"\r{C.DIM}Waiting: 00:00{C.RESET}  ", end="", flush=True)
            except Exception as e:
                # Even sleep errors shouldn't kill the scheduler
                logger.warning("Fehler beim Warte-Countdown: %s", e)
                time.sleep(interval_seconds)

    except KeyboardInterrupt:
        print(f"\n\n{C.YELLOW}Scheduler stopped{C.RESET}")
        print(f"  Total runs: {run_count}")
        print(f"  Duration:   {str(datetime.now() - start_time).split('.')[0]}")
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
        sys.exit(run_scheduler(args.interval))
    elif args.run_once:
        sys.exit(run_once())
    elif args.status:
        sys.exit(show_status())
    else:
        interactive_mode()


if __name__ == "__main__":
    main()
