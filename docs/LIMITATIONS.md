# System Limitations

## Fundamental Limitations

### Observer-Only
This system **does not trade**. It only observes and logs. Any edge detection is for calibration purposes only.

### Weather-Only
The system only processes weather markets. All other market types are explicitly filtered out:
- No politics/elections
- No sports
- No crypto
- No corporate events
- No court rulings
- No EU regulation

### Static Parameters
All model parameters are fixed in configuration:
- No automatic learning
- No parameter optimization
- No self-modification

## Model Limitations

### Forecast Horizon
- **0-72 hours**: High confidence
- **72-168 hours**: Medium confidence
- **>168 hours**: Low confidence (NO_SIGNAL)

### Geographic Coverage
Limited to cities with reliable forecast data:
- Major US cities (NYC, LA, Chicago, Miami, etc.)
- Major international cities (London, Tokyo, Paris, etc.)

### Event Types
Only objectively measurable events:
- Temperature thresholds
- Rain/snow occurrence
- Specific meteorological measurements

Does NOT support:
- Subjective weather assessments
- Cumulative weather events
- Complex multi-day patterns

## Data Limitations

### API Dependencies
System depends on external APIs:
- NOAA API availability
- Tomorrow.io API availability
- API rate limits
- Network connectivity

### Data Staleness
Forecasts degrade over time. System requires fresh data.

### Resolution Source
Market resolution depends on official weather station data, which may differ from forecasts.

## Operational Limitations

### No Execution
This system cannot and will not execute trades:
- No Polymarket API integration for trading
- No wallet management
- No order placement

### No Real-Time
System runs on a schedule (default: 15 minutes). Not designed for real-time monitoring.

### No Alerts
System does not send notifications. All output is logged to files.

## Known Issues

### Edge Detection Accuracy
Model edge detection is probabilistic and may be wrong. Calibration data should be analyzed before trusting observations.

### Market Data Delay
Polymarket odds may be delayed or stale when fetched.

### Weather Station Variance
Different weather stations may report different readings for the same location.

## Assumptions

The system assumes:
1. Weather forecasts are approximately correct
2. Market resolution will use standard weather station data
3. Normal distribution is appropriate for temperature uncertainty
4. Model is wrong by default until proven otherwise

---

## Historical Backtest Limitations

The historical backtest module (`backtest/`) has additional methodology caveats.

### Synthetic Forecast Simulation

Since we use historical data, we don't have actual forecast data from N days before each target date. Instead, we simulate forecasts by:

1. Taking the actual observed temperature
2. Adding synthetic noise based on the model's sigma parameter
3. Computing probabilities from this simulated forecast

**Implication**: This tests the model's **calibration quality** given a forecast, not the accuracy of real forecasts. A well-calibrated model applied to poor forecasts will still produce poor results in practice.

### Climatology Baseline Limitations

The climatology baseline uses a ±15 day window around each calendar day. With limited historical data:

- Years with unusual weather may skew results
- Rare events (extreme heat/cold) may not appear in the historical record
- Climate trends are not accounted for

### Persistence Baseline Limitations

The persistence baseline assumes "tomorrow will be like today." This is:

- Strong for stable weather patterns
- Weak during weather transitions
- Not representative of skilled forecasting

### Outcome Balance Filtering

Markets with >90% or <10% YES rate are filtered by default. This means:

- The backtest focuses on "interesting" markets
- Results may not generalize to extreme threshold markets
- Very hot or very cold thresholds may be underrepresented

### Sample Size Requirements

Calibration analysis requires sufficient samples:

- <50 samples: Unreliable Brier scores
- 50-200 samples: Directionally useful
- >200 samples: Statistically meaningful

### No Forecast Error Modeling

The backtest assumes forecast error is normally distributed with known sigma. In reality:

- Forecast error varies by weather pattern
- Forecast error varies by season
- Forecast error varies by location
- Forecast bias may exist (systematic over/under prediction)

### No Market Dynamics

The backtest compares model probability to **actual outcomes only**. It does not:

- Account for market efficiency
- Consider bid-ask spreads
- Model liquidity constraints
- Account for timing of probability estimation

### Synthetic Error Scale

The `synthetic_error_scale` parameter (default 0.5) controls how much noise is added to simulate forecasts. This is:

- Arbitrary and not derived from real forecast data
- May over- or under-estimate actual forecast uncertainty
- Affects model probability distribution

### Strictly No Trading Simulation

The backtest module deliberately excludes:

- PnL calculation
- Kelly sizing
- Position management
- Edge-based trade selection

This is intentional. Calibration should be evaluated independently of trading strategy.

### Interpretation Guidelines

When interpreting backtest results:

1. **Model beats naive 50%**: Minimum bar for a useful model
2. **Model beats climatology**: Model adds value over historical frequency
3. **Model beats persistence**: Model captures more than day-to-day autocorrelation
4. **All models similar**: Either data is insufficient or thresholds are at distribution center

A Brier score improvement of <5% over baselines may not be practically significant.
