"""
meta/self_improver.py - Autonomer Code-Verbesserungs-Agent

Liest Pipeline-Performance nach jedem N-ten Run, identifiziert den
Top-Engpass, ruft Claude via OpenRouter auf, wendet den Fix an,
testet, und committet bei Erfolg.

Sicherheitsmechanismen:
- Nur Dateien in ALLOWED_FILES werden modifiziert
- Eine Aenderung pro Zyklus
- Revert bei Test-Fehler
- Cooldown pro Datei (keine Re-Modifikation innerhalb COOLDOWN_CYCLES)
- Alle Entscheidungen werden in logs/self_improver.jsonl protokolliert
- Trockenlauf-Modus standardmaessig aktiviert
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent

# ============================================================================
# KONFIGURATION
# ============================================================================

# Dateien die der Agent modifizieren darf
ALLOWED_FILES = [
    "core/weather_engine.py",
    "core/weather_market_filter.py",
    "core/weather_probability_model.py",
    "paper_trader/simulator.py",
    "paper_trader/averaging_down.py",
    "paper_trader/edge_reversal.py",
    "paper_trader/kelly.py",
    "analytics/outcome_analyser.py",
    "analytics/arbitrage_detector.py",
    "collector/client.py",
]

# Wie viele Pipeline-Runs zwischen Verbesserungszyklen
IMPROVEMENT_INTERVAL = 4

# Keine Re-Modifikation derselben Datei innerhalb N Zyklen
COOLDOWN_CYCLES = 3

# OpenRouter-Konfiguration
OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "anthropic/claude-opus-4-5"
MAX_TOKENS = 4096

# Audit-Log
AUDIT_LOG = PROJECT_ROOT / "logs" / "self_improver.jsonl"
STATE_FILE = PROJECT_ROOT / "logs" / "self_improver_state.json"

# Maximale Kontextzeilen pro Datei
MAX_FILE_LINES = 300


# ============================================================================
# HILFSFUNKTIONEN
# ============================================================================

def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_json_file(path: Path) -> dict[str, Any]:
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except Exception as exc:
        logger.debug("JSON-Load fehlgeschlagen (%s): %s", path, exc)
    return {}


def _write_json_file(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def _append_audit(entry: dict[str, Any]) -> None:
    AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(AUDIT_LOG, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _read_file_excerpt(relative_path: str, max_lines: int = MAX_FILE_LINES) -> str:
    path = PROJECT_ROOT / relative_path
    if not path.exists():
        return f"# Datei nicht gefunden: {relative_path}"
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
        if len(lines) <= max_lines:
            return "\n".join(lines)
        # Erste und letzte Haelfte zeigen
        half = max_lines // 2
        return "\n".join(lines[:half]) + f"\n\n... [{len(lines) - max_lines} Zeilen gekuerzt] ...\n\n" + "\n".join(lines[-half:])
    except OSError as exc:
        return f"# Lesefehler: {exc}"


# ============================================================================
# KONTEXT-SAMMLUNG
# ============================================================================

def _collect_context() -> dict[str, Any]:
    """Sammle relevanten Pipeline-Kontext fuer den LLM-Prompt."""
    ctx: dict[str, Any] = {}

    # Performance Report
    perf = _load_json_file(PROJECT_ROOT / "analytics" / "performance_report.json")
    ctx["performance"] = {
        "total_trades": perf.get("metrics", {}).get("total_trades", 0),
        "win_rate_pct": perf.get("metrics", {}).get("win_rate_pct", 0.0),
        "total_pnl_eur": perf.get("metrics", {}).get("total_pnl_eur", 0.0),
        "health": perf.get("health", "UNKNOWN"),
        "performance_by_month": perf.get("performance_by_month", {}),
    }

    # Bot Health
    health = _load_json_file(PROJECT_ROOT / "logs" / "bot_health.json")
    ctx["bot_health"] = {
        "status": health.get("status", "UNKNOWN"),
        "triggers": health.get("triggers", []),
        "metrics": health.get("metrics_snapshot", {}),
    }

    # Letzte Beobachtungen
    obs_log = PROJECT_ROOT / "logs" / "weather_observations.jsonl"
    recent_obs: list[dict[str, Any]] = []
    if obs_log.exists():
        try:
            lines = obs_log.read_text(encoding="utf-8").splitlines()
            for line in reversed(lines[-200:]):
                if not line.strip() or not line.startswith("{"):
                    continue
                try:
                    recent_obs.append(json.loads(line))
                    if len(recent_obs) >= 20:
                        break
                except json.JSONDecodeError:
                    continue
        except OSError:
            pass

    observe_count = sum(1 for o in recent_obs if o.get("action") == "OBSERVE")
    no_signal_count = sum(1 for o in recent_obs if o.get("action") == "NO_SIGNAL")
    ctx["recent_observations"] = {
        "total_recent": len(recent_obs),
        "observe_count": observe_count,
        "no_signal_count": no_signal_count,
        "observation_rate_pct": round(observe_count / max(len(recent_obs), 1) * 100, 1),
    }

    # Market Condition
    mc = _load_json_file(PROJECT_ROOT / "data" / "market_condition.json")
    ctx["market_condition"] = mc.get("condition", "UNKNOWN")

    # Status Summary (letzter Pipeline-Run)
    summary_path = PROJECT_ROOT / "output" / "status_summary.txt"
    if summary_path.exists():
        try:
            ctx["last_run_summary"] = summary_path.read_text(encoding="utf-8")[:1000]
        except OSError:
            ctx["last_run_summary"] = ""

    return ctx


# ============================================================================
# OPENROUTER API
# ============================================================================

def _call_openrouter(prompt: str, model: str | None = None) -> str | None:
    """Rufe Claude via OpenRouter API auf."""
    import urllib.request
    import urllib.error

    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    if not api_key:
        logger.warning("OPENROUTER_API_KEY nicht gesetzt — self_improver deaktiviert")
        return None

    chosen_model = model or os.environ.get("SELF_IMPROVER_MODEL", DEFAULT_MODEL)

    payload = {
        "model": chosen_model,
        "max_tokens": MAX_TOKENS,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Du bist ein Code-Analyse-Assistent fuer einen Python Polymarket Weather-Betting Bot. "
                    "Antworte ausschliesslich mit einem JSON-Objekt. Kein Markdown, kein Fliesstext."
                ),
            },
            {"role": "user", "content": prompt},
        ],
    }

    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            OPENROUTER_API_URL,
            data=data,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://github.com/polymarket-beobachter",
                "X-Title": "polymarket-self-improver",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=60) as response:
            result = json.loads(response.read().decode("utf-8"))
            return result["choices"][0]["message"]["content"]
    except urllib.error.HTTPError as exc:
        logger.warning("OpenRouter HTTP-Fehler %s: %s", exc.code, exc.read().decode("utf-8", errors="replace")[:300])
    except urllib.error.URLError as exc:
        logger.warning("OpenRouter URL-Fehler: %s", exc.reason)
    except Exception as exc:
        logger.warning("OpenRouter unbekannter Fehler: %s", exc)
    return None


# ============================================================================
# VERBESSERUNGS-LOGIK
# ============================================================================

def _build_improvement_prompt(ctx: dict[str, Any], candidate_files: list[str]) -> str:
    """Baue den Prompt fuer den Verbesserungs-Zyklus."""
    perf = ctx.get("performance", {})
    obs = ctx.get("recent_observations", {})
    health = ctx.get("bot_health", {})

    file_contents = {}
    for f in candidate_files[:3]:  # Max 3 Dateien im Kontext
        file_contents[f] = _read_file_excerpt(f, max_lines=150)

    files_section = ""
    for fname, content in file_contents.items():
        files_section += f"\n### {fname}\n```python\n{content}\n```\n"

    prompt = f"""Analysiere diesen Polymarket Weather-Betting Bot und identifiziere die EINE wichtigste Code-Verbesserung.

## Aktuelle Performance
- Trades gesamt: {perf.get('total_trades', 0)}
- Win-Rate: {perf.get('win_rate_pct', 0.0):.1f}%
- P&L: {perf.get('total_pnl_eur', 0.0):.2f} EUR
- Gesundheit: {perf.get('health', 'UNKNOWN')}

## Beobachtungsrate (letzte 20 Runs)
- Beobachtungen mit Edge: {obs.get('observe_count', 0)}/{obs.get('total_recent', 0)}
- Beobachtungsrate: {obs.get('observation_rate_pct', 0.0):.1f}%

## Bot-Zustand
- Status: {health.get('status', 'UNKNOWN')}
- Trigger: {', '.join(health.get('triggers', [])) or 'keine'}

## Marktbedingung: {ctx.get('market_condition', 'UNKNOWN')}

## Erlaubte Dateien (nur diese duerfen veraendert werden)
{json.dumps(candidate_files, ensure_ascii=False)}

## Code-Kontext
{files_section}

## Aufgabe
Identifiziere die EINE wichtigste Verbesserung die die Beobachtungsrate oder Win-Rate erhoehen wuerde.
Aenderungen muessen minimal, sicher und testbar sein (max 20 Zeilen).

Antworte NUR mit diesem JSON-Schema (kein Markdown, kein Text ausserhalb):
{{
  "file": "relativer/pfad/zur/datei.py",
  "issue": "Kurze Beschreibung des Problems (1 Satz)",
  "confidence": "HIGH|MEDIUM|LOW",
  "old_code": "exakter Code der ersetzt wird (mind. 3 Zeilen Kontext)",
  "new_code": "neuer Code (Einrueckung beibehalten)",
  "explanation": "Warum diese Aenderung die Performance verbessert",
  "test_command": "pytest tests/ -q -k relevanter_testname --timeout=30"
}}

Wenn keine sinnvolle Verbesserung moeglich ist (Code ist bereits gut), antworte mit:
{{"file": null, "issue": "Kein Verbesserungsbedarf identifiziert", "confidence": "HIGH"}}
"""
    return prompt


def _parse_suggestion(raw_response: str) -> dict[str, Any] | None:
    """Parse JSON-Antwort des LLM."""
    # Extrahiere JSON aus Markdown-Code-Block falls vorhanden
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw_response, re.DOTALL)
    if match:
        raw_response = match.group(1)

    # Versuche direkt zu parsen
    try:
        data = json.loads(raw_response.strip())
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        # Versuche JSON-Block zu finden
        match = re.search(r"\{.*\}", raw_response, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass
    logger.warning("Konnte JSON-Antwort nicht parsen: %s...", raw_response[:200])
    return None


def _apply_change(suggestion: dict[str, Any]) -> tuple[bool, str]:
    """Wende Code-Aenderung an. Gibt (success, message) zurueck."""
    file_rel = suggestion.get("file", "")
    old_code = suggestion.get("old_code", "")
    new_code = suggestion.get("new_code", "")

    if not file_rel or not old_code or not new_code:
        return False, "Unvollstaendiger Vorschlag (file/old_code/new_code fehlt)"

    # Sicherheitscheck: Nur erlaubte Dateien
    if file_rel not in ALLOWED_FILES:
        return False, f"Datei nicht in ALLOWED_FILES: {file_rel}"

    file_path = PROJECT_ROOT / file_rel
    if not file_path.exists():
        return False, f"Datei nicht gefunden: {file_rel}"

    content = file_path.read_text(encoding="utf-8")

    if old_code not in content:
        return False, f"old_code nicht in Datei gefunden: {file_rel}"

    # Exakt eine Ersetzung durchfuehren
    occurrences = content.count(old_code)
    if occurrences > 1:
        return False, f"old_code {occurrences}x gefunden — zu uneindeutig fuer sicheren Replace"

    new_content = content.replace(old_code, new_code, 1)
    file_path.write_text(new_content, encoding="utf-8")
    return True, f"Erfolgreich angewendet: {file_rel}"


def _revert_change(suggestion: dict[str, Any]) -> bool:
    """Mache Code-Aenderung rueckgaengig."""
    file_rel = suggestion.get("file", "")
    old_code = suggestion.get("old_code", "")
    new_code = suggestion.get("new_code", "")

    if not file_rel or not old_code or not new_code:
        return False

    file_path = PROJECT_ROOT / file_rel
    if not file_path.exists():
        return False

    content = file_path.read_text(encoding="utf-8")
    if new_code not in content:
        logger.warning("new_code nicht mehr in Datei — Revert nicht moeglich: %s", file_rel)
        return False

    new_content = content.replace(new_code, old_code, 1)
    file_path.write_text(new_content, encoding="utf-8")
    return True


def _run_tests(test_command: str | None = None) -> tuple[bool, str]:
    """Fuehre Tests aus. Gibt (passed, output) zurueck."""
    cmd = test_command or "pytest tests/ -q --timeout=30 --ignore=tests/e2e -x"
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            cwd=str(PROJECT_ROOT),
            timeout=120,
        )
        passed = result.returncode == 0
        output = (result.stdout + result.stderr)[-2000:]
        return passed, output
    except subprocess.TimeoutExpired:
        return False, "Test-Timeout nach 120s"
    except Exception as exc:
        return False, f"Test-Ausführungsfehler: {exc}"


def _git_commit(suggestion: dict[str, Any]) -> bool:
    """Committe Aenderung via git."""
    file_rel = suggestion.get("file", "")
    issue = suggestion.get("issue", "auto-improvement")
    explanation = suggestion.get("explanation", "")

    msg = f"auto: {issue[:60]}\n\n{explanation[:300]}\n\nCo-Authored-By: self_improver <bot@polymarket-beobachter>"
    try:
        subprocess.run(
            ["git", "add", str(PROJECT_ROOT / file_rel)],
            cwd=str(PROJECT_ROOT),
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "commit", "-m", msg],
            cwd=str(PROJECT_ROOT),
            check=True,
            capture_output=True,
        )
        return True
    except subprocess.CalledProcessError as exc:
        logger.warning("Git-Commit fehlgeschlagen: %s", exc.stderr.decode("utf-8", errors="replace")[:200])
        return False


# ============================================================================
# ZUSTANDSVERWALTUNG
# ============================================================================

def _load_state() -> dict[str, Any]:
    return _load_json_file(STATE_FILE)


def _save_state(state: dict[str, Any]) -> None:
    _write_json_file(STATE_FILE, state)


def _get_candidate_files(state: dict[str, Any]) -> list[str]:
    """Waehle modifizierbare Dateien aus (Cooldown beachten)."""
    cooldowns: dict[str, int] = state.get("cooldowns", {})
    current_cycle = int(state.get("cycle_count", 0))
    return [
        f for f in ALLOWED_FILES
        if current_cycle - cooldowns.get(f, -999) >= COOLDOWN_CYCLES
    ]


# ============================================================================
# HAUPT-EINSTIEGSPUNKT
# ============================================================================

def run_improvement_cycle(dry_run: bool = True) -> dict[str, Any]:
    """
    Fuehre einen Verbesserungszyklus durch.

    Args:
        dry_run: Wenn True, wird keine Datei veraendert (nur Vorschlag geloggt)

    Returns:
        Dict mit Ergebnis des Zyklus
    """
    state = _load_state()
    cycle = int(state.get("cycle_count", 0)) + 1
    state["cycle_count"] = cycle

    result: dict[str, Any] = {
        "cycle": cycle,
        "started_at": _iso_now(),
        "dry_run": dry_run,
        "outcome": "no_action",
        "suggestion": None,
        "applied": False,
        "tests_passed": None,
        "committed": False,
        "error": None,
    }

    logger.info("SelfImprover Zyklus %d (dry_run=%s)", cycle, dry_run)

    # Kontext sammeln
    ctx = _collect_context()
    candidate_files = _get_candidate_files(state)

    if not candidate_files:
        result["outcome"] = "all_files_on_cooldown"
        result["error"] = "Alle erlaubten Dateien befinden sich im Cooldown"
        _append_audit({**result, "context_summary": ctx.get("performance", {})})
        _save_state(state)
        return result

    # LLM aufrufen
    prompt = _build_improvement_prompt(ctx, candidate_files)
    raw_response = _call_openrouter(prompt)

    if raw_response is None:
        result["outcome"] = "api_error"
        result["error"] = "OpenRouter API nicht erreichbar oder API-Key fehlt"
        _append_audit(result)
        _save_state(state)
        return result

    # Antwort parsen
    suggestion = _parse_suggestion(raw_response)
    if suggestion is None:
        result["outcome"] = "parse_error"
        result["error"] = f"JSON-Parse fehlgeschlagen: {raw_response[:200]}"
        _append_audit(result)
        _save_state(state)
        return result

    result["suggestion"] = suggestion

    # Kein Aenderungsbedarf erkannt
    if suggestion.get("file") is None:
        result["outcome"] = "no_improvement_needed"
        logger.info("SelfImprover: Kein Verbesserungsbedarf erkannt (%s)", suggestion.get("issue", ""))
        _append_audit(result)
        _save_state(state)
        return result

    # Vertrauens-Filter: LOW confidence nicht automatisch anwenden
    if suggestion.get("confidence", "HIGH") == "LOW":
        result["outcome"] = "low_confidence_skipped"
        result["error"] = f"LOW confidence — kein Auto-Apply: {suggestion.get('issue', '')}"
        logger.info("SelfImprover: LOW confidence, uebersprungen")
        _append_audit(result)
        _save_state(state)
        return result

    if dry_run:
        result["outcome"] = "dry_run_suggestion"
        logger.info(
            "SelfImprover [DRY RUN]: %s -> %s",
            suggestion.get("file", ""),
            suggestion.get("issue", ""),
        )
        _append_audit(result)
        _save_state(state)
        return result

    # Aenderung anwenden
    applied, apply_msg = _apply_change(suggestion)
    result["applied"] = applied

    if not applied:
        result["outcome"] = "apply_failed"
        result["error"] = apply_msg
        logger.warning("SelfImprover: Apply fehlgeschlagen: %s", apply_msg)
        _append_audit(result)
        _save_state(state)
        return result

    logger.info("SelfImprover: Aenderung angewendet: %s", apply_msg)

    # Tests ausfuehren
    tests_passed, test_output = _run_tests(suggestion.get("test_command"))
    result["tests_passed"] = tests_passed
    result["test_output"] = test_output[-500:] if test_output else ""

    if not tests_passed:
        # Revert
        reverted = _revert_change(suggestion)
        result["outcome"] = "reverted"
        result["error"] = f"Tests fehlgeschlagen, Revert {'ok' if reverted else 'FEHLGESCHLAGEN'}"
        logger.warning("SelfImprover: Tests fehlgeschlagen, Revert durchgefuehrt")
        _append_audit(result)
        _save_state(state)
        return result

    # Tests bestanden — committen
    committed = _git_commit(suggestion)
    result["committed"] = committed
    result["outcome"] = "committed" if committed else "applied_no_commit"

    # Cooldown fuer diese Datei setzen
    cooldowns: dict[str, int] = state.get("cooldowns", {})
    cooldowns[suggestion["file"]] = cycle
    state["cooldowns"] = cooldowns
    state["last_successful_cycle"] = cycle
    state["last_improvement"] = {
        "file": suggestion.get("file"),
        "issue": suggestion.get("issue"),
        "committed_at": _iso_now(),
    }

    logger.info(
        "SelfImprover: Verbesserung %s — %s",
        "committed" if committed else "angewendet (kein Commit)",
        suggestion.get("issue", ""),
    )

    result["completed_at"] = _iso_now()
    _append_audit(result)
    _save_state(state)
    return result


def should_run(run_count: int) -> bool:
    """Pruefe ob ein Verbesserungszyklus faellig ist."""
    return run_count > 0 and run_count % IMPROVEMENT_INTERVAL == 0


if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    # .env laden falls verfuegbar (fuer standalone-Ausfuehrung)
    try:
        from dotenv import load_dotenv
        load_dotenv(PROJECT_ROOT / ".env", override=False)
    except ImportError:
        pass

    parser = argparse.ArgumentParser(description="SelfImprover - Autonomer Code-Verbesserungs-Agent")
    parser.add_argument("--apply", action="store_true", help="Aenderungen anwenden (Standard: Trockenlauf)")
    parser.add_argument("--cycle", type=int, default=1, help="Anzahl der Zyklen")
    args = parser.parse_args()

    for i in range(args.cycle):
        print(f"\n--- Zyklus {i+1}/{args.cycle} ---")
        result = run_improvement_cycle(dry_run=not args.apply)
        print(f"Ergebnis: {result['outcome']}")
        if result.get("suggestion") and result["suggestion"].get("file"):
            s = result["suggestion"]
            print(f"  Datei: {s.get('file')}")
            print(f"  Problem: {s.get('issue')}")
            print(f"  Vertrauen: {s.get('confidence')}")
            if result.get("applied"):
                print(f"  Tests: {'PASS' if result.get('tests_passed') else 'FAIL'}")
                print(f"  Committed: {result.get('committed')}")
        if result.get("error"):
            print(f"  Fehler: {result['error']}")
