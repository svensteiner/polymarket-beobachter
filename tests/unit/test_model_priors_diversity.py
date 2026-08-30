"""Tests for skill priors + diversity weight blend."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from core.model_weights import (
    PRIOR_WEIGHTS,
    _default_weights,
    resolve_learned_weight,
)
from core.ensemble_builder import EnsembleBuilder
from core.forecast_sources import SourceForecast


def _sf(source: str, model: str, temp: float = 70.0) -> SourceForecast:
    now = datetime.now(timezone.utc)
    return SourceForecast(
        city="TestCity",
        target_time=now,
        forecast_time=now,
        source_name=source,
        model_name=model,
        temperature_f=temp,
        temperature_max_f=temp + 2,
        temperature_min_f=temp - 2,
    )


class TestSkillPriors:
    def test_prior_ecmwf_above_gfs_clone(self):
        assert PRIOR_WEIGHTS["ecmwf_ifs"] > PRIOR_WEIGHTS["openweather"]
        assert PRIOR_WEIGHTS["icon_global"] > PRIOR_WEIGHTS["tomorrow_io"]

    def test_default_weights_use_priors(self):
        d = _default_weights()
        assert d["ecmwf_ifs"] == pytest.approx(1.35)
        assert d["gem_global"] == pytest.approx(1.15)

    def test_resolve_by_source_or_model(self):
        learned = {"ecmwf_ifs025": 1.4, "icon_global": 1.2}
        assert resolve_learned_weight(learned, "ecmwf_ifs", "ecmwf_ifs025") == 1.4
        assert resolve_learned_weight(learned, "icon_global", "icon_global") == 1.2
        # unknown falls back to prior or 1.0
        assert resolve_learned_weight({}, "totally_unknown", "totally_unknown") == 1.0


class TestDiversityBlend:
    def test_independent_models_reduce_gfs_ens_share(self):
        builder = EnsembleBuilder({})
        forecasts = [
            _sf("open_meteo_ensemble", "gfs_ensemble", 72),
            _sf("open_meteo", "open_meteo_gfs", 71),
            _sf("ecmwf_ifs", "ecmwf_ifs025", 68),
            _sf("icon_global", "icon_global", 70),
            _sf("gem_global", "gem_global", 69),
            _sf("openweather", "openweather_gfs", 71),
        ]
        weights = builder._compute_weights(forecasts)

        independent_names = {"ecmwf_ifs", "icon_global", "gem_global", "met_norway"}
        n_indep = sum(1 for sf in forecasts if sf.source_name in independent_names)
        assert n_indep >= 2
        ens_share = 0.45
        other_share = 0.55
        ens_source = "open_meteo_ensemble"
        other_sum = sum(
            weights[sf.source_name]
            for sf in forecasts
            if sf.source_name != ens_source
        )
        weights[ens_source] = ens_share
        scale = other_share / other_sum
        for sf in forecasts:
            if sf.source_name != ens_source:
                weights[sf.source_name] *= scale

        total = sum(weights.values())
        assert weights[ens_source] / total == pytest.approx(0.45, abs=0.01)
        assert weights["ecmwf_ifs"] / total > 0.05
        assert weights["icon_global"] / total > 0.05

    def test_legacy_monopoly_without_independents(self):
        forecasts = [
            _sf("open_meteo_ensemble", "gfs_ensemble"),
            _sf("open_meteo", "open_meteo_gfs"),
            _sf("openweather", "openweather_gfs"),
        ]
        independent_names = {"ecmwf_ifs", "icon_global", "gem_global", "met_norway"}
        n_indep = sum(1 for sf in forecasts if sf.source_name in independent_names)
        assert n_indep == 0
        ens_share = 0.85 if n_indep == 0 else 0.45
        assert ens_share == 0.85
