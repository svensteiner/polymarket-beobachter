# =============================================================================
# TOMORROW.IO FORECAST SOURCE (requires API key)
# =============================================================================
#
# Wraps existing Tomorrow.io logic into ForecastSourceBase interface.
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


class TomorrowIoSource(ForecastSourceBase):
    """Tomorrow.io API forecast source (proprietary model, requires key)."""

    @property
    def source_name(self) -> str:
        return "tomorrow_io"

    @property
    def model_name(self) -> str:
        return "tomorrow_io_proprietary"

    @property
    def requires_api_key(self) -> bool:
        return True

    def is_available(self) -> bool:
        return bool(os.environ.get("TOMORROW_IO_API_KEY", ""))

    def fetch(self, city: str, target_time: datetime, timeout: int = 12) -> Optional[SourceForecast]:
        api_key = os.environ.get("TOMORROW_IO_API_KEY", "")
        if not api_key:
            return None

        coords = get_coords(city)
        if coords is None:
            return None

        lat, lon = coords
        url = (
            f"https://api.tomorrow.io/v4/weather/forecast"
            f"?location={lat},{lon}"
            f"&apikey={api_key}"
            f"&units=imperial"
        )

        data = api_get(url, timeout=timeout)
        if data is None:
            return None

        try:
            daily = data.get("timelines", {}).get("daily", [])
            if not daily:
                return None

            target_naive = target_time.replace(tzinfo=None) if target_time.tzinfo else target_time
            best = None
            best_diff = float("inf")

            for day in daily:
                time_str = day.get("time", "")
                try:
                    day_time = datetime.fromisoformat(time_str.replace("Z", "+00:00")).replace(tzinfo=None)
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

            now = datetime.now(timezone.utc)
            horizon_hours = (target_time - now).total_seconds() / 3600 if target_time.tzinfo else \
                (target_naive - datetime.utcnow()).total_seconds() / 3600

            # Wind speed from Tomorrow.io (already imperial = mph)
            wind_speed = values.get("windSpeedAvg")

            return SourceForecast(
                city=city,
                target_time=target_time,
                forecast_time=now,
                source_name=self.source_name,
                model_name=self.model_name,
                temperature_f=float(temp_avg),
                temperature_min_f=float(temp_min) if temp_min is not None else None,
                temperature_max_f=float(temp_max) if temp_max is not None else None,
                wind_speed_mph=float(wind_speed) if wind_speed is not None else None,
                forecast_horizon_hours=max(0, horizon_hours),
            )
        except Exception as e:
            logger.debug(f"Tomorrow.io parse error for {city}: {e}")
            return None
