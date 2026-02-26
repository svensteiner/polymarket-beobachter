# =============================================================================
# LLM STRATEGY AGENT
# =============================================================================
#
# Ein Claude-Haiku-basierter Agent der die System-Performance analysiert,
# Root Causes erkennt und gerichtete Mutations-Hints setzt.
#
# Ablauf:
#   1. Lese Performance, Positionen, Population, Marktbedingung via Tools
#   2. Analysiere mit LLM was gut/schlecht laeuft
#   3. Setze Mutations-Hints (biasierte Parameter-Evolution)
#   4. Schreibe Diagnose-Report + Telegram-Alert
#
# Wird nach jedem Evolutions-Tick aufgerufen (alle 50 Pipeline-Runs).
# Benutzt Claude Haiku (guenstig: ~$0.001 pro Aufruf).
#
# =============================================================================

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent
HINTS_FILE = PROJECT_ROOT / "data" / "evolution" / "strategy_hints.json"
DIAGNOSIS_FILE = PROJECT_ROOT / "data" / "evolution" / "strategy_diagnosis.json"

# =============================================================================
# TOOL DEFINITIONS (Claude Tool-Use Schema)
# =============================================================================

TOOLS = [
    {
        "name": "read_performance",
        "description": (
            "Lese den aktuellen Performance-Report: Win-Rate, PnL, Profit-Factor, "
            "Drawdown, Brier Score, Strategy Attribution und Performance nach Stadt."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "read_recent_positions",
        "description": "Lese die letzten N abgeschlossenen Positionen (CLOSED/RESOLVED).",
        "input_schema": {
            "type": "object",
            "properties": {
                "n": {
                    "type": "integer",
                    "description": "Anzahl Positionen (default: 30)",
                }
            },
            "required": [],
        },
    },
    {
        "name": "read_population_status",
        "description": (
            "Lese den aktuellen Status der Evolution-Population: "
            "Generation, Champion, Fitness-Scores, Parameter aller aktiven Agenten."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "read_market_condition",
        "description": "Lese die aktuelle Marktbedingung (BULLISH/BEARISH/WATCH etc.).",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "read_previous_diagnosis",
        "description": "Lese die letzte Diagnose um Fortschritt zu beurteilen.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "set_mutation_bias",
        "description": (
            "Setze einen gerichteten Bias fuer die naechste Mutation. "
            "Die Evolution wird in die angegebene Richtung gelenkt. "
            "direction='up' erhoeht den Parameter, 'down' verringert ihn, "
            "'reset' entfernt den Bias."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "param": {
                    "type": "string",
                    "description": (
                        "Parameter-Name. Gueltige Werte: min_edge, min_edge_absolute, "
                        "kelly_fraction, max_odds, take_profit_pct, stop_loss_pct, "
                        "avg_down_threshold_pct, variance_threshold, "
                        "medium_confidence_multiplier, min_liquidity"
                    ),
                },
                "direction": {
                    "type": "string",
                    "enum": ["up", "down", "reset"],
                    "description": "Richtung der Mutation",
                },
                "strength": {
                    "type": "number",
                    "description": "Staerke des Bias 0.1-1.0 (default: 0.5)",
                },
                "reason": {
                    "type": "string",
                    "description": "Kurze Begruendung fuer den Bias",
                },
            },
            "required": ["param", "direction"],
        },
    },
    {
        "name": "write_diagnosis",
        "description": (
            "Schreibe die finale Diagnose mit Zusammenfassung, Root Causes, "
            "Hypothesen und Status. IMMER als letztes Tool aufrufen."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "summary": {
                    "type": "string",
                    "description": "Kurze Zusammenfassung in 2-3 Saetzen",
                },
                "root_causes": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Erkannte Hauptursachen fuer aktuelle Performance",
                },
                "hypotheses": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Konkrete Hypothesen die getestet werden sollen",
                },
                "mutations_applied": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Liste der gesetzten Mutations-Hints",
                },
                "grade": {
                    "type": "string",
                    "enum": ["HEALTHY", "DEGRADED", "CRITICAL"],
                    "description": "Aktueller Systemstatus",
                },
            },
            "required": ["summary", "root_causes", "hypotheses", "grade"],
        },
    },
]

# =============================================================================
# TOOL EXECUTION
# =============================================================================

VALID_PARAMS = {
    "min_edge", "min_edge_absolute", "kelly_fraction", "max_odds",
    "take_profit_pct", "stop_loss_pct", "avg_down_threshold_pct",
    "variance_threshold", "medium_confidence_multiplier", "min_liquidity",
}


def _execute_tool(name: str, inputs: dict) -> Any:
    """Fuehre ein Tool aus und gib das Ergebnis zurueck."""

    if name == "read_performance":
        report_file = PROJECT_ROOT / "analytics" / "performance_report.json"
        if report_file.exists():
            try:
                return json.loads(report_file.read_text(encoding="utf-8"))
            except Exception as e:
                return {"error": f"Lesefehler: {e}"}
        return {"error": "Kein Performance-Report gefunden"}

    elif name == "read_recent_positions":
        n = inputs.get("n", 30)
        positions_file = PROJECT_ROOT / "paper_trader" / "logs" / "paper_positions.jsonl"
        if not positions_file.exists():
            return {"positions": [], "count": 0, "error": "Keine Positionen-Datei"}

        by_id: dict[str, dict] = {}
        try:
            for line in positions_file.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    p = json.loads(line)
                    if p.get("_type") != "LOG_HEADER" and p.get("position_id"):
                        by_id[p["position_id"]] = p
                except Exception:
                    pass
        except Exception as e:
            return {"error": f"Lesefehler: {e}"}

        closed = [
            p for p in by_id.values()
            if p.get("status") in ("CLOSED", "RESOLVED")
        ]
        closed.sort(key=lambda p: p.get("exit_time", ""), reverse=True)
        recent = closed[:n]

        # Komprimiere fuer Kontext-Effizienz
        summary = [
            {
                "market": p.get("market_question", "?")[:60],
                "side": p.get("side"),
                "entry": p.get("entry_price"),
                "exit": p.get("exit_price"),
                "pnl_eur": p.get("pnl_eur"),
                "pnl_pct": p.get("pnl_pct"),
                "exit_reason": p.get("exit_reason"),
                "city": p.get("city"),
                "confidence": p.get("confidence_level"),
            }
            for p in recent
        ]
        return {"positions": summary, "count": len(summary)}

    elif name == "read_population_status":
        pop_file = PROJECT_ROOT / "data" / "evolution" / "population.json"
        if not pop_file.exists():
            return {"error": "Keine Population gefunden"}
        try:
            pop = json.loads(pop_file.read_text(encoding="utf-8"))

            # Lade Fitness-Daten der aktiven Agenten
            agents_dir = PROJECT_ROOT / "data" / "evolution" / "agents"
            agent_summaries = []
            for aid in pop.get("agents", []):
                afile = agents_dir / aid / "agent.json"
                if afile.exists():
                    try:
                        a = json.loads(afile.read_text(encoding="utf-8"))
                        agent_summaries.append({
                            "id": a.get("agent_id"),
                            "generation": a.get("generation"),
                            "status": a.get("status"),
                            "fitness": a.get("fitness", {}),
                            "params": a.get("params", {}),
                            "notes": a.get("notes", ""),
                        })
                    except Exception:
                        pass

            return {
                "generation": pop.get("generation"),
                "total_runs": pop.get("total_runs"),
                "champion_id": pop.get("champion_id"),
                "agent_count": len(pop.get("agents", [])),
                "agents": agent_summaries,
            }
        except Exception as e:
            return {"error": f"Lesefehler: {e}"}

    elif name == "read_market_condition":
        cond_file = PROJECT_ROOT / "data" / "market_condition.json"
        if cond_file.exists():
            try:
                return json.loads(cond_file.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {"condition": "UNKNOWN", "error": "Keine Marktbedingung-Datei"}

    elif name == "read_previous_diagnosis":
        if DIAGNOSIS_FILE.exists():
            try:
                return json.loads(DIAGNOSIS_FILE.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {"error": "Keine vorherige Diagnose"}

    elif name == "set_mutation_bias":
        param = inputs.get("param", "")
        direction = inputs.get("direction", "reset")
        strength = float(inputs.get("strength", 0.5))
        reason = inputs.get("reason", "")

        if param not in VALID_PARAMS:
            return {"error": f"Ungueltiger Parameter: {param}. Gueltig: {sorted(VALID_PARAMS)}"}

        strength = max(0.1, min(1.0, strength))

        hints: dict = {}
        if HINTS_FILE.exists():
            try:
                hints = json.loads(HINTS_FILE.read_text(encoding="utf-8"))
            except Exception:
                pass

        if direction == "reset":
            hints.pop(param, None)
            action = f"Bias fuer '{param}' zurueckgesetzt"
        else:
            hints[param] = {
                "direction": direction,
                "strength": strength,
                "reason": reason,
                "set_at": datetime.now().isoformat(),
            }
            action = f"Bias '{direction}' fuer '{param}' gesetzt (strength={strength:.1f})"

        HINTS_FILE.parent.mkdir(parents=True, exist_ok=True)
        HINTS_FILE.write_text(json.dumps(hints, indent=2, ensure_ascii=False), encoding="utf-8")
        logger.info(f"Strategy Hint: {action} — {reason}")
        return {"ok": True, "action": action, "total_hints": len(hints)}

    elif name == "write_diagnosis":
        diagnosis = {
            **inputs,
            "generated_at": datetime.now().isoformat(),
        }
        DIAGNOSIS_FILE.parent.mkdir(parents=True, exist_ok=True)
        DIAGNOSIS_FILE.write_text(json.dumps(diagnosis, indent=2, ensure_ascii=False), encoding="utf-8")
        logger.info(f"Diagnose geschrieben: {inputs.get('grade')} — {inputs.get('summary', '')[:80]}")
        return {"ok": True}

    return {"error": f"Unbekanntes Tool: {name}"}


# =============================================================================
# SYSTEM PROMPT
# =============================================================================

SYSTEM_PROMPT = """Du bist ein Strategie-Analyst fuer ein Polymarket Weather-Betting System (Paper Trading).

Deine Aufgabe:
1. Analysiere Performance-Daten, Positionen, Evolution-Status und Marktbedingung
2. Erkenne Muster und Root Causes fuer Gewinne/Verluste
3. Setze gerichtete Mutations-Hints um die Parameter-Evolution zu lenken
4. Schreibe eine klare, praxisorientierte Diagnose

Parameter-Wirkungsweise:
- min_edge: Hoeher = weniger aber qualitativ hochwertigere Trades
- min_edge_absolute: Mindestabstand zu Market Price (verhindert False Positives)
- kelly_fraction: Hoeher = groessere Positionen = mehr Risiko und Chance
- max_odds: Hoeher = auch Favoriten handelbar (max empfohlen: 0.45)
- take_profit_pct: Fruehzeitiger Exit sichert Gewinne, verringert aber Upside
- stop_loss_pct: Eng = viele SL-Exits; Weit = grosse Einzelverluste moeglich
- avg_down_threshold_pct: Ab wann wird nachgekauft (bei Kursrueckgang)
- variance_threshold: Hoeher = mehr Ensemble-Unsicherheit toleriert
- min_liquidity: Hoeher = nur liquide Maerkte (reduziert Slippage)

Typische Problemmuster:
- Viele Stop-Losses → min_edge erhoehen ODER stop_loss_pct erhoehen
- Niedrige Win-Rate → min_edge erhoehen, max_odds senken
- Kein Trade-Flow → min_edge senken ODER min_liquidity senken
- Hoher Drawdown → kelly_fraction senken, stop_loss_pct senken
- Schlechter Brier Score → Forecast-Kalibrierung pruefen (variance_threshold anpassen)
- Take-Profit wird selten erreicht → take_profit_pct senken

Vorgehensweise:
1. Zuerst: read_performance
2. Dann: read_recent_positions (schaue auf Exit-Gruende)
3. Dann: read_population_status (welche Parameter performieren gut?)
4. Optional: read_market_condition, read_previous_diagnosis
5. Setze 1-3 set_mutation_bias Calls basierend auf Analyse
6. Abschliessen mit write_diagnosis

Antworte kurz und praezise. Setze NUR Hints die durch Daten belegbar sind."""


# =============================================================================
# MAIN AGENT LOOP
# =============================================================================

def run_strategy_agent(max_iterations: int = 12) -> dict:
    """
    Starte den LLM Strategy Agent mit Tool-Use.

    Returns:
        Diagnosis dict oder {"error": ...} bei Fehler
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        logger.warning("ANTHROPIC_API_KEY nicht gesetzt - Strategy Agent deaktiviert")
        return {"error": "ANTHROPIC_API_KEY nicht gesetzt"}

    try:
        import anthropic
    except ImportError:
        logger.warning("anthropic Paket nicht installiert (pip install anthropic)")
        return {"error": "anthropic nicht installiert"}

    client = anthropic.Anthropic(api_key=api_key)

    messages = [
        {
            "role": "user",
            "content": (
                "Analysiere die aktuelle System-Performance und gib gezielte Empfehlungen. "
                "Nutze die Tools in der beschriebenen Reihenfolge."
            ),
        }
    ]

    diagnosis: dict = {}
    hints_applied: list[str] = []

    logger.info("Strategy Agent gestartet (claude-haiku-4-5)")

    for i in range(max_iterations):
        try:
            response = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=2048,
                system=SYSTEM_PROMPT,
                tools=TOOLS,
                messages=messages,
            )
        except Exception as e:
            logger.error(f"Claude API Fehler: {e}")
            return {"error": str(e)}

        # Agenten-Antwort zur Message-History hinzufuegen
        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "end_turn":
            break

        if response.stop_reason == "tool_use":
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    result = _execute_tool(block.name, block.input)
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": json.dumps(result, ensure_ascii=False, default=str),
                        }
                    )
                    if block.name == "write_diagnosis":
                        diagnosis = block.input
                    elif block.name == "set_mutation_bias" and result.get("ok"):
                        hints_applied.append(result.get("action", ""))

            messages.append({"role": "user", "content": tool_results})
        else:
            # Kein weiterer Tool-Call erwartet
            break

    logger.info(
        f"Strategy Agent fertig: grade={diagnosis.get('grade', '?')}, "
        f"hints={len(hints_applied)}, iterations={i + 1}"
    )
    return diagnosis


# =============================================================================
# TELEGRAM REPORT
# =============================================================================

def send_strategy_telegram(diagnosis: dict) -> None:
    """Sende Diagnose-Report via Telegram."""
    try:
        from notifications.telegram import send_message, is_configured
        if not is_configured() or not diagnosis or "error" in diagnosis:
            return

        grade = diagnosis.get("grade", "?")
        grade_emoji = {"HEALTHY": "✅", "DEGRADED": "⚠️", "CRITICAL": "🚨"}.get(grade, "❓")

        nl = "\n"
        lines = [
            f"{grade_emoji} <b>STRATEGY AGENT — {grade}</b>",
            "",
            f"<i>{diagnosis.get('summary', '')}</i>",
        ]

        root_causes = diagnosis.get("root_causes", [])
        if root_causes:
            lines += ["", "<b>Root Causes:</b>"]
            for rc in root_causes[:3]:
                lines.append(f"• {rc}")

        mutations = diagnosis.get("mutations_applied", [])
        if mutations:
            lines += ["", "<b>Mutations-Hints gesetzt:</b>"]
            for m in mutations[:4]:
                lines.append(f"→ {m}")

        hypotheses = diagnosis.get("hypotheses", [])
        if hypotheses:
            lines += ["", "<b>Naechste Hypothesen:</b>"]
            for h in hypotheses[:2]:
                lines.append(f"💡 {h}")

        send_message(nl.join(lines), disable_notification=True)
        logger.info("Strategy Agent Telegram-Report gesendet")

    except Exception as e:
        logger.debug(f"Telegram Strategy Report fehlgeschlagen: {e}")


# =============================================================================
# STANDALONE CLI
# =============================================================================

def main():
    import sys
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    # Lade .env falls vorhanden
    env_file = PROJECT_ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())

    print("Strategy Agent wird gestartet...")
    diagnosis = run_strategy_agent()

    if "error" in diagnosis:
        print(f"FEHLER: {diagnosis['error']}")
        sys.exit(1)

    print(f"\nGrade: {diagnosis.get('grade')}")
    print(f"Summary: {diagnosis.get('summary')}")
    print("\nRoot Causes:")
    for rc in diagnosis.get("root_causes", []):
        print(f"  • {rc}")
    print("\nHypothesen:")
    for h in diagnosis.get("hypotheses", []):
        print(f"  • {h}")
    mutations = diagnosis.get("mutations_applied", [])
    if mutations:
        print("\nMutations-Hints:")
        for m in mutations:
            print(f"  → {m}")

    send_strategy_telegram(diagnosis)
    print(f"\nDiagnose gespeichert: {DIAGNOSIS_FILE}")


if __name__ == "__main__":
    main()
