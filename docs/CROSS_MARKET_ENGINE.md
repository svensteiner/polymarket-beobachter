# Cross-Market Consistency Engine

## Purpose

The Cross-Market Consistency Engine detects logical inconsistencies between prediction markets. It is a **research tool** that observes market prices and identifies potential mispricings based on logical relationships.

## Critical Isolation Statement

```
┌─────────────────────────────────────────────────────────────────────┐
│                    THIS ENGINE IS SANDBOXED                         │
│                                                                     │
│  It CANNOT:                                                         │
│    ✗ Place trades                                                   │
│    ✗ Modify trading parameters                                      │
│    ✗ Influence decision engine thresholds                           │
│    ✗ Trigger execution of any kind                                  │
│    ✗ Call back into trading code                                    │
│                                                                     │
│  It CAN only:                                                       │
│    ✓ Read market probabilities (passed as input)                    │
│    ✓ Check logical consistency                                      │
│    ✓ Log findings to a separate file                                │
│                                                                     │
│  If this engine disappeared tomorrow,                               │
│  the trading system would behave IDENTICALLY.                       │
└─────────────────────────────────────────────────────────────────────┘
```

## Why It Cannot Place Trades

1. **Zero imports from trading code**: The engine has no access to `decision_engine`, `execution_engine`, `panic_engine`, or any trading-related code.

2. **No callbacks**: There are no hooks, events, or callbacks that connect to trading systems.

3. **No signal emission**: The engine does not emit BUY, SELL, or TRADE signals. Findings are informational only.

4. **Read-only data**: Market data must be passed in explicitly. The engine cannot fetch or modify market state.

5. **Isolated logging**: Findings go to `cross_market_engine/logs/findings.jsonl`, separate from trading logs.

## Architecture

```
cross_market_engine/
├── __init__.py           # Module definition + isolation statement
├── relations.py          # Relation types (IMPLIES only in Phase 1)
├── market_graph.py       # Market nodes + relations graph
├── consistency_check.py  # Pure logic evaluation
├── findings.py           # Structured finding objects
├── runner.py             # Manual / scheduled execution
└── logs/
    └── findings.jsonl    # Output log (JSONL format)
```

## Relation Types

### Phase 1: IMPLIES Only

The `IMPLIES` relation represents logical implication between markets:

```
Market A IMPLIES Market B

Meaning: If A resolves YES, then B MUST resolve YES
Logic:   P(A) <= P(B) must hold
Rule:    If P(A) > P(B) + tolerance → INCONSISTENT
```

**Example:**
- Market A: "Will X happen by December 2025?"
- Market B: "Will X happen by December 2026?"
- A IMPLIES B (if it happens by 2025, it definitely happens by 2026)

If P(A) = 60% and P(B) = 40%, this is **inconsistent** because the earlier deadline has a higher probability than the later one.

### Tolerance

The tolerance parameter allows for small deviations due to:
- Bid-ask spreads
- Market maker fees
- Temporary price discrepancies

**Default: 5%**

A relation is flagged as INCONSISTENT only if:
```
P(A) > P(B) + tolerance
```

## Consistency Status

| Status | Meaning |
|--------|---------|
| `CONSISTENT` | The relation holds within tolerance |
| `INCONSISTENT` | The relation is violated beyond tolerance |
| `UNCLEAR` | Cannot determine (missing data, edge cases) |

**Fail-Closed Principle:** If there's any ambiguity, the result is `UNCLEAR`, not `INCONSISTENT`. We never want false positives.

## Finding Format

Each finding includes:

```json
{
  "finding_id": "finding_abc123",
  "timestamp": "2026-01-23T20:00:00Z",
  "market_a_id": "event_by_2025",
  "market_b_id": "event_by_2026",
  "relation_type": "IMPLIES",
  "p_a": 0.60,
  "p_b": 0.40,
  "delta": 0.20,
  "tolerance": 0.05,
  "status": "INCONSISTENT",
  "explanation": "INCONSISTENT: Market A (60.0%) implies Market B (40.0%), but P(A) > P(B) by 20.0% (exceeds 5% tolerance)."
}
```

## Usage

### Run Demo

```bash
python -m cross_market_engine.runner --demo
```

Output:
```
============================================================
CROSS-MARKET CONSISTENCY ENGINE
Research Tool - DOES NOT PLACE TRADES
============================================================

Consistency Check Summary (Run: run_abc123)
Timestamp: 2026-01-23T20:00:00
Relations Checked: 4
  - Consistent: 3
  - Inconsistent: 1
  - Unclear: 0

INCONSISTENCIES DETECTED:
  [!!] specific_event -> general_event: P(A)=60.00%, P(B)=40.00%, delta=+20.00%
```

### Run with Custom Data

Create a JSON file:

```json
{
  "markets": [
    {
      "market_id": "market_a",
      "question": "Will A happen?",
      "probability": 0.65
    },
    {
      "market_id": "market_b",
      "question": "Will B happen?",
      "probability": 0.80
    }
  ],
  "relations": [
    {
      "market_a_id": "market_a",
      "market_b_id": "market_b",
      "description": "A implies B",
      "tolerance": 0.05
    }
  ]
}
```

Run:
```bash
python -m cross_market_engine.runner --input markets.json
```

### Programmatic Usage

```python
from cross_market_engine.market_graph import MarketGraph, create_market_snapshot
from cross_market_engine.relations import create_implies_relation
from cross_market_engine.consistency_check import check_all_relations

# Build graph
graph = MarketGraph()
graph.add_market(create_market_snapshot("a", "Question A?", 0.65))
graph.add_market(create_market_snapshot("b", "Question B?", 0.80))
graph.add_relation(create_implies_relation("a", "b", "A implies B"))

# Check consistency
summary = check_all_relations(graph)

# Review findings
for finding in summary.findings:
    print(finding.summary())
```

## Limitations

1. **Phase 1 Only**: Only `IMPLIES` relation is supported
2. **Manual Data**: Market data must be provided explicitly
3. **No Automation**: Findings are logged but no automated actions
4. **No Learning**: Tolerance is static, no adaptive thresholds
5. **Research Only**: Designed for observation, not action

## Future Phases (Not Implemented)

Phase 2 might add:
- `MUTEX` (mutually exclusive markets)
- `COMPLEMENT` (probabilities should sum to 1)
- `SUBSET` (one outcome is subset of another)

These are NOT implemented and must maintain the same isolation guarantees.

## Safety Guarantees

| Guarantee | Implementation |
|-----------|----------------|
| No side effects | All functions are pure |
| No mutable shared state | Findings are immutable dataclasses |
| No callbacks into trading | Zero imports from trading code |
| No threshold learning | Tolerance is static configuration |
| No auto-escalation | Findings are logged, never acted upon |

## File Locations

| File | Purpose |
|------|---------|
| `cross_market_engine/logs/findings.jsonl` | Output findings |
| `cross_market_engine/*.py` | Engine code |
| `docs/CROSS_MARKET_ENGINE.md` | This documentation |

## Mental Model

```
This engine is a research microscope.

It observes.
It never acts.

Findings are for human review only.
No automated trading decisions are based on this engine.
```

## Verification

To verify isolation:

```bash
# Should find ZERO imports from trading code
grep -r "from core" cross_market_engine/
grep -r "from execution" cross_market_engine/
grep -r "from panic" cross_market_engine/
grep -r "from governance" cross_market_engine/

# All should return empty results
```
