# =============================================================================
# MET NORWAY (Yr) FORECAST SOURCE (no API key required)
# =============================================================================
#
# MET Norway Yr API provides free weather forecasts globally.
# https://api.met.no/weatherapi/locationforecast/2.0/documentation
#
# IMPORTANT: Requires User-Agent header per MET TOS.
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


class MetNorwaySource(ForecastSourceBase):
    """MET Norway Yr API forecast source (free, no key, requires User-Agent)."""

    @property
    def source_name(self) -> str:
        return "met_norway"

    @property
    def model_name(self) -> str:
        return "met_norway_yr"

    @property
    def requires_api_key(self) -> bool:
        return False

    def fetch(self, city: str, target_time: datetime, timeout: int = 12) -> Optional[SourceForecast]:
        coords = get_coords(city)
        if coords is None:
            logger.debug(f"MET Norway: no coords for {city}")
            return None

        lat, lon = coords
        url = (
            f"https://api.met.no/weatherapi/locationforecast/2.0/compact"
            f"?lat={lat:.4f}&lon={lon:.4f}"
        )

        # MET TOS requires identifying User-Agent
        headers = {
            "User-Agent": "PolymarketBeobachter/2.0 github.com/polymarket-beobachter",
        }

        data = api_get(url, headers=headers, timeout=timeout)
        if data is None:
            return None

        try:
            timeseries = data.get("properties", {}).get("timeseries", [])
            if not timeseries:
                return None

            target_naive = target_time.replace(tzinfo=None) if target_time.tzinfo else target_time

            # Parse all timeseries entries
            hourly_temps: List[Tuple[datetime, float]] = []
            best_entry = None
            best_diff = float("inf")

            for entry in timeseries:
                time_str = entry.get("time", "")
                try:
                    entry_time = datetime.fromisoformat(time_str.replace("Z", "+00:00")).replace(tzinfo=None)
                except (ValueError, TypeError):
                    continue

                instant = entry.get("data", {}).get("instant", {}).get("details", {})
                temp_c = instant.get("air_temperature")
                if temp_c is None:
                    continue

                temp_f = _celsius_to_fahrenheit(float(temp_c))
                hourly_temps.append((entry_time, temp_f))

                diff = abs((entry_time - target_naive).total_seconds())
                if diff < best_diff:
                    best_diff = diff
                    best_entry = entry
                    best_temp_f = temp_f

            if best_entry is None:
                return None

            # Collect min/max for target day
            target_date = target_naive.date()
            day_temps = [temp for t, temp in hourly_temps if t.date() == target_date]
            temp_min = min(day_temps) if day_temps else None
            temp_max = max(day_temps) if day_temps else None

            # Get wind speed (m/s -> mph)
            instant = best_entry.get("data", {}).get("instant", {}).get("details", {})
            wind_speed_ms = instant.get("wind_speed")
            wind_speed_mph = float(wind_speed_ms) * 2.23694 if wind_speed_ms is not None else None

            # Get precipitation probability from next_1_hours or next_6_hours
            precip_prob = None
            for period_key in ("next_1_hours", "next_6_hours"):
                period_data = best_entry.get("data", {}).get(period_key, {}).get("details", {})
                pp = period_data.get("precipitation_probability") or period_data.get("probability_of_precipitation")
                if pp is not None:
                    precip_prob = float(pp)
                    break

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
                wind_speed_mph=wind_speed_mph,
                forecast_horizon_hours=max(0, horizon_hours),
            )
        except Exception as e:
            logger.debug(f"MET Norway parse error for {city}: {e}")
            return None
