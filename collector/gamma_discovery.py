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
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional, Set

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

# Supported cities — mirrors ALLOWED_CITIES in weather.yaml.
# Used to score city-temperature near-expiry markets higher.
SUPPORTED_CITIES = [
    "London", "New York", "Los Angeles", "Chicago", "Miami", "Denver",
    "Phoenix", "Seattle", "Boston", "Seoul", "Tokyo", "Paris", "Berlin",
    "Sydney", "Toronto", "Austin", "Madrid", "Karachi", "Chengdu", "Qingdao",
    "Helsinki", "Houston", "Atlanta", "Dallas", "San Francisco", "Washington",
    "Philadelphia", "Buenos Aires", "Ankara",
]

# City-temperature boundary keywords. Markets containing these are the YES-bet
# opportunities we want to find (at_or_above / at_or_below).
BOUNDARY_KEYWORDS = ["or above", "or below", "or higher", "or lower", "at least", "at most"]

# at_or_below-only paper lane: phrases that mark the only tradeable type.
BELOW_KEYWORDS = [
    "or below",
    "or lower",
    "or under",
    "or less",
    "at most",
    " be below ",
    "below on",
]


def discover_weather_markets(
    limit: int = 500,
    active_only: bool = True,
    min_liquidity: float = 50.0,
    timeout: int = DEFAULT_TIMEOUT,
    prefer_at_or_below: bool = False,
    below_min_liquidity: float | None = None,
    below_pages: int = 3,
) -> List[Dict[str, Any]]:
    """
    Entdecke Wetter-Maerkte via Gamma API.

    Suchlaeufe:
    1. Top-N nach Volume (allgemeine Wetter-Maerkte)
    2. Near-expiry nach end_date (city-temperature im ~20-120h Fenster)
    3. Optional (prefer_at_or_below): paginierte end_date-Suche nur fuer
       at_or_below-Phrasen — fuellt den Paper-Lane-Funnel wenn exact/between
       die Volume-Tops dominieren.

    Args:
        limit: Max Anzahl Maerkte die geprueft werden (Pass 1)
        active_only: Nur aktive (nicht abgeschlossene) Maerkte
        min_liquidity: Minimale Liquidity in USD
        timeout: HTTP Timeout in Sekunden
        prefer_at_or_below: Extra Pass nur fuer below-Maerkte
        below_min_liquidity: Liquidity-Floor fuer Pass 3 (default: min_liquidity)
        below_pages: Anzahl Gamma-Pages (offset) fuer Pass 3

    Returns:
        Liste von Wetter-Markt-Dicts (raw Gamma API Format, dedupliziert)
    """
    seen_ids: Set[str] = set()
    all_weather: List[Dict[str, Any]] = []

    # --- Pass 1: Top-N nach Volume (bisheriges Verhalten) ---
    try:
        params: Dict[str, Any] = {
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
        if isinstance(markets, list):
            logger.info(f"Gamma API Pass-1 (volume): {len(markets)} Maerkte abgerufen")
            for m in markets:
                mid = str(m.get("id") or m.get("conditionId") or "")
                liq = _get_liquidity(m)
                if mid and mid not in seen_ids and _is_weather_market(m) and liq >= min_liquidity:
                    seen_ids.add(mid)
                    all_weather.append(m)
    except Exception as e:
        logger.warning(f"Gamma API Pass-1 fehlgeschlagen: {e}")

    # --- Pass 2: Near-expiry by end_date (city temperature im 24-96h Fenster) ---
    # Sortiert nach endDateIso aufsteigend => Maerkte die als naechstes ablaufen.
    # Diese enthalten die taeglich ablaufenden Stadttemperatur-Maerkte die in
    # Pass-1 (volume-sortiert) oft nicht unter den Top-300 auftauchen.
    try:
        near_expiry_params: Dict[str, Any] = {
            "limit": 500,
            "active": "true" if active_only else "false",
            "closed": "false",
            "order": "end_date_iso",
            "ascending": "true",
        }
        resp2 = requests.get(
            f"{GAMMA_API_BASE}/markets",
            params=near_expiry_params,
            timeout=timeout,
            headers={"User-Agent": "PolymarketWeatherBot/1.0"},
        )
        resp2.raise_for_status()
        markets2 = resp2.json()
        if isinstance(markets2, list):
            now = datetime.now(timezone.utc)
            window_start = now + timedelta(hours=20)   # etwas < 24h fuer Puffer
            window_end = now + timedelta(hours=120)    # etwas > 96h

            near_city_temp = 0
            for m in markets2:
                mid = str(m.get("id") or m.get("conditionId") or "")
                if not mid or mid in seen_ids:
                    continue

                # Pruefe ob Endzeit im Ziel-Fenster liegt
                end_dt = _parse_end_date(m)
                if end_dt is None:
                    continue
                if not (window_start <= end_dt <= window_end):
                    continue

                liq = _get_liquidity(m)
                if liq < min_liquidity:
                    continue

                if not _is_weather_market(m):
                    continue

                seen_ids.add(mid)
                all_weather.append(m)

                # Zaehle city-temperature boundary Maerkte separat fuer Logging
                q_lower = (m.get("question") or "").lower()
                if _is_city_temperature_boundary(q_lower):
                    near_city_temp += 1

            logger.info(
                "Gamma API Pass-2 (end_date): %d Maerkte geprueft, %d Wetter in Fenster "
                "(%d city-temp boundary) | neu gesamt: %d",
                len(markets2),
                len(all_weather) - (len(seen_ids) - len(markets2)),  # approx
                near_city_temp,
                len(all_weather),
            )
        else:
            logger.warning(f"Gamma API Pass-2 unexpected format: {type(markets2)}")
    except requests.exceptions.Timeout:
        logger.warning("Gamma API Pass-2: Timeout nach %ds (non-critical)", timeout)
    except Exception as e:
        logger.warning(f"Gamma API Pass-2 fehlgeschlagen (non-critical): {e}")


    # --- Pass 3: prefer at_or_below (paginated near-expiry) ---
    # Volume-Tops sind exact/between-lastig. Fuer PAPER_LANE_MODE=at_or_below_only
    # scannen wir zusaetzlich mehrere end_date-Pages und behalten nur Below-Phrasen.
    if prefer_at_or_below:
        below_floor = float(
            below_min_liquidity if below_min_liquidity is not None else min_liquidity
        )
        below_added = 0
        pages = max(1, int(below_pages or 1))
        try:
            now = datetime.now(timezone.utc)
            window_start = now + timedelta(hours=6)
            window_end = now + timedelta(hours=168)
            for page in range(pages):
                params3: Dict[str, Any] = {
                    "limit": 500,
                    "offset": page * 500,
                    "active": "true" if active_only else "false",
                    "closed": "false",
                    "order": "end_date_iso",
                    "ascending": "true",
                }
                resp3 = requests.get(
                    f"{GAMMA_API_BASE}/markets",
                    params=params3,
                    timeout=timeout,
                    headers={"User-Agent": "PolymarketWeatherBot/1.0"},
                )
                resp3.raise_for_status()
                markets3 = resp3.json()
                if not isinstance(markets3, list) or not markets3:
                    break
                for m in markets3:
                    mid = str(m.get("id") or m.get("conditionId") or "")
                    if not mid or mid in seen_ids:
                        continue
                    end_dt = _parse_end_date(m)
                    if end_dt is None or not (window_start <= end_dt <= window_end):
                        continue
                    liq = _get_liquidity(m)
                    if liq < below_floor:
                        continue
                    if not _is_weather_market(m):
                        continue
                    q_lower = (m.get("question") or "").lower()
                    if not _is_at_or_below_question(q_lower):
                        continue
                    seen_ids.add(mid)
                    all_weather.append(m)
                    below_added += 1
            logger.info(
                "Gamma API Pass-3 (prefer at_or_below): +%d Maerkte "
                "(pages=%d, below_liq>=%.0f) | gesamt=%d",
                below_added,
                pages,
                below_floor,
                len(all_weather),
            )
        except requests.exceptions.Timeout:
            logger.warning("Gamma API Pass-3: Timeout nach %ds (non-critical)", timeout)
        except Exception as e:
            logger.warning(f"Gamma API Pass-3 fehlgeschlagen (non-critical): {e}")

    logger.info(
        "Gamma API: %d Wetter-Maerkte gefunden (min_liq=%.0f)",
        len(all_weather),
        min_liquidity,
    )
    return all_weather



def _is_at_or_below_question(question_lower: str) -> bool:
    """True if question looks like an at_or_below temperature market."""
    q = question_lower or ""
    if any(kw in q for kw in ("or above", "or higher", "or more", "or over", "exceed")):
        return False
    if "between" in q:
        return False
    return any(kw in q for kw in BELOW_KEYWORDS)


def _parse_end_date(market: Dict[str, Any]) -> Optional[datetime]:
    """Parse end date from market dict into timezone-aware datetime."""
    for field in ("endDateIso", "endDate", "end_date"):
        raw = market.get(field)
        if not raw:
            continue
        try:
            if isinstance(raw, (int, float)):
                return datetime.fromtimestamp(raw, tz=timezone.utc)
            dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except (ValueError, OSError):
            continue
    return None


def _is_city_temperature_boundary(question_lower: str) -> bool:
    """True wenn die Frage ein city-temperature at_or_above/at_or_below Markt ist."""
    has_boundary = any(kw in question_lower for kw in BOUNDARY_KEYWORDS)
    has_city = any(city.lower() in question_lower for city in SUPPORTED_CITIES)
    has_temp = any(kw in question_lower for kw in ("temperature", "celsius", "fahrenheit", "°f", "°c"))
    return has_boundary and has_city and has_temp


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
    prefer_at_or_below: bool = False,
    below_min_liquidity: float | None = None,
    below_pages: int = 3,
) -> int:
    """
    Fuehre Discovery aus und speichere neue Wetter-Maerkte.

    Args:
        output_dir: Ausgabe-Verzeichnis
        limit: Max Maerkte zu pruefen
        min_liquidity: Min Liquiditaet
        prefer_at_or_below: Extra Pass fuer at_or_below Paper-Lane
        below_min_liquidity: Liquidity-Floor fuer Below-Pass
        below_pages: Pagination-Pages fuer Below-Pass

    Returns:
        Anzahl gespeicherter Maerkte
    """
    import json
    from pathlib import Path
    from datetime import date

    markets = discover_weather_markets(
        limit=limit,
        min_liquidity=min_liquidity,
        prefer_at_or_below=prefer_at_or_below,
        below_min_liquidity=below_min_liquidity,
        below_pages=below_pages,
    )
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
