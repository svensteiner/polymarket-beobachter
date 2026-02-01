# Edge Dashboard Metrics

## Module Overview

The Edge Exposure Aggregator is a **governance-safe dashboard module** that aggregates edge evolution data for display. It is **ANALYTICS ONLY** and **MUST NOT** influence trading, execution, exits, or parameters.

## What This Dashboard Answers

> **"Did we consistently have an advantage?"**

## What This Dashboard MUST NEVER Answer

> **"What should we do now?"**

If the dashboard changes behavior, the design has failed.

## Absolute Non-Negotiable Rules

1. **Read-only access** to edge evolution data
2. **No access** to execution, decision, or signal modules
3. **No PnL calculations**
4. **No "optimal exit"**, "sell now", or hypothetical profit metrics
5. **All metrics are descriptive**, not prescriptive
6. **If data is inconsistent** → omit metric, do not infer

## What is Edge Exposure?

Edge Exposure measures the cumulative "exposure" to edge over time. It is the integral of the relative edge over time:

```
Edge Exposure = Σ [ edge_relative(t_i) × Δt_i ]
```

### Units

- **Edge-Minutes** or **Edge-Hours** (explicitly labeled)
- NOT dollars, NOT profit, NOT PnL

### Why Edge Exposure is NOT Profit

Edge Exposure measures the **time-weighted advantage** we had, NOT how much money we made.

Consider two scenarios:

| Scenario | Edge | Duration | Edge Exposure |
|----------|------|----------|---------------|
| A | +20% | 1 hour | 20 edge-hours |
| B | +5% | 4 hours | 20 edge-hours |

Both have the same edge exposure, but:
- Scenario A had a larger instantaneous advantage
- Scenario B had a smaller but more persistent advantage

Neither tells us:
- How much profit was realized
- Whether we should exit
- What the optimal timing would have been

## Dashboard Metrics

### 1. Total Edge Exposure (hours)

The sum of all edge exposure across all positions.

```
Total = Σ edge_area_position
```

**Interpretation:**
- Positive = Net positive advantage over time
- Negative = Net negative advantage over time
- Zero = Advantage and disadvantage balanced out

### 2. Positive Edge Exposure (hours)

The sum of edge exposure where edge was positive.

```
Positive = Σ edge_area where edge_relative > 0
```

### 3. Negative Edge Exposure (hours)

The sum of edge exposure where edge was negative.

```
Negative = Σ edge_area where edge_relative < 0
```

### 4. Edge Exposure Ratio

The proportion of positive exposure to total exposure.

```
Ratio = Positive / (Positive + |Negative|)
```

**Interpretation:**

| Ratio | Meaning |
|-------|---------|
| 1.0 | All positive edge (consistent advantage) |
| 0.8 | Strong positive bias |
| 0.5 | Equal positive and negative |
| 0.2 | Weak positive bias |
| 0.0 | All negative edge (consistent disadvantage) |

### 5. Median Edge Duration (minutes)

The median time that positions spent with positive edge.

**Interpretation:**
- High = Positions typically maintain positive edge for a long time
- Low = Positive edge periods are typically short

### 6. Open Positions Count

Number of positions with snapshots in the time window.

### 7. Snapshot Count

Total number of edge snapshots used in the calculation.

## Time Windows

| Window | Description |
|--------|-------------|
| `last_24h` | Last 24 hours |
| `last_7d` | Last 7 days |
| `all_time` | All recorded history |

## How to Interpret the Dashboard

### High Edge Exposure Ratio (> 0.7)

**What it means:**
- We consistently had an advantage
- Our edge estimates were aligned with market direction

**What it does NOT mean:**
- We should hold longer
- We made profit
- Our strategy is optimal

### Low Edge Exposure Ratio (< 0.3)

**What it means:**
- Our edge was frequently negative
- Market moved against our estimates

**What it does NOT mean:**
- We should exit immediately
- We lost money
- Our strategy is broken

### Large Total Edge Exposure

**What it means:**
- We had significant time-weighted edge (positive or negative)
- Substantial data to analyze

**What it does NOT mean:**
- We made or lost a lot of money
- We should change our behavior

## Why This Protects Governance

### The Problem with Prescriptive Metrics

Prescriptive metrics like "optimal exit time" or "potential profit" encourage:
- Automated decision-making based on past data
- Hindsight bias ("we should have sold here")
- Signal generation that bypasses governance

### How Descriptive Metrics Help

Descriptive metrics like Edge Exposure:
- Only describe what happened
- Do not suggest what should happen
- Cannot be used to trigger automated actions
- Support human analysis without replacing judgment

### The Governance Test

Ask: "Can this metric be used to automatically trigger an exit?"

- **Edge Exposure Ratio**: No (it's a historical summary)
- **Optimal Exit Time**: Yes (FORBIDDEN - not implemented)
- **Median Duration**: No (it's a statistical summary)
- **Sell Signal**: Yes (FORBIDDEN - not implemented)

## Dashboard Display Guidelines

### Dashboard MAY Display

- Total Edge Exposure (with time window label)
- Positive vs Negative Exposure breakdown
- Edge Exposure Ratio
- Median Edge Duration
- Snapshot counts
- Historical trends

### Dashboard MUST NOT Display

- Buy/sell urgency indicators
- Exit recommendations
- Position rankings by "sell now"
- Color-coded action alerts
- "You should..." suggestions

## CLI Usage

### Build Summary

```bash
python tools/edge_dashboard_cli.py build-summary --window last_7d
```

### Print Summary

```bash
python tools/edge_dashboard_cli.py print-summary
```

### Position Details

```bash
python tools/edge_dashboard_cli.py position-details --window all_time --limit 20
```

### JSON Export

```bash
python tools/edge_dashboard_cli.py json-export --window all_time
```

## Output Schema

```json
{
  "schema_version": 1,
  "generated_at_utc": "2026-01-24T15:30:00+00:00",
  "time_window": "last_7d",
  "open_positions_count": 51,
  "snapshot_count": 1820,
  "total_edge_exposure_hours": 1240.5,
  "positive_edge_exposure_hours": 1410.2,
  "negative_edge_exposure_hours": -169.7,
  "edge_exposure_ratio": 0.89,
  "median_edge_duration_minutes": 165,
  "governance_notice": "ANALYTICS ONLY - This dashboard does NOT suggest trading actions"
}
```

## Governance Compliance Checklist

- [x] No imports from decision_engine
- [x] No imports from execution_engine
- [x] No imports from panic modules
- [x] No PnL calculations
- [x] No exit signals
- [x] No "sell now" metrics
- [x] Descriptive metrics only
- [x] Explicit governance notices
- [x] Static analysis safety test

## Mental Model

```
┌─────────────────────────────────────────────────────────────┐
│                   Edge Exposure Dashboard                    │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  INPUT (READ-ONLY):                                         │
│  - Edge snapshots from edge_snapshots.jsonl                 │
│                                                              │
│  PROCESSING:                                                │
│  - Group by position                                        │
│  - Calculate edge area (time integral)                      │
│  - Separate positive/negative exposure                      │
│  - Compute ratios and medians                               │
│                                                              │
│  OUTPUT:                                                    │
│  - edge_exposure_summary.json                               │
│  - Dashboard-safe metrics                                   │
│                                                              │
│  ❌ DOES NOT:                                               │
│  - Calculate PnL or profit                                  │
│  - Suggest exits or actions                                 │
│  - Generate signals                                         │
│  - Color-code urgency                                       │
│                                                              │
│  ✓ ANSWERS: "Did we consistently have an advantage?"        │
│  ✗ NEVER ANSWERS: "What should we do now?"                  │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```
