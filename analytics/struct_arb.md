# Structural Arbitrage — Paper Trading

**Generiert:** 2026-08-26T18:38:24.049791+00:00  

> PAPER ONLY — model-free complete-set / binary-lock after real CLOB asks + taker fees. Cash if no net edge. Kein Live-Order. Active-leg filter + ask coverage >= 0.92.

## Scan

- Scanned partitions/markets: **106**
- Complete partitions: **15**
- Candidates (prefilter): **11**
- Rejected (cost/net < MIN_NET): **10**
- Book fetches: **45**
- Skip counts: `budget=1, cost_negative=10, legs_out_of_range=1, no_real_book=1, prefilter=4, residual_other=90`
- Legs out-of-range hist: `n=13:1`

## Near-miss nets (closest to MIN_NET)

  - BINARY_LOCK | net=-0.00124 gap=0.01124 | Will US withdraw from NATO by...?
  - BINARY_LOCK | net=-0.001399 gap=0.011399 | Lecornu out as French PM by...?
  - BINARY_LOCK | net=-0.001558 gap=0.011558 | Ukraine election called by...?
  - BINARY_LOCK | net=-0.002478 gap=0.012478 | Putin out as President of Russia by...?
  - BINARY_LOCK | net=-0.003716 gap=0.013716 | Who will Bernie endorse?
  - BINARY_LOCK | net=-0.004637 gap=0.014637 | Putin and Zelenskyy shake hands by...?
  - BUY_NO_SET | net=-0.033115 gap=0.043115 | OpenAI IPO Closing Market Cap
  - BUY_YES_SET | net=-0.092348 gap=0.102348 | How many Gold Cards will Trump sell in 2026?

## Ledger

- Positionen: **1** (offen 1, aufgelöst 0)
- Offenes Notional: **5.00 EUR**
- Realisiertes Paper-P&L: **+0.00 EUR**
- Entered this cycle: **0**
- Closed this cycle: **0**

---
*PAPER ONLY — no live order*
