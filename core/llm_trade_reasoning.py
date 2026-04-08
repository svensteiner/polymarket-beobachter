# =============================================================================
# LLM TRADE REASONING - GPT-5.4 mini Sanity-Check vor jedem Trade
# =============================================================================
#
# Bevor ein Trade eingegangen wird, fragt das System GPT-5.4 mini:
# "Macht dieser Trade Sinn?"
#
# Das LLM bekommt:
# - Marktfrage + aktuelle Modell-Wahrscheinlichkeit
# - Markt-Preis (was der Markt denkt)
# - Aktuelle Wetterdaten/Forecast
# - Position-Side und Kelly-Size
#
# Das LLM antwortet mit Approve/Reject + Begruendung.
# =============================================================================

import logging
from typing import Optional, Dict, Tuple

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """Du bist ein Risikomanager fuer ein Wetter-Betting-System auf Polymarket.
Deine Aufgabe: Bewerte ob ein geplanter Trade sinnvoll ist.

Du bekommst Marktdaten und sollst entscheiden:
- APPROVE: Trade ist gut begruendet
- REJECT: Trade hat Probleme (z.B. Model-Fehler, unlogischer Edge, riskant)

Antworte als JSON:
{
  "decision": "APPROVE" oder "REJECT",
  "confidence": 0.0 bis 1.0,
  "reasoning": "Kurze Begruendung (1-2 Saetze)",
  "risk_flags": ["liste", "von", "risiken"] (leer wenn keine)
}

Bewertungskriterien:
1. Stimmt die Model-Wahrscheinlichkeit mit dem Wetter ueberein?
2. Ist der Edge realistisch oder zu gut um wahr zu sein?
3. Gibt es offensichtliche Fehlerquellen?
4. Ist die Positionsgroesse angemessen?

Sei KONSERVATIV. Im Zweifel REJECT. Lieber einen guten Trade verpassen als einen schlechten machen."""


def evaluate_trade(
    market_question: str,
    model_probability: float,
    market_price: float,
    side: str,
    position_size_eur: float,
    edge: float,
    event_type: str = "",
    city: str = "",
    forecast_temp_f: Optional[float] = None,
    threshold_f: Optional[float] = None,
    hours_to_resolution: Optional[float] = None,
    confidence: str = "",
) -> Tuple[bool, str, Dict]:
    """
    LLM-basierte Trade-Bewertung.

    Returns:
        (approved, reasoning, full_result)
    """
    try:
        from .llm_client import llm_json_call
    except ImportError:
        return True, "LLM nicht verfuegbar - Trade durchgelassen", {}

    # Prompt zusammenbauen
    prompt_parts = [
        f"Marktfrage: {market_question}",
        f"Model sagt: P(YES) = {model_probability:.1%}",
        f"Markt sagt: P(YES) = {market_price:.1%}",
        f"Geplant: {side} @ {market_price:.4f}",
        f"Edge: {edge:.1%}",
        f"Positionsgroesse: {position_size_eur:.0f} EUR",
        f"Event-Typ: {event_type}",
    ]
    if city:
        prompt_parts.append(f"Stadt: {city}")
    if forecast_temp_f is not None:
        prompt_parts.append(f"Forecast-Temperatur: {forecast_temp_f:.1f}°F")
    if threshold_f is not None:
        prompt_parts.append(f"Schwelle: {threshold_f:.1f}°F")
    if hours_to_resolution is not None:
        prompt_parts.append(f"Stunden bis Resolution: {hours_to_resolution:.0f}h")
    if confidence:
        prompt_parts.append(f"Confidence: {confidence}")

    prompt = "\n".join(prompt_parts)

    result = llm_json_call(prompt, system=SYSTEM_PROMPT, max_tokens=300, temperature=0.1)

    if result is None:
        # LLM nicht erreichbar -> Trade trotzdem durchlassen (fail-open)
        logger.debug("LLM Trade Reasoning nicht erreichbar - fail-open")
        return True, "LLM nicht erreichbar", {}

    decision = result.get("decision", "APPROVE").upper()
    reasoning = result.get("reasoning", "Keine Begruendung")
    risk_flags = result.get("risk_flags", [])
    llm_confidence = result.get("confidence", 0.5)

    approved = decision == "APPROVE"

    if not approved:
        logger.info(
            f"LLM REJECT: {market_question[:50]}... | "
            f"Grund: {reasoning} | Risiken: {risk_flags}"
        )
    else:
        logger.debug(
            f"LLM APPROVE: {market_question[:50]}... | "
            f"Confidence: {llm_confidence:.0%}"
        )

    return approved, reasoning, result


def quick_sanity_check(
    model_prob: float,
    market_prob: float,
    event_type: str,
    city: str,
) -> Tuple[bool, str]:
    """
    Schneller LLM-Sanity-Check (guenstiger als full evaluate_trade).

    Returns:
        (sane, reason)
    """
    try:
        from .llm_client import llm_call
    except ImportError:
        return True, "LLM nicht verfuegbar"

    prompt = (
        f"Schnell-Check: Model sagt P={model_prob:.1%}, Markt sagt P={market_prob:.1%} "
        f"fuer {event_type}-Markt in {city}. "
        f"Ist der Unterschied plausibel? Antworte NUR 'JA' oder 'NEIN: <Grund>'."
    )

    result = llm_call(prompt, system="Du bist Wetter-Risikomanager. Sei kurz.",
                       max_tokens=50, temperature=0.0)
    if result is None:
        return True, "LLM nicht erreichbar"

    result = result.strip()
    if result.upper().startswith("JA"):
        return True, "LLM: plausibel"
    else:
        return False, f"LLM: {result}"
