# Structural Arbitrage — Paper Trading

**Generiert:** 2026-08-25T02:23:42.671849+00:00  

> PAPER ONLY — model-free complete-set / binary-lock after real CLOB asks + taker fees. Cash if no net edge. Kein Live-Order. Active-leg filter + ask coverage >= 0.92.

## Scan

- Scanned partitions/markets: **107**
- Complete partitions: **16**
- Candidates (prefilter): **12**
- Rejected (cost/net < MIN_NET): **11**
- Book fetches: **43**
- Skip counts: `binary_cap=1, cost_negative=11, legs_out_of_range=1, no_real_book=1, prefilter=4, residual_other=90`
- Legs out-of-range hist: `n=13:1`

## Near-miss nets (closest to MIN_NET)

  - BINARY_LOCK | net=-0.001399 gap=0.011399 | Lecornu out as French PM by...?
  - BINARY_LOCK | net=-0.001558 gap=0.011558 | Putin out as President of Russia by...?
  - BINARY_LOCK | net=-0.003716 gap=0.013716 | Who will Bernie endorse?
  - BINARY_LOCK | net=-0.004637 gap=0.014637 | Putin and Zelenskyy shake hands by...?
  - BINARY_LOCK | net=-0.005716 gap=0.015716 | Will US withdraw from NATO by...?
  - BINARY_LOCK | net=-0.005874 gap=0.015874 | Which candidates will advance to Brazil's presidential runoff?
  - BINARY_LOCK | net=-0.005874 gap=0.015874 | Will Ukraine agree to cede territory to Russia by...?
  - BUY_NO_SET | net=-0.030353 gap=0.040353 | OpenAI IPO Closing Market Cap

## Ledger

- Positionen: **1** (offen 1, aufgelöst 0)
- Offenes Notional: **5.00 EUR**
- Realisiertes Paper-P&L: **+0.00 EUR**
- Entered this cycle: **0**
- Closed this cycle: **0**

---
*PAPER ONLY — no live order*
