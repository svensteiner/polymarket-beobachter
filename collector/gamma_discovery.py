# =============================================================================
# GAMMA API AUTO-DISCOVERY
# =============================================================================
#
# Entdeckt automatisch neue Wetter-Maerkte auf Polymarket via Gamma API.
# Kein API-Key noetig (kostenlos).
#
# API: https://gamma-api.polymarket.com/markets
# Sucht nach Wetter-Keywords in Titel und Beschreibung.
#
# =============================================================================

import logging
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

import requests

logger = logging.getLogger(__name__)

GAMMA_API_BASE = "https://gamma-api.polymarket.com"
DEFAULT_TIMEOUT = 15

# Wetter-Keywords fuer Suche (Englisch, da Polymarket englischsprachig)
WEATHER_KEYWORDS = [
    "temperature",
    "rain",
    "snow",
    "hurricane",
    "heat",
    "flood",
    "celsius",
    "fahrenheit",
    "degrees",
    "weather",
    "precipitation",
    "storm",
    "typhoon",
    "tornado",
    "blizzard",
    "drought",
    "high temperature",
    "low temperature",
    "exceed",      # z.B. "Will temperature exceed 100F"
    "above",       # z.B. "Will it be above 30C"
    "below",       # z.B. "Will temperature be below 0C"
]


def discover_weather_markets(
    limit: int = 500,
    active_only: bool = True,
    min_liquidity: float = 50.0,
    timeout: int = DEFAULT_TIMEOUT,
) -> List[Dict[str, Any]]:
    """
    Entdecke Wetter-Maerkte via Gamma API.

    Args:
        limit: Max Anzahl Maerkte die geprueft werden
        active_only: Nur aktive (nicht abgeschlossene) Maerkte
        min_liquidity: Minimale Liquidity in USD
        timeout: HTTP Timeout in Sekunden

    Returns:
        Liste von Wetter-Markt-Dicts (raw Gamma API Format)
    """
    try:
        params = {
            "limit": min(limit, 500),
            "active": "true" if active_only else "false",
            "closed": "false",
            "order": "volume",
            "ascending": "false",
        }

        resp = requests.get(
            f"{GAMMA_API_BASE}/markets",
            params=params,
            timeout=timeout,
            headers={"User-Agent": "PolymarketWeatherBot/1.0"},
        )
        resp.raise_for_status()
        markets = resp.json()

        if not isinstance(markets, list):
            logger.warning(f"Gamma API unexpected response format: {type(markets)}")
            return []

        logger.info(f"Gamma API: {len(markets)} Maerkte abgerufen")

        # Filtere nach Wetter-Keywords
        weather_markets = []
        for market in markets:
            if _is_weather_market(market):
                # Liquiditaets-Filter
                liq = _get_liquidity(market)
                if liq >= min_liquidity:
                    weather_markets.append(market)

        logger.info(
            f"Gamma API: {len(weather_markets)} Wetter-Maerkte gefunden "
            f"(von {len(markets)} total, min_liq={min_liquidity})"
        )
        return weather_markets

    except requests.exceptions.Timeout:
        logger.warning("Gamma API: Timeout nach {}s".format(timeout))
        return []
    except requests.exceptions.RequestException as e:
        logger.warning(f"Gamma API: Request fehlgeschlagen: {e}")
        return []
    except Exception as e:
        logger.warning(f"Gamma API: Unerwarteter Fehler: {e}")
        return []


def _is_weather_market(market: Dict[str, Any]) -> bool:
    """Pruefe ob ein Markt ein Wetter-Markt ist."""
    searchable = " ".join([
        str(market.get("question", "")),
        str(market.get("description", "")),
        str(market.get("category", "")),
        str(market.get("groupItemTitle", "")),
    ]).lower()

    return any(kw.lower() in searchable for kw in WEATHER_KEYWORDS)


def _get_liquidity(market: Dict[str, Any]) -> float:
    """Extrahiere Liquidity aus Markt-Dict."""
    for field in ("liquidity", "volume", "liquidityNum"):
        val = market.get(field)
        if val is not None:
            try:
                return float(val)
            except (TypeError, ValueError):
                pass
    return 0.0


def get_market_details(market_id: str, timeout: int = DEFAULT_TIMEOUT) -> Optional[Dict[str, Any]]:
    """
    Hole Details zu einem spezifischen Markt via Gamma API.

    Args:
        market_id: Polymarket Market ID
        timeout: HTTP Timeout

    Returns:
        Market-Dict oder None
    """
    try:
        resp = requests.get(
            f"{GAMMA_API_BASE}/markets/{market_id}",
            timeout=timeout,
            headers={"User-Agent": "PolymarketWeatherBot/1.0"},
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.debug(f"Gamma API market details fehlgeschlagen fuer {market_id}: {e}")
        return None


def normalize_gamma_market(market: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Konvertiere Gamma API Markt-Format in das Collector-Format.

    Args:
        market: Raw Gamma API Markt

    Returns:
        Normalisiertes Dict oder None wenn unvollstaendig
    """
    market_id = market.get("id") or market.get("conditionId", "")
    question = market.get("question", "").strip()
    description = market.get("description", "")

    if not market_id or not question:
        return None

    # End Date
    end_date = None
    for date_field in ("endDate", "end_date", "endDateIso"):
        raw_date = market.get(date_field)
        if raw_date:
            try:
                # Normalisiere auf ISO-Format
                if isinstance(raw_date, (int, float)):
                    dt = datetime.fromtimestamp(raw_date, tz=timezone.utc)
                else:
                    dt = datetime.fromisoformat(str(raw_date).replace("Z", "+00:00"))
                end_date = dt.isoformat()
                break
            except (ValueError, OSError):
                pass

    # Liquidity
    liquidity = _get_liquidity(market)

    # Outcome Prices
    outcome_prices = market.get("outcomePrices", '["0.5", "0.5"]')

    return {
        "market_id": market_id,
        "title": question,
        "description": description,
        "resolution_text": market.get("resolutionSource", description[:200] if description else ""),
        "end_date": end_date,
        "liquidity": liquidity,
        "outcomePrices": outcome_prices,
        "source": "gamma_discovery",
        "discovered_at": datetime.now(timezone.utc).isoformat(),
    }


def run_discovery_and_save(
    output_dir: str = "data/collector/gamma",
    limit: int = 500,
    min_liquidity: float = 50.0,
) -> int:
    """
    Fuehre Discovery aus und speichere neue Wetter-Maerkte.

    Args:
        output_dir: Ausgabe-Verzeichnis
        limit: Max Maerkte zu pruefen
        min_liquidity: Min Liquiditaet

    Returns:
        Anzahl gespeicherter Maerkte
    """
    import json
    from pathlib import Path
    from datetime import date

    markets = discover_weather_markets(limit=limit, min_liquidity=min_liquidity)
    if not markets:
        logger.info("Gamma Discovery: Keine Maerkte gefunden")
        return 0

    normalized = []
    for m in markets:
        n = normalize_gamma_market(m)
        if n:
            normalized.append(n)

    if not normalized:
        return 0

    # Speichere als JSONL neben dem regulaeren Collector-Output
    out_dir = Path(output_dir) / date.today().isoformat()
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / "gamma_candidates.jsonl"

    with open(out_file, "w", encoding="utf-8") as f:
        for m in normalized:
            f.write(json.dumps(m, ensure_ascii=False) + "\n")

    logger.info(f"Gamma Discovery: {len(normalized)} Maerkte gespeichert -> {out_file}")
    return len(normalized)
