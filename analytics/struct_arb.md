# Structural Arbitrage — Paper Trading

**Generiert:** 2026-08-29T20:37:05.634941+00:00  

> PAPER ONLY — model-free complete-set / binary-lock after real CLOB asks + taker fees. Cash if no net edge. Kein Live-Order. Active-leg filter + ask coverage >= 0.92.

## Scan

- Scanned partitions/markets: **107**
- Complete partitions: **16**
- Candidates (prefilter): **11**
- Rejected (cost/net < MIN_NET): **9**
- Book fetches: **40**
- Skip counts: `binary_cap=1, cost_negative=9, legs_out_of_range=1, no_real_book=2, prefilter=5, residual_other=90`
- Legs out-of-range hist: `n=13:1`

## Near-miss nets (closest to MIN_NET)

  - BINARY_LOCK | net=-0.00124 gap=0.01124 | Ukraine election called by...?
  - BINARY_LOCK | net=-0.00124 gap=0.01124 | Putin and Zelenskyy shake hands by...?
  - BINARY_LOCK | net=-0.00124 gap=0.01124 | Will US withdraw from NATO by...?
  - BINARY_LOCK | net=-0.00124 gap=0.01124 | Spain snap election called by...?
  - BINARY_LOCK | net=-0.001399 gap=0.011399 | Lecornu out as French PM by...?
  - BINARY_LOCK | net=-0.003558 gap=0.013558 | Foreign intervention in Gaza by..?
  - BUY_YES_SET | net=-0.087706 gap=0.097706 | How many Gold Cards will Trump sell in 2026?
  - BUY_NO_SET | net=-0.090138 gap=0.100138 | How many people will Trump deport in 2026?

## Ledger

- Positionen: **1** (offen 1, aufgelöst 0)
- Offenes Notional: **5.00 EUR**
- Realisiertes Paper-P&L: **+0.00 EUR**
- Entered this cycle: **0**
- Closed this cycle: **0**

---
*PAPER ONLY — no live order*
