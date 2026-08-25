# Structural Arbitrage — Paper Trading

**Generiert:** 2026-08-25T15:27:47.892337+00:00  

> PAPER ONLY — model-free complete-set / binary-lock after real CLOB asks + taker fees. Cash if no net edge. Kein Live-Order. Active-leg filter + ask coverage >= 0.92.

## Scan

- Scanned partitions/markets: **107**
- Complete partitions: **16**
- Candidates (prefilter): **12**
- Rejected (cost/net < MIN_NET): **10**
- Book fetches: **40**
- Skip counts: `binary_cap=1, cost_negative=10, legs_out_of_range=1, no_real_book=1, prefilter=4, residual_other=90, thin_book=1`
- Legs out-of-range hist: `n=13:1`

## Near-miss nets (closest to MIN_NET)

  - BINARY_LOCK | net=-0.001399 gap=0.011399 | Lecornu out as French PM by...?
  - BINARY_LOCK | net=-0.002637 gap=0.012637 | Putin out as President of Russia by...?
  - BINARY_LOCK | net=-0.003716 gap=0.013716 | Who will Bernie endorse?
  - BINARY_LOCK | net=-0.004637 gap=0.014637 | Putin and Zelenskyy shake hands by...?
  - BINARY_LOCK | net=-0.004795 gap=0.014795 | Will Ukraine agree to cede territory to Russia by...?
  - BINARY_LOCK | net=-0.004954 gap=0.014954 | Foreign intervention in Gaza by..?
  - BINARY_LOCK | net=-0.005874 gap=0.015874 | Which candidates will advance to Brazil's presidential runoff?
  - BUY_NO_SET | net=-0.031273 gap=0.041273 | OpenAI IPO Closing Market Cap

## Ledger

- Positionen: **1** (offen 1, aufgelöst 0)
- Offenes Notional: **5.00 EUR**
- Realisiertes Paper-P&L: **+0.00 EUR**
- Entered this cycle: **0**
- Closed this cycle: **0**

---
*PAPER ONLY — no live order*
