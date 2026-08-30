# =============================================================================
# OPEN-METEO MULTI-MODEL FORECAST SOURCES (ECMWF / ICON / GEM)
# =============================================================================
#
# WHY:
#   Commercial APIs (Tomorrow.io, OpenWeather, WeatherAPI) and the default
#   Open-Meteo endpoint are heavily GFS-correlated. That collapses ensemble
#   diversity and makes "edge" look better calibrated than it is vs market.
#
#   Open-Meteo exposes independent global models without an API key:
#     - ecmwf_ifs025  (ECMWF IFS 0.25°)  — typically highest skill mid-range
#     - icon_global   (DWD ICON)         — strong EU / mid-lat skill
#     - gem_global    (CMC GEM)          — independent Canadian global model
#
# ISOLATION: READ-ONLY, no trading imports
# Docs: https://open-meteo.com/en/docs
# =============================================================================

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from . import ForecastSourceBase, SourceForecast, api_get, get_coords

logger = logging.getLogger(__name__)


def _celsius_to_fahrenheit(c: float) -> float:
    return c * 9.0 / 5.0 + 32.0


class OpenMeteoModelSource(ForecastSourceBase):
    """
    Generic Open-Meteo single-model forecast source.

    Uses hourly temperature series + daily min/max for the target day.
    """

    def __init__(
        self,
        *,
        source_name: str,
        model_name: str,
        open_meteo_model: str,
    ) -> None:
        self._source_name = source_name
        self._model_name = model_name
        self._open_meteo_model = open_meteo_model

    @property
    def source_name(self) -> str:
        return self._source_name

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def requires_api_key(self) -> bool:
        return False

    def fetch(
        self,
        city: str,
        target_time: datetime,
        timeout: int = 12,
    ) -> Optional[SourceForecast]:
        coords = get_coords(city)
        if coords is None:
            logger.debug("%s: no coords for %s", self.source_name, city)
            return None

        lat, lon = coords
        url = (
            f"https://api.open-meteo.com/v1/forecast"
            f"?latitude={lat}&longitude={lon}"
            f"&hourly=temperature_2m,precipitation_probability,wind_speed_10m"
            f"&daily=temperature_2m_max,temperature_2m_min"
            f"&models={self._open_meteo_model}"
            f"&temperature_unit=celsius"
            f"&wind_speed_unit=mph"
            f"&timezone=UTC"
            f"&forecast_days=10"
        )

        data = api_get(url, timeout=timeout)
        if data is None:
            return None

        try:
            hourly = data.get("hourly", {}) or {}
            times = hourly.get("time", []) or []
            temps_c = hourly.get("temperature_2m", []) or []
            precip_probs = hourly.get("precipitation_probability", []) or []
            wind_speeds = hourly.get("wind_speed_10m", []) or []

            if not times or not temps_c:
                return None

            hourly_temps: List[Tuple[datetime, float]] = []
            for i, time_str in enumerate(times):
                if i >= len(temps_c) or temps_c[i] is None:
                    continue
                try:
                    t = datetime.fromisoformat(time_str).replace(tzinfo=None)
                    hourly_temps.append((t, _celsius_to_fahrenheit(float(temps_c[i]))))
                except (ValueError, TypeError):
                    continue

            if not hourly_temps:
                return None

            target_naive = (
                target_time.replace(tzinfo=None) if target_time.tzinfo else target_time
            )
            best_idx = 0
            best_diff = float("inf")
            for i, (t, _) in enumerate(hourly_temps):
                diff = abs((t - target_naive).total_seconds())
                if diff < best_diff:
                    best_diff = diff
                    best_idx = i

            best_temp_f = hourly_temps[best_idx][1]
            target_date = target_naive.date()
            day_temps = [temp for t, temp in hourly_temps if t.date() == target_date]

            # Prefer official daily min/max from the model when available
            temp_min = min(day_temps) if day_temps else None
            temp_max = max(day_temps) if day_temps else None
            daily = data.get("daily", {}) or {}
            daily_times = daily.get("time", []) or []
            daily_max = daily.get("temperature_2m_max", []) or []
            daily_min = daily.get("temperature_2m_min", []) or []
            target_date_str = target_date.isoformat()
            for i, d in enumerate(daily_times):
                if d == target_date_str:
                    if i < len(daily_max) and daily_max[i] is not None:
                        temp_max = _celsius_to_fahrenheit(float(daily_max[i]))
                    if i < len(daily_min) and daily_min[i] is not None:
                        temp_min = _celsius_to_fahrenheit(float(daily_min[i]))
                    break

            precip_prob = None
            wind_speed = None
            # Map best hourly index back to original arrays (same order as times)
            # best_idx indexes hourly_temps which may skip Nones — re-find by time
            best_time = hourly_temps[best_idx][0]
            for i, time_str in enumerate(times):
                try:
                    t = datetime.fromisoformat(time_str).replace(tzinfo=None)
                except (ValueError, TypeError):
                    continue
                if t != best_time:
                    continue
                if i < len(precip_probs) and precip_probs[i] is not None:
                    precip_prob = float(precip_probs[i])
                if i < len(wind_speeds) and wind_speeds[i] is not None:
                    wind_speed = float(wind_speeds[i])
                break

            now = datetime.now(timezone.utc)
            if target_time.tzinfo:
                horizon_hours = (target_time - now).total_seconds() / 3600
            else:
                horizon_hours = (target_naive - datetime.utcnow()).total_seconds() / 3600

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
                forecast_horizon_hours=max(0.0, horizon_hours),
            )
        except Exception as e:
            logger.debug("%s parse error for %s: %s", self.source_name, city, e)
            return None


class EcmwfIfsSource(OpenMeteoModelSource):
    """ECMWF IFS 0.25° via Open-Meteo (independent of GFS)."""

    def __init__(self) -> None:
        super().__init__(
            source_name="ecmwf_ifs",
            model_name="ecmwf_ifs025",
            open_meteo_model="ecmwf_ifs025",
        )


class IconGlobalSource(OpenMeteoModelSource):
    """DWD ICON Global via Open-Meteo."""

    def __init__(self) -> None:
        super().__init__(
            source_name="icon_global",
            model_name="icon_global",
            open_meteo_model="icon_global",
        )


class GemGlobalSource(OpenMeteoModelSource):
    """Environment Canada GEM Global via Open-Meteo."""

    def __init__(self) -> None:
        super().__init__(
            source_name="gem_global",
            model_name="gem_global",
            open_meteo_model="gem_global",
        )


def default_independent_model_sources() -> List[OpenMeteoModelSource]:
    """Independent (non-GFS) Open-Meteo models for ensemble diversity."""
    return [EcmwfIfsSource(), IconGlobalSource(), GemGlobalSource()]
