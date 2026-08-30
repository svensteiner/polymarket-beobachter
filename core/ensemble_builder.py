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
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Dict, List, Any

from .forecast_sources import SourceForecast, ForecastSourceBase
from .forecast_sources.open_meteo_client import OpenMeteoSource
from .forecast_sources.open_meteo_ensemble import (
    OpenMeteoEnsembleSource,
    compute_ensemble_probability,
)
from .forecast_sources.open_meteo_models import (
    EcmwfIfsSource,
    IconGlobalSource,
    GemGlobalSource,
)
from .forecast_sources.met_norway_client import MetNorwaySource
from .forecast_sources.openweather_client import OpenWeatherSource
from .forecast_sources.tomorrow_client import TomorrowIoSource
from .weather_probability_model import compute_probability_from_forecast_temp
from .weather_signal import WeatherConfidence
from .self_healer import validate_forecast_temperature, validate_ensemble_members

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

    # Forecast-method instrumentation (2026-06-11): enables honest
    # raw-ensemble-vs-market measurement. probability_method = which engine
    # produced the probability; raw_member_probability = the pre-shrinkage
    # 31-member count probability; member_daily_highs_f = the raw member highs.
    probability_method: str = "gaussian_cdf"
    raw_member_probability: Optional[float] = None
    member_daily_highs_f: Optional[list] = None

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
            "probability_method": self.probability_method,
            "raw_member_probability": (
                round(self.raw_member_probability, 4)
                if self.raw_member_probability is not None else None
            ),
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

        # Register all available sources.
        # Order: GFS ensemble (member-counting) + independent globals (ECMWF/ICON/GEM)
        # BEFORE commercial GFS clones, so diversity is real rather than GFS-echo.
        self._sources: List[ForecastSourceBase] = [
            OpenMeteoEnsembleSource(),
            OpenMeteoSource(),
            EcmwfIfsSource(),
            IconGlobalSource(),
            GemGlobalSource(),
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
        threshold_high_f: Optional[float] = None,
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
        # PRIORITY: GFS Ensemble member-counting > Normal-CDF fallback
        per_source_probs: Dict[str, float] = {}
        ensemble_member_prob: Optional[float] = None
        raw_member_highs: Optional[list] = None

        for sf in forecasts:
            # Try ensemble member counting first (much better calibrated)
            if sf.source_name == "open_meteo_ensemble" and hasattr(sf, "ensemble_member_temps"):
                ens_prob = compute_ensemble_probability(
                    forecast=sf,
                    threshold_f=threshold_f,
                    event_type=event_type,
                    threshold_high_f=threshold_high_f,
                )
                if ens_prob is not None:
                    per_source_probs[sf.source_name] = ens_prob
                    ensemble_member_prob = ens_prob
                    raw_member_highs = list(getattr(sf, "member_daily_highs", None) or [])
                    member_count = getattr(sf, "ensemble_member_count", 0)
                    logger.info(
                        f"Ensemble member-counting: P={ens_prob:.4f} "
                        f"({member_count} members, {event_type} {threshold_f}°F)"
                    )
                    continue

            # Fallback: Normal-CDF probability
            # Polymarket "highest temperature" markets → use daily max, not point forecast.
            # A point forecast at the target hour (often midnight) gives the wrong
            # temperature: London midnight=47°F but daily high=54°F → CDF at 47°F
            # massively overestimates P([46-48°F]) ≈22% vs correct ≈2%.
            if event_type in ("exceeds", "between_range", "at_or_above"):
                temp_for_cdf = sf.temperature_max_f if sf.temperature_max_f is not None else sf.temperature_f
            elif event_type in ("below", "at_or_below"):
                temp_for_cdf = sf.temperature_min_f if sf.temperature_min_f is not None else sf.temperature_f
            else:
                temp_for_cdf = sf.temperature_f
            prob = compute_probability_from_forecast_temp(
                temperature_f=temp_for_cdf,
                threshold_f=threshold_f,
                sigma=sigma,
                event_type=event_type,
                threshold_high_f=threshold_high_f,
            )
            per_source_probs[sf.source_name] = prob

        # Compute weights (correlated models share weight)
        weights = self._compute_weights(forecasts)

        # If we have GFS ensemble member-counting probability, use it directly
        # The 31-member counting is fundamentally more accurate than Normal-CDF
        # because it counts daily highs across ensemble members (= what Polymarket asks)
        # while Normal-CDF computes probability at a single hour (= wrong question)
        if ensemble_member_prob is not None:
            ens_source = "open_meteo_ensemble"
            # Independent NWP models must keep real voice. Hard 85% GFS-ens monopoly
            # drowned ECMWF/ICON/GEM after we added them. Soften with diversity.
            independent_names = {
                "ecmwf_ifs", "icon_global", "gem_global", "met_norway",
            }
            n_indep = sum(1 for sf in forecasts if sf.source_name in independent_names)
            if n_indep >= 2:
                ens_share = 0.45  # diversity mode
            elif n_indep == 1:
                ens_share = 0.65
            else:
                ens_share = 0.85  # legacy: only GFS family present
            other_share = 1.0 - ens_share
            other_weight_sum = sum(
                weights[sf.source_name] for sf in forecasts
                if sf.source_name != ens_source and sf.source_name in weights
            )
            if other_weight_sum > 0:
                weights[ens_source] = ens_share
                scale_factor = other_share / other_weight_sum
                for sf in forecasts:
                    if sf.source_name != ens_source and sf.source_name in weights:
                        weights[sf.source_name] *= scale_factor
            else:
                weights[ens_source] = 1.0

        # Weighted ensemble mean probability
        total_weight = sum(weights.values())
        if total_weight <= 0:
            return None

        ensemble_mean = sum(
            weights[sf.source_name] * per_source_probs[sf.source_name]
            for sf in forecasts
        ) / total_weight

        # Weighted variance
        # When ensemble member-counting is available, compute variance from
        # the ensemble's internal spread (members disagreeing with each other)
        # rather than from CDF sources that answer a different question
        if ensemble_member_prob is not None:
            ens_source_obj = next(
                (sf for sf in forecasts if sf.source_name == "open_meteo_ensemble"),
                None
            )
            if ens_source_obj is not None:
                daily_highs = getattr(ens_source_obj, "member_daily_highs", [])
                if daily_highs and len(daily_highs) >= 5:
                    # Internal ensemble variance: how much do members disagree?
                    # Use probability variance from binomial: p*(1-p)/n
                    # This is the natural uncertainty of member-counting
                    p = ensemble_member_prob
                    n = len(daily_highs)
                    ensemble_var = p * (1 - p) / n
                else:
                    ensemble_var = 0.0
            else:
                ensemble_var = 0.0
        else:
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
            probability_method=(
                "ensemble_member_counting" if ensemble_member_prob is not None
                else "gaussian_cdf"
            ),
            raw_member_probability=ensemble_member_prob,
            member_daily_highs_f=raw_member_highs,
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
                        # SELF-HEAL: Validate forecast temperature before accepting
                        valid, reason = validate_forecast_temperature(result.temperature_f, city)
                        if not valid:
                            logger.warning(
                                f"SELF-HEAL: Rejected {result.source_name} for {city}: {reason}"
                            )
                            continue
                        # Validate ensemble member temps if present
                        member_temps = getattr(result, "ensemble_member_temps", None)
                        if member_temps:
                            valid_e, reason_e = validate_ensemble_members(member_temps, city)
                            if not valid_e:
                                logger.warning(
                                    f"SELF-HEAL: Rejected ensemble members for {city}: {reason_e}"
                                )
                                continue
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

        Independent models get weight 1.0 (or learned Log-Score weight).
        Correlated models share weight: each gets 1.0/count_in_group.

        Feature 10: Bayesian Log Score Gewichte werden aus data/model_weights.json
        geladen und mit den Korrelations-Gewichten multipliziert.
        """
        # Feature 10: Lade gelernte Modell-Gewichte
        try:
            from .model_weights import get_normalized_weights
            learned_weights = get_normalized_weights()
        except Exception:
            learned_weights = {}

        # Group forecasts by correlation group
        group_counts: Dict[str, int] = {}
        source_group: Dict[str, Optional[str]] = {}

        for sf in forecasts:
            group = (
                self._model_to_group.get(sf.model_name)
                or self._model_to_group.get(sf.source_name)
            )
            source_group[sf.source_name] = group
            if group:
                group_counts[group] = group_counts.get(group, 0) + 1

        weights: Dict[str, float] = {}
        for sf in forecasts:
            group = source_group[sf.source_name]
            if group and group_counts.get(group, 0) > 1:
                base_weight = 1.0 / group_counts[group]
            else:
                base_weight = 1.0

            # Multipliziere mit gelerntem Gewicht (source_name ODER model_name)
            from .model_weights import resolve_learned_weight
            learned = resolve_learned_weight(
                learned_weights, sf.source_name, sf.model_name
            )
            weights[sf.source_name] = base_weight * learned

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
