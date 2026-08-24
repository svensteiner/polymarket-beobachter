# Structural Arbitrage — Paper Trading

**Generiert:** 2026-08-24T13:07:34.884941+00:00  

> PAPER ONLY — model-free complete-set / binary-lock after real CLOB asks + taker fees. Cash if no net edge. Kein Live-Order. Active-leg filter + ask coverage >= 0.92.

## Scan

- Scanned partitions/markets: **102**
- Complete partitions: **11**
- Candidates (prefilter): **8**
- Rejected (cost/net < MIN_NET): **7**
- Book fetches: **45**
- Skip counts: `budget=1, cost_negative=7, legs_out_of_range=1, no_real_book=1, prefilter=3, residual_other=90`
- Legs out-of-range hist: `n=13:1`

## Near-miss nets (closest to MIN_NET)

  - BINARY_LOCK | net=-0.001399 gap=0.011399 | Lecornu out as French PM by...?
  - BINARY_LOCK | net=-0.001558 gap=0.011558 | Putin out as President of Russia by...?
  - BUY_NO_SET | net=-0.023492 gap=0.033492 | OpenAI IPO Closing Market Cap
  - BUY_YES_SET | net=-0.0575 gap=0.0675 | How many Gold Cards will Trump sell in 2026?
  - BUY_YES_SET | net=-0.059869 gap=0.069869 | How many different countries will the US conduct military action against in 2026
  - BUY_NO_SET | net=-0.120935 gap=0.130935 | GDP growth in 2026
  - BUY_YES_SET | net=-0.209314 gap=0.219314 | How many people will Trump deport in 2026?

## Ledger

- Positionen: **1** (offen 1, aufgelöst 0)
- Offenes Notional: **5.00 EUR**
- Realisiertes Paper-P&L: **+0.00 EUR**
- Entered this cycle: **0**
- Closed this cycle: **0**

---
*PAPER ONLY — no live order*
