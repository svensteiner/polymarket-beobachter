# Structural Arbitrage — Paper Trading

**Generiert:** 2026-08-30T05:37:38.803061+00:00  

> PAPER ONLY — model-free complete-set / binary-lock after real CLOB asks + taker fees. Cash if no net edge. Kein Live-Order. Active-leg filter + ask coverage >= 0.92.

## Scan

- Scanned partitions/markets: **103**
- Complete partitions: **12**
- Candidates (prefilter): **9**
- Rejected (cost/net < MIN_NET): **7**
- Book fetches: **45**
- Skip counts: `budget=1, cost_negative=7, legs_out_of_range=1, no_real_book=2, prefilter=3, residual_other=90`
- Legs out-of-range hist: `n=13:1`

## Near-miss nets (closest to MIN_NET)

  - BINARY_LOCK | net=-0.00124 gap=0.01124 | Putin out as President of Russia by...?
  - BINARY_LOCK | net=-0.00124 gap=0.01124 | Ukraine election called by...?
  - BUY_YES_SET | net=-0.030679 gap=0.040679 | Balance of Power: 2026 Midterms
  - BUY_YES_SET | net=-0.086762 gap=0.096762 | How many Gold Cards will Trump sell in 2026?
  - BUY_NO_SET | net=-0.107763 gap=0.117763 | How many different countries will the US conduct military action against in 2026
  - BUY_NO_SET | net=-0.130091 gap=0.140091 | GDP growth in 2026
  - BUY_YES_SET | net=-0.247216 gap=0.257216 | How many people will Trump deport in 2026?

## Ledger

- Positionen: **1** (offen 1, aufgelöst 0)
- Offenes Notional: **5.00 EUR**
- Realisiertes Paper-P&L: **+0.00 EUR**
- Entered this cycle: **0**
- Closed this cycle: **0**

---
*PAPER ONLY — no live order*
