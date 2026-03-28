# =============================================================================
# OPENWEATHER FORECAST SOURCE (requires API key)
# =============================================================================
#
# Wraps existing OpenWeather logic into ForecastSourceBase interface.
#
# ISOLATION: READ-ONLY, no trading imports
# =============================================================================

import logging
import os
from datetime import datetime, timezone
from typing import Optional

from . import (
    ForecastSourceBase,
    SourceForecast,
    get_coords,
    api_get,
)

logger = logging.getLogger(__name__)


class OpenWeatherSource(ForecastSourceBase):
    """OpenWeather API forecast source (GFS model, requires key)."""

    @property
    def source_name(self) -> str:
        return "openweather"

    @property
    def model_name(self) -> str:
        return "openweather_gfs"

    @property
    def requires_api_key(self) -> bool:
        return True

    def is_available(self) -> bool:
        return bool(os.environ.get("OPENWEATHER_API_KEY", ""))

    def fetch(self, city: str, target_time: datetime, timeout: int = 12) -> Optional[SourceForecast]:
        api_key = os.environ.get("OPENWEATHER_API_KEY", "")
        if not api_key:
            return None

        coords = get_coords(city)
        if coords is None:
            return None

        lat, lon = coords
        url = (
            f"https://api.openweathermap.org/data/2.5/forecast"
            f"?lat={lat}&lon={lon}"
            f"&appid={api_key}"
            f"&units=imperial"
        )

        data = api_get(url, timeout=timeout)
        if data is None:
            return None

        try:
            forecasts = data.get("list", [])
            if not forecasts:
                return None

            target_naive = target_time.replace(tzinfo=None) if target_time.tzinfo else target_time
            best = None
            best_diff = float("inf")

            for fc in forecasts:
                dt = fc.get("dt", 0)
                try:
                    fc_time = datetime.fromtimestamp(dt, tz=timezone.utc).replace(tzinfo=None)
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

            if temp is None:
                return None

            # Compute true daily max/min from all 3h intervals for the target day.
            # The per-slot temp_min/temp_max in OpenWeather are 3h-interval values,
            # not the actual daily high/low — so we aggregate manually.
            target_date = target_naive.date()
            day_temps = []
            for fc in forecasts:
                dt = fc.get("dt", 0)
                try:
                    fc_time = datetime.fromtimestamp(dt, tz=timezone.utc).replace(tzinfo=None)
                    if fc_time.date() == target_date:
                        t = fc.get("main", {}).get("temp")
                        if t is not None:
                            day_temps.append(float(t))
                except (ValueError, TypeError, OSError):
                    continue
            temp_max = max(day_temps) if day_temps else main.get("temp_max")
            temp_min = min(day_temps) if day_temps else main.get("temp_min")

            now = datetime.now(timezone.utc)
            horizon_hours = (target_time - now).total_seconds() / 3600 if target_time.tzinfo else \
                (target_naive - datetime.utcnow()).total_seconds() / 3600

            # Wind speed (imperial = mph from OpenWeather)
            wind_speed = None
            wind_data = best.get("wind", {})
            if "speed" in wind_data:
                wind_speed = float(wind_data["speed"])

            return SourceForecast(
                city=city,
                target_time=target_time,
                forecast_time=now,
                source_name=self.source_name,
                model_name=self.model_name,
                temperature_f=float(temp),
                temperature_min_f=float(temp_min) if temp_min is not None else None,
                temperature_max_f=float(temp_max) if temp_max is not None else None,
                wind_speed_mph=wind_speed,
                forecast_horizon_hours=max(0, horizon_hours),
            )
        except Exception as e:
            logger.debug(f"OpenWeather parse error for {city}: {e}")
            return None
