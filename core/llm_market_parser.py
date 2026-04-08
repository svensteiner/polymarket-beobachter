# =============================================================================
# LLM MARKET PARSER - Polymarket-Fragen mit GPT-5.4 mini verstehen
# =============================================================================
#
# Verbessert das Regex-basierte Parsing von Polymarket-Fragen:
# - Extrahiert Stadt, Temperatur-Schwelle, Event-Typ zuverlaessiger
# - Erkennt Edge-Cases die Regex nicht kann
# - Wird als Fallback genutzt wenn Regex fehlschlaegt
#
# =============================================================================

import logging
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """Du bist ein Wetter-Markt-Parser fuer Polymarket.
Analysiere die Marktfrage und extrahiere EXAKT diese Felder als JSON:

{
  "city": "Stadtname (englisch)",
  "threshold_value": <Zahlenwert der Temperatur-Schwelle>,
  "threshold_unit": "F" oder "C",
  "threshold_high_value": <obere Grenze bei Ranges, sonst null>,
  "event_type": "exceeds" | "below" | "at_or_above" | "at_or_below" | "between_range" | "exact",
  "metric": "highest_temperature" | "lowest_temperature" | "temperature",
  "resolution_description": "kurze Beschreibung was passieren muss damit YES gewinnt",
  "band_width_degrees": <Bandbreite in Grad, 0 fuer Punkt-Maerkte>,
  "tradeable": true/false (false wenn Frage unklar oder nicht temperaturbasiert)
}

Regeln:
- "be 15°C" = exact, threshold=15, band = 1 Grad (Polymarket rundet)
- "between 78-79°F" = between_range, threshold=78, threshold_high=79, band=1
- "or higher" / "or above" = at_or_above
- "or below" / "or lower" = at_or_below
- "exceed" / "above" ohne "or" = exceeds
- Antworte NUR mit JSON, kein anderer Text."""


def llm_parse_market(question: str, description: str = "") -> Optional[Dict[str, Any]]:
    """
    Parse eine Polymarket-Frage mit GPT-5.4 mini.

    Args:
        question: Die Marktfrage
        description: Optionale Marktbeschreibung

    Returns:
        Parsed dict oder None bei Fehler
    """
    try:
        from .llm_client import llm_json_call
    except ImportError:
        return None

    prompt = f"Marktfrage: {question}"
    if description:
        prompt += f"\nBeschreibung: {description[:200]}"

    result = llm_json_call(prompt, system=SYSTEM_PROMPT, max_tokens=300, temperature=0.0)

    if result is None:
        return None

    # Validiere Pflichtfelder
    required = ["city", "threshold_value", "event_type"]
    for field in required:
        if field not in result or result[field] is None:
            logger.debug(f"LLM Market Parse: Pflichtfeld '{field}' fehlt")
            return None

    return result


def llm_enhance_filter_result(
    question: str,
    regex_result: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Verbessere Regex-basiertes Parsing mit LLM-Verifizierung.

    Wird NUR aufgerufen wenn Regex unsicher ist (z.B. unbekanntes Format).
    Ueberschreibt Regex-Ergebnis nur wenn LLM sicherer ist.

    Args:
        question: Marktfrage
        regex_result: Ergebnis des Regex-Parsers

    Returns:
        Verbessertes oder originales Ergebnis
    """
    llm_result = llm_parse_market(question)
    if llm_result is None:
        return regex_result  # LLM nicht verfuegbar, Regex-Ergebnis behalten

    # Vergleiche Ergebnisse
    enhanced = dict(regex_result)

    # Stadt: LLM ueberschreibt wenn Regex keine Stadt gefunden hat
    if not regex_result.get("city") and llm_result.get("city"):
        enhanced["city"] = llm_result["city"]
        logger.info(f"LLM Enhanced: Stadt '{llm_result['city']}' erkannt")

    # Event-Typ: LLM ueberschreibt wenn Regex "exceeds" (default) hat
    if regex_result.get("event_type") == "exceeds" and llm_result.get("event_type") != "exceeds":
        enhanced["event_type"] = llm_result["event_type"]
        logger.info(f"LLM Enhanced: event_type '{llm_result['event_type']}'")

    # Tradeable-Check: LLM warnt wenn Markt nicht handelbar
    if llm_result.get("tradeable") is False:
        enhanced["llm_not_tradeable"] = True
        enhanced["llm_reason"] = llm_result.get("resolution_description", "")
        logger.warning(f"LLM: Markt nicht handelbar: {question[:60]}")

    return enhanced
