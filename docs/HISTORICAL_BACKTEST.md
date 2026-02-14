# Historical Weather Backtest

## Overview

The historical weather backtest evaluates whether the weather probability model is better calibrated than baseline alternatives using **historical weather data** (not live Polymarket markets).

**Core Question**: Is our Normal distribution model with forecast-derived probabilities better calibrated than naive baselines?

## Quick Start

```python
from datetime import date
from backtest import run_historical_backtest, generate_backtest_report

# Run backtest
result = run_historical_backtest(
    cities=["new york", "chicago", "miami"],
    start_date=date(2024, 1, 1),
    end_date=date(2024, 12, 31),
    forecast_horizons=[1, 3, 7],
)

# View summary
print(result.summary())

# Generate full report
report = generate_backtest_report(result)
print(report)
```

## Architecture

```
backtest/
├── __init__.py                    # Module exports
├── historical_weather_loader.py   # Load historical NOAA data
├── synthetic_market_generator.py  # Create hypothetical threshold events
├── backtest_runner.py             # Orchestrate backtest
└── metrics.py                     # Backtest-specific analysis
```

## Data Sources

### 1. Local CSV Files (Recommended)

Place CSV files in `data/historical/` with the following format:

```csv
date,city,high,low
2024-01-01,new york,45,32
2024-01-02,new york,48,35
```

**Supported columns:**
- `date`: Date in ISO format (YYYY-MM-DD), US format (MM/DD/YYYY), or compact (YYYYMMDD)
- `city`: City name (case-insensitive)
- `high` or `tmax`: Daily high temperature in Fahrenheit
- `low` or `tmin`: Daily low temperature in Fahrenheit

### 2. NOAA Climate Data Online API

If no local data exists, the loader will attempt to fetch from NOAA's CDO API.

**Setup:**
1. Request a free API token from https://www.ncdc.noaa.gov/cdo-web/token
2. Set the environment variable: `NOAA_CDO_TOKEN=your_token_here`

## How It Works

### 1. Load Historical Data

The `HistoricalWeatherLoader` reads temperature observations:

```python
from backtest import HistoricalWeatherLoader
from datetime import date

loader = HistoricalWeatherLoader(data_dir="data/historical")
observations = loader.load_observations(
    city="new york",
    start_date=date(2024, 1, 1),
    end_date=date(2024, 12, 31),
)
```

### 2. Generate Synthetic Markets

The `SyntheticMarketGenerator` creates hypothetical threshold events:

```python
from backtest import SyntheticMarketGenerator

generator = SyntheticMarketGenerator()
markets = generator.generate_markets(
    observations,
    thresholds={
        "new york": {
            "high": [80, 85, 90, 95],  # "Did high exceed X°F?"
            "low": [32, 20],           # "Did low go below X°F?"
        }
    }
)
```

Each observation generates multiple markets:
- **Exceeds markets**: "Did {city} high exceed {threshold}°F?"
- **Below markets**: "Did {city} low go below {threshold}°F?"

### 3. Run Backtest

The `BacktestRunner` generates probabilities:

```python
from backtest import BacktestRunner

runner = BacktestRunner()
result = runner.run(
    markets=markets,
    observations=observations,
    forecast_horizons=[1, 3, 7],  # Days before target
)
```

For each market, the runner:
1. Simulates having a forecast N days before the target date
2. Generates model probability using the Normal distribution model
3. Generates baseline probabilities (naive 50%, persistence, climatology)
4. Records calibration points for analysis

### 4. Analyze Results

```python
from backtest import compare_models, generate_backtest_report

# Compare model vs baselines
comparison = compare_models(result.model_points, result.baseline_points)
print(f"Model Brier: {comparison.model_brier:.4f}")
print(f"Model rank: #{comparison.model_rank}")
print(f"Improvement vs naive: {comparison.improvement_vs_naive:.1f}%")

# Generate full report
report = generate_backtest_report(result)
```

## Baseline Strategies

| Baseline | Description | Expected Brier |
|----------|-------------|----------------|
| **Naive 50%** | Always predicts 0.5 | 0.25 (no skill) |
| **Persistence** | Yesterday's outcome | Variable |
| **Climatology** | Historical frequency for calendar day | Variable |

## Metrics

### Brier Score

```
Brier = mean((predicted_probability - actual_outcome)²)
```

- **0.0**: Perfect predictions
- **0.25**: No skill (equivalent to always guessing 50%)
- **1.0**: Perfectly wrong

### Calibration Curve

Bins predictions by probability and compares to actual frequency:

| Bin | Predicted Avg | Actual Avg | Calibration Gap |
|-----|---------------|------------|-----------------|
| 0-10% | 0.05 | 0.03 | -0.02 |
| 10-20% | 0.15 | 0.18 | +0.03 |
| ... | ... | ... | ... |

Perfect calibration: Predicted Avg ≈ Actual Avg for all bins.

## Configuration

### Custom Thresholds

```python
thresholds = {
    "new york": {
        "high": [80, 85, 90, 95, 32, 40],  # Summer and winter thresholds
        "low": [70, 75, 32, 20, 10],
    },
    "miami": {
        "high": [85, 90, 95],
        "low": [75, 70, 65],
    },
}
```

### Forecast Horizons

```python
forecast_horizons = [1, 3, 7]  # Test 1-day, 3-day, and 7-day forecasts
```

### Filtering Unbalanced Markets

By default, market types with >90% or <10% YES rate are filtered:

```python
result = run_historical_backtest(
    ...,
    filter_balanced=True,  # Default: filter unbalanced markets
)
```

## Example Output

```
=== Backtest Summary ===
Markets processed: 1500
Forecast horizons: [1, 3, 7]

Brier Scores (lower is better):
  Model:       0.1820
  Climatology: 0.2150
  Persistence: 0.2480
  Naive 50%:   0.2500

Model improvement over naive 50%: 27.2%
✅ Model is best calibrated among all tested strategies.
```

## JSON Export

```python
from backtest import generate_backtest_json
import json

json_data = generate_backtest_json(result)
with open("backtest_results.json", "w") as f:
    json.dump(json_data, f, indent=2)
```

## Strictly Out of Scope

The backtest module is **analytics only**. It does NOT include:

- ❌ Trading simulation
- ❌ PnL calculation
- ❌ Kelly sizing
- ❌ Position tracking
- ❌ Market price data
- ❌ Edge calculations
- ❌ Model parameter tuning

## Running Tests

```bash
python -m pytest tests/unit/test_backtest.py -v
```

## Limitations

See [docs/LIMITATIONS.md](LIMITATIONS.md) for methodology caveats.
