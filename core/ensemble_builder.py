# =============================================================================
# ENSEMBLE FORECAST BUILDER
# =============================================================================
#
# Combines forecasts from multiple sources into a weighted ensemble.
# Sources with correlated models share weight.
# Disagreement between sources degrades confidence.
#
# ISOLATION:
# - READ-ONLY: No trading, no execution imports
# - Uses forecast_sources package for data
# - Uses weather_probability_model for math
#
# =============================================================================

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Dict, List, Any

from .forecast_sources import SourceForecast, ForecastSourceBase
from .forecast_sources.open_meteo_client import OpenMeteoSource
from .forecast_sources.met_norway_client import MetNorwaySource
from .forecast_sources.openweather_client import OpenWeatherSource
from .forecast_sources.tomorrow_client import TomorrowIoSource
from .weather_probability_model import compute_probability_from_forecast_temp
from .weather_signal import WeatherConfidence

logger = logging.getLogger(__name__)


# =============================================================================
# ENSEMBLE FORECAST DATA MODEL
# =============================================================================

@dataclass
class EnsembleForecast:
    """Result of an ensemble forecast computation."""
    city: str
    target_time: datetime
    source_forecasts: List[SourceForecast]

    # Ensemble temperature (weighted mean of source temperatures)
    ensemble_temperature_f: float
    temperature_spread_f: float  # max - min across sources

    # Source info
    source_count: int
    independent_model_count: int

    # Per-source probabilities
    per_source_probabilities: Dict[str, float]

    # Ensemble probability
    ensemble_mean_probability: float
    ensemble_variance: float
    max_source_deviation: float

    # Confidence adjustment from ensemble disagreement
    confidence_adjustment: str  # "NONE", "DEGRADED_LOW_SOURCES", "DEGRADED_VARIANCE"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "city": self.city,
            "target_time": self.target_time.isoformat(),
            "ensemble_temperature_f": round(self.ensemble_temperature_f, 2),
            "temperature_spread_f": round(self.temperature_spread_f, 2),
            "source_count": self.source_count,
            "independent_model_count": self.independent_model_count,
            "per_source_probabilities": {
                k: round(v, 4) for k, v in self.per_source_probabilities.items()
            },
            "ensemble_mean_probability": round(self.ensemble_mean_probability, 4),
            "ensemble_variance": round(self.ensemble_variance, 6),
            "max_source_deviation": round(self.max_source_deviation, 4),
            "confidence_adjustment": self.confidence_adjustment,
            "sources": [sf.source_name for sf in self.source_forecasts],
        }


# =============================================================================
# ENSEMBLE BUILDER
# =============================================================================

class EnsembleBuilder:
    """
    Builds ensemble forecasts from multiple weather sources.

    - Fetches all available sources in parallel
    - Computes per-source probability using Normal-CDF math
    - Weights: equal, but correlated models share weight
    - Confidence degrades if too few independent sources or high variance
    """

    def __init__(self, config: Dict[str, Any]):
        ensemble_cfg = config.get("ENSEMBLE", {})
        self.enabled = ensemble_cfg.get("ENABLED", True)
        self.variance_threshold = ensemble_cfg.get("VARIANCE_THRESHOLD", 0.15)
        self.min_independent_sources = ensemble_cfg.get("MIN_INDEPENDENT_SOURCES", 2)
        self.source_timeout = ensemble_cfg.get("SOURCE_TIMEOUT_SECONDS", 12)
        self.correlated_models = ensemble_cfg.get("CORRELATED_MODELS", {
            "GFS": ["open_meteo_gfs", "openweather_gfs"],
        })

        # Sigma config for probability computation
        self.base_sigma = config.get("SIGMA_F", 3.5)
        self.sigma_horizon_adjustments = config.get(
            "SIGMA_HORIZON_ADJUSTMENTS",
            {1: 0.8, 2: 0.9, 3: 1.0, 5: 1.2, 7: 1.5, 10: 2.0}
        )

        # Build reverse lookup: model_name -> group_name
        self._model_to_group: Dict[str, str] = {}
        for group, models in self.correlated_models.items():
            for m in models:
                self._model_to_group[m] = group

        # Register all available sources
        self._sources: List[ForecastSourceBase] = [
            OpenMeteoSource(),
            MetNorwaySource(),
            OpenWeatherSource(),
            TomorrowIoSource(),
        ]

    def build(
        self,
        city: str,
        target_time: datetime,
        threshold_f: float,
        event_type: str = "exceeds",
    ) -> Optional[EnsembleForecast]:
        """
        Build an ensemble forecast for a city/threshold.

        Returns None if no sources return data.
        """
        if not self.enabled:
            return None

        # Fetch all sources in parallel
        forecasts = self._fetch_all(city, target_time)

        if not forecasts:
            logger.warning(f"Ensemble: no sources returned data for {city}")
            return None

        # Compute sigma for the horizon
        now = datetime.utcnow()
        target_naive = target_time.replace(tzinfo=None) if target_time.tzinfo else target_time
        hours = max(0, (target_naive - now).total_seconds() / 3600)
        days = hours / 24
        sigma = self._calculate_sigma(days)

        # Compute per-source probabilities
        per_source_probs: Dict[str, float] = {}
        for sf in forecasts:
            prob = compute_probability_from_forecast_temp(
                temperature_f=sf.temperature_f,
                threshold_f=threshold_f,
                sigma=sigma,
                event_type=event_type,
            )
            per_source_probs[sf.source_name] = prob

        # Compute weights (correlated models share weight)
        weights = self._compute_weights(forecasts)

        # Weighted ensemble mean probability
        total_weight = sum(weights.values())
        if total_weight <= 0:
            return None

        ensemble_mean = sum(
            weights[sf.source_name] * per_source_probs[sf.source_name]
            for sf in forecasts
        ) / total_weight

        # Weighted variance
        ensemble_var = sum(
            weights[sf.source_name] * (per_source_probs[sf.source_name] - ensemble_mean) ** 2
            for sf in forecasts
        ) / total_weight

        # Max deviation
        max_dev = max(
            abs(per_source_probs[sf.source_name] - ensemble_mean)
            for sf in forecasts
        )

        # Ensemble temperature (simple weighted mean)
        ensemble_temp = sum(
            weights[sf.source_name] * sf.temperature_f
            for sf in forecasts
        ) / total_weight

        temps = [sf.temperature_f for sf in forecasts]
        temp_spread = max(temps) - min(temps)

        # Count independent models
        independent_count = self._count_independent_models(forecasts)

        # Confidence adjustment
        adjustment = "NONE"
        if independent_count < self.min_independent_sources:
            adjustment = "DEGRADED_LOW_SOURCES"
        elif ensemble_var > self.variance_threshold:
            adjustment = "DEGRADED_VARIANCE"

        return EnsembleForecast(
            city=city,
            target_time=target_time,
            source_forecasts=forecasts,
            ensemble_temperature_f=ensemble_temp,
            temperature_spread_f=temp_spread,
            source_count=len(forecasts),
            independent_model_count=independent_count,
            per_source_probabilities=per_source_probs,
            ensemble_mean_probability=ensemble_mean,
            ensemble_variance=ensemble_var,
            max_source_deviation=max_dev,
            confidence_adjustment=adjustment,
        )

    def _fetch_all(self, city: str, target_time: datetime) -> List[SourceForecast]:
        """Fetch from all available sources in parallel with timeouts."""
        available = [s for s in self._sources if s.is_available()]
        if not available:
            return []

        results: List[SourceForecast] = []

        def _fetch_one(source: ForecastSourceBase) -> Optional[SourceForecast]:
            try:
                return source.fetch(city, target_time, timeout=self.source_timeout)
            except Exception as e:
                logger.debug(f"Ensemble source {source.source_name} failed for {city}: {e}")
                return None

        with ThreadPoolExecutor(max_workers=len(available)) as pool:
            futures = {pool.submit(_fetch_one, s): s for s in available}
            for future in as_completed(futures, timeout=self.source_timeout + 5):
                try:
                    result = future.result(timeout=2)
                    if result is not None:
                        results.append(result)
                except Exception:
                    pass

        logger.debug(
            f"Ensemble fetched {len(results)}/{len(available)} sources for {city}: "
            f"{[r.source_name for r in results]}"
        )
        return results

    def _compute_weights(self, forecasts: List[SourceForecast]) -> Dict[str, float]:
        """
        Compute weights for each source.

        Independent models get weight 1.0.
        Correlated models share weight: each gets 1.0/count_in_group.
        """
        # Group forecasts by correlation group
        group_counts: Dict[str, int] = {}
        source_group: Dict[str, Optional[str]] = {}

        for sf in forecasts:
            group = self._model_to_group.get(sf.model_name)
            source_group[sf.source_name] = group
            if group:
                group_counts[group] = group_counts.get(group, 0) + 1

        weights: Dict[str, float] = {}
        for sf in forecasts:
            group = source_group[sf.source_name]
            if group and group_counts.get(group, 0) > 1:
                weights[sf.source_name] = 1.0 / group_counts[group]
            else:
                weights[sf.source_name] = 1.0

        return weights

    def _count_independent_models(self, forecasts: List[SourceForecast]) -> int:
        """Count how many independent model families are represented."""
        seen_groups: set = set()
        independent = 0

        for sf in forecasts:
            group = self._model_to_group.get(sf.model_name)
            if group:
                if group not in seen_groups:
                    seen_groups.add(group)
                    independent += 1
            else:
                # Not in any correlation group = independent
                independent += 1

        return independent

    def _calculate_sigma(self, days_to_resolution: float) -> float:
        """Calculate sigma adjusted for forecast horizon."""
        adjustment = 1.0
        sorted_keys = sorted(self.sigma_horizon_adjustments.keys())
        for key in sorted_keys:
            if days_to_resolution >= key:
                adjustment = self.sigma_horizon_adjustments[key]
            else:
                break
        return self.base_sigma * adjustment


def degrade_confidence(
    horizon_confidence: WeatherConfidence,
    ensemble_adjustment: str,
) -> WeatherConfidence:
    """
    Apply ensemble-based confidence degradation.

    Rules:
    1. If DEGRADED_LOW_SOURCES -> force LOW
    2. If DEGRADED_VARIANCE -> one step down (HIGH->MEDIUM, MEDIUM->LOW)
    3. Return min(horizon, adjusted)
    """
    if ensemble_adjustment == "DEGRADED_LOW_SOURCES":
        return WeatherConfidence.LOW

    if ensemble_adjustment == "DEGRADED_VARIANCE":
        # One step down
        if horizon_confidence == WeatherConfidence.HIGH:
            return WeatherConfidence.MEDIUM
        elif horizon_confidence == WeatherConfidence.MEDIUM:
            return WeatherConfidence.LOW
        else:
            return WeatherConfidence.LOW

    # NONE - no degradation
    return horizon_confidence
