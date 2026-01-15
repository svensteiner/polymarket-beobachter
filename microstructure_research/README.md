# Microstructure Research Module (LAYER 2)

## CRITICAL GOVERNANCE NOTICE

```
╔═══════════════════════════════════════════════════════════════════════════╗
║                                                                           ║
║               THIS MODULE HAS ZERO DECISION AUTHORITY                     ║
║                                                                           ║
║  This is a RESEARCH-ONLY module. It cannot and must not:                  ║
║  - Recommend trades                                                       ║
║  - Rank markets                                                           ║
║  - Suggest capital allocation                                             ║
║  - Influence Layer 1 decisions                                            ║
║                                                                           ║
╚═══════════════════════════════════════════════════════════════════════════╝
```

## Purpose

This module studies Polymarket orderbook mechanics, spreads, and liquidity patterns
purely for research and understanding purposes. It answers questions like:

- How do spreads behave across different market types?
- What are typical liquidity patterns?
- How does orderbook depth correlate with market characteristics?

## Layer Separation

This module is **LAYER 2** in the governed architecture:

| Layer | Purpose | Authority |
|-------|---------|-----------|
| Layer 1 (core_analyzer) | Structural tradeability analysis | FINAL decision power |
| **Layer 2 (this module)** | Microstructure research | **NONE** |

### Import Restrictions

- This module **CANNOT** import from `core_analyzer/`
- This module **CANNOT** import execution libraries
- Violations will cause a hard runtime failure

## Allowed Outputs

✅ Spread distributions
✅ Liquidity histograms
✅ Orderbook depth statistics
✅ Volume pattern analysis
✅ Market mechanic observations

## Prohibited Outputs

❌ Trade recommendations
❌ Market rankings
❌ Allocation suggestions
❌ Signals
❌ Entry/exit points
❌ Position sizing

## Usage

```bash
# Analyze spread distributions
python -m microstructure_research.run --analysis spread

# Generate liquidity report
python -m microstructure_research.run --analysis liquidity

# Full orderbook study
python -m microstructure_research.run --analysis orderbook
```

## Data Sources

This module uses the cloned `am4d3us/polymarket-backtest` repository located at:
`./repro gekloned/`

The backtest repository is used in **READ-ONLY** mode for understanding market
mechanics. No modifications should be made to that code.

## Code Organization

```
microstructure_research/
├── __init__.py       # Layer guard enforcement
├── README.md         # This file
├── research/         # Research modules
│   ├── __init__.py
│   ├── spread_analysis.py
│   ├── liquidity_study.py
│   └── orderbook_stats.py
└── run.py           # CLI entry point
```

## Governance Checklist

Before any code change to this module, verify:

- [ ] Change does not add decision-making logic
- [ ] Change does not import from core_analyzer/
- [ ] Change does not generate trade recommendations
- [ ] Change does not rank or score markets for trading
- [ ] Output is purely observational/statistical

## Contact

This module is governed by the Polymarket Beobachter architecture.
Any questions about governance should be directed to system architects.
