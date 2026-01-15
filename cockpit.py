#!/usr/bin/env python3
# =============================================================================
# POLYMARKET BEOBACHTER - MONITORING COCKPIT
# =============================================================================
#
# Ein interaktives Dashboard zur Überwachung des Systems.
# Zeigt: Audit-Logs, System-Status, letzte Analysen, Entscheidungen
#
# Verwendung:
#   python cockpit.py           # Interaktives Menü
#   python cockpit.py --status  # Nur Status anzeigen
#   python cockpit.py --logs    # Nur Logs anzeigen
#   python cockpit.py --watch   # Live-Überwachung (alle 5 Sek.)
#
# =============================================================================

import os
import sys
import json
import argparse
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any

# Pfade
BASE_DIR = Path(__file__).parent
LOGS_DIR = BASE_DIR / "logs"
AUDIT_DIR = LOGS_DIR / "audit"
OUTPUT_DIR = BASE_DIR / "output"
CONFIG_DIR = BASE_DIR / "config"
PROPOSALS_DIR = BASE_DIR / "proposals"


# =============================================================================
# FARBEN (Terminal)
# =============================================================================

class Colors:
    """Terminal-Farben (funktioniert auf Windows mit colorama oder nativ)"""
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"

    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    MAGENTA = "\033[95m"
    CYAN = "\033[96m"
    WHITE = "\033[97m"

    BG_RED = "\033[41m"
    BG_GREEN = "\033[42m"
    BG_YELLOW = "\033[43m"
    BG_BLUE = "\033[44m"

    @classmethod
    def disable(cls):
        """Farben deaktivieren (für nicht-unterstützte Terminals)"""
        for attr in dir(cls):
            if not attr.startswith('_') and attr.isupper():
                setattr(cls, attr, "")


# Windows-Kompatibilität
if sys.platform == "win32":
    try:
        import colorama
        colorama.init()
    except ImportError:
        # Ohne colorama: ANSI aktivieren via ctypes
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
        except Exception:
            Colors.disable()


# =============================================================================
# UTILITY FUNKTIONEN
# =============================================================================

def clear_screen():
    """Terminal leeren"""
    os.system('cls' if sys.platform == 'win32' else 'clear')


def print_header(title: str, width: int = 70):
    """Überschrift drucken"""
    print(f"\n{Colors.BOLD}{Colors.CYAN}{'='*width}{Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.CYAN}  {title.center(width-4)}{Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.CYAN}{'='*width}{Colors.RESET}\n")


def print_section(title: str):
    """Abschnitt-Überschrift"""
    print(f"\n{Colors.BOLD}{Colors.YELLOW}> {title}{Colors.RESET}")
    print(f"{Colors.DIM}{'-'*60}{Colors.RESET}")


def format_decision(decision: str) -> str:
    """Entscheidung farbig formatieren"""
    if decision == "TRADE":
        return f"{Colors.BG_GREEN}{Colors.WHITE} TRADE {Colors.RESET}"
    elif decision == "NO_TRADE":
        return f"{Colors.BG_RED}{Colors.WHITE} NO_TRADE {Colors.RESET}"
    elif decision == "INSUFFICIENT_DATA":
        return f"{Colors.BG_YELLOW}{Colors.WHITE} INSUFFICIENT_DATA {Colors.RESET}"
    return decision


def format_bool(value: bool) -> str:
    """Boolean farbig formatieren"""
    if value:
        return f"{Colors.GREEN}[OK]{Colors.RESET}"
    return f"{Colors.RED}[X]{Colors.RESET}"


def format_timestamp(ts: str) -> str:
    """Timestamp formatieren"""
    try:
        dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return ts


# =============================================================================
# AUDIT LOG FUNKTIONEN
# =============================================================================

def load_audit_logs(max_entries: int = 50) -> List[Dict[str, Any]]:
    """Audit-Logs laden (neueste zuerst)"""
    logs = []

    if not AUDIT_DIR.exists():
        return logs

    # Alle JSONL-Dateien finden (neueste zuerst)
    log_files = sorted(AUDIT_DIR.glob("*.jsonl"), reverse=True)

    for log_file in log_files:
        try:
            with open(log_file, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            entry = json.loads(line)
                            logs.append(entry)
                        except json.JSONDecodeError:
                            pass
        except Exception:
            pass

        if len(logs) >= max_entries:
            break

    # Nach Timestamp sortieren (neueste zuerst)
    logs.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
    return logs[:max_entries]


def display_audit_logs(max_entries: int = 20):
    """Audit-Logs anzeigen"""
    print_section("AUDIT LOGS")

    logs = load_audit_logs(max_entries)

    if not logs:
        print(f"  {Colors.DIM}Keine Audit-Logs gefunden{Colors.RESET}")
        return

    print(f"  {Colors.DIM}Zeige {len(logs)} Eintraege (neueste zuerst){Colors.RESET}\n")

    for entry in logs:
        ts = format_timestamp(entry.get('timestamp', 'N/A'))
        event = entry.get('event', 'UNKNOWN')
        market = entry.get('market_id', 'N/A')[:30]
        decision = entry.get('decision', 'N/A')

        decision_fmt = format_decision(decision)

        print(f"  {Colors.DIM}{ts}{Colors.RESET} | {decision_fmt} | {market}")

        # Reasoning anzeigen wenn vorhanden
        reasoning = entry.get('reasoning', '')
        if reasoning:
            print(f"    {Colors.DIM}   -> {reasoning[:70]}{'...' if len(reasoning) > 70 else ''}{Colors.RESET}")


# =============================================================================
# SYSTEM STATUS
# =============================================================================

def get_system_status() -> Dict[str, Any]:
    """System-Status ermitteln"""
    status = {
        "components": {},
        "directories": {},
        "last_activity": None
    }

    # Komponenten prüfen
    components = {
        "core_analyzer": BASE_DIR / "core_analyzer" / "__init__.py",
        "collector": BASE_DIR / "collector" / "__init__.py",
        "microstructure_research": BASE_DIR / "microstructure_research" / "__init__.py",
        "shared": BASE_DIR / "shared" / "__init__.py",
    }

    for name, path in components.items():
        status["components"][name] = path.exists()

    # Verzeichnisse prüfen
    directories = {
        "logs": LOGS_DIR,
        "audit": AUDIT_DIR,
        "output": OUTPUT_DIR,
        "config": CONFIG_DIR,
    }

    for name, path in directories.items():
        status["directories"][name] = {
            "exists": path.exists(),
            "files": len(list(path.glob("*"))) if path.exists() else 0
        }

    # Letzte Aktivität
    if AUDIT_DIR.exists():
        log_files = sorted(AUDIT_DIR.glob("*.jsonl"), reverse=True)
        if log_files:
            status["last_activity"] = datetime.fromtimestamp(
                log_files[0].stat().st_mtime
            ).isoformat()

    return status


def display_system_status():
    """System-Status anzeigen"""
    print_section("SYSTEM STATUS")

    status = get_system_status()

    # Komponenten
    print(f"\n  {Colors.BOLD}Komponenten:{Colors.RESET}")
    for name, exists in status["components"].items():
        icon = format_bool(exists)
        print(f"    {icon} {name}")

    # Verzeichnisse
    print(f"\n  {Colors.BOLD}Verzeichnisse:{Colors.RESET}")
    for name, info in status["directories"].items():
        icon = format_bool(info["exists"])
        files = info["files"]
        print(f"    {icon} {name:15} ({files} Dateien)")

    # Letzte Aktivitaet
    if status["last_activity"]:
        print(f"\n  {Colors.BOLD}Letzte Aktivitaet:{Colors.RESET}")
        print(f"    {format_timestamp(status['last_activity'])}")


# =============================================================================
# LETZTE ANALYSE
# =============================================================================

def load_latest_analysis() -> Optional[Dict[str, Any]]:
    """Letzte Analyse laden"""
    analysis_file = OUTPUT_DIR / "analysis.json"

    if not analysis_file.exists():
        return None

    try:
        with open(analysis_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None


def display_latest_analysis():
    """Letzte Analyse anzeigen"""
    print_section("LETZTE ANALYSE")

    analysis = load_latest_analysis()

    if not analysis:
        print(f"  {Colors.DIM}Keine Analyse gefunden{Colors.RESET}")
        return

    # Zeitstempel
    generated = analysis.get('generated_at', 'N/A')
    print(f"  {Colors.DIM}Generiert: {format_timestamp(generated)}{Colors.RESET}\n")

    # Market Input
    market = analysis.get('market_input', {})
    title = market.get('market_title', 'N/A')[:60]
    target = market.get('target_date', 'N/A')
    implied_prob = market.get('market_implied_probability', 0)

    print(f"  {Colors.BOLD}Markt:{Colors.RESET} {title}")
    print(f"  {Colors.BOLD}Zieldatum:{Colors.RESET} {target}")
    print(f"  {Colors.BOLD}Markt-Wahrscheinlichkeit:{Colors.RESET} {implied_prob*100:.1f}%")

    # Entscheidung
    decision = analysis.get('final_decision', {})
    outcome = decision.get('outcome', 'UNKNOWN')
    confidence = decision.get('confidence', 'N/A')

    print(f"\n  {Colors.BOLD}Entscheidung:{Colors.RESET} {format_decision(outcome)}")
    print(f"  {Colors.BOLD}Konfidenz:{Colors.RESET} {confidence}")

    # Kriterien
    criteria = decision.get('criteria_met', {})
    if criteria:
        print(f"\n  {Colors.BOLD}Kriterien:{Colors.RESET}")
        for name, passed in criteria.items():
            icon = format_bool(passed)
            name_fmt = name.replace('_', ' ').title()
            print(f"    {icon} {name_fmt}")

    # Blocking Criteria
    blocking = decision.get('blocking_criteria', [])
    if blocking:
        print(f"\n  {Colors.BOLD}{Colors.RED}Blockierende Kriterien:{Colors.RESET}")
        for item in blocking:
            print(f"    {Colors.RED}[X]{Colors.RESET} {item.replace('_', ' ').title()}")

    # Warnungen
    warnings = decision.get('risk_warnings', [])
    if warnings:
        print(f"\n  {Colors.BOLD}{Colors.YELLOW}Warnungen ({len(warnings)}):{Colors.RESET}")
        for warning in warnings[:5]:
            print(f"    {Colors.YELLOW}[!]{Colors.RESET} {warning[:65]}{'...' if len(warning) > 65 else ''}")
        if len(warnings) > 5:
            print(f"    {Colors.DIM}... und {len(warnings)-5} weitere{Colors.RESET}")


# =============================================================================
# STATISTIKEN
# =============================================================================

def display_statistics():
    """Statistiken anzeigen"""
    print_section("STATISTIKEN")

    logs = load_audit_logs(1000)  # Alle Logs laden

    if not logs:
        print(f"  {Colors.DIM}Keine Daten verfuegbar{Colors.RESET}")
        return

    # Entscheidungen zählen
    decisions = {"TRADE": 0, "NO_TRADE": 0, "INSUFFICIENT_DATA": 0}
    for entry in logs:
        d = entry.get('decision', '')
        if d in decisions:
            decisions[d] += 1

    total = sum(decisions.values())

    print(f"  {Colors.BOLD}Entscheidungen (gesamt: {total}):{Colors.RESET}")
    for name, count in decisions.items():
        pct = (count / total * 100) if total > 0 else 0
        bar_len = int(pct / 5)  # Max 20 Zeichen
        bar = "#" * bar_len + "." * (20 - bar_len)

        color = Colors.GREEN if name == "TRADE" else (Colors.RED if name == "NO_TRADE" else Colors.YELLOW)
        print(f"    {color}{name:20}{Colors.RESET} {bar} {count:3} ({pct:.1f}%)")

    # Disziplin-Rate
    if total > 0:
        no_trade_rate = (decisions["NO_TRADE"] + decisions["INSUFFICIENT_DATA"]) / total * 100
        print(f"\n  {Colors.BOLD}Disziplin-Rate:{Colors.RESET} {no_trade_rate:.1f}%")
        print(f"  {Colors.DIM}(NO_TRADE + INSUFFICIENT_DATA Entscheidungen){Colors.RESET}")


# =============================================================================
# PROPOSAL SYSTEM (READ-ONLY)
# =============================================================================
#
# GOVERNANCE:
# These functions provide READ-ONLY views into the proposal system.
# No modifications, no actions, no feedback loops.
#

def format_review_outcome(outcome: str) -> str:
    """Format review outcome with color."""
    if outcome == "REVIEW_PASS":
        return f"{Colors.BG_GREEN}{Colors.WHITE} PASS {Colors.RESET}"
    elif outcome == "REVIEW_HOLD":
        return f"{Colors.BG_YELLOW}{Colors.WHITE} HOLD {Colors.RESET}"
    elif outcome == "REVIEW_REJECT":
        return f"{Colors.BG_RED}{Colors.WHITE} REJECT {Colors.RESET}"
    return outcome


def load_proposals(limit: int = 50) -> List[Dict[str, Any]]:
    """
    Load proposals from storage.

    GOVERNANCE: READ-ONLY operation.
    """
    proposals_log = PROPOSALS_DIR / "proposals_log.json"

    if not proposals_log.exists():
        return []

    try:
        with open(proposals_log, 'r', encoding='utf-8') as f:
            data = json.load(f)
            proposals = data.get("proposals", [])
            # Sort by timestamp (newest first)
            proposals.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
            return proposals[:limit]
    except Exception:
        return []


def get_proposal_by_id(proposal_id: str) -> Optional[Dict[str, Any]]:
    """
    Get a specific proposal by ID.

    GOVERNANCE: READ-ONLY operation.
    """
    proposals = load_proposals(1000)  # Load all
    for p in proposals:
        if p.get('proposal_id') == proposal_id:
            return p
    return None


def display_proposals(limit: int = 20):
    """
    Display list of recent proposals.

    GOVERNANCE: READ-ONLY view. No actions triggered.
    """
    print_section("PROPOSALS (READ-ONLY)")

    proposals = load_proposals(limit)

    if not proposals:
        print(f"  {Colors.DIM}Keine Proposals vorhanden{Colors.RESET}")
        print(f"  {Colors.DIM}Proposals werden aus Analysen generiert.{Colors.RESET}")
        return

    print(f"  {Colors.DIM}Zeige {len(proposals)} Proposals (neueste zuerst){Colors.RESET}")
    print(f"  {Colors.DIM}GOVERNANCE: Dies ist eine reine Anzeige. Keine Aktionen.{Colors.RESET}\n")

    for p in proposals:
        ts = format_timestamp(p.get('timestamp', 'N/A'))
        pid = p.get('proposal_id', 'N/A')
        decision = p.get('decision', 'N/A')
        edge = p.get('edge', 0)
        confidence = p.get('confidence_level', 'N/A')
        market = p.get('market_question', 'N/A')[:40]

        decision_fmt = format_decision(decision)

        print(f"  {Colors.CYAN}{pid}{Colors.RESET}")
        print(f"    {Colors.DIM}{ts}{Colors.RESET} | {decision_fmt} | Edge: {edge:+.1%} | Conf: {confidence}")
        print(f"    {Colors.DIM}{market}...{Colors.RESET}")
        print()


def display_proposal_detail(proposal_id: str):
    """
    Display detailed view of a specific proposal.

    GOVERNANCE: READ-ONLY view. No actions triggered.
    """
    print_section(f"PROPOSAL DETAIL: {proposal_id}")

    proposal = get_proposal_by_id(proposal_id)

    if not proposal:
        print(f"  {Colors.RED}Proposal nicht gefunden: {proposal_id}{Colors.RESET}")
        return

    # Header
    print(f"\n  {Colors.BOLD}Proposal ID:{Colors.RESET} {proposal.get('proposal_id')}")
    print(f"  {Colors.BOLD}Timestamp:{Colors.RESET} {format_timestamp(proposal.get('timestamp', 'N/A'))}")

    # Market Info
    print(f"\n  {Colors.BOLD}Market:{Colors.RESET}")
    print(f"    ID: {proposal.get('market_id', 'N/A')}")
    print(f"    {proposal.get('market_question', 'N/A')[:70]}...")

    # Decision
    decision = proposal.get('decision', 'N/A')
    print(f"\n  {Colors.BOLD}Decision:{Colors.RESET} {format_decision(decision)}")

    # Probabilities
    implied = proposal.get('implied_probability', 0)
    model = proposal.get('model_probability', 0)
    edge = proposal.get('edge', 0)

    print(f"\n  {Colors.BOLD}Probabilities:{Colors.RESET}")
    print(f"    Market Implied: {implied*100:.1f}%")
    print(f"    Model Estimate: {model*100:.1f}%")
    print(f"    Edge: {edge:+.2%}")

    # Confidence
    print(f"\n  {Colors.BOLD}Confidence:{Colors.RESET} {proposal.get('confidence_level', 'N/A')}")

    # Core Criteria
    criteria = proposal.get('core_criteria', {})
    if criteria:
        print(f"\n  {Colors.BOLD}Core Criteria:{Colors.RESET}")
        for name, passed in criteria.items():
            icon = format_bool(passed)
            print(f"    {icon} {name}")

    # Warnings
    warnings = proposal.get('warnings', [])
    if warnings:
        print(f"\n  {Colors.BOLD}{Colors.YELLOW}Warnings ({len(warnings)}):{Colors.RESET}")
        for w in warnings[:5]:
            print(f"    {Colors.YELLOW}[!]{Colors.RESET} {w[:60]}...")
        if len(warnings) > 5:
            print(f"    {Colors.DIM}... und {len(warnings)-5} weitere{Colors.RESET}")

    # Justification
    justification = proposal.get('justification_summary', '')
    if justification:
        print(f"\n  {Colors.BOLD}Justification:{Colors.RESET}")
        # Word wrap at 60 chars
        words = justification.split()
        line = "    "
        for word in words[:50]:
            if len(line) + len(word) > 70:
                print(line)
                line = "    "
            line += word + " "
        if line.strip():
            print(line)

    # Governance Notice
    print(f"\n  {Colors.DIM}---{Colors.RESET}")
    print(f"  {Colors.DIM}{proposal.get('governance_notice', 'Informational only.')}{Colors.RESET}")


def display_reviews():
    """
    Display recent proposal reviews.

    GOVERNANCE: READ-ONLY view. Shows review outcomes without triggering actions.
    """
    print_section("PROPOSAL REVIEWS (READ-ONLY)")

    reviewed_md = PROPOSALS_DIR / "proposals_reviewed.md"

    if not reviewed_md.exists():
        print(f"  {Colors.DIM}Keine Reviews vorhanden{Colors.RESET}")
        return

    try:
        with open(reviewed_md, 'r', encoding='utf-8') as f:
            content = f.read()
    except Exception:
        print(f"  {Colors.RED}Fehler beim Lesen der Reviews{Colors.RESET}")
        return

    # Parse review sections
    sections = content.split("## Proposal Review - ")

    if len(sections) <= 1:
        print(f"  {Colors.DIM}Noch keine Reviews durchgefuehrt{Colors.RESET}")
        print(f"  {Colors.DIM}Reviews werden nach Proposal-Generierung erstellt.{Colors.RESET}")
        return

    print(f"  {Colors.DIM}Zeige {len(sections)-1} Reviews{Colors.RESET}")
    print(f"  {Colors.DIM}GOVERNANCE: Reine Anzeige. Keine Aktionen ausgeloest.{Colors.RESET}\n")

    # Show last 5 reviews (newest = last in file)
    for section in sections[-6:-1] if len(sections) > 6 else sections[1:]:
        lines = section.strip().split('\n')
        if not lines:
            continue

        # Extract proposal ID from first line
        pid = lines[0].strip()

        # Find outcome
        outcome = "UNKNOWN"
        for line in lines:
            if "REVIEW_PASS" in line:
                outcome = "REVIEW_PASS"
                break
            elif "REVIEW_HOLD" in line:
                outcome = "REVIEW_HOLD"
                break
            elif "REVIEW_REJECT" in line:
                outcome = "REVIEW_REJECT"
                break

        outcome_fmt = format_review_outcome(outcome)
        print(f"  {Colors.CYAN}{pid}{Colors.RESET} | {outcome_fmt}")

    print(f"\n  {Colors.DIM}Vollstaendige Reviews: {reviewed_md}{Colors.RESET}")


def display_proposal_statistics():
    """
    Display proposal statistics.

    GOVERNANCE: READ-ONLY aggregate view.
    """
    print_section("PROPOSAL STATISTIKEN")

    proposals = load_proposals(1000)

    if not proposals:
        print(f"  {Colors.DIM}Keine Proposals vorhanden{Colors.RESET}")
        return

    # Count by decision
    trade_count = sum(1 for p in proposals if p.get('decision') == 'TRADE')
    no_trade_count = sum(1 for p in proposals if p.get('decision') == 'NO_TRADE')

    # Count by confidence
    conf_low = sum(1 for p in proposals if p.get('confidence_level') == 'LOW')
    conf_med = sum(1 for p in proposals if p.get('confidence_level') == 'MEDIUM')
    conf_high = sum(1 for p in proposals if p.get('confidence_level') == 'HIGH')

    # Average edge
    edges = [abs(p.get('edge', 0)) for p in proposals]
    avg_edge = sum(edges) / len(edges) if edges else 0

    total = len(proposals)

    print(f"\n  {Colors.BOLD}Gesamt:{Colors.RESET} {total} Proposals")

    print(f"\n  {Colors.BOLD}Nach Entscheidung:{Colors.RESET}")
    print(f"    TRADE:    {trade_count:3} ({trade_count/total*100:.1f}%)")
    print(f"    NO_TRADE: {no_trade_count:3} ({no_trade_count/total*100:.1f}%)")

    print(f"\n  {Colors.BOLD}Nach Konfidenz:{Colors.RESET}")
    print(f"    HIGH:   {conf_high:3} ({conf_high/total*100:.1f}%)")
    print(f"    MEDIUM: {conf_med:3} ({conf_med/total*100:.1f}%)")
    print(f"    LOW:    {conf_low:3} ({conf_low/total*100:.1f}%)")

    print(f"\n  {Colors.BOLD}Durchschnittlicher Edge:{Colors.RESET} {avg_edge:.2%}")


# =============================================================================
# INTERAKTIVES MENU
# =============================================================================

def display_menu():
    """Hauptmenue anzeigen"""
    print(f"\n{Colors.BOLD}Optionen:{Colors.RESET}")
    print(f"  {Colors.CYAN}[1]{Colors.RESET} System Status")
    print(f"  {Colors.CYAN}[2]{Colors.RESET} Letzte Analyse")
    print(f"  {Colors.CYAN}[3]{Colors.RESET} Audit Logs")
    print(f"  {Colors.CYAN}[4]{Colors.RESET} Statistiken")
    print(f"  {Colors.CYAN}[5]{Colors.RESET} Alles anzeigen")
    print(f"\n{Colors.BOLD}Proposals (READ-ONLY):{Colors.RESET}")
    print(f"  {Colors.CYAN}[p]{Colors.RESET} Proposals Liste")
    print(f"  {Colors.CYAN}[v]{Colors.RESET} Reviews anzeigen")
    print(f"  {Colors.CYAN}[s]{Colors.RESET} Proposal Statistiken")
    print(f"\n{Colors.BOLD}Navigation:{Colors.RESET}")
    print(f"  {Colors.CYAN}[r]{Colors.RESET} Aktualisieren")
    print(f"  {Colors.CYAN}[q]{Colors.RESET} Beenden")
    print()


def interactive_mode():
    """Interaktiver Modus"""
    while True:
        clear_screen()
        print_header("POLYMARKET BEOBACHTER COCKPIT")
        print(f"  {Colors.DIM}Zeitstempel: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}{Colors.RESET}")

        display_menu()

        try:
            choice = input(f"{Colors.BOLD}Auswahl: {Colors.RESET}").strip().lower()
        except (KeyboardInterrupt, EOFError):
            print(f"\n{Colors.DIM}Beende...{Colors.RESET}")
            break

        clear_screen()
        print_header("POLYMARKET BEOBACHTER COCKPIT")

        if choice == '1':
            display_system_status()
        elif choice == '2':
            display_latest_analysis()
        elif choice == '3':
            display_audit_logs()
        elif choice == '4':
            display_statistics()
        elif choice == '5':
            display_system_status()
            display_latest_analysis()
            display_audit_logs()
            display_statistics()
        # Proposal views (READ-ONLY)
        elif choice == 'p':
            display_proposals()
        elif choice == 'v':
            display_reviews()
        elif choice == 's':
            display_proposal_statistics()
        elif choice == 'r':
            continue
        elif choice == 'q':
            print(f"\n{Colors.DIM}Auf Wiedersehen!{Colors.RESET}\n")
            break
        else:
            print(f"{Colors.RED}Ungueltige Auswahl{Colors.RESET}")

        if choice != 'r' and choice != 'q':
            input(f"\n{Colors.DIM}Enter druecken zum Fortfahren...{Colors.RESET}")


# =============================================================================
# WATCH MODE (Live-Überwachung)
# =============================================================================

def watch_mode(interval: int = 5):
    """Live-Überwachung"""
    import time

    print(f"{Colors.DIM}Live-Ueberwachung gestartet (Intervall: {interval}s, Strg+C zum Beenden){Colors.RESET}")

    try:
        while True:
            clear_screen()
            print_header("POLYMARKET BEOBACHTER - LIVE MONITOR")
            print(f"  {Colors.DIM}Aktualisiert: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}{Colors.RESET}")
            print(f"  {Colors.DIM}Naechste Aktualisierung in {interval}s (Strg+C zum Beenden){Colors.RESET}")

            display_system_status()
            display_latest_analysis()
            display_audit_logs(max_entries=10)

            time.sleep(interval)
    except KeyboardInterrupt:
        print(f"\n{Colors.DIM}Watch-Modus beendet{Colors.RESET}\n")


# =============================================================================
# MAIN
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Polymarket Beobachter - Monitoring Cockpit",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
PROPOSAL SYSTEM (READ-ONLY):
  --proposals         List recent proposals
  --proposal ID       Show details for specific proposal
  --review            Show recent reviews

GOVERNANCE: Proposal views are READ-ONLY. No actions are triggered.
"""
    )
    # Standard views
    parser.add_argument('--status', action='store_true', help='Show system status')
    parser.add_argument('--logs', action='store_true', help='Show audit logs')
    parser.add_argument('--analysis', action='store_true', help='Show latest analysis')
    parser.add_argument('--stats', action='store_true', help='Show statistics')
    parser.add_argument('--watch', action='store_true', help='Live monitoring (every 5 sec)')
    parser.add_argument('--interval', type=int, default=5, help='Interval for watch mode (sec)')

    # Proposal views (READ-ONLY)
    parser.add_argument('--proposals', action='store_true',
                        help='List recent proposals (READ-ONLY)')
    parser.add_argument('--proposal', type=str, metavar='ID',
                        help='Show proposal details by ID (READ-ONLY)')
    parser.add_argument('--review', action='store_true',
                        help='Show recent reviews (READ-ONLY)')
    parser.add_argument('--proposal-stats', action='store_true',
                        help='Show proposal statistics (READ-ONLY)')

    # Options
    parser.add_argument('--no-color', action='store_true', help='Disable colors')

    args = parser.parse_args()

    if args.no_color:
        Colors.disable()

    # Standard views
    if args.status:
        print_header("POLYMARKET BEOBACHTER")
        display_system_status()
        return

    if args.logs:
        print_header("POLYMARKET BEOBACHTER")
        display_audit_logs()
        return

    if args.analysis:
        print_header("POLYMARKET BEOBACHTER")
        display_latest_analysis()
        return

    if args.stats:
        print_header("POLYMARKET BEOBACHTER")
        display_statistics()
        return

    if args.watch:
        watch_mode(args.interval)
        return

    # Proposal views (READ-ONLY)
    if args.proposals:
        print_header("POLYMARKET BEOBACHTER - PROPOSALS")
        print(f"  {Colors.DIM}GOVERNANCE: READ-ONLY view. No actions triggered.{Colors.RESET}")
        display_proposals()
        return

    if args.proposal:
        print_header("POLYMARKET BEOBACHTER - PROPOSAL DETAIL")
        print(f"  {Colors.DIM}GOVERNANCE: READ-ONLY view. No actions triggered.{Colors.RESET}")
        display_proposal_detail(args.proposal)
        return

    if args.review:
        print_header("POLYMARKET BEOBACHTER - REVIEWS")
        print(f"  {Colors.DIM}GOVERNANCE: READ-ONLY view. No actions triggered.{Colors.RESET}")
        display_reviews()
        return

    if args.proposal_stats:
        print_header("POLYMARKET BEOBACHTER - PROPOSAL STATS")
        print(f"  {Colors.DIM}GOVERNANCE: READ-ONLY view. No actions triggered.{Colors.RESET}")
        display_proposal_statistics()
        return

    # Default: Interactive mode
    interactive_mode()


if __name__ == "__main__":
    main()
