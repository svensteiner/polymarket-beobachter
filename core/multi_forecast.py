# =============================================================================
# MULTI-SOURCE WEATHER FORECAST FETCHER
# =============================================================================
#
# Chains multiple weather APIs for global coverage:
#   1. Tomorrow.io  (global, primary)
#   2. OpenWeather   (global, fallback)
#   3. WeatherAPI    (global, fallback)
#   4. NOAA          (US-only, free fallback)
#
# ISOLATION:
# - READ-ONLY: Fetches forecasts, does not modify anything
# - Output is ForecastData (same format as weather_probability_model)
#
# =============================================================================

import json
import logging
import os
import ssl
import time
from pathlib import Path

# Load .env from project root if not already loaded
try:
    from dotenv import load_dotenv
    _env_path = Path(__file__).parent.parent / ".env"
    if _env_path.exists():
        load_dotenv(_env_path, override=False)
except ImportError:
    pass
from datetime import datetime, timezone
from typing import Optional, Dict
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

from .weather_probability_model import ForecastData

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 15
MAX_MARKET_FORECAST_SECONDS = 30   # Max time for all API calls per single market
MAX_TOTAL_FORECAST_SECONDS = 300   # Max time for all markets combined (5 minutes)
API_CALL_DELAY = 0.2               # 200ms between consecutive API calls

# Global forecast start time - reset by caller or at first use
_forecast_global_start: float = 0.0


def reset_forecast_timer():
    """Reset the global forecast timer. Call before processing a batch of markets."""
    global _forecast_global_start
    _forecast_global_start = time.time()


def is_global_forecast_timeout() -> bool:
    """Check if the global forecast timeout has been exceeded."""
    global _forecast_global_start
    if _forecast_global_start == 0.0:
        _forecast_global_start = time.time()
    return (time.time() - _forecast_global_start) > MAX_TOTAL_FORECAST_SECONDS


# =============================================================================
# INTERNATIONAL CITY COORDINATES (for APIs that need lat/lon)
# =============================================================================

GLOBAL_CITY_COORDINATES: Dict[str, tuple] = {
    # International cities from weather.yaml config
    "london": (51.5074, -0.1278),
    "paris": (48.8566, 2.3522),
    "berlin": (52.5200, 13.4050),
    "seoul": (37.5665, 126.9780),
    "tokyo": (35.6762, 139.6503),
    "sydney": (-33.8688, 151.2093),
    "buenos aires": (-34.6037, -58.3816),
    "ankara": (39.9334, 32.8597),
    "toronto": (43.6532, -79.3832),
    # Major US cities (subset)
    "new york": (40.7128, -74.0060),
    "los angeles": (34.0522, -118.2437),
    "chicago": (41.8781, -87.6298),
    "miami": (25.7617, -80.1918),
    "denver": (39.7392, -104.9903),
    "phoenix": (33.4484, -112.0740),
    "seattle": (47.6062, -122.3321),
    "boston": (42.3601, -71.0589),
    "houston": (29.7604, -95.3698),
    "atlanta": (33.7490, -84.3880),
    "dallas": (32.7767, -96.7970),
    "san francisco": (37.7749, -122.4194),
    "washington": (38.9072, -77.0369),
    "philadelphia": (39.9526, -75.1652),
}


def _get_coords(city: str) -> Optional[tuple]:
    """Get coordinates for a city name."""
    key = city.strip().lower()
    return GLOBAL_CITY_COORDINATES.get(key)


def _api_get(url: str, headers: Optional[Dict] = None, timeout: int = REQUEST_TIMEOUT) -> Optional[Dict]:
    """HTTP GET with JSON response."""
    try:
        ctx = ssl.create_default_context()
        req_headers = {"User-Agent": "PolymarketBeobachter/2.0"}
        if headers:
            req_headers.update(headers)
        request = Request(url, headers=req_headers)
        with urlopen(request, timeout=timeout, context=ctx) as response:
            return json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, Exception) as e:
        logger.debug(f"API request failed for {url[:80]}: {e}")
        return None


# =============================================================================
# TOMORROW.IO
# =============================================================================

def _fetch_tomorrow_io(city: str, target_time: datetime) -> Optional[ForecastData]:
    """Fetch forecast from Tomorrow.io API."""
    api_key = os.environ.get("TOMORROW_IO_API_KEY", "")
    if not api_key:
        return None

    coords = _get_coords(city)
    if coords is None:
        return None

    lat, lon = coords
    url = (
        f"https://api.tomorrow.io/v4/weather/forecast"
        f"?location={lat},{lon}"
        f"&apikey={api_key}"
        f"&units=imperial"
    )

    data = _api_get(url)
    if data is None:
        return None

    try:
        # Tomorrow.io returns daily forecasts in timelines.daily
        daily = data.get("timelines", {}).get("daily", [])
        if not daily:
            return None

        # Find closest day to target
        best = None
        best_diff = float("inf")

        for day in daily:
            time_str = day.get("time", "")
            try:
                day_time = datetime.fromisoformat(time_str.replace("Z", "+00:00")).replace(tzinfo=None)
                target_naive = target_time.replace(tzinfo=None) if target_time.tzinfo else target_time
                diff = abs((day_time - target_naive).total_seconds())
                if diff < best_diff:
                    best_diff = diff
                    best = day
            except (ValueError, TypeError):
                continue

        if best is None:
            return None

        values = best.get("values", {})
        temp_avg = values.get("temperatureAvg")
        temp_max = values.get("temperatureMax")
        temp_min = values.get("temperatureMin")

        if temp_avg is None and temp_max is not None and temp_min is not None:
            temp_avg = (temp_max + temp_min) / 2.0

        if temp_avg is None:
            return None

        return ForecastData(
            city=city,
            forecast_time=datetime.now(timezone.utc),
            target_time=target_time,
            temperature_f=float(temp_avg),
            source="tomorrow_io",
            temperature_min_f=float(temp_min) if temp_min is not None else None,
            temperature_max_f=float(temp_max) if temp_max is not None else None,
        )
    except Exception as e:
        logger.debug(f"Tomorrow.io parse error for {city}: {e}")
        return None


# =============================================================================
# OPENWEATHER
# =============================================================================

def _fetch_openweather(city: str, target_time: datetime) -> Optional[ForecastData]:
    """Fetch forecast from OpenWeather API."""
    api_key = os.environ.get("OPENWEATHER_API_KEY", "")
    if not api_key:
        return None

    coords = _get_coords(city)
    if coords is None:
        return None

    lat, lon = coords
    url = (
        f"https://api.openweathermap.org/data/2.5/forecast"
        f"?lat={lat}&lon={lon}"
        f"&appid={api_key}"
        f"&units=imperial"
    )

    data = _api_get(url)
    if data is None:
        return None

    try:
        forecasts = data.get("list", [])
        if not forecasts:
            return None

        best = None
        best_diff = float("inf")

        for fc in forecasts:
            dt = fc.get("dt", 0)
            try:
                fc_time = datetime.fromtimestamp(dt, tz=timezone.utc).replace(tzinfo=None)
                target_naive = target_time.replace(tzinfo=None) if target_time.tzinfo else target_time
                diff = abs((fc_time - target_naive).total_seconds())
                if diff < best_diff:
                    best_diff = diff
                    best = fc
            except (ValueError, TypeError):
                continue

        if best is None:
            return None

        main = best.get("main", {})
        temp = main.get("temp")
        temp_min = main.get("temp_min")
        temp_max = main.get("temp_max")

        if temp is None:
            return None

        return ForecastData(
            city=city,
            forecast_time=datetime.now(timezone.utc),
            target_time=target_time,
            temperature_f=float(temp),
            source="openweather",
            temperature_min_f=float(temp_min) if temp_min is not None else None,
            temperature_max_f=float(temp_max) if temp_max is not None else None,
        )
    except Exception as e:
        logger.debug(f"OpenWeather parse error for {city}: {e}")
        return None


# =============================================================================
# WEATHERAPI
# =============================================================================

def _fetch_weatherapi(city: str, target_time: datetime) -> Optional[ForecastData]:
    """Fetch forecast from WeatherAPI.com."""
    api_key = os.environ.get("WEATHERAPI_KEY", "")
    if not api_key:
        return None

    coords = _get_coords(city)
    if coords is None:
        return None

    lat, lon = coords
    # Calculate days ahead (max 10 for free tier)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    target_naive = target_time.replace(tzinfo=None) if target_time.tzinfo else target_time
    days_ahead = max(1, min(10, int((target_naive - now).total_seconds() / 86400) + 1))

    url = (
        f"https://api.weatherapi.com/v1/forecast.json"
        f"?key={api_key}"
        f"&q={lat},{lon}"
        f"&days={days_ahead}"
    )

    data = _api_get(url)
    if data is None:
        return None

    try:
        forecast_days = data.get("forecast", {}).get("forecastday", [])
        if not forecast_days:
            return None

        best = None
        best_diff = float("inf")

        for day in forecast_days:
            date_str = day.get("date", "")
            try:
                day_time = datetime.strptime(date_str, "%Y-%m-%d")
                diff = abs((day_time - target_naive).total_seconds())
                if diff < best_diff:
                    best_diff = diff
                    best = day
            except (ValueError, TypeError):
                continue

        if best is None:
            return None

        day_data = best.get("day", {})
        avg_f = day_data.get("avgtemp_f")
        max_f = day_data.get("maxtemp_f")
        min_f = day_data.get("mintemp_f")

        if avg_f is None and max_f is not None and min_f is not None:
            avg_f = (max_f + min_f) / 2.0

        if avg_f is None:
            return None

        return ForecastData(
            city=city,
            forecast_time=datetime.now(timezone.utc),
            target_time=target_time,
            temperature_f=float(avg_f),
            source="weatherapi",
            temperature_min_f=float(min_f) if min_f is not None else None,
            temperature_max_f=float(max_f) if max_f is not None else None,
        )
    except Exception as e:
        logger.debug(f"WeatherAPI parse error for {city}: {e}")
        return None


# =============================================================================
# MULTI-SOURCE FETCHER (main entry point)
# =============================================================================

def fetch_forecast_multi(city: str, target_time: datetime) -> Optional[ForecastData]:
    """
    Fetch forecast using multiple sources with fallback chain.

    Priority:
    1. Tomorrow.io (best global coverage, most accurate)
    2. OpenWeather (good global fallback)
    3. WeatherAPI (additional fallback)
    4. NOAA (US-only, free, no API key needed)

    Args:
        city: City name
        target_time: Target datetime for forecast

    Returns:
        ForecastData from first successful source, or None
    """
    if not city:
        logger.debug("No city provided for forecast fetch")
        return None

    # Check global timeout across all markets
    if is_global_forecast_timeout():
        logger.warning(
            "Globales Forecast-Timeout erreicht (%ds), ueberspringe %s",
            MAX_TOTAL_FORECAST_SECONDS, city
        )
        return None

    market_start = time.time()

    # Try commercial APIs first (global coverage)
    api_sources = [
        ("tomorrow_io", _fetch_tomorrow_io),
        ("openweather", _fetch_openweather),
        ("weatherapi", _fetch_weatherapi),
    ]
    for idx, (name, fetcher) in enumerate(api_sources):
        # Check per-market timeout
        if (time.time() - market_start) > MAX_MARKET_FORECAST_SECONDS:
            logger.warning(
                "Market-Forecast-Timeout erreicht (%ds) fuer %s, breche ab",
                MAX_MARKET_FORECAST_SECONDS, city
            )
            break
        # Check global timeout
        if is_global_forecast_timeout():
            logger.warning(
                "Globales Forecast-Timeout erreicht (%ds), breche ab bei %s",
                MAX_TOTAL_FORECAST_SECONDS, city
            )
            break
        # Rate-limit delay between API calls (not before the first one)
        if idx > 0:
            time.sleep(API_CALL_DELAY)
        try:
            result = fetcher(city, target_time)
            if result is not None:
                logger.debug(f"Forecast for {city} from {name}")
                return result
        except Exception as e:
            logger.debug(f"{name} failed for {city}: {e}")

    # NOAA fallback (US cities only) - also check timeouts
    if ((time.time() - market_start) <= MAX_MARKET_FORECAST_SECONDS
            and not is_global_forecast_timeout()):
        time.sleep(API_CALL_DELAY)  # Rate-limit before NOAA call
        try:
            from .noaa_client import fetch_forecast_for_city
            result = fetch_forecast_for_city(city, target_time)
            if result is not None:
                logger.debug(f"Forecast for {city} from NOAA")
                return result
        except Exception as e:
            logger.debug(f"NOAA failed for {city}: {e}")

    logger.warning(f"All forecast sources failed for {city}")
    return None


# =============================================================================
# ENSEMBLE-COMPATIBLE FETCHER (returns all source results)
# =============================================================================

def fetch_all_forecasts(city: str, target_time: datetime):
    """
    Fetch forecasts from all available sources (for ensemble).

    Unlike fetch_forecast_multi() which stops at the first success,
    this collects ALL successful results.

    Returns:
        List[SourceForecast] from the forecast_sources package
    """
    from .forecast_sources import SourceForecast, get_coords
    from .forecast_sources.open_meteo_client import OpenMeteoSource
    from .forecast_sources.met_norway_client import MetNorwaySource
    from .forecast_sources.openweather_client import OpenWeatherSource
    from .forecast_sources.tomorrow_client import TomorrowIoSource

    if not city:
        return []

    # Check global timeout
    if is_global_forecast_timeout():
        logger.warning(
            "Globales Forecast-Timeout erreicht (%ds), ueberspringe %s (ensemble)",
            MAX_TOTAL_FORECAST_SECONDS, city
        )
        return []

    sources = [
        OpenMeteoSource(),
        MetNorwaySource(),
        OpenWeatherSource(),
        TomorrowIoSource(),
    ]

    results = []
    for source in sources:
        if not source.is_available():
            continue
        if is_global_forecast_timeout():
            break
        try:
            result = source.fetch(city, target_time)
            if result is not None:
                results.append(result)
                logger.debug(f"Ensemble source {source.source_name} OK for {city}")
        except Exception as e:
            logger.debug(f"Ensemble source {source.source_name} failed for {city}: {e}")

    # Also try NOAA for US cities
    if not is_global_forecast_timeout():
        try:
            from .noaa_client import fetch_forecast_for_city, geocode_city
            if geocode_city(city) is not None:
                noaa_result = fetch_forecast_for_city(city, target_time)
                if noaa_result is not None:
                    # Wrap NOAA ForecastData as SourceForecast
                    from datetime import timezone as _tz
                    results.append(SourceForecast(
                        city=city,
                        target_time=target_time,
                        forecast_time=noaa_result.forecast_time,
                        source_name="noaa",
                        model_name="noaa_gfs",
                        temperature_f=noaa_result.temperature_f,
                        temperature_min_f=noaa_result.temperature_min_f,
                        temperature_max_f=noaa_result.temperature_max_f,
                    ))
                    logger.debug(f"Ensemble source noaa OK for {city}")
        except Exception as e:
            logger.debug(f"Ensemble source noaa failed for {city}: {e}")

    logger.info(f"Ensemble: {len(results)} sources for {city}: {[r.source_name for r in results]}")
    return results
