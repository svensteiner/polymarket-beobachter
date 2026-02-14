# Weather Data Sources

## Primary Sources

### NOAA (National Oceanic and Atmospheric Administration)
- **Type**: Government weather service
- **Usage**: Primary forecast source for US cities
- **API**: api.weather.gov
- **Data**: Temperature forecasts, precipitation probability
- **Update Frequency**: Hourly
- **Confidence**: High for 0-72 hours, decreasing beyond

### Tomorrow.io
- **Type**: Commercial weather API
- **Usage**: Secondary/backup forecast source
- **API**: api.tomorrow.io
- **Data**: Temperature, precipitation, conditions
- **Update Frequency**: Sub-hourly
- **Confidence**: High for 0-72 hours

## Data Flow

```
NOAA API → noaa_client.py → ForecastData
                ↓
    weather_probability_model.py
                ↓
    Model Probability (0-1)
```

## Forecast Data Structure

```python
ForecastData:
    temperature_f: float      # Forecasted temperature (Fahrenheit)
    temperature_c: float      # Forecasted temperature (Celsius)
    source: str               # Data source identifier
    forecast_time: datetime   # When forecast was made
    target_time: datetime     # Time forecast is for
    confidence: float         # Source confidence (0-1)
```

## Data Quality Rules

1. **Freshness**: Forecasts must be < 6 hours old
2. **Horizon**: Max forecast horizon is 168 hours (7 days)
3. **Agreement**: Multiple sources should agree within tolerance
4. **Completeness**: All required fields must be present

## Missing Data Handling

If any data is missing or stale:
- Return NO_SIGNAL
- Log the issue for monitoring
- Do not interpolate or guess

## Validation

All forecast data is validated:
- Temperature range: -50F to 150F
- Confidence range: 0 to 1
- Timestamp sanity checks
- Source identifier verification
