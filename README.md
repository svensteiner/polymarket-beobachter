# Polymarket Beobachter

## Governed Multi-Layer Decision Quality & Market Structure Research System

---

## How to Run (60 Seconds)

**ONE COMMAND. ONE ENTRY POINT.**

```bash
python cockpit.py
```

That's it. The cockpit handles everything.

### Interactive Menu

```
Menu:
  1) Run pipeline now      # Collector -> Analyzer -> Proposals -> Paper
  2) Show status           # Quick summary
  3) Show latest proposal  # Last trade candidate
  4) Show paper trading    # Positions and P&L
  5) Open logs folder      # Where to find logs
  6) Exit
```

### Scheduled/Automated Runs

```bash
# Run pipeline once, exit with status code
python cockpit.py --run-once

# Just show status
python cockpit.py --status
```

Exit codes: `0`=OK, `2`=Degraded, `1`=Fail

### What Happens When You Run the Pipeline

1. **Collector**: Fetches EU/AI market metadata (no prices)
2. **Analyzer**: Determines TRADE / NO_TRADE / INSUFFICIENT_DATA
3. **Proposals**: Generates and reviews proposals (append-only)
4. **Paper Trader**: Simulates positions (no real money)
5. **Status**: Writes summary to `output/status_summary.txt`

All governance protections remain active. No live trading. Human review required.

---

**THIS IS NOT A TRADING BOT.**
**THIS IS NOT A PROFIT-OPTIMIZATION SYSTEM.**

This is a **decision-quality** and **market-structure research system** with strict governance.

---

## Architecture Overview

This system operates **TWO STRICTLY SEPARATED LAYERS**:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                                                                             │
│  LAYER 1 — INSTITUTIONAL / PROCESS EDGE (CORE)                              │
│  ═══════════════════════════════════════════════                            │
│                                                                             │
│  Purpose: Evaluate whether a market is STRUCTURALLY TRADEABLE               │
│  Focus: EU regulation, AI Act, tech governance, deadlines                   │
│                                                                             │
│  RULES:                                          OUTPUT:                    │
│  ✓ Deterministic                                 ┌───────────────────┐      │
│  ✓ Fail-closed                                   │ TRADE             │      │
│  ✗ NO prices                                     │ NO_TRADE          │      │
│  ✗ NO volumes                                    │ INSUFFICIENT_DATA │      │
│  ✗ NO probabilities                              └───────────────────┘      │
│  ✗ NO PnL                                                                   │
│  ✗ NO ML/AI                                      AUTHORITY: FINAL           │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘

           ║ STRICT ISOLATION - NO CROSS-IMPORTS ║

┌─────────────────────────────────────────────────────────────────────────────┐
│                                                                             │
│  LAYER 2 — MICROSTRUCTURE / EXECUTION RESEARCH (SATELLITE)                  │
│  ═════════════════════════════════════════════════════════                  │
│                                                                             │
│  Purpose: Study orderbook mechanics, spreads, liquidity patterns            │
│  Focus: Understanding HOW Polymarket behaves (not WHAT to trade)            │
│                                                                             │
│  RULES:                                          OUTPUT:                    │
│  ✗ NO decision authority                         ┌───────────────────┐      │
│  ✗ NO capital allocation                         │ Statistics        │      │
│  ✗ NO trade recommendations                      │ Observations      │      │
│  ✗ NO market rankings                            │ Distributions     │      │
│  ✗ NO coupling to Layer 1                        └───────────────────┘      │
│                                                                             │
│                                                  AUTHORITY: NONE            │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Directory Structure

```
polymarket_beobachter/
│
├── core_analyzer/              # LAYER 1 - Institutional/Process Edge
│   ├── __init__.py            # Layer guard enforcement
│   ├── analyzer.py            # Main analyzer orchestrator
│   ├── run.py                 # CLI entry point
│   ├── core/                  # Analysis modules
│   │   ├── resolution_parser.py
│   │   ├── process_model.py
│   │   ├── time_feasibility.py
│   │   ├── probability_estimator.py
│   │   ├── market_sanity.py
│   │   └── decision_engine.py
│   ├── models/                # Data models
│   │   └── data_models.py
│   └── historical/            # Historical/counterfactual testing
│       ├── runner.py
│       ├── cases.py
│       ├── models.py
│       └── reports.py
│
├── collector/                  # Market discovery (metadata only)
│   ├── __init__.py
│   ├── __main__.py            # CLI entry point
│   ├── client.py              # Polymarket API client
│   ├── sanitizer.py           # Strips prices/volumes/probabilities
│   ├── filter.py              # EU + AI relevance filtering
│   ├── normalizer.py          # Data normalization
│   └── storage.py             # Persistence
│
├── microstructure_research/    # LAYER 2 - Research only
│   ├── __init__.py            # Layer guard enforcement
│   ├── README.md              # ZERO DECISION AUTHORITY notice
│   ├── run.py                 # CLI entry point
│   └── research/              # Research modules
│       ├── spread_analysis.py
│       ├── liquidity_study.py
│       └── orderbook_stats.py
│
├── shared/                     # Shared utilities (both layers)
│   ├── __init__.py
│   ├── enums.py               # Shared type definitions
│   ├── layer_guard.py         # Layer isolation enforcement
│   └── logging_config.py      # Separated logging
│
├── logs/                       # Log directories (separated by layer)
│   ├── layer1/
│   ├── layer2/
│   └── audit/
│
└── output/                     # Output directories (separated by layer)
    ├── layer1/
    └── layer2/
```

## CLI Commands

### Layer 1: Core Analyzer

```bash
# Run analysis with config file
python -m core_analyzer.run --config <market.json>

# Run example analysis
python -m core_analyzer.run --example
```

### Collector (Metadata Discovery)

```bash
# Discover EU + AI markets (NO prices collected)
python -m collector --max 200

# Dry run (report only)
python -m collector --max 100 --dry-run
```

### Historical Testing (Layer 1)

```bash
# Run all historical test cases
python -m core_analyzer.historical.run --all

# Run specific case
python -m core_analyzer.historical.run --case <case_id>
```

### Layer 2: Microstructure Research

```bash
# Spread analysis (RESEARCH ONLY - NO TRADE RECOMMENDATIONS)
python -m microstructure_research.run --analysis spread

# Liquidity study
python -m microstructure_research.run --analysis liquidity

# Orderbook statistics
python -m microstructure_research.run --analysis orderbook
```

## Layer Isolation

The system enforces strict layer isolation at runtime:

- **Layer 1 CANNOT import from Layer 2**
- **Layer 2 CANNOT import from Layer 1**
- Violations cause immediate hard failure

This is enforced by `shared/layer_guard.py` which checks `sys.modules` at import time.

## Governance Rules

### Explicit Prohibitions

1. **NO cross-layer influence**
   - Layer 2 research cannot affect Layer 1 decisions
   - No "microstructure signals" feeding into tradeability

2. **NO execution logic**
   - Neither layer contains trade execution code
   - No order placement
   - No position management

3. **NO price-based decisions**
   - Layer 1 operates on structural factors only
   - Market prices used only for sanity check threshold

   **Price-Derived Data Policy:**
   The `market_implied_probability` field in MarketInput IS derived from market prices.
   However, it is explicitly LIMITED to the sanity check comparison (15 percentage point
   divergence threshold). It does NOT influence the core TRADE/NO_TRADE decision, which
   is based purely on: resolution quality, timeline feasibility, and EU process stage.
   This is a deliberate design choice documented in `core_analyzer/models/data_models.py`.

4. **NO learning loops**
   - No parameter optimization based on outcomes
   - No self-modification
   - Human review required for any changes

### Logging & Audit

- All decisions logged to `logs/audit/`
- Layer-separated operational logs
- JSON-lines format for audit records

## Configuration Files

### Market Configuration (for Layer 1 analysis)

```json
{
    "market_title": "Will the EU AI Act be enforced by March 2025?",
    "resolution_text": "This market resolves to YES if...",
    "target_date": "2025-03-31",
    "referenced_regulation": "EU AI Act",
    "authority_involved": "European Commission",
    "market_implied_probability": 0.35,
    "notes": "Optional notes"
}
```

## System Question

This system exists to answer ONE question:

> **"Should we even be ALLOWED to trade this market?"**

It does NOT answer:
- "Will this market resolve YES or NO?"
- "What position should we take?"
- "How much should we allocate?"

Those questions are OUT OF SCOPE.

## Engineering Standards

- Windows-compatible paths
- Deterministic behavior
- Clear logging
- No hidden coupling
- Code readable by auditors
- Clarity > cleverness

## What This System Does NOT Do

- ML/AI predictions
- Strategy optimization
- Dashboard/visualization
- Capital allocation
- Execution logic
- Price-based signals
- Sentiment analysis

---

*This system is governed by strict architectural boundaries.*
*Any modifications must maintain layer separation.*
*When in doubt, default to NO_TRADE.*
