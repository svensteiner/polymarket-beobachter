# Structural Arbitrage — Paper Trading

**Generiert:** 2026-08-27T23:35:33.666999+00:00  

> PAPER ONLY — model-free complete-set / binary-lock after real CLOB asks + taker fees. Cash if no net edge. Kein Live-Order. Active-leg filter + ask coverage >= 0.92.

## Scan

- Scanned partitions/markets: **107**
- Complete partitions: **16**
- Candidates (prefilter): **12**
- Rejected (cost/net < MIN_NET): **11**
- Book fetches: **44**
- Skip counts: `binary_cap=1, cost_negative=11, legs_out_of_range=1, no_real_book=1, prefilter=4, residual_other=90`
- Legs out-of-range hist: `n=13:1`

## Near-miss nets (closest to MIN_NET)

  - BINARY_LOCK | net=-0.00124 gap=0.01124 | Putin out as President of Russia by...?
  - BINARY_LOCK | net=-0.00124 gap=0.01124 | Ukraine election called by...?
  - BINARY_LOCK | net=-0.00124 gap=0.01124 | Will US withdraw from NATO by...?
  - BINARY_LOCK | net=-0.001399 gap=0.011399 | Lecornu out as French PM by...?
  - BINARY_LOCK | net=-0.002637 gap=0.012637 | Putin and Zelenskyy shake hands by...?
  - BINARY_LOCK | net=-0.003716 gap=0.013716 | Who will Bernie endorse?
  - BINARY_LOCK | net=-0.004954 gap=0.014954 | Which candidates will advance to Brazil's presidential runoff?
  - BUY_YES_SET | net=-0.020431 gap=0.030431 | Balance of Power: 2026 Midterms

## Ledger

- Positionen: **1** (offen 1, aufgelöst 0)
- Offenes Notional: **5.00 EUR**
- Realisiertes Paper-P&L: **+0.00 EUR**
- Entered this cycle: **0**
- Closed this cycle: **0**

---
*PAPER ONLY — no live order*
