# =============================================================================
# LLM STRATEGY AGENT  —  Stufe 2: Direkter Eingriff + Feedback-Loop
# =============================================================================
#
# Provider-Prioritaet (Fallback):
#   1. Kimi (moonshot-v1-8k)
#   2. OpenRouter (openai/gpt-4o-mini)
#   3. OpenAI (gpt-4o-mini)
#
# Tools:
#   READ:    read_performance, read_recent_positions, read_population_status,
#            read_market_condition, read_previous_diagnosis
#   ANALYZE: evaluate_hint_impact, run_backtest
#   ACT:     set_mutation_bias, adjust_config
#   WRITE:   write_diagnosis
#
# Ablauf:
#   Lesen → Hypothese bilden → Backtest validieren → Config anpassen
#   → Mutations-Hints setzen → Diagnose schreiben → Telegram-Alert
#
# Wird nach jedem Evolutions-Tick aufgerufen (alle 50 Pipeline-Runs).
#
# =============================================================================

from __future__ import annotations

import json
import logging
import os
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent
CONFIG_FILE  = PROJECT_ROOT / "config" / "weather.yaml"
HINTS_FILE   = PROJECT_ROOT / "data" / "evolution" / "strategy_hints.json"
DIAGNOSIS_FILE    = PROJECT_ROOT / "data" / "evolution" / "strategy_diagnosis.json"
CONFIG_LOG_FILE      = PROJECT_ROOT / "data" / "evolution" / "config_change_log.jsonl"
CODE_PATCH_LOG_FILE  = PROJECT_ROOT / "data" / "evolution" / "code_patch_log.jsonl"
GOALS_FILE           = PROJECT_ROOT / "data" / "evolution" / "goals.json"
AB_TEST_FILE         = PROJECT_ROOT / "data" / "evolution" / "ab_test.json"
CODE_PROPOSALS_FILE  = PROJECT_ROOT / "data" / "evolution" / "code_proposals.jsonl"
POSITIONS_FILE       = PROJECT_ROOT / "paper_trader" / "logs" / "paper_positions.jsonl"
CHANGE_BASELINE_FILE = PROJECT_ROOT / "data" / "evolution" / "change_baseline.json"

# =============================================================================
# PROVIDER CONFIGURATION
# =============================================================================

# 3-Tier: Tier2=Kimi Primary, Tier1=OpenAI Fallback, Tier3=OpenAI gpt-5.1
PROVIDERS = [
    {
        "name": "Kimi",          # Tier 2: mittel (Analyse, Strategy)
        "env_key": "KIMI_API_KEY",
        "base_url": "https://api.moonshot.ai/v1",
        "model": "moonshot-v1-32k",
    },
    {
        "name": "OpenAI",        # Tier 1 Fallback: leicht
        "env_key": "OPENAI_API_KEY",
        "base_url": None,
        "model": "gpt-4.1-mini",
    },
    {
        "name": "OpenAI-Code",   # Tier 3: wichtig (Code-Evolution)
        "env_key": "OPENAI_API_KEY",
        "base_url": None,
        "model": "gpt-5.1",
    },
]

# =============================================================================
# CONFIG-PARAMETER CONSTRAINTS
# Nur diese Parameter darf der Agent direkt aendern.
# Ranges sind enge Safety-Guardrails.
# =============================================================================

CONFIG_PARAMS: dict[str, dict] = {
    "MIN_EDGE":                       {"min": 0.06,  "max": 0.30,  "desc": "Relativer Edge-Floor"},
    "MIN_EDGE_ABSOLUTE":              {"min": 0.02,  "max": 0.12,  "desc": "Absoluter Edge-Floor"},
    "MIN_ODDS":                       {"min": 0.05,  "max": 0.40,  "desc": "Minimale Market-Odds (Longshot-Schutz)"},
    "MAX_ODDS":                       {"min": 0.15,  "max": 0.50,  "desc": "Maximale Market-Odds"},
    "MIN_LIQUIDITY":                  {"min": 10.0,  "max": 500.0, "desc": "Mindest-Liquiditaet USD"},
    "MEDIUM_CONFIDENCE_EDGE_MULTIPLIER": {"min": 1.0, "max": 2.5,  "desc": "Edge-Multiplikator MEDIUM"},
    "SAFETY_BUFFER_HOURS":            {"min": 6.0,   "max": 48.0,  "desc": "Safety-Buffer vor Resolution"},
}

# Max Aenderung pro Call: 25% des aktuellen Wertes
MAX_CHANGE_PCT = 0.25

# =============================================================================
# CODE-PATCH WHITELIST
# Nur diese Konstanten in diesen Dateien darf der Agent auto-editieren.
# =============================================================================

CODE_PATCH_WHITELIST: dict[str, dict] = {
    "paper_trader/kelly.py": {
        "MIN_POSITION_EUR":     {"min": 10.0,  "max": 150.0,  "desc": "Min Position EUR"},
        "MAX_POSITION_EUR":     {"min": 100.0, "max": 500.0,  "desc": "Max Position EUR"},
        "KELLY_FRACTION":       {"min": 0.10,  "max": 0.50,   "desc": "Kelly-Bruch"},
        "FALLBACK_POSITION_EUR":{"min": 25.0,  "max": 150.0,  "desc": "Fallback Position EUR"},
    },
    "paper_trader/position_manager.py": {
        "TP1_PCT":       {"min": 0.05, "max": 0.20,  "desc": "Take-Profit 1 (erste Teilschliessung)"},
        "TP2_PCT":       {"min": 0.10, "max": 0.30,  "desc": "Take-Profit 2"},
        "TP3_PCT":       {"min": 0.15, "max": 0.40,  "desc": "Take-Profit 3"},
        "STOP_LOSS_PCT": {"min": -0.40,"max": -0.10, "desc": "Stop-Loss (negativ)"},
    },
    "paper_trader/averaging_down.py": {
        "MIN_PRICE_DROP_PCT":   {"min": 0.05, "max": 0.25, "desc": "Min Kursrueckgang fuer Nachkauf"},
        "MIN_EDGE_IMPROVEMENT": {"min": 0.02, "max": 0.15, "desc": "Min Edge-Verbesserung fuer Nachkauf"},
    },
}

# =============================================================================
# TOOL DEFINITIONS  (OpenAI Function-Calling Format)
# =============================================================================

TOOLS = [
    # --- READ TOOLS ---
    {
        "type": "function",
        "function": {
            "name": "read_performance",
            "description": "Lese Performance-Report: Win-Rate, PnL, Profit-Factor, Drawdown, Brier Score.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_recent_positions",
            "description": "Lese die letzten N abgeschlossenen Positionen.",
            "parameters": {
                "type": "object",
                "properties": {
                    "n": {"type": "integer", "description": "Anzahl (default: 30)"}
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_population_status",
            "description": "Lese Evolution-Population: Generation, Champion, Fitness, Parameter.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_market_condition",
            "description": "Lese aktuelle Marktbedingung.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_previous_diagnosis",
            "description": "Lese letzte Diagnose inkl. welche Hints/Config-Aenderungen damals gemacht wurden.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_current_config",
            "description": "Lese die aktuellen Werte aller aenderbaren Config-Parameter aus weather.yaml.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    # --- ANALYZE TOOLS ---
    {
        "type": "function",
        "function": {
            "name": "evaluate_hint_impact",
            "description": (
                "Vergleiche Metriken vor/nach den letzten Mutations-Hints. "
                "Beantwortet: Hat der letzte Eingriff geholfen?"
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_backtest",
            "description": (
                "Mini-Backtest: Replay historischer Positionen mit hypothetischen Parametern. "
                "Gibt an wie viele Trades wir unter neuen Parametern eingegangen waeren "
                "und wie die simulierte Win-Rate/PnL waere."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "min_edge":          {"type": "number", "description": "Relativer Edge-Floor (z.B. 0.15)"},
                    "min_edge_absolute": {"type": "number", "description": "Absoluter Edge-Floor (z.B. 0.05)"},
                    "max_odds":          {"type": "number", "description": "Max Market-Odds (z.B. 0.35)"},
                    "min_liquidity":     {"type": "number", "description": "Min Liquiditaet USD (z.B. 50)"},
                },
                "required": [],
            },
        },
    },
    # --- ACTION TOOLS ---
    {
        "type": "function",
        "function": {
            "name": "adjust_config",
            "description": (
                "Aendere einen Config-Parameter DIREKT in config/weather.yaml. "
                "Nur erlaubte Parameter, max 25% Aenderung pro Call. "
                "Backup wird automatisch erstellt. Wirkung ab naechstem Pipeline-Run."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "param": {
                        "type": "string",
                        "description": (
                            "Parameter-Name. Erlaubt: "
                            + ", ".join(CONFIG_PARAMS.keys())
                        ),
                    },
                    "value": {
                        "type": "number",
                        "description": "Neuer Wert (innerhalb der erlaubten Range)",
                    },
                    "reason": {
                        "type": "string",
                        "description": "Begruendung basierend auf Daten",
                    },
                },
                "required": ["param", "value", "reason"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_mutation_bias",
            "description": (
                "Setze Bias fuer naechste Evolution-Mutation. "
                "Ergaenzend zu adjust_config: lenkt langfristige Parameter-Suche."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "param": {
                        "type": "string",
                        "description": "Evolution-Parameter (min_edge, kelly_fraction, etc.)",
                    },
                    "direction": {"type": "string", "enum": ["up", "down", "reset"]},
                    "strength":  {"type": "number", "description": "0.1-1.0"},
                    "reason":    {"type": "string"},
                },
                "required": ["param", "direction"],
            },
        },
    },
    # --- GOAL TRACKING ---
    {
        "type": "function",
        "function": {
            "name": "set_goal",
            "description": (
                "Setze ein messbares Ziel mit Deadline. "
                "Beispiel: Win-Rate auf 55% in 14 Tagen. "
                "Ersetzt vorherige Ziele fuer dieselbe Metrik."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "metric": {
                        "type": "string",
                        "enum": ["win_rate_pct", "profit_factor", "total_pnl_eur", "trade_count"],
                        "description": "Zu verbessernde Metrik",
                    },
                    "target": {"type": "number", "description": "Zielwert"},
                    "deadline_days": {"type": "integer", "description": "Tage bis Deadline"},
                    "reason": {"type": "string", "description": "Warum dieses Ziel?"},
                },
                "required": ["metric", "target", "deadline_days"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_goals",
            "description": "Pruefe alle aktiven Ziele gegen aktuelle Metriken. Zeigt Fortschritt und Abweichungen.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    # --- A/B TEST ---
    {
        "type": "function",
        "function": {
            "name": "start_ab_test",
            "description": (
                "Starte einen A/B-Test: Vergleiche Control (aktuelle Config) "
                "gegen Challenger (neue Parameter) via Backtest auf historischen Daten. "
                "Ergebnis wird sofort zurueckgegeben."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "challenger_params": {
                        "type": "object",
                        "description": "Neue Parameter zum Testen (min_edge, max_odds, min_liquidity, min_edge_absolute)",
                    },
                    "description": {
                        "type": "string",
                        "description": "Was wird getestet und warum?",
                    },
                },
                "required": ["challenger_params", "description"],
            },
        },
    },
    # --- CODE PROPOSALS ---
    {
        "type": "function",
        "function": {
            "name": "propose_code_change",
            "description": (
                "Schlage eine Code-Aenderung vor die zu gross/riskant fuer automatischen Eingriff ist. "
                "Schreibt Vorschlag in Datei + Telegram-Alert. Mensch entscheidet ob Umsetzung."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "file": {"type": "string", "description": "Betroffene Datei (z.B. paper_trader/kelly.py)"},
                    "title": {"type": "string", "description": "Kurztitel des Vorschlags"},
                    "description": {"type": "string", "description": "Was und warum geaendert werden soll"},
                    "expected_impact": {"type": "string", "description": "Erwartete Auswirkung auf Performance"},
                    "priority": {"type": "string", "enum": ["LOW", "MEDIUM", "HIGH"]},
                },
                "required": ["file", "title", "description", "priority"],
            },
        },
    },
    # --- AUTO CODE EDIT ---
    {
        "type": "function",
        "function": {
            "name": "apply_code_patch",
            "description": (
                "Aendere eine Konstante DIREKT im Python-Code (Whitelist). "
                "Fuehrt Syntax-Check durch, committed automatisch via Git. "
                "Nur fuer kalibrierbare Zahlen-Konstanten (Kelly, TP/SL, Sizing). "
                "Telegram-Alert wird gesendet."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "file": {
                        "type": "string",
                        "description": (
                            "Relative Datei. Erlaubt: "
                            + ", ".join(CODE_PATCH_WHITELIST.keys())
                        ),
                    },
                    "constant": {
                        "type": "string",
                        "description": "Name der Konstante (z.B. KELLY_FRACTION, STOP_LOSS_PCT)",
                    },
                    "value": {
                        "type": "number",
                        "description": "Neuer Wert",
                    },
                    "reason": {
                        "type": "string",
                        "description": "Datenbasierte Begruendung",
                    },
                },
                "required": ["file", "constant", "value", "reason"],
            },
        },
    },
    # --- WRITE TOOLS ---
    {
        "type": "function",
        "function": {
            "name": "write_diagnosis",
            "description": "Schreibe finale Diagnose. IMMER als letztes Tool.",
            "parameters": {
                "type": "object",
                "properties": {
                    "summary":           {"type": "string"},
                    "root_causes":       {"type": "array", "items": {"type": "string"}},
                    "hypotheses":        {"type": "array", "items": {"type": "string"}},
                    "config_changes":    {"type": "array", "items": {"type": "string"},
                                         "description": "Liste der Config-Aenderungen"},
                    "mutations_applied": {"type": "array", "items": {"type": "string"}},
                    "hint_impact":       {"type": "string",
                                         "description": "Bewertung ob letzte Hints geholfen haben"},
                    "goals_status":      {"type": "string",
                                         "description": "Kurz-Status der aktiven Ziele"},
                    "code_patches":      {"type": "array", "items": {"type": "string"},
                                         "description": "Liste der auto-editierten Code-Konstanten"},
                    "code_proposals":    {"type": "array", "items": {"type": "string"},
                                         "description": "Titel der vorgeschlagenen Code-Aenderungen"},
                    "grade": {"type": "string", "enum": ["HEALTHY", "DEGRADED", "CRITICAL"]},
                },
                "required": ["summary", "root_causes", "hypotheses", "grade"],
            },
        },
    },
]

# =============================================================================
# HELPER: POSITIONS LADEN
# =============================================================================

def _snapshot_current_metrics() -> dict:
    """Erstelle Snapshot aktueller Metriken + letzter Position-ID (fuer Before/After-Vergleich)."""
    positions = _load_all_positions_raw()
    closed = [p for p in positions if p.get("status") in ("CLOSED", "RESOLVED")]
    closed.sort(key=lambda p: p.get("exit_time", ""))

    pnls = [p.get("realized_pnl_eur") or p.get("pnl_eur") or 0 for p in closed]
    wins = [x for x in pnls if x > 0]

    perf_file = PROJECT_ROOT / "analytics" / "performance_report.json"
    total_pnl = 0.0
    if perf_file.exists():
        try:
            perf = json.loads(perf_file.read_text(encoding="utf-8"))
            total_pnl = float(perf.get("metrics", {}).get("total_pnl_eur", 0) or 0)
        except Exception:
            total_pnl = sum(pnls)

    return {
        "timestamp": datetime.now().isoformat(),
        "total_closed_trades": len(closed),
        "win_rate": round(len(wins) / len(closed), 4) if closed else 0.0,
        "total_pnl_eur": round(total_pnl, 2),
        "last_position_id": closed[-1].get("position_id", "") if closed else "",
        "last_exit_time": closed[-1].get("exit_time", "") if closed else "",
    }


def _write_change_baseline(param: str, old_value: float, new_value: float, reason: str) -> None:
    """Speichere Baseline-Snapshot wenn eine Config-Aenderung gemacht wird."""
    snapshot = _snapshot_current_metrics()
    baseline = {
        "param": param,
        "old_value": old_value,
        "new_value": new_value,
        "reason": reason,
        "changed_at": datetime.now().isoformat(),
        **{f"before_{k}": v for k, v in snapshot.items() if k != "timestamp"},
    }
    CHANGE_BASELINE_FILE.parent.mkdir(parents=True, exist_ok=True)
    CHANGE_BASELINE_FILE.write_text(json.dumps(baseline, indent=2, ensure_ascii=False), encoding="utf-8")


def _evaluate_change_impact_detailed() -> dict:
    """
    Echter Before/After-Vergleich: Trades vor vs. nach letzter Config-Aenderung.
    Nutzt Timestamps um Trades korrekt zu bucketen.
    """
    if not CHANGE_BASELINE_FILE.exists():
        return {"error": "Kein Baseline-Snapshot gefunden. Noch keine Config-Aenderung mit Tracking."}

    baseline = json.loads(CHANGE_BASELINE_FILE.read_text(encoding="utf-8"))
    changed_at = baseline.get("changed_at", "")
    if not changed_at:
        return {"error": "Baseline hat keinen Timestamp"}

    positions = _load_all_positions_raw()
    closed = [p for p in positions if p.get("status") in ("CLOSED", "RESOLVED")]

    before = [p for p in closed if (p.get("exit_time") or "") < changed_at]
    after  = [p for p in closed if (p.get("exit_time") or "") >= changed_at]

    def _stats(ps: list) -> dict:
        pnls = [p.get("realized_pnl_eur") or p.get("pnl_eur") or 0 for p in ps]
        wins = [x for x in pnls if x > 0]
        losses = [x for x in pnls if x < 0]
        return {
            "trades": len(ps),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": round(len(wins) / len(ps), 3) if ps else 0.0,
            "total_pnl_eur": round(sum(pnls), 2),
            "avg_pnl_eur": round(sum(pnls) / len(ps), 2) if ps else 0.0,
        }

    before_stats = _stats(before)
    after_stats  = _stats(after)

    # Urteil
    verdict = "INSUFFICIENT_DATA"
    if after_stats["trades"] >= 5:
        if after_stats["win_rate"] > before_stats["win_rate"] * 1.1:
            verdict = "IMPROVED"
        elif after_stats["win_rate"] < before_stats["win_rate"] * 0.8 and after_stats["trades"] >= 10:
            verdict = "DEGRADED"
        else:
            verdict = "NEUTRAL"

    return {
        "change": {
            "param": baseline.get("param"),
            "old_value": baseline.get("old_value"),
            "new_value": baseline.get("new_value"),
            "changed_at": changed_at[:16],
            "reason": baseline.get("reason", "")[:100],
        },
        "before": before_stats,
        "after": after_stats,
        "verdict": verdict,
        "recommendation": {
            "IMPROVED":           "Aenderung hat geholfen. Ggf. weitergehen.",
            "DEGRADED":           "Aenderung hat geschadet. Revert empfohlen.",
            "NEUTRAL":            "Kein klarer Effekt. Weiter beobachten.",
            "INSUFFICIENT_DATA":  f"Nur {after_stats['trades']} Trades nach Aenderung. Mind. 5 noetig.",
        }.get(verdict, ""),
    }


def _load_all_positions_raw() -> list[dict]:
    """Lade alle Positionen (inkl. OPEN) ohne Dedup."""
    if not POSITIONS_FILE.exists():
        return []
    result = []
    try:
        for line in POSITIONS_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                p = json.loads(line)
                if p.get("_type") != "LOG_HEADER" and p.get("position_id"):
                    result.append(p)
            except Exception:
                pass
    except Exception:
        return []
    return result


def _load_all_positions() -> list[dict]:
    """Lade alle abgeschlossenen Positionen."""
    if not POSITIONS_FILE.exists():
        return []
    by_id: dict[str, dict] = {}
    try:
        for line in POSITIONS_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                p = json.loads(line)
                if p.get("_type") != "LOG_HEADER" and p.get("position_id"):
                    by_id[p["position_id"]] = p
            except Exception:
                pass
    except Exception:
        return []
    return [p for p in by_id.values() if p.get("status") in ("CLOSED", "RESOLVED")]


# =============================================================================
# HELPER: CONFIG LESEN/SCHREIBEN
# =============================================================================

def _read_config_values() -> dict[str, float]:
    """Lese aktuelle numerische Werte der erlaubten Config-Parameter."""
    result = {}
    if not CONFIG_FILE.exists():
        return result
    text = CONFIG_FILE.read_text(encoding="utf-8")
    for param in CONFIG_PARAMS:
        m = re.search(rf"^{param}:\s*([0-9.]+)", text, re.MULTILINE)
        if m:
            try:
                result[param] = float(m.group(1))
            except ValueError:
                pass
    return result


def _write_config_value(param: str, new_value: float) -> bool:
    """Aendere einen einzelnen Parameter in weather.yaml (in-place, Kommentare bleiben)."""
    if not CONFIG_FILE.exists():
        return False
    text = CONFIG_FILE.read_text(encoding="utf-8")
    # Suche nach "PARAM: <zahl>" (mit optionalem Leerzeichen)
    pattern = rf"(^{re.escape(param)}:\s*)([0-9.]+)"
    new_text, count = re.subn(pattern, rf"\g<1>{new_value}", text, flags=re.MULTILINE)
    if count == 0:
        return False
    CONFIG_FILE.write_text(new_text, encoding="utf-8")
    return True


def _backup_config() -> str:
    """Erstelle Backup der weather.yaml. Gibt Backup-Pfad zurueck."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = CONFIG_FILE.parent / f"weather_backup_{ts}.yaml"
    shutil.copy2(CONFIG_FILE, backup)
    return str(backup)


# =============================================================================
# TOOL EXECUTION
# =============================================================================

VALID_EVOLUTION_PARAMS = {
    "min_edge", "min_edge_absolute", "kelly_fraction", "max_odds",
    "take_profit_pct", "stop_loss_pct", "avg_down_threshold_pct",
    "variance_threshold", "medium_confidence_multiplier", "min_liquidity",
}


def _execute_tool(name: str, inputs: dict) -> Any:

    # ---- READ TOOLS ----

    if name == "read_performance":
        f = PROJECT_ROOT / "analytics" / "performance_report.json"
        return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {"error": "Kein Report"}

    elif name == "read_recent_positions":
        n = inputs.get("n", 30)
        positions = _load_all_positions()
        positions.sort(key=lambda p: p.get("exit_time", ""), reverse=True)
        # Entry-Price Verteilung berechnen (kritisch für Longshot-Diagnose)
        all_entries = [p.get("entry_price") or 0 for p in positions if p.get("entry_price")]
        entry_buckets = {
            "under_5pct":  sum(1 for e in all_entries if e < 0.05),
            "5_to_15pct":  sum(1 for e in all_entries if 0.05 <= e < 0.15),
            "15_to_30pct": sum(1 for e in all_entries if 0.15 <= e < 0.30),
            "over_30pct":  sum(1 for e in all_entries if e >= 0.30),
        }
        avg_entry = round(sum(all_entries) / len(all_entries), 4) if all_entries else 0

        return {
            "positions": [
                {
                    "market": p.get("market_question", "?")[:60],
                    "side": p.get("side"),
                    "entry": p.get("entry_price"),
                    "exit": p.get("exit_price"),
                    "pnl_eur": p.get("realized_pnl_eur") or p.get("pnl_eur"),
                    "pnl_pct": p.get("pnl_pct"),
                    "exit_reason": p.get("exit_reason"),
                    "city": p.get("city"),
                    "confidence": p.get("confidence_level"),
                    "edge": p.get("initial_edge"),
                }
                for p in positions[:n]
            ],
            "count": len(positions),
            "entry_price_distribution": entry_buckets,
            "avg_entry_price": avg_entry,
            "longshot_warning": entry_buckets["under_5pct"] > len(all_entries) * 0.3 if all_entries else False,
        }

    elif name == "read_population_status":
        pop_file = PROJECT_ROOT / "data" / "evolution" / "population.json"
        if not pop_file.exists():
            return {"error": "Keine Population"}
        pop = json.loads(pop_file.read_text(encoding="utf-8"))
        agents_dir = PROJECT_ROOT / "data" / "evolution" / "agents"
        summaries = []
        for aid in pop.get("agents", []):
            af = agents_dir / aid / "agent.json"
            if af.exists():
                try:
                    a = json.loads(af.read_text(encoding="utf-8"))
                    summaries.append({
                        "id": a["agent_id"],
                        "generation": a.get("generation"),
                        "status": a.get("status"),
                        "fitness": a.get("fitness", {}),
                        "params": a.get("params", {}),
                    })
                except Exception:
                    pass
        return {
            "generation": pop.get("generation"),
            "total_runs": pop.get("total_runs"),
            "champion_id": pop.get("champion_id"),
            "agents": summaries,
        }

    elif name == "read_market_condition":
        f = PROJECT_ROOT / "data" / "market_condition.json"
        return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {"condition": "UNKNOWN"}

    elif name == "read_previous_diagnosis":
        return json.loads(DIAGNOSIS_FILE.read_text(encoding="utf-8")) if DIAGNOSIS_FILE.exists() else {"error": "Keine vorherige Diagnose"}

    elif name == "read_current_config":
        values = _read_config_values()
        result = {}
        for param, val in values.items():
            meta = CONFIG_PARAMS.get(param, {})
            result[param] = {
                "current": val,
                "min": meta.get("min"),
                "max": meta.get("max"),
                "desc": meta.get("desc"),
            }
        return result

    # ---- ANALYZE TOOLS ----

    elif name == "evaluate_hint_impact":
        """Echter Before/After-Vergleich anhand Timestamps der letzten Config-Aenderung."""
        return _evaluate_change_impact_detailed()

    elif name == "run_backtest":
        """Mini-Backtest: Replay historischer Positionen mit neuen Parametern."""
        positions = _load_all_positions()
        if not positions:
            return {"error": "Keine historischen Positionen", "trades": 0}

        # Parameter
        min_edge     = float(inputs.get("min_edge", 0.12))
        min_edge_abs = float(inputs.get("min_edge_absolute", 0.05))
        max_odds     = float(inputs.get("max_odds", 0.35))
        min_liq      = float(inputs.get("min_liquidity", 50.0))

        # Filtern: welche Trades haetten wir unter neuen Params gemacht?
        taken = []
        for p in positions:
            entry = p.get("entry_price", 0) or 0
            edge  = p.get("initial_edge") or p.get("edge") or 0
            liq   = p.get("liquidity_usd", 100) or 100

            # Odds-Filter
            if entry > max_odds:
                continue
            # Edge-Filter (relativer Edge)
            if edge and abs(edge) < min_edge:
                continue
            # Absoluter Edge (entry_price als Proxy)
            if abs(entry - 0.5) < min_edge_abs:
                continue
            # Liquiditaet
            if liq < min_liq:
                continue
            taken.append(p)

        if not taken:
            return {
                "params_tested": inputs,
                "trades_would_take": 0,
                "trades_total": len(positions),
                "note": "Kein Trade wuerde die neuen Filter passieren",
            }

        pnls   = [p.get("realized_pnl_eur") or p.get("pnl_eur") or 0 for p in taken]
        wins   = [x for x in pnls if x > 0]
        losses = [x for x in pnls if x < 0]
        win_rate = len(wins) / len(taken) if taken else 0
        pf = (sum(wins) / abs(sum(losses))) if losses else (5.0 if wins else 0.0)

        # Vergleich: aktuelle Parameter
        current_pnls = [p.get("realized_pnl_eur") or p.get("pnl_eur") or 0 for p in positions]
        current_wins = [x for x in current_pnls if x > 0]

        return {
            "params_tested": inputs,
            "trades_would_take": len(taken),
            "trades_total": len(positions),
            "simulated_win_rate": round(win_rate, 3),
            "simulated_pnl_eur": round(sum(pnls), 2),
            "simulated_profit_factor": round(pf, 3),
            "current_win_rate": round(len(current_wins) / len(positions), 3) if positions else 0,
            "current_pnl_eur": round(sum(current_pnls), 2),
        }

    # ---- ACTION TOOLS ----

    elif name == "adjust_config":
        param  = inputs.get("param", "")
        value  = inputs.get("value")
        reason = inputs.get("reason", "")

        if param not in CONFIG_PARAMS:
            return {"error": f"Parameter '{param}' nicht erlaubt. Erlaubt: {list(CONFIG_PARAMS.keys())}"}
        if value is None:
            return {"error": "Kein Wert angegeben"}

        value = float(value)
        meta = CONFIG_PARAMS[param]

        # Range-Check
        if value < meta["min"] or value > meta["max"]:
            return {
                "error": f"Wert {value} ausserhalb Range [{meta['min']}, {meta['max']}]",
                "param": param,
            }

        # Max-Change-Check
        current_vals = _read_config_values()
        current = current_vals.get(param)
        if current is not None and current != 0:
            change_pct = abs(value - current) / abs(current)
            if change_pct > MAX_CHANGE_PCT:
                allowed_min = round(current * (1 - MAX_CHANGE_PCT), 4)
                allowed_max = round(current * (1 + MAX_CHANGE_PCT), 4)
                return {
                    "error": f"Aenderung zu gross ({change_pct:.0%} > {MAX_CHANGE_PCT:.0%}). "
                             f"Max erlaubt: [{allowed_min}, {allowed_max}]",
                    "current_value": current,
                }

        # Backup + Schreiben
        backup_path = _backup_config()
        success = _write_config_value(param, value)
        if not success:
            return {"error": f"Konnte '{param}' nicht in weather.yaml schreiben"}

        # Baseline-Snapshot fuer spaeteres Before/After-Tracking
        try:
            _write_change_baseline(param, current, value, reason)
        except Exception as e:
            logger.debug(f"Baseline-Snapshot fehlgeschlagen (unkritisch): {e}")

        # Change-Log (mit Metriken zum Zeitpunkt der Aenderung)
        try:
            snap = _snapshot_current_metrics()
        except Exception:
            snap = {}
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "param": param,
            "old_value": current,
            "new_value": value,
            "reason": reason,
            "backup": backup_path,
            "trades_at_change": snap.get("total_closed_trades"),
            "win_rate_at_change": snap.get("win_rate"),
            "pnl_at_change": snap.get("total_pnl_eur"),
        }
        CONFIG_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(CONFIG_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")

        logger.info(f"Config geaendert: {param} {current} -> {value} | {reason}")
        return {
            "ok": True,
            "param": param,
            "old_value": current,
            "new_value": value,
            "action": f"{param}: {current} → {value} ({reason})",
            "note": "Wirksam ab naechstem Pipeline-Run",
        }

    elif name == "set_mutation_bias":
        param     = inputs.get("param", "")
        direction = inputs.get("direction", "reset")
        strength  = float(inputs.get("strength", 0.5))
        reason    = inputs.get("reason", "")

        if param not in VALID_EVOLUTION_PARAMS:
            return {"error": f"Ungueltiger Evolution-Parameter: {param}"}

        strength = max(0.1, min(1.0, strength))
        hints: dict = {}
        if HINTS_FILE.exists():
            try:
                hints = json.loads(HINTS_FILE.read_text(encoding="utf-8"))
            except Exception:
                pass

        if direction == "reset":
            hints.pop(param, None)
            action = f"Bias '{param}' zurueckgesetzt"
        else:
            hints[param] = {
                "direction": direction,
                "strength": strength,
                "reason": reason,
                "set_at": datetime.now().isoformat(),
            }
            action = f"'{param}' → {direction} (strength={strength:.1f}): {reason}"

        HINTS_FILE.parent.mkdir(parents=True, exist_ok=True)
        HINTS_FILE.write_text(json.dumps(hints, indent=2, ensure_ascii=False), encoding="utf-8")
        logger.info(f"Mutation Hint: {action}")
        return {"ok": True, "action": action, "total_hints": len(hints)}

    # ---- GOAL TRACKING ----

    elif name == "set_goal":
        metric   = inputs.get("metric", "")
        target   = float(inputs.get("target", 0))
        days     = int(inputs.get("deadline_days", 14))
        reason   = inputs.get("reason", "")

        goals: dict = {"goals": []}
        if GOALS_FILE.exists():
            try:
                goals = json.loads(GOALS_FILE.read_text(encoding="utf-8"))
            except Exception:
                pass

        # Perf-Baseline lesen
        baseline = 0.0
        perf_file = PROJECT_ROOT / "analytics" / "performance_report.json"
        if perf_file.exists():
            try:
                perf = json.loads(perf_file.read_text(encoding="utf-8"))
                baseline = float(perf.get("metrics", {}).get(metric, 0) or 0)
            except Exception:
                pass

        from datetime import timedelta
        deadline = (datetime.now() + timedelta(days=days)).isoformat()

        # Gleiches Metric-Ziel ersetzen
        goals["goals"] = [g for g in goals.get("goals", []) if g.get("metric") != metric]
        goals["goals"].append({
            "metric": metric,
            "target": target,
            "baseline": baseline,
            "deadline": deadline,
            "deadline_days": days,
            "reason": reason,
            "created_at": datetime.now().isoformat(),
        })

        GOALS_FILE.parent.mkdir(parents=True, exist_ok=True)
        GOALS_FILE.write_text(json.dumps(goals, indent=2, ensure_ascii=False), encoding="utf-8")
        logger.info(f"Ziel gesetzt: {metric} → {target} (in {days} Tagen, Baseline: {baseline})")
        return {
            "ok": True,
            "goal": f"{metric} → {target} bis {deadline[:10]}",
            "baseline": baseline,
            "gap": round(target - baseline, 3),
        }

    elif name == "check_goals":
        if not GOALS_FILE.exists():
            return {"goals": [], "note": "Noch keine Ziele gesetzt"}

        goals = json.loads(GOALS_FILE.read_text(encoding="utf-8")).get("goals", [])
        perf_file = PROJECT_ROOT / "analytics" / "performance_report.json"
        metrics: dict = {}
        if perf_file.exists():
            try:
                perf = json.loads(perf_file.read_text(encoding="utf-8"))
                metrics = perf.get("metrics", {})
            except Exception:
                pass

        result = []
        for g in goals:
            metric   = g["metric"]
            target   = g["target"]
            baseline = g.get("baseline", 0)
            current  = float(metrics.get(metric, 0) or 0)
            progress = ((current - baseline) / (target - baseline)) * 100 if (target != baseline) else 0
            deadline = g.get("deadline", "?")[:10]
            result.append({
                "metric": metric,
                "target": target,
                "current": current,
                "baseline": baseline,
                "progress_pct": round(progress, 1),
                "deadline": deadline,
                "status": "ERREICHT" if current >= target else "OFFEN",
            })
        return {"goals": result, "total": len(result)}

    # ---- A/B TEST ----

    elif name == "start_ab_test":
        challenger = inputs.get("challenger_params", {})
        description = inputs.get("description", "")

        # Control = aktuelle Config
        control = _read_config_values()
        control_bt = _execute_tool("run_backtest", {
            "min_edge":          control.get("MIN_EDGE", 0.12),
            "min_edge_absolute": control.get("MIN_EDGE_ABSOLUTE", 0.05),
            "max_odds":          control.get("MAX_ODDS", 0.35),
            "min_liquidity":     control.get("MIN_LIQUIDITY", 50.0),
        })

        # Challenger = neue Parameter
        challenger_bt = _execute_tool("run_backtest", challenger)

        ab_result = {
            "started_at": datetime.now().isoformat(),
            "description": description,
            "control_params": {
                "MIN_EDGE": control.get("MIN_EDGE"),
                "MAX_ODDS": control.get("MAX_ODDS"),
                "MIN_LIQUIDITY": control.get("MIN_LIQUIDITY"),
            },
            "challenger_params": challenger,
            "control_backtest": control_bt,
            "challenger_backtest": challenger_bt,
        }

        AB_TEST_FILE.parent.mkdir(parents=True, exist_ok=True)
        AB_TEST_FILE.write_text(json.dumps(ab_result, indent=2, ensure_ascii=False), encoding="utf-8")

        # Gewinner bestimmen
        c_wr = control_bt.get("simulated_win_rate", 0) or control_bt.get("current_win_rate", 0)
        ch_wr = challenger_bt.get("simulated_win_rate", 0)
        c_pnl = control_bt.get("simulated_pnl_eur", 0) or control_bt.get("current_pnl_eur", 0)
        ch_pnl = challenger_bt.get("simulated_pnl_eur", 0)

        winner = "CHALLENGER" if (ch_pnl > c_pnl and ch_wr >= c_wr * 0.9) else "CONTROL"

        return {
            "ok": True,
            "description": description,
            "control": {"win_rate": c_wr, "pnl_eur": c_pnl, "trades": control_bt.get("trades_would_take", 0)},
            "challenger": {"win_rate": ch_wr, "pnl_eur": ch_pnl, "trades": challenger_bt.get("trades_would_take", 0)},
            "winner": winner,
            "recommendation": f"{'Challenger-Parameter uebernehmen' if winner == 'CHALLENGER' else 'Aktuelle Config beibehalten'}",
        }

    # ---- CODE PROPOSALS ----

    elif name == "propose_code_change":
        proposal = {
            "timestamp": datetime.now().isoformat(),
            "file": inputs.get("file", ""),
            "title": inputs.get("title", ""),
            "description": inputs.get("description", ""),
            "expected_impact": inputs.get("expected_impact", ""),
            "priority": inputs.get("priority", "MEDIUM"),
            "status": "PENDING",
        }

        CODE_PROPOSALS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(CODE_PROPOSALS_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(proposal, ensure_ascii=False) + "\n")

        # Telegram Alert
        try:
            from notifications.telegram import send_message, is_configured
            if is_configured():
                prio_emoji = {"HIGH": "🔴", "MEDIUM": "🟡", "LOW": "🟢"}.get(proposal["priority"], "⚪")
                nl = "\n"
                msg = (
                    f"{prio_emoji} <b>CODE-VORSCHLAG {proposal['priority']}</b>{nl}"
                    f"📄 <code>{proposal['file']}</code>{nl}"
                    f"<b>{proposal['title']}</b>{nl}{nl}"
                    f"{proposal['description'][:300]}{nl}{nl}"
                    f"💡 Impact: {proposal['expected_impact'][:150]}"
                )
                send_message(msg, disable_notification=(proposal["priority"] != "HIGH"))
        except Exception:
            pass

        logger.info(f"Code-Vorschlag: [{proposal['priority']}] {proposal['title']} ({proposal['file']})")
        return {
            "ok": True,
            "title": proposal["title"],
            "priority": proposal["priority"],
            "note": "Vorschlag gespeichert + Telegram-Alert gesendet. Mensch entscheidet.",
        }

    elif name == "apply_code_patch":
        file_rel = inputs.get("file", "")
        constant = inputs.get("constant", "")
        value    = inputs.get("value")
        reason   = inputs.get("reason", "")

        # Whitelist-Check
        if file_rel not in CODE_PATCH_WHITELIST:
            return {"error": f"Datei '{file_rel}' nicht in Whitelist. Erlaubt: {list(CODE_PATCH_WHITELIST.keys())}"}

        allowed = CODE_PATCH_WHITELIST[file_rel]
        if constant not in allowed:
            return {"error": f"Konstante '{constant}' nicht erlaubt in {file_rel}. Erlaubt: {list(allowed.keys())}"}

        value = float(value)
        meta  = allowed[constant]

        # Range-Check
        if value < meta["min"] or value > meta["max"]:
            return {"error": f"{constant}={value} ausserhalb Range [{meta['min']}, {meta['max']}]"}

        # Datei lesen
        target_file = PROJECT_ROOT / file_rel
        if not target_file.exists():
            return {"error": f"Datei nicht gefunden: {file_rel}"}

        original_text = target_file.read_text(encoding="utf-8")

        # Aktuellen Wert lesen
        # Erkennt: "CONST = 0.25", "CONST: float = 0.25", "    CONST = 0.25" (class-level)
        pattern = rf"(\b{re.escape(constant)}(?:\s*:\s*\w+)?\s*=\s*)([-]?[\d.]+)"
        m = re.search(pattern, original_text)
        if not m:
            return {"error": f"Konstante '{constant}' nicht in {file_rel} gefunden (Pattern-Match fehlgeschlagen)"}

        old_value = float(m.group(2))

        # Max-Change-Check (25%)
        if old_value != 0:
            change_pct = abs(value - old_value) / abs(old_value)
            if change_pct > MAX_CHANGE_PCT:
                return {
                    "error": f"Aenderung {change_pct:.0%} > Max {MAX_CHANGE_PCT:.0%}. "
                             f"Aktuell: {old_value}, Erlaubt: [{round(old_value*(1-MAX_CHANGE_PCT),4)}, {round(old_value*(1+MAX_CHANGE_PCT),4)}]"
                }

        # Replacement
        new_text = re.sub(pattern, rf"\g<1>{value}", original_text, count=1)

        # Syntax-Check
        import py_compile, tempfile as tmpmod
        with tmpmod.NamedTemporaryFile(suffix=".py", delete=False, mode="w", encoding="utf-8") as tmp:
            tmp.write(new_text)
            tmp_path = tmp.name
        try:
            py_compile.compile(tmp_path, doraise=True)
        except py_compile.PyCompileError as e:
            import os as _os
            _os.unlink(tmp_path)
            return {"error": f"Syntax-Check fehlgeschlagen: {e}"}
        import os as _os
        _os.unlink(tmp_path)

        # Backup
        backup = target_file.with_suffix(f".py.bak_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
        shutil.copy2(target_file, backup)

        # Schreiben
        target_file.write_text(new_text, encoding="utf-8")

        # Git-Commit
        git_msg = f"auto: {constant} {old_value}→{value} in {file_rel} [{reason[:60]}]"
        try:
            import subprocess
            subprocess.run(
                ["git", "add", file_rel],
                cwd=str(PROJECT_ROOT), capture_output=True, timeout=15
            )
            subprocess.run(
                ["git", "commit", "-m", git_msg,
                 "--author=StrategyAgent <agent@polymarket-beobachter>"],
                cwd=str(PROJECT_ROOT), capture_output=True, timeout=15
            )
        except Exception as git_err:
            logger.warning(f"Git-Commit fehlgeschlagen (Code wurde trotzdem geschrieben): {git_err}")

        # Patch-Log
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "file": file_rel,
            "constant": constant,
            "old_value": old_value,
            "new_value": value,
            "reason": reason,
            "git_msg": git_msg,
        }
        CODE_PATCH_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(CODE_PATCH_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")

        # Telegram Alert
        try:
            from notifications.telegram import send_message, is_configured
            if is_configured():
                nl = "\n"
                msg = (
                    f"🤖 <b>AUTO CODE PATCH</b>{nl}"
                    f"📄 <code>{file_rel}</code>{nl}"
                    f"<b>{constant}</b>: {old_value} → {value}{nl}"
                    f"💡 {reason[:200]}{nl}"
                    f"<i>Syntax-Check: OK | Git-Commit: OK</i>"
                )
                send_message(msg)
        except Exception:
            pass

        logger.info(f"Code-Patch: {constant} {old_value}→{value} in {file_rel}")
        return {
            "ok": True,
            "file": file_rel,
            "constant": constant,
            "old_value": old_value,
            "new_value": value,
            "action": f"{file_rel}: {constant} {old_value} → {value}",
            "note": "Syntax-Check OK, Git-Commit erstellt, wirksam ab naechstem Import",
        }

    elif name == "write_diagnosis":
        diagnosis = {**inputs, "generated_at": datetime.now().isoformat()}
        DIAGNOSIS_FILE.parent.mkdir(parents=True, exist_ok=True)
        DIAGNOSIS_FILE.write_text(json.dumps(diagnosis, indent=2, ensure_ascii=False), encoding="utf-8")
        logger.info(f"Diagnose: {inputs.get('grade')} — {inputs.get('summary','')[:80]}")
        return {"ok": True}

    return {"error": f"Unbekanntes Tool: {name}"}


# =============================================================================
# SYSTEM PROMPT
# =============================================================================

SYSTEM_PROMPT = """Du bist ein autonomer Strategie-Agent fuer ein Polymarket Weather-Betting System.

Du hast ECHTEN Zugriff auf Config-Aenderungen und Backtests. Gehe systematisch vor:

ABLAUF:
1. read_performance + read_recent_positions → Was laeuft gut/schlecht?
2. read_previous_diagnosis + evaluate_hint_impact → Letzte Eingriffe bewertet?
3. check_goals → Sind Ziele on-track?
4. read_current_config → Aktuelle Werte?
5. start_ab_test (optional) → Hypothese mit A/B-Test validieren
6. run_backtest (optional) → Alternativ: einfacher Backtest
7. adjust_config (0-3x) → Direkter Eingriff wenn Daten es begruenden
8. set_mutation_bias (0-2x) → Langfristige Evolution lenken
9. apply_code_patch (0-1x) → Direkte Code-Aenderung (Kelly, TP/SL, Sizing)
10. set_goal (0-1x) → Ziel setzen/aktualisieren wenn sinnvoll
11. propose_code_change (0-1x) → Groessere Aenderungen die nicht auto-editierbar sind
12. write_diagnosis → Immer als letztes

REGELN:
- NUR aendern wenn Daten es begruenden, max 25% pro Parameter
- Bei < 10 Trades: KEINE Eingriffe, nur Ziel setzen + beobachten
- Bei KRITISCHEN Problemen (Win-Rate 0%, alle Stop-Losses): SOFORT eingreifen ohne A/B-Test
- apply_code_patch fuer: KELLY_FRACTION, MAX_POSITION_EUR, STOP_LOSS_PCT, TP-Levels
- propose_code_change fuer: neue Logik, neue Module, strukturelle Aenderungen
- Wirkungsbereich: adjust_config wirkt sofort, apply_code_patch ab naechstem Import

PARAMETER-WIRKUNGEN:
- MIN_ODDS hoeher → nur hoehere Wahrscheinlichkeiten (SCHUTZ vor Longshot-Falle)
- MIN_ODDS niedriger → auch Longshots erlaubt (gefaehrlich bei schlechter Win-Rate)
- MIN_EDGE hoeher → weniger aber bessere Trades (bei niedriger Win-Rate)
- MIN_EDGE niedriger → mehr Trades (bei Null Trade-Flow)
- MAX_ODDS hoeher → auch Favoriten (z.B. >30% Odds)
- MIN_LIQUIDITY hoeher → nur liquide Maerkte
- SAFETY_BUFFER_HOURS niedriger → auch kurzfristige Maerkte

!! NOTFALL-PROTOKOLL: LONGSHOT-FALLE !!
Symptome: Win-Rate 0%, alle Trades gehen sofort in Stop-Loss, entry_price < 0.05 (5%) bei vielen Trades.
Ursache: MIN_ODDS zu niedrig → System kauft nahezu-unmogliche Ereignisse die nie eintreten.
Sofortmassnahme (OHNE A/B-Test, SOFORT):
  1. read_current_config → Prüfe MIN_ODDS (Zielwert: >= 0.15)
  2. adjust_config(MIN_ODDS, neuer_wert, reason) → Auf 0.15-0.25 setzen
  3. adjust_config(MAX_ODDS, neuer_wert) → Auf max 0.40 setzen (damit Markt existiert zwischen MIN und MAX)
  4. set_mutation_bias(min_odds/max_odds, up) → Evolution in gleiche Richtung lenken
Diagnostik: read_recent_positions gibt entry_price_distribution und longshot_warning.
Wenn longshot_warning=True oder >30% der Trades unter 5% entry_price: LONGSHOT-FALLE aktiv → sofort korrigieren.

TYPISCHE PROBLEME:
- Keine Trades → MIN_EDGE senken ODER MIN_LIQUIDITY senken
- Viele Stop-Losses + niedrige entry_price → MIN_ODDS erhoehen (LONGSHOT-FALLE)
- Viele Stop-Losses + normale entry_price → MIN_EDGE erhoehen
- Niedrige Win-Rate → MIN_ODDS erhoehen + MIN_EDGE erhoehen + MAX_ODDS senken
- Hoher Drawdown → kelly_fraction via apply_code_patch senken"""


# =============================================================================
# REGELBASIERTER PRE-CHECK  (deterministisch, kein LLM noetig)
# Faengt kritische Situationen ab bevor der LLM ueberhaupt dran kommt.
# =============================================================================

def _run_rule_based_checks() -> list[str]:
    """
    Pruefe offensichtliche Probleme anhand harter Schwellwerte und handle sofort.
    Gibt Liste der durchgefuehrten Aktionen zurueck (fuer Diagnose-Kontext).
    """
    actions: list[str] = []

    # Daten laden
    pos_data = _execute_tool("read_recent_positions", {"n": 50})
    perf_file = PROJECT_ROOT / "analytics" / "performance_report.json"
    perf: dict = {}
    if perf_file.exists():
        try:
            perf = json.loads(perf_file.read_text(encoding="utf-8"))
        except Exception:
            pass

    metrics = perf.get("metrics", {})
    win_rate = float(metrics.get("win_rate_pct", 0) or 0)
    total_trades = int(metrics.get("total_trades", 0) or 0)

    entry_dist = pos_data.get("entry_price_distribution", {})
    under_5pct = entry_dist.get("under_5pct", 0)
    total_entries = sum(entry_dist.values()) if entry_dist else 0

    cfg = _read_config_values()
    current_min_odds = cfg.get("MIN_ODDS", 0.01)
    current_max_odds = cfg.get("MAX_ODDS", 0.35)

    # --- REGEL 1: LONGSHOT-FALLE ---
    # Bedingung: >30% Trades unter 5% entry_price UND Win-Rate 0% UND >= 10 Trades
    longshot_ratio = under_5pct / total_entries if total_entries > 0 else 0
    if longshot_ratio > 0.30 and win_rate == 0.0 and total_trades >= 10:
        # Direktes Schreiben (kein 25%-Limit) — Notfall-Override
        target_min_odds = 0.15  # Fester Zielwert: keine Longshots unter 15%
        target_min_odds = min(target_min_odds, CONFIG_PARAMS["MIN_ODDS"]["max"])
        reason = (
            f"NOTFALL-REGEL: Longshot-Falle. {under_5pct}/{total_entries} Trades "
            f"({longshot_ratio:.0%}) unter 5% entry_price. Win-Rate=0% bei {total_trades} Trades. "
            f"MIN_ODDS {current_min_odds} -> {target_min_odds}."
        )
        backup_path = _backup_config()
        if _write_config_value("MIN_ODDS", target_min_odds):
            # Baseline-Snapshot fuer Before/After-Tracking
            try:
                _write_change_baseline("MIN_ODDS", current_min_odds, target_min_odds, reason)
            except Exception:
                pass
            # Log-Eintrag mit Metriken
            try:
                snap = _snapshot_current_metrics()
            except Exception:
                snap = {}
            log_entry = {
                "timestamp": datetime.now().isoformat(),
                "param": "MIN_ODDS",
                "old_value": current_min_odds,
                "new_value": target_min_odds,
                "reason": reason,
                "source": "rule_based_check",
                "backup": backup_path,
                "trades_at_change": snap.get("total_closed_trades"),
                "win_rate_at_change": snap.get("win_rate"),
                "pnl_at_change": snap.get("total_pnl_eur"),
            }
            CONFIG_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(CONFIG_LOG_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")
            actions.append(f"[RULE:LONGSHOT] MIN_ODDS {current_min_odds} -> {target_min_odds}")
            current_min_odds = target_min_odds
            logger.info(f"[RULE-CHECK] Longshot-Falle BEHOBEN: MIN_ODDS -> {target_min_odds}")

        # MAX_ODDS muss groesser als MIN_ODDS bleiben (min. 15% Abstand)
        if current_max_odds < current_min_odds + 0.15:
            target_max_odds = round(min(current_min_odds + 0.20, 0.45), 3)
            if _write_config_value("MAX_ODDS", target_max_odds):
                log_entry = {
                    "timestamp": datetime.now().isoformat(),
                    "param": "MAX_ODDS",
                    "old_value": current_max_odds,
                    "new_value": target_max_odds,
                    "reason": f"NOTFALL-REGEL: MAX_ODDS muss > MIN_ODDS+15%. MIN_ODDS={current_min_odds}",
                    "source": "rule_based_check",
                }
                with open(CONFIG_LOG_FILE, "a", encoding="utf-8") as f:
                    f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")
                actions.append(f"[RULE:ODDS-SPREAD] MAX_ODDS {current_max_odds} -> {target_max_odds}")

        # Evolution in richtige Richtung lenken
        _execute_tool("set_mutation_bias", {
            "param": "min_odds",
            "direction": "up",
            "strength": 0.8,
            "reason": "Longshot-Falle: min_odds muss hoeher evoluieren",
        })
        actions.append("[RULE:MUTATION] min_odds bias -> up (0.8)")

    # --- REGEL 2: AUTO-REVERT ---
    # Bedingung: letzte Config-Aenderung hat Performance klar verschlechtert (>= 10 Trades danach)
    if not longshot_ratio > 0.30:  # Nur wenn kein akuterer Notfall aktiv ist
        try:
            impact = _evaluate_change_impact_detailed()
            if impact.get("verdict") == "DEGRADED":
                baseline_data = json.loads(CHANGE_BASELINE_FILE.read_text(encoding="utf-8"))
                param = baseline_data.get("param", "")
                old_val = baseline_data.get("old_value")
                after_trades = impact.get("after", {}).get("trades", 0)
                if param and old_val is not None and param in CONFIG_PARAMS:
                    meta = CONFIG_PARAMS[param]
                    revert_val = float(old_val)
                    revert_val = max(meta["min"], min(meta["max"], revert_val))
                    if _write_config_value(param, revert_val):
                        revert_reason = (
                            f"AUTO-REVERT: {param} hat Performance verschlechtert. "
                            f"{after_trades} Trades nach Aenderung: "
                            f"Win-Rate {impact['after']['win_rate']:.1%} vs vorher {impact['before']['win_rate']:.1%}. "
                            f"Revert auf {revert_val}."
                        )
                        log_entry = {
                            "timestamp": datetime.now().isoformat(),
                            "param": param,
                            "old_value": baseline_data.get("new_value"),
                            "new_value": revert_val,
                            "reason": revert_reason,
                            "source": "auto_revert",
                        }
                        with open(CONFIG_LOG_FILE, "a", encoding="utf-8") as f:
                            f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")
                        # Baseline zuruecksetzen
                        CHANGE_BASELINE_FILE.unlink(missing_ok=True)
                        actions.append(f"[RULE:REVERT] {param} {baseline_data.get('new_value')} -> {revert_val}")
                        logger.info(f"[RULE-CHECK] Auto-Revert: {param} -> {revert_val}")
        except Exception as e:
            logger.debug(f"[RULE-CHECK] Auto-Revert-Check fehlgeschlagen (unkritisch): {e}")

    return actions


# =============================================================================
# PROVIDER CLIENT
# =============================================================================

def _get_client(provider: dict):
    from openai import OpenAI
    api_key = os.environ.get(provider["env_key"], "").strip()
    if not api_key:
        return None
    kwargs: dict = {"api_key": api_key}
    if provider["base_url"]:
        kwargs["base_url"] = provider["base_url"]
    return OpenAI(**kwargs)


# =============================================================================
# AGENT LOOP
# =============================================================================

def run_strategy_agent(max_iterations: int = 15) -> dict:
    """
    Starte den LLM Strategy Agent mit Tool-Use und Provider-Fallback.
    Reihenfolge: Kimi → OpenRouter → OpenAI
    """
    # .env laden
    env_file = PROJECT_ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ[k.strip()] = v.strip()  # .env hat immer Vorrang

    try:
        from openai import OpenAI  # noqa
    except ImportError:
        return {"error": "openai nicht installiert"}

    # Provider mit Fallback
    client = None
    active_provider = None
    for provider in PROVIDERS:
        c = _get_client(provider)
        if c is not None:
            client = c
            active_provider = provider
            break

    if client is None:
        logger.warning("Kein LLM-Provider verfuegbar")
        return {"error": "Kein LLM-Provider verfuegbar"}

    logger.info(f"Strategy Agent via {active_provider['name']} ({active_provider['model']})")

    # --- Regelbasierter Pre-Check (deterministisch, kein LLM) ---
    try:
        rule_actions = _run_rule_based_checks()
        if rule_actions:
            logger.info(f"[RULE-CHECK] Automatische Eingriffe: {rule_actions}")
    except Exception as e:
        rule_actions = []
        logger.warning(f"[RULE-CHECK] Fehlgeschlagen (unkritisch): {e}")

    # LLM bekommt Kontext ueber bereits durchgefuehrte Regel-Aktionen
    rule_context = ""
    if rule_actions:
        rule_context = (
            "\n\nHINWEIS: Der regelbasierte Pre-Check hat bereits folgende Eingriffe durchgefuehrt:\n"
            + "\n".join(f"  - {a}" for a in rule_actions)
            + "\nBitte beziehe dies in deine Analyse ein und pruefe ob weitere Massnahmen noetig sind."
        )

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": "Analysiere die Performance und handle falls noetig." + rule_context},
    ]

    diagnosis: dict = {}
    config_changes: list[str] = list(rule_actions)  # Regel-Aktionen vorbelegen
    code_patches: list[str] = []
    hints_applied: list[str] = []

    for i in range(max_iterations):
        try:
            response = client.chat.completions.create(
                model=active_provider["model"],
                messages=messages,
                tools=TOOLS,
                tool_choice="auto",
                max_tokens=2048,
                temperature=0.2,
            )
        except Exception as e:
            logger.warning(f"{active_provider['name']} fehlgeschlagen: {e}")
            # Fallback
            current_idx = PROVIDERS.index(active_provider)
            succeeded = False
            for fallback in PROVIDERS[current_idx + 1:]:
                c = _get_client(fallback)
                if c is None:
                    continue
                try:
                    client = c
                    active_provider = fallback
                    logger.info(f"Fallback auf {fallback['name']}")
                    response = client.chat.completions.create(
                        model=active_provider["model"],
                        messages=messages,
                        tools=TOOLS,
                        tool_choice="auto",
                        max_tokens=2048,
                        temperature=0.2,
                    )
                    succeeded = True
                    break
                except Exception as e2:
                    logger.warning(f"{fallback['name']} auch fehlgeschlagen: {e2}")
            if not succeeded:
                return {"error": f"Alle Provider fehlgeschlagen: {e}"}

        choice = response.choices[0]

        # Assistenten-Nachricht korrekt aufbauen
        asst_msg: dict = {"role": "assistant", "content": choice.message.content or ""}
        if choice.message.tool_calls:
            asst_msg["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                }
                for tc in choice.message.tool_calls
            ]
        messages.append(asst_msg)

        if choice.finish_reason == "stop":
            break

        if choice.finish_reason == "tool_calls" and choice.message.tool_calls:
            tool_results = []
            for tc in choice.message.tool_calls:
                try:
                    tool_inputs = json.loads(tc.function.arguments)
                except Exception:
                    tool_inputs = {}

                result = _execute_tool(tc.function.name, tool_inputs)

                tool_results.append({
                    "role": "tool",
                    "tool_use_id": tc.id,
                    "tool_call_id": tc.id,
                    "content": json.dumps(result, ensure_ascii=False, default=str),
                })

                if tc.function.name == "write_diagnosis":
                    diagnosis = tool_inputs
                elif tc.function.name == "adjust_config" and result.get("ok"):
                    config_changes.append(result.get("action", ""))
                elif tc.function.name == "apply_code_patch" and result.get("ok"):
                    code_patches.append(result.get("action", ""))
                elif tc.function.name == "set_mutation_bias" and result.get("ok"):
                    hints_applied.append(result.get("action", ""))

            messages.extend(tool_results)
        else:
            break

    if diagnosis:
        diagnosis["config_changes"]    = config_changes
        diagnosis["code_patches"]      = code_patches
        diagnosis["mutations_applied"] = hints_applied
        diagnosis["provider"]          = active_provider["name"]
        # Re-save: write_diagnosis wurde während Loop geschrieben, aber actions fehlten noch
        try:
            DIAGNOSIS_FILE.parent.mkdir(parents=True, exist_ok=True)
            DIAGNOSIS_FILE.write_text(
                json.dumps(diagnosis, indent=2, ensure_ascii=False), encoding="utf-8"
            )
        except Exception as e:
            logger.warning(f"Diagnose-Re-Save fehlgeschlagen: {e}")

    logger.info(
        f"Strategy Agent: grade={diagnosis.get('grade','?')}, "
        f"config_changes={len(config_changes)}, hints={len(hints_applied)}, "
        f"provider={active_provider['name']}, iter={i+1}"
    )
    return diagnosis


# =============================================================================
# TELEGRAM REPORT
# =============================================================================

def send_strategy_telegram(diagnosis: dict) -> None:
    try:
        from notifications.telegram import send_message, is_configured
        if not is_configured() or not diagnosis or "error" in diagnosis:
            return

        grade = diagnosis.get("grade", "?")
        provider = diagnosis.get("provider", "?")
        grade_emoji = {"HEALTHY": "✅", "DEGRADED": "⚠️", "CRITICAL": "🚨"}.get(grade, "❓")

        nl = "\n"
        lines = [
            f"{grade_emoji} <b>STRATEGY AGENT — {grade}</b> <i>({provider})</i>",
            f"<i>{diagnosis.get('summary', '')[:200]}</i>",
        ]

        for rc in diagnosis.get("root_causes", [])[:3]:
            lines.append(f"• {rc}")

        patches = diagnosis.get("code_patches", [])
        if patches:
            lines += ["", "<b>Code auto-editiert:</b>"]
            for p in patches[:3]:
                lines.append(f"🔧 {p}")

        changes = diagnosis.get("config_changes", [])
        if changes:
            lines += ["", "<b>Config geaendert:</b>"]
            for c in changes[:3]:
                lines.append(f"⚙️ {c}")

        hints = diagnosis.get("mutations_applied", [])
        if hints:
            lines += ["", "<b>Mutation-Hints:</b>"]
            for h in hints[:3]:
                lines.append(f"→ {h}")

        impact = diagnosis.get("hint_impact")
        if impact:
            lines += ["", f"<b>Letzte Hints:</b> {impact[:100]}"]

        goals_status = diagnosis.get("goals_status")
        if goals_status:
            lines += ["", f"<b>Ziele:</b> {goals_status[:120]}"]

        proposals = diagnosis.get("code_proposals", [])
        if proposals:
            lines += ["", "<b>Code-Vorschlaege:</b>"]
            for p in proposals[:2]:
                lines.append(f"💡 {p}")

        send_message(nl.join(lines), disable_notification=True)

    except Exception as e:
        logger.debug(f"Telegram fehlgeschlagen: {e}")


# =============================================================================
# STANDALONE CLI
# =============================================================================

def main():
    import sys, io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")

    print("Strategy Agent wird gestartet (Stufe 2)...")
    diagnosis = run_strategy_agent()

    if "error" in diagnosis:
        print(f"FEHLER: {diagnosis['error']}")
        sys.exit(1)

    print(f"\nProvider:  {diagnosis.get('provider')}")
    print(f"Grade:     {diagnosis.get('grade')}")
    print(f"Summary:   {diagnosis.get('summary','')[:150]}")
    for rc in diagnosis.get("root_causes", []):
        print(f"  * {rc}")
    for c in diagnosis.get("config_changes", []):
        print(f"  ⚙ {c}")
    for h in diagnosis.get("mutations_applied", []):
        print(f"  → {h}")
    if diagnosis.get("hint_impact"):
        print(f"  Impact: {diagnosis['hint_impact']}")

    send_strategy_telegram(diagnosis)
    print(f"\nDiagnose: {DIAGNOSIS_FILE}")


if __name__ == "__main__":
    main()
