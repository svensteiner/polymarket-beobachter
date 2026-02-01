# Weather Trading Engine Documentation

## Overview

The Weather Trading Engine is a **GOVERNANCE-FIRST, ISOLATED** signal generation system for Polymarket weather markets. It compares physical reality (weather forecasts) to market pricing and identifies potential mispricing opportunities.

## Core Principles

### 1. ISOLATION

The Weather Engine is **completely isolated** from:
- Panic Contrarian Engine
- Execution Engine
- Decision Engine
- Learning/ML modules
- Paper Trader
- Any live trading components

**Why?** To ensure the weather engine cannot accidentally:
- Execute trades
- Modify parameters automatically
- Learn and adapt without human review
- Interfere with other trading strategies

### 2. READ-ONLY SIGNAL PRODUCER

The engine **ONLY** produces `WeatherSignal` objects. It never:
- Places orders
- Modifies positions
- Changes configuration
- Writes to trading systems

Signals are **immutable facts** that downstream systems can choose to act on (or ignore).

### 3. STATIC PARAMETERS

All parameters come from `config/weather.yaml`. The engine:
- Does NOT adapt thresholds
- Does NOT learn from outcomes
- Does NOT modify its own configuration

Changes require human review and bot restart.

### 4. FAIL-CLOSED

When in doubt, the correct output is `NO_SIGNAL`:
- Uncertainty → NO_SIGNAL
- Missing data → NO_SIGNAL
- Low confidence → NO_SIGNAL
- Insufficient edge → NO_SIGNAL

The engine prioritizes signal quality over quantity.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     WeatherEngine                           │
│                    (Orchestrator)                           │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌─────────────┐    ┌──────────────┐    ┌───────────────┐  │
│  │   Market    │    │  Probability │    │    Signal     │  │
│  │   Filter    │ →  │    Model     │ →  │   Generator   │  │
│  └─────────────┘    └──────────────┘    └───────────────┘  │
│         ↑                  ↑                    │          │
│         │                  │                    │          │
│  ┌──────┴──────┐    ┌──────┴──────┐    ┌───────┴───────┐  │
│  │   Config    │    │  Forecast   │    │ WeatherSignal │  │
│  │   (YAML)    │    │   Fetcher   │    │   (Output)    │  │
│  └─────────────┘    └─────────────┘    └───────────────┘  │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

## Pipeline

1. **Fetch Markets** - Retrieve weather markets from Polymarket (READ-ONLY)
2. **Filter Markets** - Apply strict filter criteria (7 checks, all must pass)
3. **Fetch Forecasts** - Get external weather forecast data
4. **Compute Probability** - Calculate fair probability using statistical model
5. **Calculate Edge** - Compare fair probability to market probability
6. **Generate Signal** - Emit BUY signal only if edge is significant

## Filter Criteria

All criteria must pass for a market to be eligible:

| Criterion | Description | Config Key |
|-----------|-------------|------------|
| Category | Must be WEATHER category | N/A |
| Binary | Must be YES/NO market | N/A |
| Liquidity | >= MIN_LIQUIDITY USD | `MIN_LIQUIDITY` |
| Time | >= MIN_TIME_TO_RESOLUTION_HOURS | `MIN_TIME_TO_RESOLUTION_HOURS` |
| Odds Range | Between MIN_ODDS and MAX_ODDS | `MIN_ODDS`, `MAX_ODDS` |
| City | In ALLOWED_CITIES list | `ALLOWED_CITIES` |
| Resolution | Explicit, verifiable definition | N/A |

## Probability Model

### Mathematical Foundation

The model assumes temperature follows a Normal distribution:
- **Mean**: Forecast temperature
- **Standard Deviation (σ)**: Configurable, adjusted by forecast horizon

For "exceeds threshold" events:
```
P(T > threshold) = 1 - Φ((threshold - mean) / σ)
```

Where Φ is the standard normal CDF.

### Example Calculation

Market: "Will NYC exceed 100°F on July 15?"
- Forecast: 95°F expected
- σ = 3.5°F (3-day horizon)
- P(T > 100) = 1 - Φ((100 - 95) / 3.5) = 1 - Φ(1.43) ≈ 0.077 (7.7%)

If market prices this at 3%:
```
edge = (0.077 - 0.03) / 0.03 = 1.57 (157% edge)
```

### Confidence Levels

| Confidence | Forecast Horizon | Effect |
|------------|------------------|--------|
| HIGH | ≤ 3 days | Standard MIN_EDGE applies |
| MEDIUM | 3-7 days | Higher edge required (×1.5) |
| LOW | > 7 days | Always NO_SIGNAL |

## Signal Schema

```json
{
  "signal_id": "uuid4",
  "timestamp_utc": "ISO8601",
  "market_id": "string",
  "city": "string",
  "event_description": "string",
  "market_probability": 0.03,
  "fair_probability": 0.077,
  "edge": 1.57,
  "confidence": "HIGH",
  "recommended_action": "BUY",
  "engine": "weather_engine_v1",
  "parameters_hash": "sha256(config)"
}
```

## Configuration Reference

### config/weather.yaml

```yaml
# Market Filter Parameters
MIN_LIQUIDITY: 50          # Minimum USD liquidity
MIN_ODDS: 0.01            # Minimum market odds
MAX_ODDS: 0.10            # Maximum market odds
MIN_TIME_TO_RESOLUTION_HOURS: 48
SAFETY_BUFFER_HOURS: 48

# Edge Calculation
MIN_EDGE: 0.25            # 25% minimum edge
MEDIUM_CONFIDENCE_EDGE_MULTIPLIER: 1.5

# Probability Model
SIGMA_F: 3.5              # Base standard deviation (°F)
MAX_FORECAST_HORIZON_DAYS: 10

# Allowed Cities
ALLOWED_CITIES:
  - London
  - New York
  - Seoul
  # ... etc.
```

## Integration

### Signal Registry

The Weather Engine integrates with the broader system via signals:

1. Engine runs periodically (e.g., every 6 hours)
2. Signals are logged to `logs/weather_signals.jsonl`
3. Human operators review signals
4. If signal is actionable, human decides whether to trade

The engine NEVER auto-trades. All execution decisions are human-in-the-loop.

### Injection Points

The engine accepts injectable dependencies for testing:

```python
engine = WeatherEngine(
    config=config,
    market_fetcher=my_market_fetcher,  # Custom market source
    forecast_fetcher=my_forecast_fetcher,  # Custom forecast source
)
```

## What the Engine DOES NOT Do

| NOT This | Why |
|----------|-----|
| Execute trades | Signal-only by design |
| Modify parameters | Static configuration |
| Learn from outcomes | No ML, no memory |
| Interface with execution | Complete isolation |
| Predict weather | Converts forecasts to probabilities |
| Make sizing decisions | Outside scope |

## Why This is Governance-Safe

1. **Isolation**: Cannot accidentally trigger trades
2. **Immutability**: Signals are facts, not commands
3. **Audit Trail**: All signals logged with parameters hash
4. **Human Review**: Requires human to act on signals
5. **No Learning**: Cannot drift from intended behavior
6. **Fail-Closed**: Uncertainty produces NO_SIGNAL

## Testing

### Required Tests

1. **Unit Tests - Probability Calculation**
   - Normal distribution CDF accuracy
   - Edge calculation correctness
   - Confidence level determination

2. **Unit Tests - Market Filtering**
   - Each filter criterion tested individually
   - All-pass and all-fail scenarios
   - Edge cases (boundary values)

3. **Integration Tests**
   - Mocked markets + mocked forecasts
   - Full pipeline execution
   - Signal correctness verification

4. **Isolation Verification**
   - No imports from forbidden modules
   - Grep test for isolation violations

### Running Tests

```bash
pytest tests/test_weather_engine.py -v
pytest tests/test_weather_probability_model.py -v
pytest tests/test_weather_market_filter.py -v
```

## Mental Model

> This engine does not predict the world.
> It compares human mispricing vs physical reality.
> If the model is wrong, the correct behavior is silence.

The Weather Engine is a **mispricing detector**, not a weather predictor. Its value comes from identifying when market participants misprice weather events relative to available forecast data.

When uncertain, silence is correct. Missing a good trade is acceptable. Making a bad signal is not.
