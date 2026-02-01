# Edge Evolution Tracker

## Module Overview

The Edge Evolution Tracker is a **governance-first analytics module** that measures how the edge of a position evolves after entry. It is **READ-ONLY** with respect to trading and **NEVER** triggers sells, buys, parameter changes, or signals.

## Purpose

This module answers ONE question only:

> **"How long was our advantage real?"**

If someone tries to use this for selling decisions, the design has failed.

## Absolute Non-Negotiable Rules

1. **No interaction with execution or decision logic**
2. **No order placement, no exit signals**
3. **Append-only storage**: never overwrite historical data
4. **Edge is MEASURED, not acted upon**
5. **If data is missing or inconsistent → write NOTHING**
6. **Tracker must be removable without affecting trading behavior**

## Why This Module is NOT an Exit Signal

The Edge Evolution Tracker is designed purely for post-hoc analysis. It helps us understand:

- Did our edge persist or evaporate?
- How quickly did the market converge to our estimate?
- Were our initial assessments accurate?

This information is valuable for:
- Improving future probability estimates
- Understanding market efficiency
- Calibrating confidence levels

However, this data is **explicitly NOT** used for:
- Triggering exits
- Modifying positions
- Making trading decisions
- Adjusting parameters

## Architecture

### Module Structure

```
core/
├── edge_snapshot.py        # Schema and validation
└── edge_evolution_tracker.py  # Main tracker logic

tools/
└── edge_tracker_cli.py     # Command-line interface

data/
└── edge_evolution/
    └── edge_snapshots.jsonl  # Append-only storage

docs/
└── EDGE_EVOLUTION_TRACKER.md  # This documentation
```

### Isolation Guarantees

The module explicitly **DOES NOT** import:
- `decision_engine`
- `execution_engine`
- `panic_contrarian_engine`
- Any learning or training modules

This is enforced at runtime with import checks.

## Schema

### EdgeSnapshot

```json
{
  "schema_version": 1,
  "snapshot_id": "<uuid4>",
  "position_id": "<uuid4>",
  "market_id": "<string>",
  "timestamp_utc": "<ISO8601>",
  "time_since_entry_minutes": 123,
  "market_probability_current": 0.65,
  "fair_probability_entry": 0.80,
  "edge_relative": 0.23,
  "edge_delta_since_entry": -0.05,
  "source": "scheduler",
  "record_hash": "<sha256>",
  "governance_notice": "This is an ANALYTICS record only. NOT a trading signal."
}
```

### Field Definitions

| Field | Type | Description |
|-------|------|-------------|
| `schema_version` | int | Always 1 |
| `snapshot_id` | uuid | Unique identifier for this snapshot |
| `position_id` | uuid | The position being tracked |
| `market_id` | string | Market identifier |
| `timestamp_utc` | ISO8601 | When the snapshot was taken |
| `time_since_entry_minutes` | int | Minutes since position entry |
| `market_probability_current` | float | Current market probability (0-1) |
| `fair_probability_entry` | float | Our fair probability at entry (0-1) |
| `edge_relative` | float | Current relative edge |
| `edge_delta_since_entry` | float | Change in edge since entry |
| `source` | string | "scheduler", "cli", or "manual" |
| `record_hash` | string | SHA256 of canonical JSON |

### Edge Calculations

**Relative Edge:**
```
edge_relative = (fair_probability_entry - market_probability_current)
                / market_probability_current
```

**Edge Delta Since Entry:**
```
edge_delta_since_entry = edge_relative - edge_at_entry

where:
edge_at_entry = (fair_probability_entry - market_probability_entry)
                / market_probability_entry
```

## Three Patterns to Understand

### 1. Fast Convergence

**What it looks like:**
- Initial edge: +20%
- After 2 days: +5%
- After 5 days: ~0%

**What it means:**
The market has converged toward our fair value estimate. The initial mispricing has been corrected. This is the ideal scenario - our edge was real and the market recognized it.

**Analysis implication:**
Our probability estimate was likely accurate. The market eventually priced in the information we identified.

### 2. Persistent Edge

**What it looks like:**
- Initial edge: +15%
- After 2 days: +14%
- After 5 days: +13%
- After 10 days: +12%

**What it means:**
The edge remains stable over time. The market has not moved toward our estimate. This could indicate:
- Market inefficiency persists
- Our estimate may be wrong
- Resolution date is distant and market hasn't reacted yet

**Analysis implication:**
Requires further investigation. The persistent gap could represent opportunity or miscalibration.

### 3. False Edge

**What it looks like:**
- Initial edge: +15%
- After 2 days: +5%
- After 5 days: -10%

**What it means:**
The edge has disappeared and reversed. The market is moving **away** from our estimate. This suggests:
- Our initial estimate was wrong
- New information has changed the probability
- We may have missed something in our analysis

**Analysis implication:**
Our probability estimate was likely incorrect. This is valuable calibration data for improving future estimates.

## CLI Usage

### Capture Snapshot

```bash
python tools/edge_tracker_cli.py snapshot-now
```

### View Statistics

```bash
python tools/edge_tracker_cli.py stats
```

### View Position History

```bash
python tools/edge_tracker_cli.py history --position PAPER-20260124-abc12345
```

### List Open Positions

```bash
python tools/edge_tracker_cli.py list-open
```

### Verify Data Integrity

```bash
python tools/edge_tracker_cli.py verify-hashes
```

### Rebuild Index

```bash
python tools/edge_tracker_cli.py rebuild-index
```

## Scheduler Integration

The tracker runs every 15 minutes via the scheduler. The integration follows these rules:

1. **If tracker fails:**
   - Log the error
   - **DO NOT** block trading
   - **DO NOT** retry automatically

2. **If data is missing:**
   - Skip that position
   - Write nothing
   - Log a warning

3. **Deduplication:**
   - Only one snapshot per position per minute
   - Duplicate writes are silently skipped

## Storage Rules

1. **JSONL format** - One JSON object per line
2. **Append-only** - Never modify existing records
3. **One snapshot per position per minute** - Deduplication enforced
4. **Atomic writes** - Line + newline written together
5. **Canonical JSON** - Sorted keys, no whitespace for hashing

## Safety Guarantees

### Fail-Closed Principle

If anything is unclear, ambiguous, or invalid → **write NOTHING**.

This includes:
- Missing position data
- Missing market snapshots
- Invalid probabilities
- Network errors

### Module Removal

The Edge Evolution Tracker can be completely removed without affecting:
- Trading behavior
- Position management
- Decision making
- Execution logic

This is the ultimate test of its governance compliance.

## Mental Model

```
┌─────────────────────────────────────────────────────────────┐
│                    Edge Evolution Tracker                    │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  INPUT (READ-ONLY):                                         │
│  - Open positions from Position Manager                     │
│  - Current market prices from Snapshot Client               │
│                                                              │
│  PROCESSING:                                                │
│  - Calculate edge relative to entry                         │
│  - Calculate edge delta since entry                         │
│                                                              │
│  OUTPUT (APPEND-ONLY):                                      │
│  - EdgeSnapshot records to JSONL file                       │
│                                                              │
│  ❌ DOES NOT:                                               │
│  - Trigger exits                                            │
│  - Modify positions                                         │
│  - Send signals                                             │
│  - Change parameters                                        │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

## Governance Compliance Checklist

- [x] No imports from decision_engine
- [x] No imports from execution_engine
- [x] No imports from panic modules
- [x] No imports from learning modules
- [x] Append-only storage
- [x] Fail-closed on missing data
- [x] Removable without affecting trading
- [x] No exit signals generated
- [x] No parameter modifications
- [x] Explicit governance notices in schema
