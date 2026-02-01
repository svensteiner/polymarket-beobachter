# Shadow Mode Evaluation Guide

## Overview

Shadow mode is a **mandatory validation phase** for the Panic Contrarian Engine.
The engine is assumed to be **WRONG by default**. Its job is to prove usefulness over time.

**If unsure, the correct action is: DO NOTHING.**

---

## Core Principle

No real trades may be executed until the engine has demonstrated:
1. A FALSE_TRIGGER rate below 30% over 10+ trades
2. A positive win rate (GOOD_REVERSION > CONTINUED_PANIC)
3. Absence of critical failure patterns

---

## Shadow Mode Configuration

| Parameter | Value | Description |
|-----------|-------|-------------|
| `PANIC_SHADOW_MODE` | `True` | Global flag - ALWAYS ON by default |
| `FALSE_TRIGGER_THRESHOLD` | `0.30` | Kill switch triggers at 30% |
| `KILL_SWITCH_MIN_SAMPLES` | `10` | Minimum trades before kill switch can activate |
| `REVERSION_THRESHOLD` | `0.05` | 5% price reversion = GOOD_REVERSION |
| `CONTINUED_PANIC_THRESHOLD` | `0.05` | 5% continued move = CONTINUED_PANIC |

---

## Log Files

Shadow mode generates the following logs in `logs/panic_shadow/`:

### `shadow_stats.json`
Aggregate statistics for all simulated trades.

```json
{
  "total_signals": 15,
  "total_completed_trades": 12,
  "good_reversions": 5,
  "no_reversions": 4,
  "continued_panics": 2,
  "false_triggers": 1,
  "aborted": 0,
  "pending": 3,
  "kill_switch_triggered": false,
  "kill_switch_timestamp": null,
  "false_trigger_rate": 0.083,
  "win_rate": 0.417
}
```

### `simulated_trades.jsonl`
Detailed record of each simulated trade (JSON Lines format).

```json
{
  "trade_id": "0x123_20240115_143022",
  "market_id": "0x123...",
  "market_title": "Will X happen by Y?",
  "entry_timestamp": "2024-01-15T14:30:22",
  "entry_price": 0.35,
  "direction": "UNDERPRICED",
  "triggering_metrics": {...},
  "price_after_1h": 0.38,
  "price_after_6h": 0.42,
  "price_after_12h": 0.45,
  "price_at_exit_time": 0.48,
  "max_adverse_move": 0.02,
  "max_favorable_move": 0.13,
  "exit_timestamp": "2024-01-16T14:30:22",
  "exit_reason": "time_expiry",
  "outcome": "GOOD_REVERSION",
  "aborted": false,
  "abort_reason": null,
  "pre_panic_price": 0.50
}
```

---

## Outcome Classifications

### GOOD_REVERSION
**Definition**: Price reverted toward pre-panic level by >= 5%.

**Example**:
- Entry: 35% (panic sold from 50%)
- Exit: 41% (+6% reversion toward 50%)
- Classification: GOOD_REVERSION

**Interpretation**: Contrarian thesis was CORRECT. This is the desired outcome.

---

### NO_REVERSION
**Definition**: Price stayed flat, movement < 5% in either direction.

**Example**:
- Entry: 35%
- Exit: 37% (+2%)
- Classification: NO_REVERSION

**Interpretation**: Contrarian thesis was NEUTRAL. No harm, but no value either.

---

### CONTINUED_PANIC
**Definition**: Price continued in panic direction by >= 5%.

**Example**:
- Entry: 35% (bought expecting reversion)
- Exit: 29% (-6% continued down)
- Classification: CONTINUED_PANIC

**Interpretation**: Contrarian thesis was WRONG. This is a loss scenario.

---

### FALSE_TRIGGER
**Definition**: Panic detection was incorrect. Price movement was fundamental, not panic.

**Indicators**:
- Resolution rules changed during observation
- Trade was aborted due to rule clarification
- Price never showed panic characteristics

**Interpretation**: CRITICAL failure mode. Engine signal quality is compromised.

---

### ABORTED
**Definition**: Trade was terminated before completion due to safety conditions.

**Abort Reasons**:
- `RESOLUTION_CHANGED`: Resolution definition changed
- `RULE_CLARIFICATION`: Official clarification released
- `SAFETY_BUFFER_BREACHED`: Time until resolution fell below buffer
- `KILL_SWITCH_TRIGGERED`: FALSE_TRIGGER rate exceeded threshold
- `MANUAL_ABORT`: Operator requested abort

**Interpretation**: Signal quality uncertain. Not counted as win or loss.

---

## Evaluation Metrics

### Primary: FALSE_TRIGGER Rate

```
FALSE_TRIGGER_RATE = false_triggers / total_completed_trades
```

**Thresholds**:
- `< 20%`: Acceptable, normal noise
- `20-30%`: Concerning, investigate triggers
- `> 30%`: **KILL SWITCH TRIGGERED** - engine disabled

---

### Secondary: Win Rate

```
WIN_RATE = good_reversions / total_completed_trades
```

**Thresholds**:
- `> 50%`: Good, edge appears to exist
- `40-50%`: Marginal, may not cover costs
- `< 40%`: Poor, consider disabling

---

### Tertiary: Risk-Adjusted Return

```
NET_OUTCOME = good_reversions - continued_panics
```

**Interpretation**:
- Positive: Engine is adding value
- Zero: Engine is neutral (not useful)
- Negative: Engine is destructive

---

## Kill Switch

The kill switch automatically disables the engine when:

1. `total_completed_trades >= 10` (minimum sample)
2. `false_trigger_rate > 0.30` (30%)

**When kill switch triggers**:
- Engine returns `IGNORE` for all markets
- Status logged as `DISABLED_KILL_SWITCH`
- Manual investigation required
- Manual re-enable required (edit code)

---

## How to Interpret Results

### Healthy Engine Performance

```
total_completed_trades: 25
good_reversions: 12 (48%)
no_reversions: 8 (32%)
continued_panics: 4 (16%)
false_triggers: 1 (4%)
aborted: 0 (0%)

false_trigger_rate: 4%
win_rate: 48%
net_outcome: +8
```

**Verdict**: Engine is performing well. Continue shadow mode.

---

### Marginal Engine Performance

```
total_completed_trades: 20
good_reversions: 7 (35%)
no_reversions: 6 (30%)
continued_panics: 5 (25%)
false_triggers: 2 (10%)
aborted: 0 (0%)

false_trigger_rate: 10%
win_rate: 35%
net_outcome: +2
```

**Verdict**: Engine is marginal. Need more data, but concerning.

---

### Failing Engine Performance

```
total_completed_trades: 15
good_reversions: 3 (20%)
no_reversions: 4 (27%)
continued_panics: 5 (33%)
false_triggers: 3 (20%)
aborted: 0 (0%)

false_trigger_rate: 20%
win_rate: 20%
net_outcome: -2
```

**Verdict**: Engine is failing. Disable and investigate.

---

## Investigation Checklist

When performance is poor, investigate:

### 1. Are thresholds too loose?
- Is `PANIC_PRICE_DELTA` (15%) sufficient?
- Is `PANIC_VOLUME_MULTIPLIER` (3x) enough?
- Is `SAFETY_BUFFER_HOURS` (48h) adequate?

### 2. Is news detection accurate?
- Are `news_shock_indicator` signals reliable?
- Are false positives common?

### 3. Are markets appropriate?
- Are target markets liquid enough?
- Do they exhibit panic patterns?

### 4. Is timing correct?
- Is `PANIC_TIME_WINDOW_MINUTES` (60) right?
- Is `MAX_HOLDING_TIME_HOURS` (24) appropriate?

---

## Proceeding to Production

**DO NOT proceed to production** unless ALL of the following are true:

1. **Sample size**: >= 30 completed trades
2. **FALSE_TRIGGER rate**: < 15% (not just < 30%)
3. **Win rate**: > 50%
4. **Net outcome**: Positive by >= 5 trades
5. **No kill switch triggers**: Ever
6. **Manual review**: Human has reviewed all trades

**Proceeding to production requires**:
1. Setting `PANIC_SHADOW_MODE = False` in code
2. Code review and approval
3. Deployment to production

---

## Summary

| Metric | Requirement for Production |
|--------|---------------------------|
| Sample size | >= 30 trades |
| FALSE_TRIGGER rate | < 15% |
| Win rate | > 50% |
| Net outcome | >= +5 |
| Kill switch history | Never triggered |
| Human review | All trades reviewed |

**Remember**: This engine is assumed to be WRONG by default.
It must PROVE its value through extensive shadow mode validation.

**When in doubt: DO NOTHING.**
