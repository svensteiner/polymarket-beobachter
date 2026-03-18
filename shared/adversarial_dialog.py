# =============================================================================
# ADVERSARIAL DIALOG  —  Internes Teufelssadvokat-Reasoning
# =============================================================================
#
# Fuehrt drei sequenzielle LLM-Calls durch, um eine Edge-Entscheidung zu
# hinterfragen bevor gehandelt wird:
#
#   1. Bull-Case:  Staerkste Argumente FUER den Trade
#   2. Bear-Case:  Staerkste Argumente GEGEN den Trade
#   3. Richter:    Bewertet beide Seiten → HIGH / MEDIUM / LOW
#
# Ergebnis bestimmt ob der Trade weitergefuehrt wird (proceed=True/False).
# Bei LLM-Fehler: graceful degradation, proceed=True (nie blockieren).
#
# Log: logs/adversarial_dialogs.jsonl (append-only)
#
# Provider-Reihenfolge (identisch zu strategy_agent.py):
#   1. Kimi (moonshot-v1-8k)
#   2. OpenRouter (openai/gpt-4o-mini)
#   3. OpenAI (gpt-4o-mini)
#
# =============================================================================

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent
ADVERSARIAL_LOG = PROJECT_ROOT / "logs" / "adversarial_dialogs.jsonl"

# Konfiguration der LLM-Provider (spiegelgleich zu strategy_agent.py)
# 3-Tier: Kimi Primary (Debate/Dialog = Tier 2), OpenAI Fallback (Tier 1)
_PROVIDERS = [
    {
        "name": "Kimi",          # Tier 2: mittel (Debate, adversarialer Dialog)
        "env_key": "KIMI_API_KEY",
        "base_url": "https://api.moonshot.ai/v1",
        "model": "moonshot-v1-32k",
    },
    {
        "name": "OpenAI",        # Tier 1 Fallback
        "env_key": "OPENAI_API_KEY",
        "base_url": None,
        "model": "gpt-4.1-mini",
    },
]


# =============================================================================
# DATENSTRUKTUR
# =============================================================================

@dataclass
class AdversarialResult:
    """Ergebnis des internen Teufelssadvokat-Dialogs."""

    market_question: str
    bull_argument: str    # Staerkster Fall fuer den Trade
    bear_argument: str    # Staerkster Fall gegen den Trade
    judge_verdict: str    # "HIGH", "MEDIUM" oder "LOW"
    judge_reason: str     # Begruendung des Richters
    edge_pct: float       # Berechneter Edge in Prozent (z.B. 15.3)
    proceed: bool         # True wenn Verdict != "LOW"
    provider: str         # Verwendeter LLM-Provider
    timestamp: str        # ISO-Zeitstempel


# =============================================================================
# INTERNER LLM-CLIENT (kein externer State)
# =============================================================================

def _get_client(provider: dict) -> Optional[Any]:
    """Erstelle OpenAI-Client fuer gegebenen Provider. Gibt None zurueck wenn kein API-Key."""
    try:
        from openai import OpenAI
    except ImportError:
        return None

    api_key = os.environ.get(provider["env_key"], "").strip()
    if not api_key:
        return None

    kwargs: dict = {"api_key": api_key, "timeout": 25.0}  # 25s Connection+Read Timeout
    if provider["base_url"]:
        kwargs["base_url"] = provider["base_url"]

    try:
        return OpenAI(**kwargs)
    except Exception:
        return None


def _load_env() -> None:
    """Lade .env-Datei falls vorhanden (idempotent)."""
    env_file = PROJECT_ROOT / ".env"
    if not env_file.exists():
        return
    try:
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                k = k.strip()
                v = v.strip()
                # .env hat Vorrang — immer ueberschreiben
                os.environ[k] = v
    except Exception as e:
        logger.debug(f"[ADVERSARIAL] .env laden fehlgeschlagen (unkritisch): {e}")


def _call_llm(client: Any, model: str, system: str, user: str, max_tokens: int = 100) -> str:
    """
    Einzelner LLM-Call. Gibt Antwort-Text zurueck.
    Wirft Exception bei Fehler (wird vom Aufrufer abgefangen).
    """
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user",   "content": user},
        ],
        max_tokens=max_tokens,
        temperature=0.4,
        timeout=20,  # 20s Timeout — verhindert unbegrenztes Haengen
    )
    return (response.choices[0].message.content or "").strip()


def _find_working_client() -> Optional[tuple[Any, dict]]:
    """
    Suche ersten verfuegbaren Provider.
    Gibt (client, provider_dict) zurueck oder (None, None).
    """
    _load_env()
    for provider in _PROVIDERS:
        client = _get_client(provider)
        if client is not None:
            return client, provider
    return None, None


# =============================================================================
# HAUPTFUNKTION
# =============================================================================

def run_adversarial_check(
    market_question: str,
    edge_pct: float,
    our_probability: float,
    market_probability: float,
    context: dict,
    llm_client: Any = None,  # Optional: externer Client wird akzeptiert, aber wir nutzen eigenen
) -> AdversarialResult:
    """
    Fuehre internen Teufelssadvokat-Dialog durch.

    Laeuft 3 LLM-Calls:
      1. Bull-Case: Staerkste Argumente FUeR den Trade
      2. Bear-Case: Staerkste Argumente GEGEN den Trade
      3. Richter:   Bewertet → HIGH / MEDIUM / LOW

    Args:
        market_question:    Polymarket-Frage (z.B. "Will temp in NYC exceed 80F on July 4?")
        edge_pct:           Berechneter Edge in Prozent (z.B. 15.3 fuer 15.3%)
        our_probability:    Unser Modell-Wahrscheinlichkeit (0.0-1.0)
        market_probability: Markt-Wahrscheinlichkeit / Implied Probability (0.0-1.0)
        context:            Forecast-Daten, Confidence etc. (freie dict-Struktur)
        llm_client:         Wird akzeptiert aber ignoriert — wir nutzen eigenen Provider-Stack

    Returns:
        AdversarialResult mit Verdict und proceed-Flag.
        Bei LLM-Fehler: proceed=True (graceful degradation).
    """
    timestamp = datetime.now().isoformat()

    # --- Fallback-Ergebnis bei Fehler (nie blockieren) ---
    fallback = AdversarialResult(
        market_question=market_question,
        bull_argument="[LLM nicht verfuegbar]",
        bear_argument="[LLM nicht verfuegbar]",
        judge_verdict="MEDIUM",
        judge_reason="Adversarial Check nicht durchfuehrbar — LLM nicht erreichbar. Weiter mit Standardlogik.",
        edge_pct=edge_pct,
        proceed=True,
        provider="none",
        timestamp=timestamp,
    )

    try:
        client, provider = _find_working_client()
        if client is None:
            logger.warning("[ADVERSARIAL] Kein LLM-Provider verfuegbar — ueberspringe Check.")
            _log_result(fallback)
            return fallback

        provider_name = provider["name"]
        model = provider["model"]

        # Basis-Kontext fuer alle Calls (kurz halten — max_tokens=100)
        ctx_str = _format_context(context)
        market_info = (
            f"Marktfrage: {market_question}\n"
            f"Unser Modell: {our_probability:.1%} | Markt: {market_probability:.1%} | Edge: +{edge_pct:.1f}%\n"
            f"{ctx_str}"
        )

        # -----------------------------------------------------------------
        # CALL 1: BULL-CASE
        # "Du bist ein ueberzeugter Befuerworter dieses Trades."
        # -----------------------------------------------------------------
        bull_system = (
            "Du bist ein Wettervorhersage-Experte, der FUER diesen Trade argumentiert. "
            "Nenne das stichhaltigste Argument warum die Wette korrekt ist. "
            "Max 2 Saetze. Deutsch."
        )
        try:
            bull_argument = _call_llm(client, model, bull_system, market_info, max_tokens=100)
            logger.debug(f"[ADVERSARIAL] Bull: {bull_argument}")
        except Exception as e:
            logger.debug(f"[ADVERSARIAL] Bull-Call fehlgeschlagen: {e}")
            _log_result(fallback)
            return fallback

        # -----------------------------------------------------------------
        # CALL 2: BEAR-CASE
        # "Du bist ein Skeptiker, der GEGEN diesen Trade argumentiert."
        # -----------------------------------------------------------------
        bear_system = (
            "Du bist ein kritischer Skeptiker. Nenne das stichhaltigste Argument GEGEN diesen Trade — "
            "was koennte mit der Vorhersage falsch liegen? "
            "Max 2 Saetze. Deutsch."
        )
        try:
            bear_argument = _call_llm(client, model, bear_system, market_info, max_tokens=100)
            logger.debug(f"[ADVERSARIAL] Bear: {bear_argument}")
        except Exception as e:
            logger.debug(f"[ADVERSARIAL] Bear-Call fehlgeschlagen: {e}")
            _log_result(fallback)
            return fallback

        # -----------------------------------------------------------------
        # CALL 3: RICHTER
        # Bewertet beide Seiten → HIGH / MEDIUM / LOW
        # -----------------------------------------------------------------
        judge_user = (
            f"{market_info}\n\n"
            f"PRO-Argument: {bull_argument}\n"
            f"KONTRA-Argument: {bear_argument}\n\n"
            "Bewerte das Vertrauen in den Edge als HIGH, MEDIUM oder LOW. "
            "Antworte mit genau: VERDICT: <HIGH|MEDIUM|LOW> | GRUND: <max 15 Woerter>"
        )
        judge_system = (
            "Du bist ein neutraler Richter. Bewerte ob der berechnete Edge zuverlaessig ist. "
            "Antworte NUR im Format: VERDICT: HIGH | GRUND: ... oder VERDICT: MEDIUM | GRUND: ... "
            "oder VERDICT: LOW | GRUND: ..."
        )
        try:
            judge_raw = _call_llm(client, model, judge_system, judge_user, max_tokens=80)
            logger.debug(f"[ADVERSARIAL] Richter raw: {judge_raw}")
        except Exception as e:
            logger.debug(f"[ADVERSARIAL] Richter-Call fehlgeschlagen: {e}")
            _log_result(fallback)
            return fallback

        # Richter-Antwort parsen
        verdict, reason = _parse_verdict(judge_raw)
        proceed = verdict != "LOW"

        result = AdversarialResult(
            market_question=market_question,
            bull_argument=bull_argument,
            bear_argument=bear_argument,
            judge_verdict=verdict,
            judge_reason=reason,
            edge_pct=edge_pct,
            proceed=proceed,
            provider=provider_name,
            timestamp=timestamp,
        )

        _log_result(result)

        if proceed:
            logger.info(
                f"[ADVERSARIAL] Edge bestaetigt ({verdict}): {reason} "
                f"[{market_question[:50]}]"
            )
        else:
            logger.info(
                f"[ADVERSARIAL] Edge abgelehnt (LOW): {reason} "
                f"[{market_question[:50]}]"
            )

        return result

    except Exception as e:
        # Niemals crashen — graceful degradation
        logger.warning(f"[ADVERSARIAL] Unerwarteter Fehler (proceed=True): {e}")
        _log_result(fallback)
        return fallback


# =============================================================================
# HILFSFUNKTIONEN
# =============================================================================

def _format_context(context: dict) -> str:
    """
    Formatiere Kontext-Dict zu kurzem lesbaren String.
    Begrenzt auf max 200 Zeichen damit die Prompts kurz bleiben.
    """
    if not context:
        return ""
    try:
        # Nur relevante Felder extrahieren
        relevant_keys = [
            "confidence", "forecast_temperature_f", "threshold_temperature_f",
            "city", "forecast_source", "sigma_f", "hours_to_resolution",
        ]
        parts = []
        for k in relevant_keys:
            if k in context:
                parts.append(f"{k}={context[k]}")
        # Fallback: alle Schluesse bis 5 Keys
        if not parts:
            for i, (k, v) in enumerate(context.items()):
                if i >= 5:
                    break
                parts.append(f"{k}={v}")
        raw = ", ".join(parts)
        return raw[:200]
    except Exception:
        return ""


def _parse_verdict(judge_raw: str) -> tuple[str, str]:
    """
    Parse Richter-Antwort im Format "VERDICT: HIGH | GRUND: ..."
    Gibt (verdict, reason) zurueck. Fallback: ("MEDIUM", judge_raw[:80])
    """
    if not judge_raw:
        return "MEDIUM", "Keine Antwort vom Richter."

    upper = judge_raw.upper()

    # Verdict extrahieren
    verdict = "MEDIUM"  # Sicherer Standard
    for v in ("HIGH", "LOW", "MEDIUM"):
        if v in upper:
            verdict = v
            break

    # Grund extrahieren (nach "GRUND:" oder "REASON:")
    reason = judge_raw
    for marker in ("GRUND:", "REASON:", "grund:", "reason:"):
        if marker.lower() in judge_raw.lower():
            idx = judge_raw.lower().index(marker.lower())
            reason = judge_raw[idx + len(marker):].strip()
            break

    # Einschraenken auf vernuenftige Laenge
    reason = reason[:150].strip()
    if not reason:
        reason = judge_raw[:80]

    return verdict, reason


def _log_result(result: AdversarialResult) -> None:
    """
    Schreibe Ergebnis als JSON-Zeile in logs/adversarial_dialogs.jsonl (append-only).
    Fehler werden geloggt aber nicht weitergeworfen.
    """
    try:
        ADVERSARIAL_LOG.parent.mkdir(parents=True, exist_ok=True)
        entry = asdict(result)
        with open(ADVERSARIAL_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as e:
        logger.debug(f"[ADVERSARIAL] Log schreiben fehlgeschlagen (unkritisch): {e}")
