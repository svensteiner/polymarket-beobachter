"""Unit tests for Open-Meteo multi-model sources (ECMWF / ICON / GEM)."""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from unittest.mock import patch

import pytest

from core.forecast_sources.open_meteo_models import (
    EcmwfIfsSource,
    IconGlobalSource,
    GemGlobalSource,
    OpenMeteoModelSource,
    default_independent_model_sources,
)


SAMPLE_PAYLOAD = {
    "hourly": {
        "time": [
            "2026-08-31T00:00",
            "2026-08-31T12:00",
            "2026-08-31T18:00",
        ],
        "temperature_2m": [20.0, 28.0, 26.0],
        "precipitation_probability": [10, 20, 15],
        "wind_speed_10m": [5.0, 8.0, 6.0],
    },
    "daily": {
        "time": ["2026-08-31"],
        "temperature_2m_max": [29.0],
        "temperature_2m_min": [19.0],
    },
}


class TestOpenMeteoModelSource:
    def test_source_metadata(self):
        ecmwf = EcmwfIfsSource()
        assert ecmwf.source_name == "ecmwf_ifs"
        assert ecmwf.model_name == "ecmwf_ifs025"
        assert ecmwf.requires_api_key is False

        icon = IconGlobalSource()
        assert icon.source_name == "icon_global"
        assert icon.model_name == "icon_global"

        gem = GemGlobalSource()
        assert gem.source_name == "gem_global"
        assert gem.model_name == "gem_global"

    def test_default_independent_sources(self):
        sources = default_independent_model_sources()
        assert len(sources) == 3
        names = {s.source_name for s in sources}
        assert names == {"ecmwf_ifs", "icon_global", "gem_global"}

    def test_fetch_parses_hourly_and_daily(self):
        src = EcmwfIfsSource()
        target = datetime(2026, 8, 31, 12, 0, tzinfo=timezone.utc)
        with patch("core.forecast_sources.open_meteo_models.get_coords", return_value=(40.71, -74.01)), \
             patch("core.forecast_sources.open_meteo_models.api_get", return_value=SAMPLE_PAYLOAD):
            result = src.fetch("New York", target)

        assert result is not None
        assert result.source_name == "ecmwf_ifs"
        assert result.model_name == "ecmwf_ifs025"
        # 28°C at 12:00 closest to target → 82.4°F
        assert result.temperature_f == pytest.approx(28 * 9 / 5 + 32, abs=0.1)
        # daily max 29°C → 84.2°F preferred over hourly max
        assert result.temperature_max_f == pytest.approx(29 * 9 / 5 + 32, abs=0.1)
        assert result.temperature_min_f == pytest.approx(19 * 9 / 5 + 32, abs=0.1)

    def test_fetch_returns_none_without_coords(self):
        src = IconGlobalSource()
        with patch("core.forecast_sources.open_meteo_models.get_coords", return_value=None):
            assert src.fetch("Atlantis", datetime.now(timezone.utc)) is None

    def test_fetch_returns_none_on_empty_payload(self):
        src = GemGlobalSource()
        with patch("core.forecast_sources.open_meteo_models.get_coords", return_value=(40.71, -74.01)), \
             patch("core.forecast_sources.open_meteo_models.api_get", return_value={"hourly": {}}):
            assert src.fetch("New York", datetime.now(timezone.utc)) is None

    def test_url_contains_model_id(self):
        src = EcmwfIfsSource()
        captured = {}

        def fake_api_get(url, timeout=12):
            captured["url"] = url
            return SAMPLE_PAYLOAD

        with patch("core.forecast_sources.open_meteo_models.get_coords", return_value=(40.71, -74.01)), \
             patch("core.forecast_sources.open_meteo_models.api_get", side_effect=fake_api_get):
            src.fetch("New York", datetime(2026, 8, 31, 12, tzinfo=timezone.utc))

        assert "models=ecmwf_ifs025" in captured["url"]


class TestEnsembleWiresIndependentModels:
    def test_ensemble_builder_registers_independent_models(self):
        from core.ensemble_builder import EnsembleBuilder

        builder = EnsembleBuilder({})
        names = [s.source_name for s in builder._sources]
        assert "ecmwf_ifs" in names
        assert "icon_global" in names
        assert "gem_global" in names
        # Independent models should appear before commercial GFS clones
        assert names.index("ecmwf_ifs") < names.index("openweather")
        assert names.index("icon_global") < names.index("tomorrow_io")
