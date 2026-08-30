#!/usr/bin/env python3
"""Live multi-model diversity report (paper diagnostics, no trading).

Fetches Open-Meteo GFS + ECMWF + ICON + GEM for sample cities and shows:
- daily-high spread across models
- ensemble weight allocation with skill priors + diversity blend

Usage:
  python scripts/model_diversity_report.py
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    from core.forecast_sources.open_meteo_client import OpenMeteoSource
    from core.forecast_sources.open_meteo_models import (
        EcmwfIfsSource,
        IconGlobalSource,
        GemGlobalSource,
    )
    from core.ensemble_builder import EnsembleBuilder
    from core.forecast_sources import SourceForecast
    import yaml

    cities = ["Chicago", "New York", "London", "Tokyo", "Berlin"]
    target = datetime.now(timezone.utc) + timedelta(days=1)
    sources = [
        OpenMeteoSource(),
        EcmwfIfsSource(),
        IconGlobalSource(),
        GemGlobalSource(),
    ]

    print("=== Multi-Model Diversity Report ===")
    print(f"target≈{target.date().isoformat()} (D+1 high °F)\n")

    rows = []
    for city in cities:
        highs = {}
        for src in sources:
            try:
                fc = src.fetch(city, target)
            except Exception as e:
                highs[src.source_name] = f"ERR:{type(e).__name__}"
                continue
            if fc is None:
                highs[src.source_name] = None
            else:
                highs[src.source_name] = round(
                    fc.temperature_max_f
                    if fc.temperature_max_f is not None
                    else fc.temperature_f,
                    1,
                )
        numeric = [v for v in highs.values() if isinstance(v, (int, float))]
        spread = round(max(numeric) - min(numeric), 1) if len(numeric) >= 2 else None
        rows.append({"city": city, "highs_f": highs, "spread_f": spread})
        print(f"{city:12} {highs}  spread={spread}")

    cfg = {}
    weather_yaml = ROOT / "config" / "weather.yaml"
    if weather_yaml.exists():
        cfg = yaml.safe_load(weather_yaml.read_text(encoding="utf-8")) or {}

    builder = EnsembleBuilder(cfg)
    now = datetime.now(timezone.utc)
    demo_forecasts = []
    for src in sources:
        fc = src.fetch("Chicago", target)
        if fc is not None:
            demo_forecasts.append(fc)

    if demo_forecasts:
        gfs = next(
            (f for f in demo_forecasts if f.source_name == "open_meteo"),
            demo_forecasts[0],
        )
        ens = SourceForecast(
            city=gfs.city,
            target_time=gfs.target_time,
            forecast_time=now,
            source_name="open_meteo_ensemble",
            model_name="gfs_ensemble",
            temperature_f=gfs.temperature_f,
            temperature_min_f=gfs.temperature_min_f,
            temperature_max_f=gfs.temperature_max_f,
        )
        demo_forecasts.append(ens)

        weights = builder._compute_weights(demo_forecasts)
        independent_names = {"ecmwf_ifs", "icon_global", "gem_global", "met_norway"}
        n_indep = sum(1 for sf in demo_forecasts if sf.source_name in independent_names)
        ens_share = 0.45 if n_indep >= 2 else (0.65 if n_indep == 1 else 0.85)
        other_share = 1.0 - ens_share
        ens_source = "open_meteo_ensemble"
        other_sum = sum(
            weights[sf.source_name]
            for sf in demo_forecasts
            if sf.source_name != ens_source and sf.source_name in weights
        )
        if other_sum > 0:
            weights[ens_source] = ens_share
            scale = other_share / other_sum
            for sf in demo_forecasts:
                if sf.source_name != ens_source and sf.source_name in weights:
                    weights[sf.source_name] *= scale

        total = sum(weights.values()) or 1.0
        print("\n=== Chicago weight allocation (priors + diversity blend) ===")
        print(f"independent_models={n_indep}  ens_share={ens_share:.0%}")
        for name, w in sorted(weights.items(), key=lambda kv: -kv[1]):
            print(f"  {name:22} {w:6.3f}  ({w / total:5.1%})")

    out = ROOT / "output" / "model_diversity_report.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(
            {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "target_date": target.date().isoformat(),
                "cities": rows,
                "note": "PAPER diagnostics only — no trading.",
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\nWrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
