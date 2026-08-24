# Structural Arbitrage — Paper Trading

**Generiert:** 2026-08-24T13:01:08.538311+00:00  

> PAPER ONLY — model-free complete-set / binary-lock after real CLOB asks + taker fees. Cash if no net edge. Kein Live-Order. Active-leg filter + ask coverage >= 0.92.

## Scan

- Scanned partitions/markets: **99**
- Complete partitions: **86**
- Candidates (prefilter): **32**
- Rejected (cost/net < MIN_NET): **15**
- Book fetches: **30**
- Skip counts: `budget=18, cost_negative=15, duplicate=1, legs_out_of_range=13, prefilter=53`
- Legs out-of-range hist: `n=13:1, n=14:2, n=18:2, n=20:1, n=22:1, n=23:1, n=31:1, n=41:1, n=43:1, n=51:1, n=52:1`

## Near-miss nets (closest to MIN_NET)

  - BUY_YES_SET | net=0.001329 gap=0.008671 | Oregon Senate Election Winner
  - BUY_YES_SET | net=0.00028 gap=0.00972 | New Mexico Governor Election Winner
  - BUY_YES_SET | net=-0.001595 gap=0.011595 | Hawaii Governor Election Winner
  - BUY_YES_SET | net=-0.002626 gap=0.012626 | Massachusetts Governor Election Winner
  - BUY_YES_SET | net=-0.004806 gap=0.014806 | Colorado Senate Election Winner
  - BUY_YES_SET | net=-0.006354 gap=0.016354 | West Virginia Senate Election Winner
  - BUY_YES_SET | net=-0.006956 gap=0.016956 | Wyoming Senate Election Winner
  - BUY_YES_SET | net=-0.009364 gap=0.019364 | Oklahoma Senate Election Winner

## Ledger

- Positionen: **1** (offen 1, aufgelöst 0)
- Offenes Notional: **5.00 EUR**
- Realisiertes Paper-P&L: **+0.00 EUR**
- Entered this cycle: **0**
- Closed this cycle: **0**

---
*PAPER ONLY — no live order*
