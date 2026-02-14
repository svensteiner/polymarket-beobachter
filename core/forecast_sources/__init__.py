# =============================================================================
# FORECAST SOURCES - Multi-Source Weather Forecast Package
# =============================================================================
#
# Normalised interface for all weather forecast providers.
# Each source implements ForecastSourceBase and returns SourceForecast.
#
# ISOLATION:
# - READ-ONLY: Fetches forecasts, does not modify anything
# - NO imports from trading, execution, or decision modules
#
# =============================================================================

import json
import logging
import os
import ssl
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, Dict, List, Tuple
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

logger = logging.getLogger(__name__)

# Load .env from project root if not already loaded
try:
    from dotenv import load_dotenv
    from pathlib import Path
    _env_path = Path(__file__).parent.parent.parent / ".env"
    if _env_path.exists():
        load_dotenv(_env_path, override=False)
except ImportError:
    pass


# =============================================================================
# SHARED CITY COORDINATES
# =============================================================================

GLOBAL_CITY_COORDINATES: Dict[str, Tuple[float, float]] = {
    # International cities
    "london": (51.5074, -0.1278),
    "paris": (48.8566, 2.3522),
    "berlin": (52.5200, 13.4050),
    "seoul": (37.5665, 126.9780),
    "tokyo": (35.6762, 139.6503),
    "sydney": (-33.8688, 151.2093),
    "buenos aires": (-34.6037, -58.3816),
    "ankara": (39.9334, 32.8597),
    "toronto": (43.6532, -79.3832),
    # Major US cities
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


def get_coords(city: str) -> Optional[Tuple[float, float]]:
    """Get coordinates for a city name."""
    key = city.strip().lower()
    return GLOBAL_CITY_COORDINATES.get(key)


# =============================================================================
# HTTP HELPER
# =============================================================================

REQUEST_TIMEOUT = 12


def api_get(url: str, headers: Optional[Dict] = None, timeout: int = REQUEST_TIMEOUT) -> Optional[Dict]:
    """HTTP GET with JSON response. Shared across all forecast sources."""
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
# SOURCE FORECAST DATA MODEL
# =============================================================================

@dataclass
class SourceForecast:
    """
    Normalised forecast from any weather source.

    All sources convert their data into this common format.
    Temperature is always in Fahrenheit.
    """
    city: str
    target_time: datetime
    forecast_time: datetime
    source_name: str
    model_name: str
    temperature_f: float
    temperature_min_f: Optional[float] = None
    temperature_max_f: Optional[float] = None
    hourly_temperatures: Optional[List[Tuple[datetime, float]]] = field(default_factory=list)
    precipitation_probability: Optional[float] = None
    wind_speed_mph: Optional[float] = None
    forecast_horizon_hours: Optional[float] = None

    def to_dict(self) -> Dict:
        return {
            "city": self.city,
            "target_time": self.target_time.isoformat(),
            "forecast_time": self.forecast_time.isoformat(),
            "source_name": self.source_name,
            "model_name": self.model_name,
            "temperature_f": self.temperature_f,
            "temperature_min_f": self.temperature_min_f,
            "temperature_max_f": self.temperature_max_f,
            "precipitation_probability": self.precipitation_probability,
            "wind_speed_mph": self.wind_speed_mph,
            "forecast_horizon_hours": self.forecast_horizon_hours,
        }


# =============================================================================
# FORECAST SOURCE BASE CLASS
# =============================================================================

class ForecastSourceBase(ABC):
    """Abstract base class for all forecast sources."""

    @property
    @abstractmethod
    def source_name(self) -> str:
        """Unique name for this source (e.g. 'open_meteo')."""
        ...

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Underlying model name (e.g. 'open_meteo_gfs'). Used for correlation grouping."""
        ...

    @property
    def requires_api_key(self) -> bool:
        """Whether this source needs an API key."""
        return False

    @abstractmethod
    def fetch(self, city: str, target_time: datetime) -> Optional[SourceForecast]:
        """
        Fetch forecast for a city at a target time.

        Returns SourceForecast or None if unavailable.
        """
        ...

    def is_available(self) -> bool:
        """Check if this source can be used (e.g. API key present)."""
        return True


__all__ = [
    "SourceForecast",
    "ForecastSourceBase",
    "GLOBAL_CITY_COORDINATES",
    "get_coords",
    "api_get",
    "REQUEST_TIMEOUT",
]
