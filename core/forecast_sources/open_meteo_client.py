# =============================================================================
# OPEN-METEO FORECAST SOURCE (no API key required)
# =============================================================================
#
# Open-Meteo provides free weather forecast data via GFS model.
# https://open-meteo.com/
#
# ISOLATION: READ-ONLY, no trading imports
# =============================================================================

import logging
from datetime import datetime, timezone
from typing import Optional, List, Tuple

from . import (
    ForecastSourceBase,
    SourceForecast,
    get_coords,
    api_get,
)

logger = logging.getLogger(__name__)


def _celsius_to_fahrenheit(c: float) -> float:
    return c * 9.0 / 5.0 + 32.0


class OpenMeteoSource(ForecastSourceBase):
    """Open-Meteo API forecast source (GFS model, free, no key)."""

    @property
    def source_name(self) -> str:
        return "open_meteo"

    @property
    def model_name(self) -> str:
        return "open_meteo_gfs"

    @property
    def requires_api_key(self) -> bool:
        return False

    def fetch(self, city: str, target_time: datetime, timeout: int = 12) -> Optional[SourceForecast]:
        coords = get_coords(city)
        if coords is None:
            logger.debug(f"Open-Meteo: no coords for {city}")
            return None

        lat, lon = coords
        url = (
            f"https://api.open-meteo.com/v1/forecast"
            f"?latitude={lat}&longitude={lon}"
            f"&hourly=temperature_2m,precipitation_probability,wind_speed_10m"
            f"&temperature_unit=celsius"
            f"&wind_speed_unit=mph"
            f"&timezone=UTC"
        )

        data = api_get(url, timeout=timeout)
        if data is None:
            return None

        try:
            hourly = data.get("hourly", {})
            times = hourly.get("time", [])
            temps_c = hourly.get("temperature_2m", [])
            precip_probs = hourly.get("precipitation_probability", [])
            wind_speeds = hourly.get("wind_speed_10m", [])

            if not times or not temps_c:
                return None

            # Parse all hourly data points
            hourly_temps: List[Tuple[datetime, float]] = []
            for i, time_str in enumerate(times):
                if i >= len(temps_c) or temps_c[i] is None:
                    continue
                try:
                    t = datetime.fromisoformat(time_str).replace(tzinfo=None)
                    hourly_temps.append((t, _celsius_to_fahrenheit(temps_c[i])))
                except (ValueError, TypeError):
                    continue

            if not hourly_temps:
                return None

            # Find the hour closest to target_time
            target_naive = target_time.replace(tzinfo=None) if target_time.tzinfo else target_time
            best_idx = 0
            best_diff = float("inf")
            for i, (t, _) in enumerate(hourly_temps):
                diff = abs((t - target_naive).total_seconds())
                if diff < best_diff:
                    best_diff = diff
                    best_idx = i

            best_temp_f = hourly_temps[best_idx][1]

            # Collect min/max from all hours on target day
            target_date = target_naive.date()
            day_temps = [temp for t, temp in hourly_temps if t.date() == target_date]
            temp_min = min(day_temps) if day_temps else None
            temp_max = max(day_temps) if day_temps else None

            # Get precipitation and wind for closest hour
            precip_prob = None
            wind_speed = None
            if best_idx < len(precip_probs) and precip_probs[best_idx] is not None:
                precip_prob = float(precip_probs[best_idx])
            if best_idx < len(wind_speeds) and wind_speeds[best_idx] is not None:
                wind_speed = float(wind_speeds[best_idx])

            now = datetime.now(timezone.utc)
            horizon_hours = (target_time - now).total_seconds() / 3600 if target_time.tzinfo else \
                (target_naive - datetime.utcnow()).total_seconds() / 3600

            return SourceForecast(
                city=city,
                target_time=target_time,
                forecast_time=now,
                source_name=self.source_name,
                model_name=self.model_name,
                temperature_f=best_temp_f,
                temperature_min_f=temp_min,
                temperature_max_f=temp_max,
                hourly_temperatures=hourly_temps,
                precipitation_probability=precip_prob,
                wind_speed_mph=wind_speed,
                forecast_horizon_hours=max(0, horizon_hours),
            )
        except Exception as e:
            logger.debug(f"Open-Meteo parse error for {city}: {e}")
            return None
