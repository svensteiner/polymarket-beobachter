# Weather Observer Strategy

## Overview

This is a **weather-only observation system** for Polymarket weather markets.
It is **NOT a trading system**. No trades are executed. No positions are taken.

## Scope

The system observes ONLY weather-related prediction markets:
- Temperature threshold markets (e.g., "Will NYC reach 100F?")
- Precipitation markets (e.g., "Will it rain in LA?")
- Measurable meteorological events

## What This System Does

1. **Scans** Polymarket for weather markets
2. **Fetches** external weather forecasts (NOAA, Tomorrow.io)
3. **Computes** model probability based on forecast data
4. **Compares** model probability to market odds
5. **Logs** observations for calibration analysis

## What This System Does NOT Do

- Execute trades
- Recommend positions
- Manage capital
- Size positions (no Kelly, no leverage)
- Learn from outcomes (no parameter adaptation)
- Process news or sentiment

## Signal Types

The system produces two observation types:

### OBSERVE
- Model detects potential edge (model probability differs from market)
- Logged for calibration analysis
- NOT a trade recommendation

### NO_SIGNAL
- Insufficient edge
- Low model confidence
- Missing or ambiguous data
- Market fails filter criteria

## Fail-Closed Design

The system assumes it is **wrong by default**:
- If data is missing → NO_SIGNAL
- If data is ambiguous → NO_SIGNAL
- If confidence is low → NO_SIGNAL
- If forecast horizon > 7 days → NO_SIGNAL

## Calibration

Observations are logged for calibration analysis:
- Brier score tracking
- Hit rate calculation
- Edge evolution over time
- Resolution outcome tracking

## No Hidden Trading Logic

This codebase contains:
- NO execution engine
- NO paper trading
- NO position sizing
- NO capital management
- NO order generation

The system is observer-only.
