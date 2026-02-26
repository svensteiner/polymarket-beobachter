# =============================================================================
# LLM STRATEGY AGENT
# =============================================================================
#
# Claude/GPT/Kimi-basierter Agent der die System-Performance analysiert,
# Root Causes erkennt und gerichtete Mutations-Hints setzt.
#
# Provider-Prioritaet (Fallback):
#   1. Kimi (moonshot-v1-8k, sehr guenstig)
#   2. OpenAI (gpt-4o-mini, guenstig + zuverlaessig)
#   3. OpenRouter (anthropic/claude-haiku-4-5, Claude-native)
#
# Ablauf:
#   1. Lese Performance, Positionen, Population, Marktbedingung via Tools
#   2. Analysiere mit LLM was gut/schlecht laeuft
#   3. Setze Mutations-Hints (biasierte Parameter-Evolution)
#   4. Schreibe Diagnose-Report + Telegram-Alert
#
# Wird nach jedem Evolutions-Tick aufgerufen (alle 50 Pipeline-Runs).
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
# PROVIDER CONFIGURATION
# =============================================================================

PROVIDERS = [
    {
        "name": "Kimi",
        "env_key": "KIMI_API_KEY",
        "base_url": "https://api.moonshot.cn/v1",
        "model": "moonshot-v1-8k",
    },
    {
        "name": "OpenRouter",
        "env_key": "OPENROUTER_API_KEY",
        "base_url": "https://openrouter.ai/api/v1",
        "model": "openai/gpt-4o-mini",
    },
    {
        "name": "OpenAI",
        "env_key": "OPENAI_API_KEY",
        "base_url": None,  # default
        "model": "gpt-4o-mini",
    },
]

# =============================================================================
# TOOL DEFINITIONS (OpenAI Function-Calling Format)
# =============================================================================

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "read_performance",
            "description": (
                "Lese den aktuellen Performance-Report: Win-Rate, PnL, Profit-Factor, "
                "Drawdown, Brier Score, Strategy Attribution und Performance nach Stadt."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_recent_positions",
            "description": "Lese die letzten N abgeschlossenen Positionen (CLOSED/RESOLVED).",
            "parameters": {
                "type": "object",
                "properties": {
                    "n": {"type": "integer", "description": "Anzahl Positionen (default: 30)"}
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_population_status",
            "description": (
                "Lese den Status der Evolution-Population: Generation, Champion, "
                "Fitness-Scores und Parameter aller aktiven Agenten."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_market_condition",
            "description": "Lese die aktuelle Marktbedingung (BULLISH/BEARISH/WATCH etc.).",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_previous_diagnosis",
            "description": "Lese die letzte Diagnose um Fortschritt zu beurteilen.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_mutation_bias",
            "description": (
                "Setze einen gerichteten Bias fuer die naechste Mutation. "
                "direction='up' erhoeht den Parameter, 'down' verringert, 'reset' entfernt."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "param": {
                        "type": "string",
                        "description": (
                            "Parameter-Name. Gueltig: min_edge, min_edge_absolute, "
                            "kelly_fraction, max_odds, take_profit_pct, stop_loss_pct, "
                            "avg_down_threshold_pct, variance_threshold, "
                            "medium_confidence_multiplier, min_liquidity"
                        ),
                    },
                    "direction": {
                        "type": "string",
                        "enum": ["up", "down", "reset"],
                    },
                    "strength": {
                        "type": "number",
                        "description": "Staerke 0.1-1.0 (default: 0.5)",
                    },
                    "reason": {
                        "type": "string",
                        "description": "Kurze Begruendung",
                    },
                },
                "required": ["param", "direction"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_diagnosis",
            "description": "Schreibe die finale Diagnose. IMMER als letztes Tool aufrufen.",
            "parameters": {
                "type": "object",
                "properties": {
                    "summary": {"type": "string", "description": "Zusammenfassung 2-3 Saetze"},
                    "root_causes": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Erkannte Hauptursachen",
                    },
                    "hypotheses": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Hypothesen zum Testen",
                    },
                    "mutations_applied": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Liste der gesetzten Mutations-Hints",
                    },
                    "grade": {
                        "type": "string",
                        "enum": ["HEALTHY", "DEGRADED", "CRITICAL"],
                        "description": "Systemstatus",
                    },
                },
                "required": ["summary", "root_causes", "hypotheses", "grade"],
            },
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
            return {"positions": [], "count": 0}

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

        closed = [p for p in by_id.values() if p.get("status") in ("CLOSED", "RESOLVED")]
        closed.sort(key=lambda p: p.get("exit_time", ""), reverse=True)
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
            for p in closed[:n]
        ]
        return {"positions": summary, "count": len(summary)}

    elif name == "read_population_status":
        pop_file = PROJECT_ROOT / "data" / "evolution" / "population.json"
        if not pop_file.exists():
            return {"error": "Keine Population"}
        try:
            pop = json.loads(pop_file.read_text(encoding="utf-8"))
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
                        })
                    except Exception:
                        pass
            return {
                "generation": pop.get("generation"),
                "total_runs": pop.get("total_runs"),
                "champion_id": pop.get("champion_id"),
                "agents": agent_summaries,
            }
        except Exception as e:
            return {"error": str(e)}

    elif name == "read_market_condition":
        cond_file = PROJECT_ROOT / "data" / "market_condition.json"
        if cond_file.exists():
            try:
                return json.loads(cond_file.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {"condition": "UNKNOWN"}

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
            return {"error": f"Ungueltiger Parameter: {param}"}

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
            action = f"'{param}' → {direction} (strength={strength:.1f}): {reason}"

        HINTS_FILE.parent.mkdir(parents=True, exist_ok=True)
        HINTS_FILE.write_text(json.dumps(hints, indent=2, ensure_ascii=False), encoding="utf-8")
        logger.info(f"Strategy Hint: {action}")
        return {"ok": True, "action": action, "total_hints": len(hints)}

    elif name == "write_diagnosis":
        diagnosis = {**inputs, "generated_at": datetime.now().isoformat()}
        DIAGNOSIS_FILE.parent.mkdir(parents=True, exist_ok=True)
        DIAGNOSIS_FILE.write_text(
            json.dumps(diagnosis, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        logger.info(f"Diagnose: {inputs.get('grade')} — {inputs.get('summary', '')[:80]}")
        return {"ok": True}

    return {"error": f"Unbekanntes Tool: {name}"}


# =============================================================================
# SYSTEM PROMPT
# =============================================================================

SYSTEM_PROMPT = """Du bist ein Strategie-Analyst fuer ein Polymarket Weather-Betting System (Paper Trading).

Deine Aufgabe:
1. Analysiere Performance-Daten, Positionen, Population und Marktbedingung via Tools
2. Erkenne Root Causes fuer Gewinne/Verluste
3. Setze gerichtete Mutations-Hints (1-3 Stueck, nur datenbasiert)
4. Schliesse mit write_diagnosis ab

Parameter-Wirkung:
- min_edge hoeher → weniger aber qualitativ bessere Trades
- kelly_fraction hoeher → groessere Positionen, mehr Risiko
- max_odds hoeher → auch Favoriten handelbar
- take_profit_pct niedriger → fruehzeitiger sicherer Exit
- stop_loss_pct hoeher → weniger voreilige SL-Exits
- min_liquidity hoeher → nur gute Maerkte, weniger Slippage

Typische Problemmuster:
- Viele SL-Exits → stop_loss_pct erhoehen ODER min_edge erhoehen
- Niedrige Win-Rate → min_edge erhoehen, max_odds senken
- Kein Trade-Flow → min_edge senken ODER min_liquidity senken
- Hoher Drawdown → kelly_fraction senken
- Wenig Daten → noch keine Hints setzen, nur beobachten

Reihenfolge: read_performance → read_recent_positions → read_population_status → (optional weitere) → set_mutation_bias (0-3x) → write_diagnosis"""


# =============================================================================
# PROVIDER CLIENT
# =============================================================================

def _get_client(provider: dict):
    """Erstelle OpenAI-kompatiblen Client fuer den Provider."""
    from openai import OpenAI

    api_key = os.environ.get(provider["env_key"], "").strip()
    if not api_key:
        return None

    kwargs = {"api_key": api_key}
    if provider["base_url"]:
        kwargs["base_url"] = provider["base_url"]

    return OpenAI(**kwargs)


# =============================================================================
# AGENT LOOP
# =============================================================================

def run_strategy_agent(max_iterations: int = 12) -> dict:
    """
    Starte den LLM Strategy Agent mit Tool-Use und Provider-Fallback.

    Reihenfolge: Kimi → OpenAI → OpenRouter

    Returns:
        Diagnosis dict oder {"error": ...}
    """
    # .env laden falls noch nicht geschehen
    env_file = PROJECT_ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())

    try:
        from openai import OpenAI  # noqa: F401
    except ImportError:
        return {"error": "openai Paket nicht installiert (pip install openai)"}

    # Provider mit Fallback durchprobieren
    client = None
    active_provider = None
    for provider in PROVIDERS:
        c = _get_client(provider)
        if c is not None:
            client = c
            active_provider = provider
            break

    if client is None:
        logger.warning("Kein LLM-Provider konfiguriert (KIMI/OPENAI/OPENROUTER Key fehlt)")
        return {"error": "Kein LLM-Provider verfuegbar"}

    logger.info(f"Strategy Agent gestartet via {active_provider['name']} ({active_provider['model']})")

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                "Analysiere die aktuelle System-Performance und gib gezielte Empfehlungen. "
                "Nutze die Tools in der beschriebenen Reihenfolge."
            ),
        },
    ]

    diagnosis: dict = {}
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

            # Fallback: naechsten Provider versuchen
            current_idx = PROVIDERS.index(active_provider)
            for fallback in PROVIDERS[current_idx + 1:]:
                c = _get_client(fallback)
                if c is not None:
                    logger.info(f"Fallback auf {fallback['name']} ({fallback['model']})")
                    client = c
                    active_provider = fallback
                    try:
                        response = client.chat.completions.create(
                            model=active_provider["model"],
                            messages=messages,
                            tools=TOOLS,
                            tool_choice="auto",
                            max_tokens=2048,
                            temperature=0.2,
                        )
                        break
                    except Exception as e2:
                        logger.warning(f"{fallback['name']} auch fehlgeschlagen: {e2}")
                        continue
            else:
                return {"error": f"Alle Provider fehlgeschlagen. Letzter Fehler: {e}"}

        choice = response.choices[0]

        # Assistenten-Nachricht korrekt aufbauen (content kann None sein bei tool_calls)
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
                    inputs = json.loads(tc.function.arguments)
                except Exception:
                    inputs = {}

                result = _execute_tool(tc.function.name, inputs)

                tool_results.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": json.dumps(result, ensure_ascii=False, default=str),
                })

                if tc.function.name == "write_diagnosis":
                    diagnosis = inputs
                elif tc.function.name == "set_mutation_bias" and result.get("ok"):
                    hints_applied.append(result.get("action", ""))

            messages.extend(tool_results)
        else:
            break

    if diagnosis:
        diagnosis["mutations_applied"] = hints_applied
        diagnosis["provider"] = active_provider["name"]

    logger.info(
        f"Strategy Agent fertig: grade={diagnosis.get('grade', '?')}, "
        f"hints={len(hints_applied)}, provider={active_provider['name']}, iter={i + 1}"
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
        provider = diagnosis.get("provider", "?")
        grade_emoji = {"HEALTHY": "✅", "DEGRADED": "⚠️", "CRITICAL": "🚨"}.get(grade, "❓")

        nl = "\n"
        lines = [
            f"{grade_emoji} <b>STRATEGY AGENT — {grade}</b> <i>({provider})</i>",
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
            lines += ["", "<b>Mutations-Hints:</b>"]
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

    print("Strategy Agent wird gestartet...")
    diagnosis = run_strategy_agent()

    if "error" in diagnosis:
        print(f"FEHLER: {diagnosis['error']}")
        sys.exit(1)

    print(f"\nProvider: {diagnosis.get('provider')}")
    print(f"Grade:    {diagnosis.get('grade')}")
    print(f"Summary:  {diagnosis.get('summary')}")
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
    print(f"\nDiagnose: {DIAGNOSIS_FILE}")


if __name__ == "__main__":
    main()
