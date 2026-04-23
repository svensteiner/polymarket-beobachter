"""Brain — LLM-Intelligenz-Layer.

Lädt SOUL.md als System-Kontext und stellt 4 Kern-Funktionen bereit:
  think()    → Aufgabe verstehen + Plan erstellen
  act()      → Tool ausführen + Ergebnis bewerten
  reflect()  → Aus Ergebnis lernen
  evaluate() → Output-Qualität prüfen (1-10 Score)

LLM-Kette: OpenAI → Anthropic → Keyword-Fallback
"""

import json
import logging
import os
import re
from pathlib import Path

logger = logging.getLogger("brain")

SOUL_PATH = Path(__file__).parent / "SOUL.md"
CONFIG_PATH = Path(__file__).parent / "config.json"

_session_usage: dict = {
    "calls": 0,
    "input_tokens": 0,
    "output_tokens": 0,
    "cache_read_tokens": 0,
    "cache_write_tokens": 0,
}


def _load_config() -> dict:
    if CONFIG_PATH.exists():
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    return {}


def _load_soul() -> str:
    if SOUL_PATH.exists():
        return SOUL_PATH.read_text(encoding="utf-8")
    return "Du bist ein autonomer KI-Agent. Handle verantwortungsbewusst."


def _get_client(use_fast: bool = False):
    """Gibt (client, model, provider) zurück. Probiert OpenAI dann Anthropic.

    use_fast=True  → günstiges Modell für reflect/evaluate
    use_fast=False → smartes Modell für think/act/proactive
    """
    cfg = _load_config()

    # OpenAI
    api_key = os.getenv("OPENAI_API_KEY") or cfg.get("openai_api_key", "")
    if api_key:
        try:
            from openai import OpenAI
            default = cfg.get("model", "gpt-4o-mini")
            model = cfg.get("model_fast", default) if use_fast else cfg.get("model_smart", default)
            return OpenAI(api_key=api_key), model, "openai"
        except ImportError:
            pass

    # Anthropic
    api_key = os.getenv("ANTHROPIC_API_KEY") or cfg.get("anthropic_api_key", "")
    if api_key:
        try:
            import anthropic
            default = cfg.get("model_anthropic", "claude-haiku-4-5-20251001")
            model = cfg.get("model_anthropic_fast", default) if use_fast else cfg.get("model_anthropic_smart", default)
            return anthropic.Anthropic(api_key=api_key), model, "anthropic"
        except ImportError:
            pass

    return None, None, "fallback"


def _call_llm(system: str, user: str, temperature: float = 0.7, max_tokens: int = 1000,
              use_fast: bool = False) -> str:
    """Ruft LLM auf. Gibt Text zurück oder leeren String bei Fehler."""
    client, model, provider = _get_client(use_fast=use_fast)

    if provider == "fallback" or client is None:
        logger.warning("Kein LLM verfügbar — Keyword-Fallback aktiv")
        return ""

    try:
        if provider == "openai":
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=temperature,
                max_tokens=max_tokens,
            )
            _session_usage["calls"] += 1
            _session_usage["input_tokens"] += getattr(response.usage, "prompt_tokens", 0)
            _session_usage["output_tokens"] += getattr(response.usage, "completion_tokens", 0)
            return response.choices[0].message.content.strip()

        elif provider == "anthropic":
            # Prompt Caching: SOUL.md als ephemeral cache (bis zu 90% Kostenersparnis)
            # Cache TTL: 5 Minuten — rentiert sich bei mehreren Calls pro Session
            response = client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=[{
                    "type": "text",
                    "text": system,
                    "cache_control": {"type": "ephemeral"},
                }],
                messages=[{"role": "user", "content": user}],
            )
            _session_usage["calls"] += 1
            _session_usage["input_tokens"] += getattr(response.usage, "input_tokens", 0)
            _session_usage["output_tokens"] += getattr(response.usage, "output_tokens", 0)
            _session_usage["cache_read_tokens"] += getattr(response.usage, "cache_read_input_tokens", 0)
            _session_usage["cache_write_tokens"] += getattr(response.usage, "cache_creation_input_tokens", 0)
            return response.content[0].text.strip()

    except Exception as e:
        logger.error(f"LLM-Fehler ({provider}): {e}")
        return ""


def _parse_json(text: str) -> dict:
    """Extrahiert JSON aus LLM-Antwort (auch wenn in Markdown-Block)."""
    # JSON-Block aus Markdown extrahieren
    match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
    if match:
        text = match.group(1)
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        return {}


# ── Kern-Funktionen ────────────────────────────────────────────────────────

def think(task: str, context: str = "") -> dict:
    """Aufgabe verstehen, Schritte planen, Tool wählen.

    Returns:
        {
            "understood": "Was der Agent verstanden hat",
            "plan": ["Schritt 1", "Schritt 2"],
            "tool": "tool_name oder None",
            "tool_input": "Was dem Tool übergeben wird",
            "needs_human": False,
            "reasoning": "Warum dieser Plan"
        }
    """
    soul = _load_soul()
    system = f"""{soul}

Du planst eine Aufgabe. Antworte NUR mit JSON:
{{
    "understood": "Kurze Zusammenfassung was du verstanden hast",
    "plan": ["Konkreter Schritt 1", "Schritt 2", "..."],
    "tool": "tool_name oder null",
    "tool_input": "Input für das Tool oder null",
    "needs_human": false,
    "reasoning": "Warum dieser Plan"
}}"""

    user = f"Aufgabe: {task}"
    if context:
        user += f"\n\nKontext: {context}"

    result = _call_llm(system, user, temperature=0.3, max_tokens=500)
    parsed = _parse_json(result)

    if not parsed:
        # Keyword-Fallback
        return {
            "understood": task,
            "plan": ["Aufgabe direkt ausführen"],
            "tool": None,
            "tool_input": task,
            "needs_human": False,
            "reasoning": "Fallback — kein LLM verfügbar",
        }

    return parsed


def challenge(plan: dict, context: str = "") -> dict:
    """Plan adversarial hinterfragen — zweite Meinung vor dem Handeln.

    Returns:
        {
            "approved": True/False,
            "concerns": ["Bedenken 1", ...],
            "risk_level": "low | medium | high",
            "suggestion": "Alternative oder None"
        }
    """
    soul = _load_soul()
    system = f"""{soul}

Du bist ein kritischer Reviewer. Hinterfrage diesen Plan streng.
Antworte NUR mit JSON:
{{
    "approved": true,
    "concerns": [],
    "risk_level": "low",
    "suggestion": null
}}

risk_level: "low" = sicher ausführen | "medium" = mit Vorsicht | "high" = besser nicht"""

    user = f"Plan zur Überprüfung: {json.dumps(plan, ensure_ascii=False)}"
    if context:
        user += f"\n\nKontext: {context}"

    result = _call_llm(system, user, temperature=0.2, max_tokens=300)
    parsed = _parse_json(result)

    if not parsed:
        logger.warning("Challenge nicht verfügbar (kein LLM) — Plan wird ohne Review ausgeführt")
        return {
            "approved": True,
            "concerns": ["Challenge nicht verfügbar — kein LLM"],
            "risk_level": "low",
            "suggestion": None,
        }

    return parsed


def act(plan: dict, tool_result: str = "") -> dict:
    """Ergebnis eines Tool-Aufrufs bewerten + nächsten Schritt bestimmen.

    Returns:
        {
            "success": True/False,
            "next_action": "done / retry / escalate / next_tool",
            "summary": "Was passiert ist",
            "output": "Finales Ergebnis (wenn done)"
        }
    """
    soul = _load_soul()
    system = f"""{soul}

Bewerte ein Tool-Ergebnis. Antworte NUR mit JSON:
{{
    "success": true,
    "next_action": "done",
    "summary": "Was ist passiert",
    "output": "Finales Ergebnis oder null"
}}

next_action kann sein: "done" | "retry" | "escalate" | "use_different_tool"
"""

    user = f"""Plan war: {json.dumps(plan, ensure_ascii=False)}

Tool-Ergebnis: {tool_result or '(kein Ergebnis)'}

War das erfolgreich? Was ist der nächste Schritt?"""

    result = _call_llm(system, user, temperature=0.2, max_tokens=300)
    parsed = _parse_json(result)

    if not parsed:
        success = "error" not in tool_result.lower() and "fail" not in tool_result.lower()
        return {
            "success": success,
            "next_action": "done" if success else "retry",
            "summary": tool_result[:200] if tool_result else "Kein Ergebnis",
            "output": tool_result if success else None,
        }

    return parsed


def reflect(action_taken: str, result: str, expected: str = "") -> dict:
    """Aus dem Ergebnis lernen. Gibt Learning zurück.

    Returns:
        {
            "worked": True/False,
            "insight": "Was ich gelernt habe",
            "improve_next_time": "Was ich nächstes Mal anders mache"
        }
    """
    soul = _load_soul()
    system = f"""{soul}

Reflektiere über eine abgeschlossene Aktion. Antworte NUR mit JSON:
{{
    "worked": true,
    "insight": "Konkretes Learning (1 Satz)",
    "improve_next_time": "Was nächstes Mal anders machen (1 Satz oder null)"
}}"""

    user = f"""Aktion: {action_taken}
Erwartet: {expected or 'Erfolgreiche Ausführung'}
Tatsächlich: {result}"""

    result_text = _call_llm(system, user, temperature=0.4, max_tokens=200, use_fast=True)
    parsed = _parse_json(result_text)

    if not parsed:
        return {
            "worked": True,
            "insight": "Aktion wurde ausgeführt.",
            "improve_next_time": None,
        }

    return parsed


def evaluate(content: str, content_type: str = "output", criteria: str = "") -> dict:
    """Output qualitativ bewerten (1–10 Score).

    Returns:
        {
            "score": 8,
            "passes": True,
            "feedback": ["Feedback 1", "Feedback 2"],
            "improved_version": "Verbesserter Output oder None"
        }
    """
    soul = _load_soul()
    cfg = _load_config()
    threshold = cfg.get("quality_threshold", 7)

    system = f"""{soul}

Bewerte einen Output nach Qualität. Antworte NUR mit JSON:
{{
    "score": 8,
    "passes_quality": true,
    "feedback": ["Stärke 1", "Verbesserungspunkt 1"],
    "improved_version": "Verbesserter Text oder null (nur wenn score < {threshold})"
}}

Score 1-10: 1=unbrauchbar, 7=gut genug, 10=perfekt.
passes_quality = score >= {threshold}"""

    criteria_text = f"\n\nBewertungskriterien: {criteria}" if criteria else ""
    user = f"Content-Typ: {content_type}{criteria_text}\n\nZu bewerten:\n{content}"

    result = _call_llm(system, user, temperature=0.3, max_tokens=600, use_fast=True)
    parsed = _parse_json(result)

    if not parsed:
        return {
            "score": 5,
            "passes": False,
            "feedback": ["LLM nicht verfügbar — manuelle Prüfung nötig"],
            "improved_version": None,
        }

    parsed["passes"] = parsed.get("passes_quality", parsed.get("score", 0) >= threshold)
    return parsed


def proactive(state_context: str) -> list[dict]:
    """Generiert proaktive Ziele basierend auf dem Agenten-Zustand.

    Returns:
        List von {"id", "task", "priority", "reasoning"}
    """
    soul = _load_soul()
    result = _call_llm(soul, state_context, temperature=0.6, max_tokens=600)
    parsed = _parse_json(result)
    return parsed.get("goals", [])


def get_usage_stats() -> dict:
    """Token-Verbrauch der aktuellen Session."""
    s = _session_usage
    billed = s["input_tokens"] - s["cache_read_tokens"] + s["output_tokens"]
    return {
        "calls": s["calls"],
        "input_tokens": s["input_tokens"],
        "output_tokens": s["output_tokens"],
        "cache_read_tokens": s["cache_read_tokens"],
        "cache_write_tokens": s["cache_write_tokens"],
        "billed_tokens": billed,
        "cache_savings_pct": round(s["cache_read_tokens"] / max(s["input_tokens"], 1) * 100, 1),
    }


def reset_usage_stats() -> None:
    """Setzt Session-Zähler zurück (z.B. nach jedem Loop-Zyklus)."""
    _session_usage.update({
        "calls": 0, "input_tokens": 0, "output_tokens": 0,
        "cache_read_tokens": 0, "cache_write_tokens": 0,
    })
