# =============================================================================
# POLYMARKET BEOBACHTER - NOAA WEATHER FORECAST CLIENT
# =============================================================================
#
# NOAA Weather API (api.weather.gov) — free, no API key required.
#
# ISOLATION:
# - READ-ONLY: Fetches forecasts, does not modify anything
# - NO imports from trading, execution, or decision modules
# - Output is ForecastData (same format as weather_probability_model)
#
# =============================================================================

import json
import logging
import ssl
from datetime import datetime, timezone
from typing import Optional, Dict, Tuple
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

from .weather_probability_model import ForecastData

logger = logging.getLogger(__name__)


# =============================================================================
# CITY GEOCODING (hardcoded Top-20 US cities)
# =============================================================================

# Lat/Lon for major US cities used in Polymarket weather markets
CITY_COORDINATES: Dict[str, Tuple[float, float]] = {
    "new york": (40.7128, -74.0060),
    "nyc": (40.7128, -74.0060),
    "los angeles": (34.0522, -118.2437),
    "la": (34.0522, -118.2437),
    "chicago": (41.8781, -87.6298),
    "houston": (29.7604, -95.3698),
    "phoenix": (33.4484, -112.0740),
    "philadelphia": (39.9526, -75.1652),
    "san antonio": (29.4241, -98.4936),
    "san diego": (32.7157, -117.1611),
    "dallas": (32.7767, -96.7970),
    "austin": (30.2672, -97.7431),
    "jacksonville": (30.3322, -81.6557),
    "san jose": (37.3382, -121.8863),
    "fort worth": (32.7555, -97.3308),
    "columbus": (39.9612, -82.9988),
    "charlotte": (35.2271, -80.8431),
    "indianapolis": (39.7684, -86.1581),
    "san francisco": (37.7749, -122.4194),
    "seattle": (47.6062, -122.3321),
    "denver": (39.7392, -104.9903),
    "washington": (38.9072, -77.0369),
    "dc": (38.9072, -77.0369),
    "washington dc": (38.9072, -77.0369),
    "nashville": (36.1627, -86.7816),
    "oklahoma city": (35.4676, -97.5164),
    "el paso": (31.7619, -106.4850),
    "boston": (42.3601, -71.0589),
    "portland": (45.5152, -122.6784),
    "las vegas": (36.1699, -115.1398),
    "memphis": (35.1495, -90.0490),
    "louisville": (38.2527, -85.7585),
    "baltimore": (39.2904, -76.6122),
    "milwaukee": (43.0389, -87.9065),
    "albuquerque": (35.0844, -106.6504),
    "tucson": (32.2226, -110.9747),
    "fresno": (36.7378, -119.7871),
    "sacramento": (38.5816, -121.4944),
    "mesa": (33.4152, -111.8315),
    "atlanta": (33.7490, -84.3880),
    "miami": (25.7617, -80.1918),
    "minneapolis": (44.9778, -93.2650),
    "detroit": (42.3314, -83.0458),
    "new orleans": (29.9511, -90.0715),
    "cleveland": (41.4993, -81.6944),
    "pittsburgh": (40.4406, -79.9959),
    "st louis": (38.6270, -90.1994),
    "saint louis": (38.6270, -90.1994),
    "tampa": (27.9506, -82.4572),
    "orlando": (28.5383, -81.3792),
    "cincinnati": (39.1031, -84.5120),
    "kansas city": (39.0997, -94.5786),
    "raleigh": (35.7796, -78.6382),
    "honolulu": (21.3069, -157.8583),
    "anchorage": (61.2181, -149.9003),
}


def geocode_city(city_name: str) -> Optional[Tuple[float, float]]:
    """
    Resolve city name to (lat, lon) coordinates.

    Args:
        city_name: City name (case-insensitive)

    Returns:
        (latitude, longitude) tuple or None if not found
    """
    key = city_name.strip().lower()
    return CITY_COORDINATES.get(key)


# =============================================================================
# NOAA API CLIENT
# =============================================================================

NOAA_API_BASE = "https://api.weather.gov"
REQUEST_TIMEOUT = 15  # seconds


def _noaa_request(url: str) -> Optional[Dict]:
    """
    Make a GET request to the NOAA API.

    Args:
        url: Full URL

    Returns:
        Parsed JSON dict or None on error
    """
    try:
        ctx = ssl.create_default_context()
        request = Request(url, headers={
            "User-Agent": "PolymarketBeobachter/2.0 (weather-forecast-research)",
            "Accept": "application/geo+json",
        })
        with urlopen(request, timeout=REQUEST_TIMEOUT, context=ctx) as response:
            return json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError) as e:
        logger.warning(f"NOAA API error for {url}: {e}")
        return None
    except Exception as e:
        logger.error(f"NOAA request failed: {e}")
        return None


def _get_forecast_url(lat: float, lon: float) -> Optional[str]:
    """
    Get the forecast URL for a lat/lon from NOAA points API.

    NOAA requires a two-step process:
    1. /points/{lat},{lon} → get forecast URL
    2. Fetch the forecast URL

    Args:
        lat: Latitude
        lon: Longitude

    Returns:
        Forecast URL or None
    """
    points_url = f"{NOAA_API_BASE}/points/{lat:.4f},{lon:.4f}"
    data = _noaa_request(points_url)
    if data is None:
        return None

    properties = data.get("properties", {})
    forecast_url = properties.get("forecast")
    return forecast_url


def fetch_forecast(lat: float, lon: float) -> Optional[Dict]:
    """
    Fetch 7-day forecast from NOAA for given coordinates.

    Args:
        lat: Latitude
        lon: Longitude

    Returns:
        NOAA forecast response dict or None
    """
    forecast_url = _get_forecast_url(lat, lon)
    if forecast_url is None:
        logger.warning(f"Could not get forecast URL for ({lat}, {lon})")
        return None

    return _noaa_request(forecast_url)


def fetch_forecast_for_city(city_name: str, target_time: datetime) -> Optional[ForecastData]:
    """
    Fetch forecast for a city and return as ForecastData.

    This is the main entry point for the Weather Engine integration.

    Args:
        city_name: City name (must be in CITY_COORDINATES)
        target_time: Target datetime for the forecast

    Returns:
        ForecastData or None if unavailable
    """
    coords = geocode_city(city_name)
    if coords is None:
        logger.warning(f"City not found in geocode database: {city_name}")
        return None

    lat, lon = coords
    forecast_data = fetch_forecast(lat, lon)
    if forecast_data is None:
        return None

    # Parse NOAA forecast periods
    properties = forecast_data.get("properties", {})
    periods = properties.get("periods", [])

    if not periods:
        logger.warning(f"No forecast periods for {city_name}")
        return None

    # Find the period closest to target_time
    best_period = None
    best_diff = float("inf")

    for period in periods:
        start_str = period.get("startTime", "")
        try:
            # NOAA uses ISO 8601 with timezone
            # Parse just the datetime part
            period_start = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
            # Compare naive datetimes
            period_naive = period_start.replace(tzinfo=None)
            target_naive = target_time.replace(tzinfo=None) if target_time.tzinfo else target_time
            diff = abs((period_naive - target_naive).total_seconds())
            if diff < best_diff:
                best_diff = diff
                best_period = period
        except (ValueError, TypeError):
            continue

    if best_period is None:
        logger.warning(f"No matching forecast period for {city_name} at {target_time}")
        return None

    # Extract temperature
    temperature = best_period.get("temperature")
    temp_unit = best_period.get("temperatureUnit", "F")

    if temperature is None:
        return None

    temp_f = float(temperature)
    if temp_unit == "C":
        temp_f = temp_f * 9.0 / 5.0 + 32.0

    return ForecastData(
        city=city_name,
        forecast_time=datetime.now(timezone.utc),
        target_time=target_time,
        temperature_f=temp_f,
        source="noaa_api",
        temperature_min_f=None,
        temperature_max_f=None,
    )
