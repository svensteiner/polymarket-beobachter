"""Agent — Autonomer Haupt-Loop (Vorlage v2.2).

Vorlage-Standard für alle AI_Studioxyz Agenten.
ReAct-Zyklus: Observe → Think → [Challenge] → Act → Reflect

NEU in v2.0:
  - Proaktive Goal-Generierung: Agent entwickelt eigene Ziele via Brain
  - MessageBus: Empfängt und sendet Nachrichten an andere Agenten
  - Eingehende Messages werden als Tasks verarbeitet

NEU in v2.2:
  - Governance: Action-Registry mit Cooldowns + Tageslimits (governance.py)
    → run_task() prüft can_act() vor jedem ACT-Schritt
    → gov.record() protokolliert jede Aktion in state/governance.json
  - Challenge: optionaler adversarialer Plan-Review via zweitem LLM-Call
    → aktivierbar per "challenge_enabled": true in config.json
    → blockiert Pläne mit risk_level "high" oder approved=false
  - Benachrichtigungen: Telegram + Slack als eigenständige Tools (tools/)
  - --status zeigt jetzt Governance-Übersicht aller registrierten Aktionen

Verwendung:
    python agent.py                    # Einmal ausführen
    python agent.py --loop             # Dauerbetrieb (alle X Minuten)
    python agent.py --task "Aufgabe"   # Spezifische Aufgabe
    python agent.py --dry-run          # Vorschau ohne Ausführung
    python agent.py --status           # Memory-Zusammenfassung
    python agent.py --messages         # Ungelesene Bus-Nachrichten anzeigen

Anpassen:
    1. SOUL.md mit Agenten-Identität füllen
    2. TOOLS mit eigenen Tools bestücken
    3. proactive_goals() mit domänenspezifischer Logik ergänzen
    4. run_task() Tool-Logik implementieren
"""

import argparse
import json
import logging
import os
import signal
import sys
import time
from datetime import datetime, date
from pathlib import Path

from dotenv import load_dotenv

import brain
from governance import Governor
from memory import Memory
from tools.message_bus import MessageBus

load_dotenv(Path(__file__).parent / ".env")

# ── Konfiguration ──────────────────────────────────────────────────────────

AGENT_NAME = "agent"  # ← ANPASSEN: Name dieses Agenten (z.B. "cmo", "cto", "cso")

CONFIG_PATH = Path(__file__).parent / "config.json"
LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [Agent] %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(str(LOG_DIR / "agent.log"), encoding="utf-8"),
    ],
)
logger = logging.getLogger("agent")


_REQUIRED_CONFIG_KEYS = {"agent_name", "model"}


def validate_config(cfg: dict) -> None:
    missing = _REQUIRED_CONFIG_KEYS - set(cfg.keys())
    if missing:
        logger.warning(f"Config-Felder fehlen (Defaults aktiv): {missing}")


def load_config() -> dict:
    if CONFIG_PATH.exists():
        cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        validate_config(cfg)
        return cfg
    return {
        "agent_name": AGENT_NAME,
        "loop_interval_minutes": 60,
        "max_retries": 2,
        "quality_threshold": 7,
        "dry_run": False,
        "proactive": True,
    }


# ── Tool-Registry ──────────────────────────────────────────────────────────
# Auto-Discovery lädt alle tools/*.py automatisch. Manuelle Overrides hier möglich.

TOOLS: dict = {}


def _load_tools() -> None:
    """Lädt alle BaseTool-Subklassen aus tools/ automatisch in TOOLS."""
    import importlib
    import inspect
    from tools.base_tool import BaseTool
    skip = {"base_tool", "message_bus", "__init__"}
    tools_dir = Path(__file__).parent / "tools"
    for path in tools_dir.glob("[!_]*.py"):
        if path.stem in skip:
            continue
        try:
            mod = importlib.import_module(f"tools.{path.stem}")
            for _, cls in inspect.getmembers(mod, inspect.isclass):
                if issubclass(cls, BaseTool) and cls is not BaseTool and cls.name != "base_tool":
                    inst = cls()
                    if inst.name not in TOOLS:
                        TOOLS[inst.name] = inst
                        logger.debug(f"Tool auto-geladen: {inst.name}")
        except Exception as e:
            logger.warning(f"Tool-Discovery ({path.stem}): {e}")


_load_tools()


# ── Proaktive Ziel-Generierung ─────────────────────────────────────────────

def proactive_goals(mem: Memory) -> list[dict]:
    """Der Agent analysiert seinen Zustand und generiert eigene Ziele.

    Das ist der Unterschied zwischen einem Script und einem Agenten:
    Er entscheidet selbst, was als nächstes wichtig ist.

    Anpassen: Ergänze domänenspezifische Trigger für diesen Agenten.
    """
    cfg = load_config()
    if not cfg.get("proactive", True):
        return []

    # Zustand für Brain aufbereiten
    summary = mem.summary()
    recent_actions = mem.load("actions", limit=10)
    recent_learnings = mem.load("learnings", limit=5)
    today = date.today().isoformat()
    weekday = date.today().strftime("%A")

    state_context = f"""
Aktueller Agenten-Zustand ({today}, {weekday}):

Memory-Übersicht: {json.dumps(summary, ensure_ascii=False)}

Letzte 5 Aktionen: {json.dumps([{
    'task': a.get('task', '')[:60],
    'success': a.get('success'),
    'date': a.get('date')
} for a in recent_actions[-5:]], ensure_ascii=False)}

Letzte Learnings: {json.dumps([l.get('insight', '') for l in recent_learnings], ensure_ascii=False)}

Aufgabe: Analysiere diesen Zustand und entscheide, was der Agent als nächstes tun sollte.
Generiere 1-3 konkrete, proaktive Aufgaben die JETZT relevant sind.
Berücksichtige: Was wurde heute noch nicht gemacht? Was sollte regelmäßig passieren?
Welche Learnings sollten in Aktionen umgesetzt werden?

Antworte NUR mit JSON:
{{
    "goals": [
        {{
            "id": "proactive_001",
            "task": "Konkrete Aufgabe die der Agent jetzt tun sollte",
            "reasoning": "Warum ist das jetzt wichtig",
            "priority": "high | medium | low"
        }}
    ],
    "skip_reason": null
}}
"""

    try:
        goals_raw = brain.proactive(state_context)
        if not goals_raw:
            return []

        goals = []
        for g in goals_raw[:3]:  # max 3 proaktive Goals
            goals.append({
                "id": g.get("id", f"proactive_{date.today().isoformat()}"),
                "task": g.get("task", ""),
                "source": "proactive",
                "priority": g.get("priority", "medium"),
                "reasoning": g.get("reasoning", ""),
            })

        logger.info(f"  Proaktiv: {len(goals)} eigene Ziele generiert")
        for g in goals:
            logger.info(f"    [{g['priority']}] {g['task'][:80]}")

        return goals

    except Exception as e:
        logger.warning(f"Proaktive Goal-Generierung fehlgeschlagen: {e}")
        return []


# ── MessageBus-Integration ─────────────────────────────────────────────────

def get_bus_tasks(bus: MessageBus) -> list[dict]:
    """Wandelt eingehende Bus-Nachrichten in ausführbare Tasks um."""
    messages = bus.receive(unread_only=True)
    if not messages:
        return []

    tasks = []
    for msg in messages:
        task_text = ""
        msg_type = msg.get("type", "")
        content = msg.get("content", "")
        sender = msg.get("from", "?")

        # Nachrichtentypen → Tasks
        if msg_type == "deploy_request":
            task_text = f"Deployment-Anfrage von {sender}: {content}"
        elif msg_type == "content_ready":
            task_text = f"Content von {sender} ist bereit zur Verarbeitung: {content}"
        elif msg_type == "alert":
            task_text = f"ALERT von {sender}: {content} — sofort reagieren"
        elif msg_type == "review_request":
            task_text = f"{sender} bittet um Review: {content}"
        elif msg_type == "task":
            task_text = str(content)
        else:
            task_text = f"Nachricht von {sender} ({msg_type}): {content}"

        if task_text:
            tasks.append({
                "id": f"bus_{msg['id']}",
                "task": task_text,
                "source": "message_bus",
                "bus_msg_id": msg["id"],
                "priority": msg.get("priority", "normal"),
            })

    if tasks:
        logger.info(f"  MessageBus: {len(tasks)} eingehende Nachrichten als Tasks")
    return tasks


# ── Task-Quelle (kombiniert) ────────────────────────────────────────────────

def get_tasks(mem: Memory, bus: MessageBus) -> list[dict]:
    """Sammelt Tasks aus allen Quellen:
    1. Externe Queue (tasks.json)
    2. Eingehende Bus-Nachrichten
    3. Proaktiv generierte Ziele (via Brain)
    """
    tasks = []

    # 1. Externe Task-Queue
    tasks_file = Path(__file__).parent / "tasks.json"
    if tasks_file.exists():
        queued = json.loads(tasks_file.read_text(encoding="utf-8"))
        pending = [t for t in queued if t.get("status") == "pending"]
        tasks.extend(pending)
        if pending:
            logger.info(f"  Queue: {len(pending)} Tasks aus tasks.json")

    # 2. Bus-Nachrichten (höhere Priorität als proaktive Ziele)
    bus_tasks = get_bus_tasks(bus)
    tasks.extend(bus_tasks)

    # 3. Proaktive Ziele (wenn Queue leer oder config erlaubt)
    cfg = load_config()
    if cfg.get("proactive", True):
        proactive = proactive_goals(mem)
        # Proaktive Goals nur hinzufügen wenn kein überlappender Task existiert
        existing_tasks = {t.get("task", "")[:40] for t in tasks}
        for g in proactive:
            if g.get("task", "")[:40] not in existing_tasks:
                tasks.append(g)

    # Sortiere: Priorität high → normal → medium → low
    priority_order = {"high": 0, "urgent": 0, "normal": 1, "medium": 2, "low": 3}
    tasks.sort(key=lambda t: priority_order.get(t.get("priority", "normal"), 2))

    return tasks


def _update_task_status(task_id: str, status: str, extra: dict = None) -> None:
    """Setzt Status eines Queue-Tasks (pending → in_progress → done/failed)."""
    tasks_file = Path(__file__).parent / "tasks.json"
    if not tasks_file.exists():
        return
    all_tasks = json.loads(tasks_file.read_text(encoding="utf-8"))
    for t in all_tasks:
        if t.get("id") == task_id:
            t["status"] = status
            t[f"{status}_at"] = datetime.now().isoformat()
            if extra:
                t.update(extra)
            break
    tasks_file.write_text(json.dumps(all_tasks, ensure_ascii=False, indent=2), encoding="utf-8")


def _recover_stuck_tasks() -> int:
    """Setzt in_progress-Tasks auf pending zurück (z.B. nach Absturz)."""
    tasks_file = Path(__file__).parent / "tasks.json"
    if not tasks_file.exists():
        return 0
    all_tasks = json.loads(tasks_file.read_text(encoding="utf-8"))
    stuck = [t for t in all_tasks if t.get("status") == "in_progress"]
    if stuck:
        for t in stuck:
            t["status"] = "pending"
            t["recovered_at"] = datetime.now().isoformat()
        tasks_file.write_text(json.dumps(all_tasks, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.warning(f"State Recovery: {len(stuck)} abgebrochene Task(s) zurückgesetzt")
    return len(stuck)


def mark_done(task: dict, bus: MessageBus) -> None:
    """Markiert Task als erledigt — inkl. Bus-Bestätigung."""
    _update_task_status(task.get("id", ""), "done")

    # Bus-Nachricht als gelesen markieren
    if task.get("bus_msg_id"):
        bus.mark_read(task["bus_msg_id"])


# ── Kern-Loop: Observe → Think → Act → Reflect ────────────────────────────

def run_task(task: dict, mem: Memory, bus: MessageBus, gov: Governor = None, dry_run: bool = False) -> dict:
    """Führt einen Task durch den vollen ReAct-Zyklus."""
    task_text = task.get("task", str(task))
    task_id = task.get("id", "?")
    task_source = task.get("source", "queue")
    cfg = load_config()
    max_retries = cfg.get("max_retries", 2)

    source_label = {"proactive": "🎯", "message_bus": "📨", "queue": "📋"}.get(task_source, "•")
    logger.info(f"─── {source_label} Task [{task_id}]: {task_text[:80]}")

    # ── 1. OBSERVE ────────────────────────────────────────────────
    context_parts = []
    recent = mem.load("actions", limit=5)
    if recent:
        context_parts.append(f"Letzte Aktionen: {json.dumps(recent[-3:], ensure_ascii=False)}")
    learnings = mem.load("learnings", limit=5)
    if learnings:
        context_parts.append(f"Learnings: {[l.get('insight', '') for l in learnings[-3:]]}")

    # Bus-Kontext: Gibt es relevante Nachrichten anderer Agenten?
    unread = bus.unread_count()
    if unread > 0:
        context_parts.append(f"Ungelesene Bus-Nachrichten: {unread}")

    context_parts.append(f"Task-Quelle: {task_source}")
    context = "\n".join(context_parts)

    # ── 2. THINK ──────────────────────────────────────────────────
    logger.info("  → Think...")
    plan = brain.think(task_text, context)
    logger.info(f"  → Plan: {plan.get('plan', [])[:2]}")
    logger.info(f"  → Tool: {plan.get('tool', 'keins')}")

    if plan.get("needs_human"):
        reason = plan.get("reasoning", "")
        logger.warning(f"  → Eskalation: Mensch benötigt — {reason[:80]}")
        mem.save("escalations", {"task": task_text, "reason": reason, "source": task_source})
        # Sofortige Benachrichtigung an Menschen (Telegram/Slack)
        if "notify" in TOOLS:
            agent_name = cfg.get("agent_name", AGENT_NAME)
            TOOLS["notify"].safe_run(
                f"⚠️ [{agent_name}] Eskalation\n\nAufgabe: {task_text[:200]}\n\nGrund: {reason[:300]}"
            )
        # Auch über Bus melden (für andere Agenten)
        bus.send("all", "escalation", {
            "task": task_text[:100],
            "reason": reason,
        }, priority="high")
        return {"success": False, "result": "Eskalation", "learning": {}}

    # ── 2.5 CHALLENGE (optional — zweite Meinung vor dem Handeln) ─────────
    if cfg.get("challenge_enabled", False):
        review = brain.challenge(plan, context)
        risk = review.get("risk_level", "low")
        if risk == "high":
            logger.warning(f"  → Challenge blockiert Plan (risk=high): {review.get('concerns', [])}")
            if review.get("suggestion"):
                logger.info(f"  → Vorschlag: {review['suggestion'][:100]}")
            mem.save("escalations", {
                "task": task_text,
                "reason": f"Challenge high-risk: {review.get('concerns')}",
                "source": task_source,
            })
            return {"success": False, "result": "Challenge abgelehnt (high risk)", "learning": {}}
        if risk == "medium" or not review.get("approved"):
            logger.warning(f"  → Challenge Warnung (risk={risk}): {review.get('concerns', [])} — fahre fort")
            if review.get("suggestion"):
                logger.info(f"  → Vorschlag: {review['suggestion'][:100]}")
        elif review.get("concerns"):
            logger.info(f"  → Challenge OK, Hinweise: {review['concerns']}")

    if dry_run:
        logger.info(f"  [DRY RUN] Plan: {json.dumps(plan, ensure_ascii=False)[:200]}")
        return {"success": True, "result": "dry-run", "learning": {}}

    # ── 3. ACT ───────────────────────────────────────────────────
    tool_name = plan.get("tool")
    tool_input = plan.get("tool_input", task_text)
    tool_result = ""

    # Governance: Cooldown + Tageslimit prüfen
    if gov is not None:
        action_key = tool_name or "run_task"
        ok, reason = gov.can_act(action_key)
        if not ok:
            logger.info(f"  → Governance blockiert: {reason}")
            return {"success": False, "result": f"Blockiert: {reason}", "learning": {}}

    for attempt in range(max_retries + 1):
        if attempt > 0:
            wait = 2 ** attempt
            logger.info(f"  → Retry {attempt}/{max_retries} (warte {wait}s)...")
            time.sleep(wait)

        if tool_name and tool_name in TOOLS:
            logger.info(f"  → Tool: {tool_name}")
            tool_result = TOOLS[tool_name].safe_run(tool_input)
        else:
            # ── ANPASSEN: Eigene Ausführungslogik ──────────────
            logger.info(f"  → Direkte Ausführung")
            tool_result = f"Task '{task_text[:60]}' verarbeitet."

        act_result = brain.act(plan, tool_result)
        logger.info(f"  → {act_result.get('next_action')} | {act_result.get('summary', '')[:80]}")

        if act_result.get("success") or act_result.get("next_action") == "escalate":
            break

    # Qualitäts-Check: Ergebnis bewerten (nur wenn Output vorhanden)
    output = act_result.get("output") or tool_result
    if output and cfg.get("quality_threshold", 7) > 0:
        quality = brain.evaluate(output, content_type="agent_output")
        if not quality.get("passes") and quality.get("improved_version"):
            act_result["output"] = quality["improved_version"]
            logger.info(f"  → Qualität: {quality.get('score')}/10 — verbesserte Version übernommen")
        else:
            logger.debug(f"  → Qualität: {quality.get('score')}/10")

    # ── 4. REFLECT ────────────────────────────────────────────────
    learning = brain.reflect(
        action_taken=f"Task: {task_text[:60]}, Tool: {tool_name}, Quelle: {task_source}",
        result=act_result.get("summary", tool_result),
        expected="Erfolgreiche Ausführung",
    )
    logger.info(f"  → Learning: {learning.get('insight', '')[:80]}")

    # ── 5. PERSISTIEREN ───────────────────────────────────────────
    success = act_result.get("success", False)

    mem.save("actions", {
        "task": task_text[:200],
        "task_id": task_id,
        "task_source": task_source,
        "tool": tool_name,
        "success": success,
        "summary": act_result.get("summary", ""),
    })

    if learning.get("insight"):
        mem.save("learnings", {
            "insight": learning["insight"],
            "source": task_id,
            "improve": learning.get("improve_next_time"),
        })

    # Governance: Aktion protokollieren
    if gov is not None:
        action_key = tool_name or "run_task"
        gov.record(action_key, result="success" if success else "failed", details=task_text[:100])

    # Erfolgreiche proaktive Aktionen als Metriken tracken
    if task_source == "proactive" and success:
        mem.log_metric("proactive_success", 1.0)

    return {
        "success": success,
        "result": act_result.get("output") or act_result.get("summary", ""),
        "learning": learning,
    }


# ── Haupt-Entrypoints ──────────────────────────────────────────────────────


def _write_heartbeat(agent_name: str) -> None:
    """Schreibt Lebenszeichen-Datei für externes Monitoring."""
    path = Path(__file__).parent / "state" / "heartbeat.json"
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps({
        "agent": agent_name,
        "alive_at": datetime.now().isoformat(),
        "pid": os.getpid(),
    }, ensure_ascii=False), encoding="utf-8")

def _log_session_summary(mem: Memory, successes: int, failures: int) -> None:
    """Schreibt Session-Zusammenfassung nach jedem Zyklus."""
    usage = brain.get_usage_stats()
    total = successes + failures
    success_rate = successes / total if total else 0

    if usage["calls"] > 0:
        cache_info = ""
        if usage["cache_read_tokens"] > 0:
            cache_info = f", Cache-Ersparnis: {usage['cache_savings_pct']}%"
        logger.info(
            f"Session: {total} Task(s), {successes} ✅ {failures} ❌ | "
            f"LLM: {usage['calls']} Calls, {usage['billed_tokens']:,} abgerechnet{cache_info}"
        )
        mem.log_metric("llm_tokens", usage["billed_tokens"])
        mem.log_metric("session_success_rate", success_rate)

    # Benachrichtigung bei kritischer Fehlerrate (>50% Failures, mind. 2 Tasks)
    cfg = load_config()
    agent_name = cfg.get("agent_name", AGENT_NAME)
    if failures >= 2 and (failures / max(successes + failures, 1)) > 0.5:
        if "notify" in TOOLS:
            msg = (
                f"\u26a0\ufe0f [{agent_name}] Hohe Fehlerrate\n"
                f"{failures} von {successes + failures} Tasks fehlgeschlagen.\n"
                f"LLM: {usage.get('calls', 0)} Calls, {usage.get('billed_tokens', 0):,} Token"
            )
            TOOLS["notify"].safe_run(msg)


def run_once(task_text: str = None, dry_run: bool = False) -> None:
    """Führt einen vollständigen Agenten-Zyklus aus."""
    cfg = load_config()
    agent_name = cfg.get("agent_name", AGENT_NAME)
    mem = Memory()
    bus = MessageBus(agent_name=agent_name)

    # State Recovery: abgebrochene Tasks aus letzter Session zurücksetzen
    _recover_stuck_tasks()

    # Cleanup alter Bus-Nachrichten
    bus.cleanup(max_age_days=7)

    if task_text:
        tasks = [{"id": "cli", "task": task_text, "source": "cli"}]
    else:
        tasks = get_tasks(mem, bus)

    if not tasks:
        logger.info("Keine Tasks — Agent ist idle.")
        return

    # Tageslimit prüfen (max_actions_per_day in config.json)
    max_actions = cfg.get("max_actions_per_day", 0)
    if max_actions > 0:
        done_today = mem.count_today("actions", success=True)
        if done_today >= max_actions:
            logger.info(f"Tageslimit erreicht ({done_today}/{max_actions} Aktionen) — Agent pausiert bis morgen.")
            return
        remaining = max_actions - done_today
        if remaining < len(tasks):
            tasks = tasks[:remaining]
            logger.info(f"Tageslimit: noch {remaining} Aktionen möglich — {len(tasks)} Tasks eingeplant.")

    logger.info(f"Agent [{agent_name}] startet — {len(tasks)} Task(s)")

    gov = Governor()
    # ── ANPASSEN: Aktionen mit Cooldown/Tageslimit registrieren ───────────
    # gov.register("send_report",  cooldown_hours=24,    description="Tagesreport")
    # gov.register("notify",       cooldown_minutes=30,  description="Benachrichtigung", max_per_day=10)
    # gov.register("web_search",   cooldown_minutes=5,   description="Web-Suche",        max_per_day=50)
    # gov.register("file",         cooldown_minutes=1,   description="Datei schreiben")
    brain.reset_usage_stats()
    successes = failures = 0

    for task in tasks:
        # in_progress markieren vor Ausführung (Crash-Recovery)
        if task.get("source") == "queue":
            _update_task_status(task.get("id", ""), "in_progress")

        result = run_task(task, mem, bus, gov=gov, dry_run=dry_run or cfg.get("dry_run", False))
        if result["success"]:
            mark_done(task, bus)
            successes += 1
            logger.info(f"✅ Task erledigt: {task.get('id', '?')}")
        else:
            _update_task_status(task.get("id", ""), "failed")
            failures += 1
            logger.warning(f"⚠️  Task fehlgeschlagen: {task.get('id', '?')}")

    _log_session_summary(mem, successes, failures)


def run_loop(interval_minutes: int = None) -> None:
    """Dauerbetrieb: läuft alle X Minuten."""
    cfg = load_config()
    interval = interval_minutes or cfg.get("loop_interval_minutes", 60)

    running = [True]

    def handle_stop(sig, frame):
        logger.info("Signal empfangen — stoppe nach diesem Zyklus...")
        running[0] = False

    signal.signal(signal.SIGTERM, handle_stop)
    signal.signal(signal.SIGINT, handle_stop)

    logger.info(f"Dauerbetrieb gestartet — Zyklus alle {interval} Minuten")

    while running[0]:
        _write_heartbeat(cfg.get("agent_name", AGENT_NAME))
        try:
            run_once()
        except Exception as e:
            logger.error(f"Fehler im Zyklus: {e}", exc_info=True)

        if running[0]:
            logger.info(f"Nächster Zyklus in {interval} Minuten...")
            time.sleep(interval * 60)

    logger.info("Agent gestoppt.")


# ── CLI ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Autonomer Agent (Vorlage v2.2)")
    parser.add_argument("--loop", action="store_true", help="Dauerbetrieb")
    parser.add_argument("--task", type=str, help="Spezifischer Task")
    parser.add_argument("--dry-run", action="store_true", help="Vorschau ohne Ausführung")
    parser.add_argument("--status", action="store_true", help="Memory-Status anzeigen")
    parser.add_argument("--interval", type=int, help="Loop-Intervall in Minuten")
    parser.add_argument("--messages", action="store_true", help="Bus-Nachrichten anzeigen")
    args = parser.parse_args()

    cfg = load_config()
    agent_name = cfg.get("agent_name", AGENT_NAME)

    if args.status:
        mem = Memory()
        summary = mem.summary()
        print(f"\n=== Agent [{agent_name}] Memory Status ===")
        for key, info in summary.items():
            print(f"  {key}: {info['total']} gesamt, {info['today']} heute, letzter: {info['last']}")

        # Token-Kosten der letzten 7 Tage
        avg_tokens = mem.avg_metric("llm_tokens", days=7)
        if avg_tokens is not None:
            print(f"\n  Ø Tokens/Zyklus (7 Tage): {avg_tokens:,.0f}")

        # Verfügbare Tools anzeigen
        print(f"\n  Tools geladen: {list(TOOLS.keys()) or '(keine)'}")

        avg_proactive = mem.avg_metric("proactive_success", days=7)
        if avg_proactive is not None:
            print(f"\n  Proaktive Erfolgsrate (7 Tage): {avg_proactive:.0%}")

        # Governance-Status
        gov = Governor()
        gov_summary = gov.summary_text()
        if "(keine" not in gov_summary:
            print(f"\n  Governance:\n{gov_summary}")
        return

    if args.messages:
        bus = MessageBus(agent_name=agent_name)
        msgs = bus.receive(unread_only=False)
        print(f"\n=== Bus-Nachrichten für [{agent_name}] ===")
        if not msgs:
            print("  Keine Nachrichten.")
        for m in msgs[-10:]:
            status = "📬" if not m.get("read") else "✓"
            print(f"  {status} [{m['priority']}] Von {m['from']}: {m['type']} — {str(m['content'])[:60]}")
        return

    if args.loop:
        run_loop(interval_minutes=args.interval)
    else:
        run_once(task_text=args.task, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
