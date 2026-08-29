# Structural Arbitrage — Paper Trading

**Generiert:** 2026-08-29T05:34:02.443641+00:00  

> PAPER ONLY — model-free complete-set / binary-lock after real CLOB asks + taker fees. Cash if no net edge. Kein Live-Order. Active-leg filter + ask coverage >= 0.92.

## Scan

- Scanned partitions/markets: **104**
- Complete partitions: **13**
- Candidates (prefilter): **10**
- Rejected (cost/net < MIN_NET): **7**
- Book fetches: **45**
- Skip counts: `budget=1, cost_negative=7, legs_out_of_range=1, no_real_book=3, prefilter=3, residual_other=90`
- Legs out-of-range hist: `n=13:1`

## Near-miss nets (closest to MIN_NET)

  - BINARY_LOCK | net=-0.00124 gap=0.01124 | Putin and Zelenskyy shake hands by...?
  - BINARY_LOCK | net=-0.00124 gap=0.01124 | Ukraine election called by...?
  - BUY_NO_SET | net=-0.026673 gap=0.036673 | OpenAI IPO Closing Market Cap
  - BUY_YES_SET | net=-0.030679 gap=0.040679 | Balance of Power: 2026 Midterms
  - BUY_YES_SET | net=-0.085819 gap=0.095819 | How many Gold Cards will Trump sell in 2026?
  - BUY_NO_SET | net=-0.087337 gap=0.097337 | How many people will Trump deport in 2026?
  - BUY_NO_SET | net=-0.124547 gap=0.134547 | GDP growth in 2026

## Ledger

- Positionen: **1** (offen 1, aufgelöst 0)
- Offenes Notional: **5.00 EUR**
- Realisiertes Paper-P&L: **+0.00 EUR**
- Entered this cycle: **0**
- Closed this cycle: **0**

---
*PAPER ONLY — no live order*
