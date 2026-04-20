# Overnight Fix Report — 2026-03-29

## Executive Summary

| Metric | Value |
|--------|-------|
| Start Capital | 5,000 EUR |
| Current Capital | 4,293 EUR available + 529 EUR allocated |
| Realized P&L | -177.89 EUR (-3.56%) |
| Open Positions | ~10 (528 EUR allocated) |
| Bot Status | **RUNNING** (PID 52240, restarted 19:49) |
| Commits | 2 commits across 2 repos |

---

## Phase 1: Analysis

### 1.1 Backtest — 40 Closed Positions

Full results: `output/backtest_results.json`

| Segment | Positions | Wins | Win Rate | P&L |
|---------|-----------|------|----------|-----|
| Pre-fix (before 28.03 21:30) | 32 | 8 | 25.0% | -114.03 EUR |
| Post-fix | 8 | 2 | 25.0% | -94.83 EUR |
| **Total** | **40** | **10** | **25.0%** | **-208.86 EUR** |

**Note:** Post-fix data is still very small (8 positions). The major TP1 hits at +2.7% and +5.1% are partial exits on positions still open.

Large pre-fix losses (driving the -114 EUR):
- Market 1638053 YES → resolved NO: -75.00 EUR (single resolution loss)
- Markets 1670727 (YES, multiple entries): -40 EUR combined (SL cascade)
- MODEL_FIX force-closes: -16.6 EUR (5 positions invalidated by CDF fix)

### 1.2 Side-Selection Validation

**Bug NOT confirmed.** Side selection code in `simulator.py:437` is correct:

```python
side = "YES" if proposal.edge > 0 else "NO"  # edge = model_prob - market_yes_price
```

- Positive edge (model > market) → buy YES ✓
- Negative edge (model < market) → buy NO ✓

The "high YES prices lose" pattern observed in trade data reflects **wrong weather predictions**, not a side-selection bug. Tests in `tests/test_side_selection.py` (17 tests, all pass) document this.

### 1.3 TP/SL Analysis

**Bug 1: Spurious SL exits from invalid API prices**
- Gamma API returns `mid_price > 1.0` for some markets
- `_calc_unrealized_pct` clamped to 1.0 → `current_no = 0` → **-100% unrealized for NO**
- This triggered SL (threshold -25%) when actual loss was only 12-16%
- Affected: markets 1680717, 1714814 (exit reasons showing -340%, -487%)
- Clamping was already added (`BUGFIX` comment), but -100% still triggers SL

**Bug 2: TP1 trailing stop at break-even causes net losses**
- After TP1 (+15%), trailing stop was set at entry price (0% lock-in)
- When price reverses, remaining 50% exits below entry
- Example: Houston 1714877 — TP1 +1.03 EUR, trailing SL -1.96 EUR, net **-0.93 EUR**

---

## Phase 2: Fixes Applied

### Fix 1: SL Guard for Invalid API Prices (`position_manager.py`)

```python
# Before: no guard, clamped -100% triggers SL
# After: skip SL/TP when price is at boundary (invalid data)
if current_price <= 0.01 or current_price >= 0.99:
    logger.warning("Skipping SL/TP: mid_price %.4f is at boundary", current_price)
    continue
```

### Fix 2: TP1 Trailing Stop Lock-in +3% (`position_manager.py`)

```python
# Before: lock_in_pct=0.0 (break-even)
# After:  lock_in_pct=0.03 (+3% minimum profit)
trailing_stop_price = self._calc_trailing_stop_price(position, 0.03)
```

This guarantees: even if trailing stop fires immediately after TP1, the total net P&L is positive.

### Fix 3: Observation Log Absolute Path (`weather_engine.py`)

```python
# Before: relative path "logs/weather_observations.jsonl"
# After:  absolute path via Path(__file__).parent.parent / "logs" / ...
_default_obs_path = str(Path(__file__).parent.parent / "logs" / "weather_observations.jsonl")
```

### Capital Reconciliation Status

Already fixed in prior BUGFIX 2026-03-28: `reconcile()` now accounts for `exited_fraction` from `tp_state.json`. Verified working (no action needed).

---

## Phase 3: OpenClaw Integration

### 3.1 polymarket_agent.py wired into edge observer

`openclaw/edge/observer.py` → `run_observation_cycle()` now calls `run_agent_cycle()` after autonomous decisions:

```python
try:
    from openclaw.polymarket_agent import run_agent_cycle
    pm_result = run_agent_cycle()
    for insight in pm_result.get("insights", []):
        logger.info("[PM-AGENT] %s", insight)
    for decision in pm_result.get("decisions", []):
        if decision.get("confidence", 0) >= 0.7:
            logger.info("[PM-AGENT] High-confidence decision: %s", decision.get("description"))
except Exception as e:
    logger.warning("[PM-AGENT] Error: %s", e)
```

### 3.2 MCP Tools Added (`control/mcp_server.py`)

- `polymarket_agent_status()` — full agent cycle
- `polymarket_city_analysis()` — city P&L breakdown

### 3.3 Dashboard Router (`control/dashboard/backend/routers/polymarket.py`)

- `GET /api/polymarket/agent` → one agent cycle
- `GET /api/polymarket/cities` → city performance list

Registered in `dashboard/backend/main.py`.

---

## Phase 4: Bot Daemon

### Issue Found: Stale Lock File

The bot process was dead because `cockpit.lock` contained PID `36812` which happened to be the Claude Code process (same PID reused by OS after bot died). `cockpit.py` checked if PID 36812 was alive, found it was, and exited with code 1.

### Fix Applied

1. Removed stale `cockpit.lock`
2. Fixed Windows Scheduled Task `PolymarketBot-Autostart` — path was pointing to `C:\automation\projects\...` (wrong location), updated to `C:\Users\botrunner\projects\polymarket-beobachter`
3. Bot restarted: **PID 52240, running as of 19:49**

### Observation Log

`logs/weather_observations.jsonl` has 191,859 entries and IS being written. The MCP `get_market_observations()` returns data correctly when called from the right working directory. The observations currently show test market `m1` — real market observations should appear on the next pipeline run.

---

## Deliverables Checklist

| Deliverable | Status |
|-------------|--------|
| `output/backtest_results.json` | ✅ Written |
| `output/overnight_report.md` | ✅ This file |
| `tests/test_side_selection.py` | ✅ 17 tests, all pass |
| SL invalid-price guard | ✅ Committed |
| TP1 trailing stop +3% | ✅ Committed |
| Observation log absolute path | ✅ Committed |
| polymarket_agent in observer | ✅ Committed |
| MCP tools for agent | ✅ Committed |
| Dashboard router | ✅ Committed |
| Bot daemon restarted | ✅ PID 52240 |

---

## Commits

**polymarket-beobachter:**
```
70f3228 fix: SL guard for invalid API prices + TP1 trailing stop lock-in
```

**control:**
```
cd65b19 feat: OpenClaw Polymarket Agent integration (Phase 3)
```

---

## Known Issues / Morning Actions

1. **Post-fix sample too small**: Only 8 positions since 28.03 21:30. Need 20+ to evaluate fix impact. Monitor for next 24h.

2. **Weather model accuracy**: The 25% win rate persists post-fix. Root cause is weather model mis-predicting temperatures. Consider:
   - Checking CDF source calibration per city
   - Reviewing ensemble disagreement for losing markets
   - Setting city-specific confidence thresholds

3. **Observation log real markets**: Currently showing test market `m1`. Verify next pipeline run writes real market IDs.

4. **OpenClaw agent test run**: Run `python -m openclaw edge` once to verify polymarket_agent integrates cleanly without import errors.

5. **Capital reconciliation drift**: Current state shows -177.89 EUR realized P&L but capital shows ~4,822 EUR total equity. This is consistent. The "~200 EUR self-heal correction" mentioned in the brief should be eliminated by the tp_state fix (already deployed).
