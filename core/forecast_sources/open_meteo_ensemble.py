# =============================================================================
# OPEN-METEO GFS ENSEMBLE FORECAST SOURCE (31 Members, no API key required)
# =============================================================================
#
# Uses the Open-Meteo Ensemble API to fetch 31 GFS ensemble members.
# Instead of assuming a Normal distribution, probability is computed by
# counting the fraction of members above/below the market threshold.
#
# This is the same approach used by profitable weather bots on Polymarket
# (e.g. suislanchez/polymarket-kalshi-weather-bot: $1.8k+ profit).
#
# API: https://ensemble-api.open-meteo.com/v1/ensemble
# Model: gfs025 (GFS 0.25° resolution, 31 members, 10-day forecast)
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

# Number of GFS ensemble members (control run + 30 perturbations)
GFS_ENSEMBLE_MEMBERS = 31


def _celsius_to_fahrenheit(c: float) -> float:
    return c * 9.0 / 5.0 + 32.0


class OpenMeteoEnsembleSource(ForecastSourceBase):
    """
    Open-Meteo GFS Ensemble API source.

    Fetches 31 individual GFS ensemble members and provides:
    - Per-member temperatures for probabilistic counting
    - More accurate probability estimation than Normal-CDF
    """

    @property
    def source_name(self) -> str:
        return "open_meteo_ensemble"

    @property
    def model_name(self) -> str:
        return "gfs_ensemble"

    @property
    def requires_api_key(self) -> bool:
        return False

    def fetch(self, city: str, target_time: datetime, timeout: int = 15) -> Optional[SourceForecast]:
        coords = get_coords(city)
        if coords is None:
            logger.debug(f"GFS-Ensemble: no coords for {city}")
            return None

        lat, lon = coords
        url = (
            f"https://ensemble-api.open-meteo.com/v1/ensemble"
            f"?latitude={lat}&longitude={lon}"
            f"&hourly=temperature_2m"
            f"&models=gfs025"
            f"&forecast_days=10"
            f"&temperature_unit=fahrenheit"
            f"&timezone=UTC"
        )

        data = api_get(url, timeout=timeout)
        if data is None:
            logger.debug(f"GFS-Ensemble: API returned None for {city}")
            return None

        try:
            hourly = data.get("hourly", {})
            times = hourly.get("time", [])

            if not times:
                return None

            # Parse time array
            parsed_times: List[datetime] = []
            for time_str in times:
                try:
                    parsed_times.append(datetime.fromisoformat(time_str).replace(tzinfo=None))
                except (ValueError, TypeError):
                    parsed_times.append(None)

            # Find index closest to target_time
            target_naive = target_time.replace(tzinfo=None) if target_time.tzinfo else target_time
            best_idx = 0
            best_diff = float("inf")
            for i, t in enumerate(parsed_times):
                if t is None:
                    continue
                diff = abs((t - target_naive).total_seconds())
                if diff < best_diff:
                    best_diff = diff
                    best_idx = i

            # Collect all ensemble member temperatures at the best time index
            # Control run: temperature_2m, Members: temperature_2m_member01..30
            member_temps_at_target: List[float] = []

            # Control run
            control_temps = hourly.get("temperature_2m", [])
            if best_idx < len(control_temps) and control_temps[best_idx] is not None:
                member_temps_at_target.append(float(control_temps[best_idx]))

            # Perturbation members 01..30
            for m in range(1, 31):
                key = f"temperature_2m_member{m:02d}"
                member_temps = hourly.get(key, [])
                if best_idx < len(member_temps) and member_temps[best_idx] is not None:
                    member_temps_at_target.append(float(member_temps[best_idx]))

            if len(member_temps_at_target) < 5:
                logger.debug(f"GFS-Ensemble: only {len(member_temps_at_target)} members for {city}")
                return None

            # Also collect daily high/low across all members for the target day
            target_date = target_naive.date()
            all_day_temps: List[float] = []
            for m_idx in range(-1, 30):
                if m_idx == -1:
                    key = "temperature_2m"
                else:
                    key = f"temperature_2m_member{m_idx + 1:02d}"
                member_temps = hourly.get(key, [])
                for i, t in enumerate(parsed_times):
                    if t is not None and t.date() == target_date:
                        if i < len(member_temps) and member_temps[i] is not None:
                            all_day_temps.append(float(member_temps[i]))

            # Collect daily HIGH per member for "highest temperature" markets
            member_daily_highs: List[float] = []
            for m_idx in range(-1, 30):
                if m_idx == -1:
                    key = "temperature_2m"
                else:
                    key = f"temperature_2m_member{m_idx + 1:02d}"
                member_temps = hourly.get(key, [])
                day_temps_for_member = []
                for i, t in enumerate(parsed_times):
                    if t is not None and t.date() == target_date:
                        if i < len(member_temps) and member_temps[i] is not None:
                            day_temps_for_member.append(float(member_temps[i]))
                if day_temps_for_member:
                    member_daily_highs.append(max(day_temps_for_member))

            # Collect daily LOW per member for "lowest temperature" markets
            member_daily_lows: List[float] = []
            for m_idx in range(-1, 30):
                if m_idx == -1:
                    key = "temperature_2m"
                else:
                    key = f"temperature_2m_member{m_idx + 1:02d}"
                member_temps = hourly.get(key, [])
                day_temps_for_member = []
                for i, t in enumerate(parsed_times):
                    if t is not None and t.date() == target_date:
                        if i < len(member_temps) and member_temps[i] is not None:
                            day_temps_for_member.append(float(member_temps[i]))
                if day_temps_for_member:
                    member_daily_lows.append(min(day_temps_for_member))

            # Mean temperature across members (for SourceForecast)
            mean_temp = sum(member_temps_at_target) / len(member_temps_at_target)

            # Build hourly temps from control run for compatibility
            hourly_temps: List[Tuple[datetime, float]] = []
            for i, t in enumerate(parsed_times):
                if t is not None and i < len(control_temps) and control_temps[i] is not None:
                    hourly_temps.append((t, float(control_temps[i])))

            # Min/max from all members on target day
            temp_min = min(all_day_temps) if all_day_temps else None
            temp_max = max(all_day_temps) if all_day_temps else None

            now = datetime.now(timezone.utc)
            horizon_hours = (target_time - now).total_seconds() / 3600 if target_time.tzinfo else \
                (target_naive - datetime.utcnow()).total_seconds() / 3600

            forecast = SourceForecast(
                city=city,
                target_time=target_time,
                forecast_time=now,
                source_name=self.source_name,
                model_name=self.model_name,
                temperature_f=mean_temp,
                temperature_min_f=temp_min,
                temperature_max_f=temp_max,
                hourly_temperatures=hourly_temps,
                precipitation_probability=None,
                wind_speed_mph=None,
                forecast_horizon_hours=max(0, horizon_hours),
            )

            # Attach ensemble-specific data as extra attributes
            forecast.ensemble_member_temps = member_temps_at_target
            forecast.ensemble_member_count = len(member_temps_at_target)
            forecast.member_daily_highs = member_daily_highs
            forecast.member_daily_lows = member_daily_lows

            logger.info(
                f"GFS-Ensemble: {city} | {len(member_temps_at_target)} members | "
                f"mean={mean_temp:.1f}°F | spread={max(member_temps_at_target) - min(member_temps_at_target):.1f}°F | "
                f"daily_highs={len(member_daily_highs)} members"
            )

            return forecast

        except Exception as e:
            logger.warning(f"GFS-Ensemble parse error for {city}: {e}")
            return None


def compute_ensemble_probability(
    forecast: SourceForecast,
    threshold_f: float,
    event_type: str = "exceeds",
    threshold_high_f: Optional[float] = None,
) -> Optional[float]:
    """
    Compute probability by counting ensemble members.

    For "highest temperature" markets (most Polymarket weather markets),
    uses member_daily_highs instead of point temperatures.

    Args:
        forecast: SourceForecast with ensemble data attached
        threshold_f: Temperature threshold in Fahrenheit
        event_type: "exceeds", "below", "at_or_below", "at_or_above", "between_range"
        threshold_high_f: Upper bound for "between_range" markets

    Returns:
        Probability (0.0-1.0) or None if no ensemble data
    """
    # Check which temperature set to use
    # For daily high/low markets, use the daily aggregated temps
    daily_highs = getattr(forecast, "member_daily_highs", None)
    point_temps = getattr(forecast, "ensemble_member_temps", None)

    if point_temps is None or len(point_temps) < 5:
        return None

    # Determine which temperature set to use based on event_type
    # Most Polymarket markets are about "highest temperature" or "lowest temperature"
    if event_type in ("exceeds", "at_or_above"):
        # "Will highest temp exceed X?" -> use daily highs
        temps = daily_highs if daily_highs and len(daily_highs) >= 5 else point_temps
    elif event_type in ("below", "at_or_below"):
        # "Will highest temp be X or below?" -> use daily highs
        # (Polymarket asks about the daily HIGH being at or below threshold)
        temps = daily_highs if daily_highs and len(daily_highs) >= 5 else point_temps
    elif event_type == "between_range":
        # "Will highest temp be between X-Y?" -> use daily highs
        # Polymarket asks about the daily HIGH falling in the range
        temps = daily_highs if daily_highs and len(daily_highs) >= 5 else point_temps
    else:
        temps = point_temps

    n = len(temps)

    if event_type in ("exceeds", "at_or_above"):
        count = sum(1 for t in temps if t > threshold_f)
    elif event_type in ("below", "at_or_below"):
        # "below" in Polymarket context means: daily high < threshold
        # We use < (strict) as the default, matching Polymarket resolution
        count = sum(1 for t in temps if t < threshold_f)
    elif event_type == "between_range":
        if threshold_high_f is None:
            return None
        count = sum(1 for t in temps if threshold_f <= t <= threshold_high_f)
    else:
        # Fallback
        count = sum(1 for t in temps if t > threshold_f)

    # Laplace smoothing: verhindert P=0.0 und P=1.0
    # Bei 31 Members: P=0 wird zu P=0.016, P=1 wird zu P=0.984
    # Das ist realistischer – kein Wetter-Event hat exakt 0% oder 100% Chance
    probability = (count + 0.5) / (n + 1.0)

    logger.debug(
        f"Ensemble probability: {count}/{n} members {event_type} {threshold_f}°F "
        f"-> P={probability:.4f} (smoothed) | temps range [{min(temps):.1f}, {max(temps):.1f}]"
    )

    return probability
