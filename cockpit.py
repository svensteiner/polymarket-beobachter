#!/usr/bin/env python3
# =============================================================================
# POLYMARKET BEOBACHTER - COCKPIT
# =============================================================================
#
# THE SINGLE ENTRY POINT FOR ALL OPERATIONS
#
# Usage:
#   python cockpit.py                    # Interactive menu
#   python cockpit.py --run-once         # Run pipeline once, exit
#   python cockpit.py --status           # Show status only
#   python cockpit.py --scheduler        # Run every 15 minutes (default)
#   python cockpit.py --scheduler --interval 600  # Run every 10 minutes
#
# Exit codes:
#   0 = Success (OK)
#   1 = Failure (FAIL)
#   2 = Degraded (some steps failed)
#
# =============================================================================

import sys
import argparse
import time
import threading
from pathlib import Path
from datetime import datetime, timedelta

# Setup paths
BASE_DIR = Path(__file__).parent
sys.path.insert(0, str(BASE_DIR))

# =============================================================================
# TERMINAL COLORS
# =============================================================================

class C:
    """Terminal colors (extended)."""
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    CYAN = "\033[96m"
    BLUE = "\033[94m"
    MAGENTA = "\033[95m"
    WHITE = "\033[97m"
    BG_GREEN = "\033[42m"
    BG_YELLOW = "\033[43m"
    BG_RED = "\033[41m"
    BG_BLUE = "\033[44m"

    @classmethod
    def disable(cls):
        for attr in dir(cls):
            if attr.isupper() and not attr.startswith('_'):
                setattr(cls, attr, "")


# Spinner frames for animation
SPINNER_FRAMES = ['|', '/', '-', '\\']
PROGRESS_CHARS = ['[          ]', '[=         ]', '[==        ]', '[===       ]',
                  '[====      ]', '[=====     ]', '[======    ]', '[=======   ]',
                  '[========  ]', '[========= ]', '[==========]']


# Windows compatibility
if sys.platform == "win32":
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
    except Exception:
        C.disable()


# =============================================================================
# OUTPUT HELPERS
# =============================================================================

def clear():
    """Clear screen using ANSI escape codes (safer than os.system)."""
    # ANSI escape: \033[2J clears screen, \033[H moves cursor to top-left
    print("\033[2J\033[H", end="", flush=True)


def print_header(subtitle: str = None):
    """Print header with optional subtitle."""
    print(f"\n{C.BOLD}{C.CYAN}{'='*50}{C.RESET}")
    print(f"{C.BOLD}{C.CYAN}   POLYMARKET BEOBACHTER{C.RESET}")
    if subtitle:
        print(f"{C.DIM}   {subtitle}{C.RESET}")
    print(f"{C.BOLD}{C.CYAN}{'='*50}{C.RESET}")
    print(f"{C.DIM}   {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}{C.RESET}")
    print()


def print_step_start(step_name: str, description: str):
    """Print step start indicator."""
    icon = {
        "collector": "[1/7]",
        "analyzer": "[2/7]",
        "proposals": "[3/7]",
        "paper_trader": "[4/7]",
        "cross_market": "[5/7]",
        "outcome_tracker": "[6/7]",
        "status_writer": "[7/7]"
    }.get(step_name, "[...]")
    print(f"{C.CYAN}{icon}{C.RESET} {C.BOLD}{description}{C.RESET}", end="", flush=True)


def print_step_result(success: bool, message: str, duration_ms: int = 0):
    """Print step result."""
    if success:
        status = f"{C.GREEN}OK{C.RESET}"
    else:
        status = f"{C.RED}FAIL{C.RESET}"

    time_str = f" {C.DIM}({duration_ms}ms){C.RESET}" if duration_ms > 0 else ""
    print(f" ... {status}{time_str}")
    if message:
        print(f"      {C.DIM}{message}{C.RESET}")


def print_spinner(text: str, duration: float = 0.5):
    """Show a brief spinner animation."""
    for i in range(int(duration * 10)):
        frame = SPINNER_FRAMES[i % len(SPINNER_FRAMES)]
        print(f"\r{C.CYAN}{frame}{C.RESET} {text}", end="", flush=True)
        time.sleep(0.1)
    print(f"\r{' ' * (len(text) + 3)}\r", end="", flush=True)


def print_countdown(seconds: int, next_run_time: datetime):
    """Print countdown timer with activity indicator."""
    print(f"\n{C.BOLD}Next run:{C.RESET} {next_run_time.strftime('%H:%M:%S')}")
    print(f"{C.DIM}Press Ctrl+C to stop scheduler{C.RESET}\n")

    for remaining in range(seconds, 0, -1):
        mins, secs = divmod(remaining, 60)
        progress_idx = int((1 - remaining / seconds) * 10)
        progress_bar = PROGRESS_CHARS[min(progress_idx, 10)]

        # Animate dots
        dots = "." * ((seconds - remaining) % 4)

        print(f"\r{C.CYAN}{progress_bar}{C.RESET} {mins:02d}:{secs:02d} remaining{dots.ljust(3)}", end="", flush=True)
        time.sleep(1)

    print(f"\r{C.GREEN}[==========]{C.RESET} Starting pipeline...          ")


def print_box(title: str, lines: list, color: str = None):
    """Print a boxed section."""
    color = color or C.WHITE
    width = max(len(title) + 4, max(len(l) for l in lines) + 4) if lines else len(title) + 4
    width = min(width, 50)

    print(f"{color}+{'-' * width}+{C.RESET}")
    print(f"{color}| {C.BOLD}{title.ljust(width - 2)}{C.RESET}{color} |{C.RESET}")
    print(f"{color}+{'-' * width}+{C.RESET}")
    for line in lines:
        print(f"{color}|{C.RESET} {line[:width-2].ljust(width - 2)} {color}|{C.RESET}")
    print(f"{color}+{'-' * width}+{C.RESET}")


def print_status(status: dict):
    """Print detailed status summary with visual boxes."""
    last_run = status.get('last_run', 'Never')
    last_state = status.get('last_state', 'UNKNOWN')

    print()
    print_box("Last Run", [
        f"Time:   {last_run}",
        f"State:  {format_state(last_state)}",
    ], C.CYAN)

    today = status.get('today', {})
    trade_count = today.get('trade', 0)
    no_trade_count = today.get('no_trade', 0)
    insufficient_count = today.get('insufficient', 0)
    markets_checked = today.get('markets_checked', 0)

    print()
    print_box("Today's Activity", [
        f"Markets checked:  {markets_checked}",
        f"",
        f"{C.GREEN}TRADE signals:{C.RESET}   {trade_count}",
        f"NO_TRADE:         {no_trade_count}",
        f"INSUFFICIENT:     {insufficient_count}",
    ], C.MAGENTA)

    paper_open = status.get('paper_positions_open', 0)
    paper_pnl = status.get('paper_total_pnl', 0.0)
    pnl_color = C.GREEN if paper_pnl >= 0 else C.RED

    print()
    print_box("Paper Trading", [
        f"Open positions:   {paper_open}",
        f"Total P&L:        {pnl_color}{paper_pnl:+.2f} EUR{C.RESET}",
    ], C.BLUE)

    total_proposals = status.get('total_proposals', 0)
    if total_proposals > 0:
        print()
        print(f"  {C.DIM}Total proposals generated: {total_proposals}{C.RESET}")

    print()


def print_run_result(result, verbose: bool = False):
    """Print pipeline run result."""
    state = result.state.value
    summary = result.summary

    # Result header
    if state == "OK":
        print(f"\n{C.BG_GREEN}{C.WHITE}{C.BOLD}  PIPELINE COMPLETE: OK  {C.RESET}")
    elif state == "DEGRADED":
        print(f"\n{C.BG_YELLOW}{C.WHITE}{C.BOLD}  PIPELINE COMPLETE: DEGRADED  {C.RESET}")
    else:
        print(f"\n{C.BG_RED}{C.WHITE}{C.BOLD}  PIPELINE COMPLETE: FAIL  {C.RESET}")

    print(f"{C.DIM}Finished at {datetime.now().strftime('%H:%M:%S')}{C.RESET}\n")

    # Market analysis summary
    markets_checked = summary.get('markets_checked', 0)
    candidates = summary.get('candidates_found', 0)
    trade = summary.get('trade_count', 0)
    no_trade = summary.get('no_trade_count', 0)
    insufficient = summary.get('insufficient_count', 0)

    print_box("Market Analysis", [
        f"Markets fetched:    {markets_checked}",
        f"Candidates found:   {candidates}",
        f"",
        f"{C.GREEN}TRADE:{C.RESET}             {trade}",
        f"NO_TRADE:           {no_trade}",
        f"INSUFFICIENT:       {insufficient}",
    ], C.CYAN)

    # Proposals
    proposals_gen = summary.get('proposals_generated', 0)
    proposals_pass = summary.get('proposals_passed', 0)
    if proposals_gen > 0:
        print()
        print_box("Proposals", [
            f"Generated:  {proposals_gen}",
            f"Passed:     {C.GREEN}{proposals_pass}{C.RESET}" if proposals_pass > 0 else f"Passed:     {proposals_pass}",
        ], C.MAGENTA)

    # Paper Trading
    paper_open = summary.get('paper_positions_open', 0)
    paper_pnl = summary.get('paper_total_pnl', 0.0)
    pnl_color = C.GREEN if paper_pnl >= 0 else C.RED
    print()
    print_box("Paper Trading", [
        f"Open positions:  {paper_open}",
        f"Total P&L:       {pnl_color}{paper_pnl:+.2f} EUR{C.RESET}",
    ], C.BLUE)

    # Cross-Market Research (ISOLATED)
    cm_relations = summary.get('cross_market_relations', 0)
    cm_inconsistencies = summary.get('cross_market_inconsistencies', 0)
    cm_topics = summary.get('cross_market_topics', 0)
    if cm_relations > 0 or cm_topics > 0:
        inc_color = C.RED if cm_inconsistencies > 0 else C.GREEN
        print()
        print_box("Cross-Market Research", [
            f"Topic groups:       {cm_topics}",
            f"Relations checked:  {cm_relations}",
            f"Inconsistencies:    {inc_color}{cm_inconsistencies}{C.RESET}",
            f"{C.DIM}(Research only - no trading impact){C.RESET}",
        ], C.MAGENTA)

    # Latest TRADE candidate - EXTENDED INFO
    latest = summary.get('latest_trade')
    if latest:
        print()
        edge = latest.get('edge', 0)
        edge_color = C.GREEN if edge > 0 else C.RED if edge < 0 else C.WHITE
        direction = latest.get('direction', 'UNKNOWN')
        dir_hint = "YES" if direction == "MARKET_TOO_LOW" else "NO" if direction == "MARKET_TOO_HIGH" else "?"

        print_box("TRADE SIGNAL DETECTED", [
            f"{C.BOLD}{latest.get('title', 'N/A')[:45]}{C.RESET}",
            f"",
            f"Category:    {latest.get('category', 'N/A')}",
            f"End Date:    {latest.get('end_date', 'N/A')}",
            f"",
            f"{C.CYAN}--- Probability Analysis ---{C.RESET}",
            f"Our Estimate:   {latest.get('our_estimate', 0):.1%} ({latest.get('estimate_range', 'N/A')})",
            f"Market Price:   {latest.get('market_price', 0):.1%}",
            f"Edge:           {edge_color}{edge:+.1%}{C.RESET}",
            f"Direction:      {direction} -> Consider {C.BOLD}{dir_hint}{C.RESET}",
            f"",
            f"{C.CYAN}--- Decision Quality ---{C.RESET}",
            f"Confidence:     {latest.get('confidence', 'N/A')}",
            f"Criteria:       {latest.get('criteria_passed', 0)}/{latest.get('criteria_total', 0)} passed",
            f"Days to Target: {latest.get('days_until_target', 'N/A')}",
        ], C.GREEN)

        # Risk warnings
        warnings = latest.get('risk_warnings', [])
        if warnings:
            print(f"\n{C.YELLOW}{C.BOLD}Risk Warnings:{C.RESET}")
            for w in warnings[:3]:
                print(f"  {C.YELLOW}!{C.RESET} {w[:70]}")

        # Recommended action
        action = latest.get('recommended_action', '')
        if action:
            print(f"\n{C.CYAN}Recommendation:{C.RESET}")
            print(f"  {action[:80]}")

    # Errors/Warnings
    errors = [s for s in result.steps if not s.success]
    if errors:
        print(f"\n{C.YELLOW}{C.BOLD}Warnings:{C.RESET}")
        for e in errors:
            print(f"  {C.YELLOW}!{C.RESET} {e.name}: {e.error[:50] if e.error else 'Failed'}")
        print(f"  {C.DIM}See logs/ for details{C.RESET}")

    # Verbose step details
    if verbose:
        print(f"\n{C.DIM}--- Step Details ---{C.RESET}")
        for step in result.steps:
            icon = f"{C.GREEN}+{C.RESET}" if step.success else f"{C.RED}x{C.RESET}"
            print(f"  {icon} {step.name}: {step.message}")

    print()


def print_proposal(proposal: dict):
    """Print latest proposal with visual styling."""
    if not proposal:
        print()
        print_box("Latest Proposal", [
            f"{C.DIM}No proposals yet{C.RESET}",
            f"",
            f"Run the pipeline to generate proposals.",
        ], C.YELLOW)
        print()
        return

    decision = proposal.get('decision', 'N/A')
    edge = proposal.get('edge', 0)
    edge_color = C.GREEN if edge > 0 else C.RED if edge < 0 else C.WHITE

    print()
    print_box("Latest Proposal", [
        f"ID:          {proposal.get('proposal_id', 'N/A')}",
        f"Time:        {proposal.get('timestamp', 'N/A')[:16]}",
        f"",
        f"Market:      {proposal.get('market', 'N/A')[:35]}",
        f"Decision:    {format_decision(decision)}",
        f"Edge:        {edge_color}{edge:+.1%}{C.RESET}",
        f"Confidence:  {proposal.get('confidence', 'N/A')}",
    ], C.GREEN if decision == "TRADE" else C.CYAN)
    print()


def print_paper_summary(summary: dict):
    """Print paper trading summary with visual styling."""
    open_positions = summary.get('open_positions', 0)
    total_positions = summary.get('total_positions', 0)
    realized_pnl = summary.get('realized_pnl', 0.0)
    pnl_color = C.GREEN if realized_pnl >= 0 else C.RED

    print()
    print_box("Paper Trading Overview", [
        f"Open positions:    {open_positions}",
        f"Total positions:   {total_positions}",
        f"Realized P&L:      {pnl_color}{realized_pnl:+.2f} EUR{C.RESET}",
    ], C.BLUE)

    positions = summary.get('positions', [])
    if positions:
        print()
        print(f"{C.BOLD}Open Positions:{C.RESET}")
        print(f"{C.DIM}{'-' * 50}{C.RESET}")
        for p in positions[:5]:
            side = p.get('side', '?')
            side_color = C.GREEN if side == 'YES' else C.RED
            entry = p.get('entry_price', 0)
            market = p.get('market', 'Unknown')[:40]
            print(f"  {side_color}{side:3}{C.RESET} @ {entry:.2f} | {market}")
        if len(positions) > 5:
            print(f"  {C.DIM}+{len(positions)-5} more positions...{C.RESET}")
    else:
        print()
        print(f"  {C.DIM}No open positions{C.RESET}")

    actions = summary.get('recent_actions', [])
    if actions:
        print()
        print(f"{C.BOLD}Recent Actions:{C.RESET}")
        print(f"{C.DIM}{'-' * 50}{C.RESET}")
        for a in actions[:5]:
            action = a.get('action', 'N/A')
            market_id = a.get('market_id', 'N/A')[:15]
            pnl = a.get('pnl')
            if pnl:
                pnl_str = f"{C.GREEN}{pnl:+.2f}{C.RESET}" if pnl >= 0 else f"{C.RED}{pnl:+.2f}{C.RESET}"
            else:
                pnl_str = "-"
            print(f"  {action:6} | {market_id:15} | P&L: {pnl_str}")

    print()


def format_state(state: str) -> str:
    """Format run state with color."""
    if state == "OK":
        return f"{C.GREEN}OK{C.RESET}"
    elif state == "DEGRADED":
        return f"{C.YELLOW}DEGRADED{C.RESET}"
    elif state == "FAIL":
        return f"{C.RED}FAIL{C.RESET}"
    return state


def format_decision(decision: str) -> str:
    """Format decision with color."""
    if decision == "TRADE":
        return f"{C.GREEN}TRADE{C.RESET}"
    elif decision == "NO_TRADE":
        return f"{C.RED}NO_TRADE{C.RESET}"
    return decision


# =============================================================================
# MENU
# =============================================================================

MENU = """
{bold}Menu:{reset}
  {cyan}1{reset}) Run pipeline now
  {cyan}2{reset}) {green}Start scheduler (15 min){reset}
  {cyan}3{reset}) Show status
  {cyan}4{reset}) Show latest proposal
  {cyan}5{reset}) Show paper trading
  {cyan}6{reset}) Open logs folder
  {cyan}7{reset}) Exit
""".format(bold=C.BOLD, reset=C.RESET, cyan=C.CYAN, green=C.GREEN)


def interactive_mode():
    """Run interactive menu."""
    from app.orchestrator import get_status, get_latest_proposal, get_paper_summary

    while True:
        clear()
        print_header("Interactive Mode")

        # Show quick status box
        try:
            status = get_status()
            last_run = status.get('last_run', 'Never')[:16]
            positions = status.get('paper_positions_open', 0)
            pnl = status.get('paper_total_pnl', 0.0)
            pnl_color = C.GREEN if pnl >= 0 else C.RED
            state = status.get('last_state', 'UNKNOWN')

            print(f"  {C.DIM}Last run:{C.RESET} {last_run} | {C.DIM}State:{C.RESET} {format_state(state)}")
            print(f"  {C.DIM}Positions:{C.RESET} {positions} | {C.DIM}P&L:{C.RESET} {pnl_color}{pnl:+.2f} EUR{C.RESET}")
        except Exception:
            print(f"  {C.DIM}Status unavailable{C.RESET}")

        print(MENU)

        try:
            choice = input(f"{C.BOLD}Select [1-7]: {C.RESET}").strip()
        except (KeyboardInterrupt, EOFError):
            print(f"\n{C.DIM}Goodbye!{C.RESET}\n")
            break

        if choice == '1':
            clear()
            print_header("Single Run")
            try:
                result = run_pipeline_with_progress()
                print_run_result(result, verbose=True)
            except Exception as e:
                print(f"{C.RED}Error: {e}{C.RESET}")
            input(f"{C.DIM}Press Enter to continue...{C.RESET}")

        elif choice == '2':
            clear()
            print(f"\n{C.BOLD}{C.GREEN}Starting Scheduler Mode{C.RESET}")
            print(f"{C.DIM}Pipeline will run every 15 minutes.{C.RESET}")
            print(f"{C.DIM}Press Ctrl+C to stop and return to menu.{C.RESET}\n")
            try:
                run_scheduler(900)  # 15 minutes
            except KeyboardInterrupt:
                pass
            input(f"{C.DIM}Press Enter to continue...{C.RESET}")

        elif choice == '3':
            clear()
            print_header("System Status")
            try:
                status = get_status()
                print_status(status)
            except Exception as e:
                print(f"{C.RED}Error: {e}{C.RESET}")
            input(f"{C.DIM}Press Enter to continue...{C.RESET}")

        elif choice == '4':
            clear()
            print_header("Latest Proposal")
            try:
                proposal = get_latest_proposal()
                print_proposal(proposal)
            except Exception as e:
                print(f"{C.RED}Error: {e}{C.RESET}")
            input(f"{C.DIM}Press Enter to continue...{C.RESET}")

        elif choice == '5':
            clear()
            print_header("Paper Trading")
            try:
                summary = get_paper_summary()
                print_paper_summary(summary)
            except Exception as e:
                print(f"{C.RED}Error: {e}{C.RESET}")
            input(f"{C.DIM}Press Enter to continue...{C.RESET}")

        elif choice == '6':
            clear()
            print_header("Log Locations")
            logs_path = BASE_DIR / "logs"
            print()
            print_box("Log Folders", [
                f"Main logs:   {logs_path}",
                f"Audit logs:  {logs_path / 'audit'}",
                f"Paper logs:  {BASE_DIR / 'paper_trader' / 'logs'}",
            ], C.CYAN)
            print()
            input(f"{C.DIM}Press Enter to continue...{C.RESET}")

        elif choice == '7':
            print(f"\n{C.DIM}Goodbye!{C.RESET}\n")
            break

        else:
            pass  # Invalid choice, just redraw menu


# =============================================================================
# CLI MODE
# =============================================================================

def run_pipeline_with_progress() -> 'PipelineResult':
    """
    Run pipeline with live progress output.

    Returns:
        PipelineResult
    """
    from app.orchestrator import get_orchestrator
    from datetime import datetime as dt

    orchestrator = get_orchestrator()

    # We'll manually orchestrate to show progress
    from app.orchestrator import PipelineResult, RunState

    result = PipelineResult(
        state=RunState.OK,
        timestamp=dt.now().isoformat()
    )

    steps = [
        ("collector", "Fetching market data from Polymarket"),
        ("analyzer", "Analyzing candidates for trade signals"),
        ("proposals", "Generating and reviewing proposals"),
        ("paper_trader", "Updating paper trading positions"),
        ("cross_market", "Cross-market consistency research"),
        ("outcome_tracker", "Recording predictions for calibration"),
        ("weather_engine", "Scanning weather markets for signals"),
        ("signal_trading", "Converting signals to paper trades"),
        ("status_writer", "Writing status summary"),
    ]

    print(f"{C.BOLD}Pipeline Execution{C.RESET}")
    print(f"{C.DIM}{'-' * 45}{C.RESET}\n")

    for step_name, description in steps:
        print_step_start(step_name, description)
        start_time = time.time()

        try:
            if step_name == "collector":
                step_result = orchestrator._run_collector()
            elif step_name == "analyzer":
                collector_step = next((s for s in result.steps if s.name == "collector"), None)
                step_result = orchestrator._run_analyzer(collector_step.data if collector_step else {})
            elif step_name == "proposals":
                analyzer_step = next((s for s in result.steps if s.name == "analyzer"), None)
                step_result = orchestrator._run_proposals(analyzer_step.data if analyzer_step else {})
            elif step_name == "paper_trader":
                proposal_step = next((s for s in result.steps if s.name == "proposals"), None)
                step_result = orchestrator._run_paper_trader(proposal_step.data if proposal_step else {})
            elif step_name == "cross_market":
                collector_step = next((s for s in result.steps if s.name == "collector"), None)
                step_result = orchestrator._run_cross_market(collector_step.data if collector_step else {})
            elif step_name == "outcome_tracker":
                collector_step = next((s for s in result.steps if s.name == "collector"), None)
                analyzer_step = next((s for s in result.steps if s.name == "analyzer"), None)
                step_result = orchestrator._run_outcome_tracker(
                    collector_step.data if collector_step else {},
                    analyzer_step.data if analyzer_step else {},
                    result.timestamp
                )
            elif step_name == "weather_engine":
                step_result = orchestrator._run_weather_engine()
            elif step_name == "signal_trading":
                step_result = orchestrator._run_signal_trading()
            elif step_name == "status_writer":
                result.summary = orchestrator._build_summary(result)
                step_result = orchestrator._write_status_summary(result)

            result.add_step(step_result)
            duration_ms = int((time.time() - start_time) * 1000)
            print_step_result(step_result.success, step_result.message, duration_ms)

        except Exception as e:
            from app.orchestrator import StepResult
            step_result = StepResult(
                name=step_name,
                success=False,
                message=f"Step failed: {str(e)[:50]}",
                error=str(e)
            )
            result.add_step(step_result)
            duration_ms = int((time.time() - start_time) * 1000)
            print_step_result(False, str(e)[:50], duration_ms)

    # Log to audit
    orchestrator._log_to_audit(result)

    return result


def run_once() -> int:
    """
    Run pipeline once and return exit code.

    Returns:
        0 = OK
        1 = FAIL
        2 = DEGRADED
    """
    print_header("Single Run Mode")

    try:
        result = run_pipeline_with_progress()
        print_run_result(result, verbose=True)

        if result.state.value == "OK":
            return 0
        elif result.state.value == "DEGRADED":
            return 2
        else:
            return 1

    except Exception as e:
        print(f"{C.RED}Pipeline failed: {e}{C.RESET}")
        return 1


def run_scheduler(interval_seconds: int = 900) -> int:
    """
    Run pipeline on a schedule.

    Args:
        interval_seconds: Seconds between runs (default: 900 = 15 minutes)

    Returns:
        Exit code (only on error, normally runs forever)
    """
    run_count = 0
    total_trades = 0
    total_errors = 0
    start_time = datetime.now()

    print_header("Scheduler Mode")
    print(f"{C.BOLD}Configuration:{C.RESET}")
    print(f"  Interval: {interval_seconds // 60} minutes ({interval_seconds} seconds)")
    print(f"  Started:  {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"\n{C.DIM}Press Ctrl+C to stop{C.RESET}\n")
    print(f"{'-' * 50}\n")

    try:
        while True:
            run_count += 1
            run_start = datetime.now()

            print(f"\n{C.BOLD}{C.CYAN}{'='*50}{C.RESET}")
            print(f"{C.BOLD}Run #{run_count}{C.RESET} - {run_start.strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"{C.DIM}Uptime: {str(run_start - start_time).split('.')[0]}{C.RESET}")
            print(f"{C.BOLD}{C.CYAN}{'='*50}{C.RESET}\n")

            try:
                result = run_pipeline_with_progress()
                print_run_result(result)

                # Track stats
                if result.state.value != "OK":
                    total_errors += 1
                total_trades += result.summary.get('trade_count', 0)

                # Session stats
                print(f"\n{C.DIM}--- Session Stats ---{C.RESET}")
                print(f"  Total runs:     {run_count}")
                print(f"  Total TRADEs:   {C.GREEN}{total_trades}{C.RESET}")
                print(f"  Errors:         {total_errors}")

            except Exception as e:
                total_errors += 1
                print(f"{C.RED}Pipeline error: {e}{C.RESET}")

            # Calculate next run time
            next_run = datetime.now() + timedelta(seconds=interval_seconds)

            # Show countdown
            print_countdown(interval_seconds, next_run)

    except KeyboardInterrupt:
        print(f"\n\n{C.YELLOW}Scheduler stopped by user{C.RESET}")
        print(f"\n{C.BOLD}Final Session Stats:{C.RESET}")
        print(f"  Total runs:     {run_count}")
        print(f"  Total TRADEs:   {total_trades}")
        print(f"  Errors:         {total_errors}")
        print(f"  Duration:       {str(datetime.now() - start_time).split('.')[0]}")
        print()
        return 0


def show_status() -> int:
    """
    Show status and return exit code.

    Returns:
        0 = OK
        1 = Error
    """
    from app.orchestrator import get_status

    print_header()

    try:
        status = get_status()
        print_status(status)
        return 0
    except Exception as e:
        print(f"{C.RED}Error: {e}{C.RESET}")
        return 1


# =============================================================================
# MAIN
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Polymarket Beobachter - Cockpit",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python cockpit.py                    Interactive menu
  python cockpit.py --run-once         Run pipeline once, exit
  python cockpit.py --status           Show status only
  python cockpit.py --scheduler        Run every 15 minutes
  python cockpit.py --scheduler --interval 600   Run every 10 minutes
"""
    )

    parser.add_argument('--run-once', action='store_true',
                        help='Run pipeline once and exit')
    parser.add_argument('--status', action='store_true',
                        help='Show status only')
    parser.add_argument('--scheduler', action='store_true',
                        help='Run pipeline on a schedule (default: every 15 minutes)')
    parser.add_argument('--interval', type=int, default=900,
                        help='Interval between runs in seconds (default: 900 = 15 min)')
    parser.add_argument('--no-color', action='store_true',
                        help='Disable colors')

    args = parser.parse_args()

    if args.no_color:
        C.disable()

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
