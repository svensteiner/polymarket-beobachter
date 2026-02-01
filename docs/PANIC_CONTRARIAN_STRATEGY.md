# Panic Contrarian Strategy

## Overview

The Panic Contrarian Strategy is a strictly constrained trading approach designed to identify and exploit short-lived price dislocations caused by human panic in prediction markets.

**Core Principle**: Trade ONLY when human panic creates temporary price dislocations. If in doubt, DO NOTHING.

---

## Strategic Rationale

Prediction markets are susceptible to emotional reactions when:
1. Breaking news creates sudden fear or euphoria
2. Misinterpretation of events leads to overreaction
3. Herd behavior amplifies initial price movements

These panic events typically resolve within hours as rational actors:
- Correctly interpret the actual impact of news
- Provide liquidity to absorb the panic selling/buying
- Arbitrage away the dislocation

The Panic Contrarian Strategy aims to be one of those rational actors.

---

## System Architecture

### Complete Isolation

The Panic Contrarian Engine is **completely isolated** from the core decision engine:

```
┌─────────────────────────────────────────────────────────────┐
│                    CORE DECISION ENGINE                      │
│              (Unchanged, Fail-Closed, No Prices)            │
│                                                             │
│  - Analyzes market structure                                │
│  - Validates resolution criteria                            │
│  - Determines if market is STRUCTURALLY tradeable           │
│  - Does NOT use price/volume data                           │
└─────────────────────────────────────────────────────────────┘
                            │
                            │ No interaction
                            ▼
┌─────────────────────────────────────────────────────────────┐
│               PANIC CONTRARIAN ENGINE                        │
│            (Separate Module, Price-Based)                   │
│                                                             │
│  - Monitors for panic price dislocations                    │
│  - Requires external news shock indicator                   │
│  - State machine prevents overtrading                       │
│  - Emits signals, does NOT execute trades                   │
└─────────────────────────────────────────────────────────────┘
                            │
                            │ Signals only
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                   EXECUTION LAYER                            │
│           (Enforces position limits, time exits)            │
└─────────────────────────────────────────────────────────────┘
```

---

## Activation Conditions

The engine activates ONLY when ALL of the following are true:

### A) External News Shock
- Sudden news or narrative shock detected (external signal)
- No change to official resolution rules or definitions
- **Why**: Panic without news is likely informed trading, not emotional reaction

### B) Price Dislocation
- Price moves >= 15% (configurable)
- Within <= 60 minutes (configurable)
- **Why**: Small moves are noise; fast large moves indicate panic

### C) Volume Spike
- Volume >= 3x rolling baseline (configurable)
- Compared to 24-hour historical average
- **Why**: High volume confirms broad participation, not manipulation

### D) Temporal Safety
- Time until market resolution >= 48 hours (configurable)
- **Why**: Near resolution, fundamental risk dominates panic opportunity

**If ANY condition fails → IGNORE (no trade, no signal)**

---

## State Machine

```
    ┌──────────────────────────────────────┐
    │                                      │
    ▼                                      │
┌─────────┐  All conditions   ┌───────────────────┐
│ NORMAL  │ ───────────────►  │ PANIC_WINDOW_OPEN │
└─────────┘      pass         └───────────────────┘
    ▲                                 │
    │                                 │ Window expires
    │                                 │ OR trade executed
    │     Cooldown expires            ▼
    │                          ┌──────────┐
    └───────────────────────── │ COOLDOWN │
                               └──────────┘
```

### State Descriptions

| State | Duration | Behavior |
|-------|----------|----------|
| NORMAL | Indefinite | Monitoring for panic conditions |
| PANIC_WINDOW_OPEN | 30 minutes | ONE trade opportunity available |
| COOLDOWN | 4 hours | No trading, prevents re-entry |

### State Transitions

- **NORMAL → PANIC_WINDOW_OPEN**: All 5 conditions pass
- **PANIC_WINDOW_OPEN → COOLDOWN**: Window expires OR trade executed
- **COOLDOWN → NORMAL**: Cooldown period elapses

---

## Output States

The engine outputs ONE of three states:

### IGNORE
- No action required
- Engine is monitoring but conditions not met
- **Downstream action**: None

### PANIC_WINDOW_OPEN
- Panic detected, contrarian opportunity exists
- Includes: market_id, direction, metrics, expiration
- **Downstream action**: MAY execute ONE trade

### COOLDOWN
- Recently traded or window expired
- Includes: remaining cooldown duration
- **Downstream action**: None (blocked)

---

## Trade Execution Rules

**These rules are enforced by the execution layer, not this engine:**

| Rule | Value | Rationale |
|------|-------|-----------|
| Position size | Fixed $100 max | Limits total loss |
| Holding time | Max 24 hours | Panic should resolve quickly |
| Trades per window | Exactly ONE | Prevents averaging down |
| Exit trigger | Time-based only | No discretion, no hoping |
| Retries | None | Failed = failed |
| Averaging | None | Position is fixed |
| Leverage | None | Ever |

---

## Configuration Parameters

All parameters are **hardcoded** to prevent live modification:

| Parameter | Value | Description |
|-----------|-------|-------------|
| `PANIC_PRICE_DELTA` | 0.15 (15%) | Minimum price move |
| `PANIC_TIME_WINDOW_MINUTES` | 60 | Max time for price move |
| `PANIC_VOLUME_MULTIPLIER` | 3.0 | Min volume spike |
| `VOLUME_BASELINE_HOURS` | 24 | Baseline calculation window |
| `SAFETY_BUFFER_HOURS` | 48 | Min hours to resolution |
| `PANIC_WINDOW_DURATION_MINUTES` | 30 | Trade opportunity window |
| `COOLDOWN_DURATION_HOURS` | 4 | Post-trade cooldown |
| `MAX_POSITION_SIZE_USD` | 100 | Maximum position |
| `MAX_HOLDING_TIME_HOURS` | 24 | Forced exit time |

---

## Risks and Mitigations

### Risk 1: False Positive Panic Detection
**Scenario**: Price moves on legitimate news, not panic.
**Mitigation**:
- Requires external news shock indicator
- Requires resolution rules unchanged
- High volume threshold filters single-actor manipulation

### Risk 2: Panic Continues After Entry
**Scenario**: Panic deepens instead of reversing.
**Mitigation**:
- Fixed position size limits loss
- Time-based exit prevents holding indefinitely
- No averaging down

### Risk 3: Resolution Uncertainty
**Scenario**: Market resolves against position during hold.
**Mitigation**:
- 48-hour safety buffer before resolution
- 24-hour max holding time
- Combined: 24+ hours of resolution buffer

### Risk 4: Overtrading
**Scenario**: Multiple "panic" signals lead to excessive trading.
**Mitigation**:
- One trade per panic window
- 4-hour cooldown after each window
- State machine enforces invariants

### Risk 5: System Error
**Scenario**: Bug causes unintended trades.
**Mitigation**:
- Engine emits signals, does NOT execute
- Execution layer has independent checks
- Full audit trail for post-mortem

---

## Expected Trading Frequency

This strategy is designed to trade **rarely**:

- **Expected signals**: 1-5 per month across all markets
- **Executed trades**: 0-3 per month
- **Win rate target**: 60-70% (contrarian thesis valid more often than not)

**If the system trades frequently, something is wrong.**

---

## Audit Trail

Every analysis produces a full audit record:

```json
{
  "output": "IGNORE",
  "engine_state": "NORMAL",
  "market_id": "0x...",
  "metrics": {
    "price_delta": 0.08,
    "volume_multiplier": 1.5,
    "hours_until_resolution": 120.5,
    "price_condition": "FAILED",
    "volume_condition": "FAILED",
    "temporal_condition": "PASSED"
  },
  "reasoning": "NO PANIC: 2 condition(s) not met...",
  "generated_at": "2024-01-15T10:30:00Z"
}
```

---

## What This Strategy Does NOT Do

1. **Learn or adapt** - Thresholds are fixed
2. **Use leverage** - Ever
3. **Scale positions** - Size is fixed
4. **Retry failed trades** - Once is once
5. **Average down/up** - No position modifications
6. **Predict outcomes** - Only identifies panic, not resolution
7. **Modify core engine** - Complete isolation

---

## When to Disable This Strategy

Consider disabling if:
- Win rate drops below 50% over 20+ trades
- Market structure changes (new liquidity providers)
- Regulatory changes affect prediction markets
- Execution costs exceed expected edge

---

## Summary

The Panic Contrarian Strategy is a **defensive, constrained** approach to capturing short-lived emotional price dislocations. It is designed to:

- Trade rarely
- Lose small when wrong
- Win modestly when right
- Never blow up

**The correct default behavior is: DO NOTHING.**
