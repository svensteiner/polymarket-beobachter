# =============================================================================
# POLYMARKET BEOBACHTER - MCP SERVER
# =============================================================================
#
# GOVERNANCE INTENT:
# Dieser MCP-Server gibt Claude die Rolle der "Führungskraft" des Trading-Bots.
# Claude kann:
# - Bot-Status und Performance einsehen
# - Konfiguration ändern (mit Governance-Regeln)
# - Proposals genehmigen/ablehnen
# - Den Bot pausieren/fortsetzen
#
# SICHERHEITSREGELN:
# - Keine direkten Trades ohne Proposal-System
# - Alle Änderungen werden geloggt
# - Live-Trading bleibt standardmäßig deaktiviert
#
# =============================================================================

import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# MCP imports
try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    print("ERROR: mcp package not installed. Run: pip install mcp")
    sys.exit(1)

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("polymarket-mcp")

# =============================================================================
# CONFIGURATION
# =============================================================================

# Project root (relative to this file)
PROJECT_ROOT = Path(__file__).parent.parent.resolve()

# Key paths
DATA_DIR = PROJECT_ROOT / "data"
CONFIG_DIR = PROJECT_ROOT / "config"
OUTPUT_DIR = PROJECT_ROOT / "output"
PAPER_TRADER_DIR = PROJECT_ROOT / "paper_trader"
LOGS_DIR = PROJECT_ROOT / "logs"
PROPOSALS_DIR = PROJECT_ROOT / "proposals"

# Config files
CAPITAL_CONFIG = DATA_DIR / "capital_config.json"
WEATHER_CONFIG = CONFIG_DIR / "weather.yaml"
BOT_STATUS_FILE = PROJECT_ROOT / "bot_status.json"
HEARTBEAT_FILE = PROJECT_ROOT / "heartbeat.txt"

# Control file for pause/resume
CONTROL_FILE = PROJECT_ROOT / "bot_control.json"

# =============================================================================
# MCP SERVER INITIALIZATION
# =============================================================================

mcp = FastMCP(
    "polymarket-beobachter",
    description="MCP Server für Polymarket Weather Bot - Claude als Führungskraft"
)

# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def _load_json(path: Path) -> Optional[Dict]:
    """Load JSON file safely."""
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Error loading {path}: {e}")
        return None


def _save_json(path: Path, data: Dict) -> bool:
    """Save JSON file with atomic write."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(".tmp")
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        tmp_path.replace(path)
        return True
    except Exception as e:
        logger.error(f"Error saving {path}: {e}")
        return False


def _load_yaml(path: Path) -> Optional[Dict]:
    """Load YAML file safely."""
    if not path.exists():
        return None
    try:
        import yaml
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    except Exception as e:
        logger.error(f"Error loading {path}: {e}")
        return None


def _save_yaml(path: Path, data: Dict) -> bool:
    """Save YAML file."""
    try:
        import yaml
        path.parent.mkdir(parents=True, exist_ok=True)
        # Backup first
        if path.exists():
            backup = path.with_suffix(".yaml.bak")
            import shutil
            shutil.copy2(path, backup)
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(data, f, default_flow_style=False, allow_unicode=True)
        return True
    except Exception as e:
        logger.error(f"Error saving {path}: {e}")
        return False


def _load_jsonl_tail(path: Path, n: int = 50) -> List[Dict]:
    """Load last N lines from JSONL file."""
    if not path.exists():
        return []
    try:
        lines = []
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    lines.append(json.loads(line))
        return lines[-n:]
    except Exception as e:
        logger.error(f"Error loading {path}: {e}")
        return []


def _log_action(action: str, details: Dict) -> None:
    """Log MCP action for audit."""
    audit_path = LOGS_DIR / "mcp_audit.jsonl"
    audit_path.parent.mkdir(parents=True, exist_ok=True)

    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "action": action,
        "details": details,
    }

    try:
        with open(audit_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as e:
        logger.error(f"Failed to log action: {e}")


# =============================================================================
# STATUS TOOLS
# =============================================================================

@mcp.tool()
def get_bot_status() -> Dict[str, Any]:
    """
    Hole den aktuellen Bot-Status.

    Gibt zurück:
    - Ist der Bot online?
    - Letzter Heartbeat
    - Anzahl Runs
    - Consecutive Errors
    - Letzter Run Zeitstempel
    """
    status = _load_json(BOT_STATUS_FILE)

    # Check heartbeat
    heartbeat_age = None
    if HEARTBEAT_FILE.exists():
        try:
            heartbeat_time = datetime.fromisoformat(
                HEARTBEAT_FILE.read_text().strip().replace("Z", "+00:00")
            )
            heartbeat_age = (datetime.now(timezone.utc) - heartbeat_time).total_seconds()
        except:
            pass

    # Determine if bot is alive
    is_alive = heartbeat_age is not None and heartbeat_age < 1200  # 20 min

    return {
        "is_alive": is_alive,
        "heartbeat_age_seconds": heartbeat_age,
        "status": status or {"error": "bot_status.json not found"},
        "project_root": str(PROJECT_ROOT),
    }


@mcp.tool()
def get_capital_status() -> Dict[str, Any]:
    """
    Hole den aktuellen Kapital-Status.

    Gibt zurück:
    - Verfügbares Kapital
    - Allokiertes Kapital
    - Realisierter P&L
    - ROI
    """
    config = _load_json(CAPITAL_CONFIG)

    if not config:
        return {"error": "capital_config.json not found"}

    initial = config.get("initial_capital_eur", 0)
    available = config.get("available_capital_eur", 0)
    allocated = config.get("allocated_capital_eur", 0)
    realized_pnl = config.get("realized_pnl_eur", 0)

    total_equity = available + allocated
    roi_pct = (realized_pnl / initial * 100) if initial > 0 else 0

    return {
        "initial_capital_eur": initial,
        "available_capital_eur": available,
        "allocated_capital_eur": allocated,
        "total_equity_eur": total_equity,
        "realized_pnl_eur": realized_pnl,
        "roi_pct": round(roi_pct, 2),
        "max_open_positions": config.get("max_open_positions", 10),
    }


@mcp.tool()
def get_open_positions() -> Dict[str, Any]:
    """
    Hole alle offenen Positionen.

    Gibt zurück:
    - Liste aller offenen Positionen mit Details
    - Anzahl Positionen
    - Gesamtes allokiertes Kapital
    """
    positions_file = PAPER_TRADER_DIR / "logs" / "paper_positions.jsonl"

    if not positions_file.exists():
        return {"positions": [], "count": 0, "total_allocated_eur": 0}

    # Load all position entries
    all_entries = _load_jsonl_tail(positions_file, 1000)

    # Find open positions (entry without matching exit)
    position_states = {}
    for entry in all_entries:
        pos_id = entry.get("position_id")
        if not pos_id:
            continue

        event_type = entry.get("event_type", entry.get("type", ""))

        if event_type in ("ENTRY", "entry", "ADDON"):
            position_states[pos_id] = entry
        elif event_type in ("EXIT", "exit", "CLOSE"):
            position_states.pop(pos_id, None)

    open_positions = list(position_states.values())
    total_allocated = sum(p.get("cost_basis_eur", 0) for p in open_positions)

    return {
        "positions": open_positions,
        "count": len(open_positions),
        "total_allocated_eur": round(total_allocated, 2),
    }


@mcp.tool()
def get_recent_trades(limit: int = 20) -> Dict[str, Any]:
    """
    Hole die letzten Trades.

    Args:
        limit: Maximale Anzahl Trades (default: 20)

    Gibt zurück:
    - Liste der letzten Trades
    - Win/Loss Statistik
    """
    trades_file = PAPER_TRADER_DIR / "logs" / "paper_trades.jsonl"

    if not trades_file.exists():
        return {"trades": [], "stats": {}}

    trades = _load_jsonl_tail(trades_file, limit)

    # Calculate stats
    wins = sum(1 for t in trades if t.get("pnl_eur", 0) > 0)
    losses = sum(1 for t in trades if t.get("pnl_eur", 0) < 0)
    total_pnl = sum(t.get("pnl_eur", 0) for t in trades)

    return {
        "trades": trades,
        "stats": {
            "count": len(trades),
            "wins": wins,
            "losses": losses,
            "win_rate": round(wins / len(trades) * 100, 1) if trades else 0,
            "total_pnl_eur": round(total_pnl, 2),
        }
    }


@mcp.tool()
def get_performance_summary() -> Dict[str, Any]:
    """
    Hole eine umfassende Performance-Zusammenfassung.

    Kombiniert:
    - Kapital-Status
    - Offene Positionen
    - Trade-Statistiken
    - Bot-Gesundheit
    """
    capital = get_capital_status()
    positions = get_open_positions()
    trades = get_recent_trades(100)
    bot_status = get_bot_status()

    return {
        "capital": capital,
        "positions": {
            "count": positions.get("count", 0),
            "total_allocated_eur": positions.get("total_allocated_eur", 0),
        },
        "trades": trades.get("stats", {}),
        "bot": {
            "is_alive": bot_status.get("is_alive", False),
            "heartbeat_age_seconds": bot_status.get("heartbeat_age_seconds"),
        },
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# =============================================================================
# CONFIGURATION TOOLS
# =============================================================================

@mcp.tool()
def get_strategy_config() -> Dict[str, Any]:
    """
    Hole die aktuelle Strategie-Konfiguration.

    Gibt zurück:
    - MIN_EDGE, MAX_ODDS, etc.
    - Alle Parameter aus weather.yaml
    """
    config = _load_yaml(WEATHER_CONFIG)

    if not config:
        return {"error": "weather.yaml not found"}

    return {
        "config": config,
        "config_path": str(WEATHER_CONFIG),
    }


@mcp.tool()
def update_strategy_param(param_name: str, new_value: Any, reason: str) -> Dict[str, Any]:
    """
    Ändere einen Strategie-Parameter.

    Args:
        param_name: Name des Parameters (z.B. "MIN_EDGE", "MAX_ODDS")
        new_value: Neuer Wert
        reason: Begründung für die Änderung (für Audit)

    GOVERNANCE:
    - Änderung wird geloggt
    - Backup wird erstellt
    - Bestimmte Parameter haben Limits
    """
    config = _load_yaml(WEATHER_CONFIG)

    if not config:
        return {"success": False, "error": "weather.yaml not found"}

    # Governance: Parameter-Limits
    PARAM_LIMITS = {
        "MIN_EDGE": (0.05, 0.50),
        "MIN_EDGE_ABSOLUTE": (0.01, 0.20),
        "MAX_ODDS": (0.10, 0.60),
        "MIN_ODDS": (0.01, 0.30),
        "KELLY_FRACTION": (0.05, 0.50),
    }

    if param_name in PARAM_LIMITS:
        min_val, max_val = PARAM_LIMITS[param_name]
        if not (min_val <= float(new_value) <= max_val):
            return {
                "success": False,
                "error": f"{param_name} must be between {min_val} and {max_val}",
            }

    old_value = config.get(param_name)
    config[param_name] = new_value

    if _save_yaml(WEATHER_CONFIG, config):
        _log_action("update_strategy_param", {
            "param": param_name,
            "old_value": old_value,
            "new_value": new_value,
            "reason": reason,
        })

        return {
            "success": True,
            "param": param_name,
            "old_value": old_value,
            "new_value": new_value,
            "reason": reason,
        }
    else:
        return {"success": False, "error": "Failed to save config"}


@mcp.tool()
def update_capital_config(
    max_open_positions: Optional[int] = None,
    position_size_eur: Optional[float] = None,
    reason: str = ""
) -> Dict[str, Any]:
    """
    Ändere Kapital-Konfiguration.

    Args:
        max_open_positions: Maximale offene Positionen (optional)
        position_size_eur: Position-Größe in EUR (optional)
        reason: Begründung

    GOVERNANCE:
    - max_open_positions: 1-50
    - position_size_eur: 10-500 EUR
    """
    config = _load_json(CAPITAL_CONFIG)

    if not config:
        return {"success": False, "error": "capital_config.json not found"}

    changes = {}

    if max_open_positions is not None:
        if not (1 <= max_open_positions <= 50):
            return {"success": False, "error": "max_open_positions must be 1-50"}
        changes["max_open_positions"] = (config.get("max_open_positions"), max_open_positions)
        config["max_open_positions"] = max_open_positions

    if position_size_eur is not None:
        if not (10 <= position_size_eur <= 500):
            return {"success": False, "error": "position_size_eur must be 10-500"}
        changes["position_size_eur"] = (config.get("position_size_eur"), position_size_eur)
        config["position_size_eur"] = position_size_eur

    if changes:
        config["last_updated"] = datetime.now(timezone.utc).isoformat()
        config["last_updated_reason"] = reason or "MCP update"

        if _save_json(CAPITAL_CONFIG, config):
            _log_action("update_capital_config", {"changes": changes, "reason": reason})
            return {"success": True, "changes": changes}

    return {"success": False, "error": "No changes specified"}


# =============================================================================
# BOT CONTROL TOOLS
# =============================================================================

@mcp.tool()
def pause_bot(reason: str) -> Dict[str, Any]:
    """
    Pausiere den Bot.

    Args:
        reason: Begründung für die Pause

    Der Bot wird keine neuen Trades eröffnen, aber offene Positionen
    werden weiter überwacht (Exit bei TP/SL).
    """
    control = _load_json(CONTROL_FILE) or {}

    control["paused"] = True
    control["paused_at"] = datetime.now(timezone.utc).isoformat()
    control["paused_reason"] = reason
    control["paused_by"] = "claude-mcp"

    if _save_json(CONTROL_FILE, control):
        _log_action("pause_bot", {"reason": reason})
        return {"success": True, "message": f"Bot pausiert: {reason}"}

    return {"success": False, "error": "Failed to save control file"}


@mcp.tool()
def resume_bot(reason: str = "") -> Dict[str, Any]:
    """
    Setze den Bot fort.

    Args:
        reason: Optionale Begründung
    """
    control = _load_json(CONTROL_FILE) or {}

    was_paused = control.get("paused", False)

    control["paused"] = False
    control["resumed_at"] = datetime.now(timezone.utc).isoformat()
    control["resumed_reason"] = reason
    control["resumed_by"] = "claude-mcp"

    if _save_json(CONTROL_FILE, control):
        _log_action("resume_bot", {"reason": reason, "was_paused": was_paused})
        return {"success": True, "message": "Bot fortgesetzt", "was_paused": was_paused}

    return {"success": False, "error": "Failed to save control file"}


@mcp.tool()
def get_bot_control_status() -> Dict[str, Any]:
    """
    Hole den aktuellen Control-Status (pausiert/aktiv).
    """
    control = _load_json(CONTROL_FILE) or {"paused": False}
    return control


# =============================================================================
# PROPOSAL TOOLS
# =============================================================================

@mcp.tool()
def get_pending_proposals() -> Dict[str, Any]:
    """
    Hole alle ausstehenden Proposals die auf Genehmigung warten.

    HINWEIS: Im aktuellen System werden Proposals automatisch ausgeführt.
    Dieses Tool zeigt die letzten generierten Proposals.
    """
    proposals_log = PROPOSALS_DIR / "proposals_log.json"

    if not proposals_log.exists():
        return {"proposals": [], "count": 0}

    data = _load_json(proposals_log)

    if not data:
        return {"proposals": [], "count": 0}

    proposals = data.get("proposals", [])

    # Filter for recent, non-executed proposals
    pending = [p for p in proposals if p.get("status") == "PENDING"]

    return {
        "proposals": pending[-20:],  # Last 20
        "count": len(pending),
    }


@mcp.tool()
def get_proposal_history(limit: int = 50) -> Dict[str, Any]:
    """
    Hole Proposal-Historie.

    Args:
        limit: Maximale Anzahl (default: 50)
    """
    proposals_log = PROPOSALS_DIR / "proposals_log.json"

    if not proposals_log.exists():
        return {"proposals": [], "count": 0}

    data = _load_json(proposals_log)

    if not data:
        return {"proposals": [], "count": 0}

    proposals = data.get("proposals", [])

    return {
        "proposals": proposals[-limit:],
        "count": len(proposals),
        "total_in_log": len(proposals),
    }


# =============================================================================
# ANALYSIS TOOLS
# =============================================================================

@mcp.tool()
def get_market_observations(limit: int = 20) -> Dict[str, Any]:
    """
    Hole die letzten Markt-Beobachtungen.

    Args:
        limit: Maximale Anzahl
    """
    obs_file = LOGS_DIR / "weather_observations.jsonl"

    if not obs_file.exists():
        return {"observations": [], "count": 0}

    observations = _load_jsonl_tail(obs_file, limit)

    # Filter for observations with edge
    with_edge = [o for o in observations if o.get("edge", 0) != 0]

    return {
        "observations": observations,
        "count": len(observations),
        "with_edge_count": len(with_edge),
    }


@mcp.tool()
def analyze_city_performance(city: Optional[str] = None) -> Dict[str, Any]:
    """
    Analysiere Performance nach Stadt.

    Args:
        city: Optional - nur diese Stadt analysieren
    """
    trades_file = PAPER_TRADER_DIR / "logs" / "paper_trades.jsonl"

    if not trades_file.exists():
        return {"error": "No trades found"}

    trades = _load_jsonl_tail(trades_file, 500)

    # Group by city
    city_stats = {}
    for trade in trades:
        trade_city = trade.get("city", "Unknown")

        if city and trade_city != city:
            continue

        if trade_city not in city_stats:
            city_stats[trade_city] = {
                "trades": 0,
                "wins": 0,
                "losses": 0,
                "total_pnl": 0,
            }

        city_stats[trade_city]["trades"] += 1
        pnl = trade.get("pnl_eur", 0)
        city_stats[trade_city]["total_pnl"] += pnl

        if pnl > 0:
            city_stats[trade_city]["wins"] += 1
        elif pnl < 0:
            city_stats[trade_city]["losses"] += 1

    # Calculate win rates
    for stats in city_stats.values():
        if stats["trades"] > 0:
            stats["win_rate"] = round(stats["wins"] / stats["trades"] * 100, 1)
            stats["total_pnl"] = round(stats["total_pnl"], 2)

    return {"city_performance": city_stats}


# =============================================================================
# DIAGNOSTIC TOOLS
# =============================================================================

@mcp.tool()
def get_logs(log_type: str = "observer", lines: int = 50) -> Dict[str, Any]:
    """
    Hole Log-Einträge.

    Args:
        log_type: "observer", "crash", "audit", "mcp"
        lines: Anzahl Zeilen
    """
    log_files = {
        "observer": LOGS_DIR / "observer.log",
        "crash": PROJECT_ROOT / "crash.log",
        "audit": LOGS_DIR / "audit" / f"observer_{datetime.now().strftime('%Y-%m-%d')}.jsonl",
        "mcp": LOGS_DIR / "mcp_audit.jsonl",
    }

    log_path = log_files.get(log_type)

    if not log_path or not log_path.exists():
        return {"error": f"Log file not found: {log_type}"}

    try:
        with open(log_path, "r", encoding="utf-8") as f:
            all_lines = f.readlines()

        return {
            "log_type": log_type,
            "path": str(log_path),
            "lines": all_lines[-lines:],
            "total_lines": len(all_lines),
        }
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def health_check() -> Dict[str, Any]:
    """
    Führe einen umfassenden Health-Check durch.

    Prüft:
    - Bot-Heartbeat
    - Kritische Dateien
    - Disk Space (data directory)
    - Letzte Aktivität
    """
    checks = {}

    # Heartbeat check
    if HEARTBEAT_FILE.exists():
        try:
            heartbeat_time = datetime.fromisoformat(
                HEARTBEAT_FILE.read_text().strip().replace("Z", "+00:00")
            )
            age = (datetime.now(timezone.utc) - heartbeat_time).total_seconds()
            checks["heartbeat"] = {
                "status": "OK" if age < 1200 else "STALE",
                "age_seconds": age,
                "last_beat": heartbeat_time.isoformat(),
            }
        except Exception as e:
            checks["heartbeat"] = {"status": "ERROR", "error": str(e)}
    else:
        checks["heartbeat"] = {"status": "MISSING"}

    # Critical files
    critical_files = [
        ("capital_config", CAPITAL_CONFIG),
        ("weather_config", WEATHER_CONFIG),
        ("bot_status", BOT_STATUS_FILE),
    ]

    checks["files"] = {}
    for name, path in critical_files:
        checks["files"][name] = {
            "exists": path.exists(),
            "path": str(path),
        }

    # Data directory size
    try:
        total_size = sum(f.stat().st_size for f in DATA_DIR.rglob("*") if f.is_file())
        checks["data_size_mb"] = round(total_size / (1024 * 1024), 1)
    except:
        checks["data_size_mb"] = None

    # Overall status
    all_ok = (
        checks.get("heartbeat", {}).get("status") == "OK" and
        all(f["exists"] for f in checks.get("files", {}).values())
    )

    checks["overall_status"] = "HEALTHY" if all_ok else "DEGRADED"

    return checks


# =============================================================================
# SERVER ENTRY POINT
# =============================================================================

def run_server():
    """Start the MCP server."""
    logger.info(f"Starting Polymarket MCP Server")
    logger.info(f"Project root: {PROJECT_ROOT}")
    mcp.run()


if __name__ == "__main__":
    run_server()
