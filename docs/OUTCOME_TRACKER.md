# Outcome Tracker

## Purpose

The Outcome Tracker is the **foundation of the learning system**. It records predictions and their actual outcomes to enable calibration analysis over time.

**This module records FACTS only. It does NOT influence trading decisions.**

## Critical Isolation Statement

```
+---------------------------------------------------------------------+
|                    THIS MODULE IS ISOLATED                           |
|                                                                     |
|  It CANNOT:                                                         |
|    - Modify trading parameters or thresholds                        |
|    - Influence decision engine behavior                             |
|    - Place or modify trades                                         |
|    - Import from decision_engine or panic_contrarian_engine         |
|                                                                     |
|  It CAN only:                                                       |
|    - Record prediction snapshots (append-only)                      |
|    - Record market resolutions (append-only)                        |
|    - Record corrections (append-only, never modify originals)       |
|    - Generate statistics and indexes                                |
|                                                                     |
|  FAIL-CLOSED: If anything is unclear -> write nothing.              |
+---------------------------------------------------------------------+
```

## Storage Structure

```
data/outcomes/
├── predictions.jsonl   # Append-only prediction records
├── resolutions.jsonl   # Append-only resolution records
├── corrections.jsonl   # Append-only correction records
└── index.json          # Derived index (rebuildable)
```

### Append-Only Guarantee

Once a record is written to a JSONL file:
- It is **never modified**
- It is **never deleted**
- Corrections are recorded as separate entries
- The index applies corrections during rebuild

## Data Schema

### PredictionSnapshot (Schema Version 1)

```json
{
  "schema_version": 1,
  "event_id": "<uuid4>",
  "timestamp_utc": "2026-01-15T12:34:56.789Z",
  "market_id": "0x1234...",
  "question": "Will X happen by Y?",
  "outcomes": ["YES", "NO"],
  "market_price_yes": 0.65,
  "market_price_no": 0.35,
  "our_estimate_yes": 0.70,
  "estimate_confidence": "MEDIUM",
  "decision": "TRADE",
  "decision_reasons": ["All criteria passed"],
  "engine_context": {
    "engine": "baseline",
    "mode": "SHADOW",
    "run_id": "scheduler_abc12345"
  },
  "source": "scheduler",
  "record_hash": "<sha256>"
}
```

| Field | Type | Description |
|-------|------|-------------|
| `schema_version` | int | Always 1 (current version) |
| `event_id` | string | Unique UUID for this record |
| `timestamp_utc` | string | ISO8601 timestamp in UTC |
| `market_id` | string | Polymarket market/condition ID |
| `question` | string | Market question text |
| `outcomes` | list | Possible outcomes (usually ["YES", "NO"]) |
| `market_price_yes` | float\|null | Market price for YES (0-1) |
| `market_price_no` | float\|null | Market price for NO (0-1) |
| `our_estimate_yes` | float\|null | Our probability estimate (0-1) |
| `estimate_confidence` | string\|null | LOW, MEDIUM, HIGH, or null |
| `decision` | string | TRADE, NO_TRADE, or INSUFFICIENT_DATA |
| `decision_reasons` | list | Reasons for the decision |
| `engine_context` | object | Engine, mode, and run information |
| `source` | string | "scheduler", "cli", or "manual" |
| `record_hash` | string | SHA256 of canonical JSON |

### ResolutionRecord (Schema Version 1)

```json
{
  "schema_version": 1,
  "event_id": "<uuid4>",
  "timestamp_utc": "2026-01-20T00:00:00Z",
  "market_id": "0x1234...",
  "resolved": true,
  "resolution": "YES",
  "resolution_source": "gamma-api.polymarket.com/markets",
  "resolved_timestamp_utc": "2026-01-19T23:59:59Z",
  "record_hash": "<sha256>"
}
```

| Field | Type | Description |
|-------|------|-------------|
| `resolution` | string | YES, NO, INVALID, CANCELLED, or AMBIGUOUS |
| `resolution_source` | string | API endpoint or URL where resolution was found |
| `resolved_timestamp_utc` | string\|null | When the market actually resolved |

### CorrectionRecord (Schema Version 1)

```json
{
  "schema_version": 1,
  "event_id": "<uuid4>",
  "timestamp_utc": "2026-01-21T10:00:00Z",
  "target_event_id": "<uuid4 of record to correct>",
  "reason": "Incorrect market_id recorded",
  "patch": {
    "market_id": "0x5678..."
  },
  "record_hash": "<sha256>"
}
```

Corrections **never modify original records**. They are applied during index rebuild.

## CLI Usage

### Show Statistics

```bash
python tools/outcome_tracker_cli.py stats
```

Output:
```
==================================================
OUTCOME TRACKER STATISTICS
==================================================

Total Predictions:  150
Total Resolutions:  45
Total Corrections:  2

Unique Markets Predicted: 150
Resolved Markets:         45
Unresolved Markets:       105
Coverage:                 30.0%

Decisions:
  INSUFFICIENT_DATA: 50
  NO_TRADE: 80
  TRADE: 20

Resolutions:
  NO: 20
  YES: 25
```

### Capture Prediction Snapshots

```bash
python tools/outcome_tracker_cli.py snapshot-now
python tools/outcome_tracker_cli.py snapshot-now --limit 50 --verbose
```

This captures predictions from today's analyzed candidates.

### Update Resolutions

```bash
python tools/outcome_tracker_cli.py update-resolutions
python tools/outcome_tracker_cli.py update-resolutions --limit 20
```

Checks unresolved markets via API and records any new resolutions.

### Rebuild Index

```bash
python tools/outcome_tracker_cli.py rebuild-index
```

Rebuilds `index.json` from the JSONL files, applying any corrections.

### List Unresolved Markets

```bash
python tools/outcome_tracker_cli.py list-unresolved
python tools/outcome_tracker_cli.py list-unresolved --limit 50
```

Shows markets with predictions but no recorded resolution.

### Verify Hashes

```bash
python tools/outcome_tracker_cli.py verify-hashes
```

Checks all record hashes for integrity.

## Scheduler Integration

The outcome tracker runs automatically as **Step 6** in the pipeline:

```
[1/7] Fetching market data from Polymarket
[2/7] Analyzing candidates for trade signals
[3/7] Generating and reviewing proposals
[4/7] Updating paper trading positions
[5/7] Cross-market consistency research
[6/7] Recording predictions for calibration     <-- Outcome Tracker
[7/7] Writing status summary
```

### What the Scheduler Does

1. **Records Predictions**: For each analyzed candidate, records:
   - Market ID and question
   - Decision (TRADE/NO_TRADE/INSUFFICIENT_DATA)
   - Market prices (if available)
   - Decision reasons

2. **Updates Resolutions**: Checks up to 10 unresolved markets per run
   - Only fetches from API, never writes to API
   - Records any new resolutions found

### Non-Blocking Behavior

The outcome tracker **never blocks trading**:
- If tracking fails, the pipeline continues
- Errors are logged but don't affect trading decisions
- The step is marked as "success" even on errors (to not degrade pipeline state)

## Understanding index.json

The index is a convenience structure for quick lookups:

```json
{
  "schema_version": 1,
  "built_at": "2026-01-15T12:00:00Z",
  "stats": {
    "total_predictions": 150,
    "total_resolutions": 45,
    "coverage_pct": 30.0,
    ...
  },
  "entries": [
    {
      "market_id": "0x1234...",
      "predictions": [...],
      "resolution": {...},
      "has_resolution": true
    },
    ...
  ]
}
```

**Important**: The index can always be rebuilt from the JSONL files. If it becomes corrupted, simply run:

```bash
python tools/outcome_tracker_cli.py rebuild-index
```

## Deduplication Rules

### Predictions

A prediction is considered a duplicate if it has the same:
- `market_id`
- Minute bucket of timestamp (e.g., 2026-01-15T12:34)
- `engine`
- `decision`

Duplicates are silently skipped.

### Resolutions

Only **one resolution per market_id** is allowed. Subsequent resolution attempts are rejected.

## Hash Verification

Every record includes a `record_hash` computed as:

1. Remove `record_hash` field from data
2. Convert to canonical JSON (sorted keys, no whitespace)
3. Compute SHA256 hash

This allows verification of record integrity:

```bash
python tools/outcome_tracker_cli.py verify-hashes
```

## Example JSONL Records

### predictions.jsonl

```json
{"schema_version":1,"event_id":"550e8400-e29b-41d4-a716-446655440000","timestamp_utc":"2026-01-15T12:34:56.789Z","market_id":"0x1234567890abcdef","question":"Will Bitcoin reach $100k by March 2026?","outcomes":["YES","NO"],"market_price_yes":0.45,"market_price_no":0.55,"our_estimate_yes":null,"estimate_confidence":null,"decision":"NO_TRADE","decision_reasons":["Blocked: insufficient_resolution_clarity"],"engine_context":{"engine":"baseline","mode":"SHADOW","run_id":"scheduler_abc12345"},"source":"scheduler","record_hash":"a1b2c3d4e5f6..."}
{"schema_version":1,"event_id":"660e8400-e29b-41d4-a716-446655440001","timestamp_utc":"2026-01-15T12:35:00.123Z","market_id":"0xfedcba0987654321","question":"Will EU AI Act enforcement begin by Q1 2026?","outcomes":["YES","NO"],"market_price_yes":0.72,"market_price_no":0.28,"our_estimate_yes":0.85,"estimate_confidence":"HIGH","decision":"TRADE","decision_reasons":["All criteria passed"],"engine_context":{"engine":"baseline","mode":"SHADOW","run_id":"scheduler_abc12345"},"source":"scheduler","record_hash":"f6e5d4c3b2a1..."}
```

### resolutions.jsonl

```json
{"schema_version":1,"event_id":"770e8400-e29b-41d4-a716-446655440002","timestamp_utc":"2026-01-20T00:00:00Z","market_id":"0xfedcba0987654321","resolved":true,"resolution":"YES","resolution_source":"gamma-api.polymarket.com/markets","resolved_timestamp_utc":"2026-01-19T23:59:59Z","record_hash":"1a2b3c4d5e6f..."}
```

## Future: Calibration Analysis

This data enables future calibration analysis:

1. **Accuracy by Decision**: How often do TRADE decisions lead to correct outcomes?
2. **Confidence Calibration**: Are HIGH confidence predictions more accurate?
3. **Category Performance**: Which market categories have better prediction accuracy?
4. **Edge Realization**: When we estimate 70% and market says 50%, how often do we win?

**These analyses will be implemented in future modules.** The Outcome Tracker only records the raw data.

## Safety Guarantees

| Guarantee | Implementation |
|-----------|----------------|
| No side effects on trading | Zero imports from decision code |
| Append-only storage | Never modify, only append |
| Deterministic hashing | Canonical JSON + SHA256 |
| Fail-closed | Any error = write nothing |
| Non-blocking | Pipeline continues on errors |
| Full audit trail | Every record has timestamp + hash |
