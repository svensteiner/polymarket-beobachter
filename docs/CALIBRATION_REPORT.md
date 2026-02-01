# Calibration Report — Interpretation Guide

## What Is Calibration?

Calibration measures whether your probability estimates match reality.

If your system says "60% chance of YES" across 100 markets, calibration asks:
**did roughly 60 of those markets actually resolve YES?**

- If 60 out of 100 resolved YES → perfectly calibrated
- If 80 out of 100 resolved YES → underconfident (reality exceeds predictions)
- If 40 out of 100 resolved YES → overconfident (predictions exceed reality)

## Why Good PnL With Bad Calibration Is Dangerous

A system can be profitable *and* badly calibrated — temporarily.

Example: You predict 90% on 10 markets. 7 resolve YES. You're overconfident
(predicted 90%, got 70%), but still profitable because you bought cheap.
Eventually the market catches up, your edge disappears, and the
miscalibration becomes pure loss.

**Bad calibration means your edge estimate is wrong.** If you don't know
your true edge, you cannot size positions correctly. Kelly Criterion with
wrong probabilities guarantees ruin over time.

## Why This Engine Does Not Improve Performance

This engine is **analytics only**. It observes and reports. It never:

- Adjusts thresholds
- Tunes model parameters
- Suggests trades
- Feeds back into any decision pipeline

If this engine influenced trading decisions, it would create a feedback loop
that invalidates its own measurements. The calibration report is a
thermometer — it tells you the temperature but doesn't turn on the AC.

## How to Read the Report

### Brier Score
- **< 0.15**: Good calibration
- **0.15 – 0.25**: Moderate — room for improvement
- **> 0.25**: Poor — predictions are not much better than coin flips

### Calibration Gap
- **|gap| < 3pp**: Well-calibrated
- **Positive gap**: Underconfident — events happen more often than you predict
- **Negative gap**: Overconfident — events happen less often than you predict

### Sample Size Warning
Results with fewer than 30 data points are statistically unreliable.
Wait for more resolved markets before drawing conclusions.

### By-Model Breakdown
Shows which probability model (baseline, weather, fed_rate, etc.) is
best calibrated. A model with good Brier score but small sample size
needs more data before trusting it.

### By-Confidence Breakdown
Shows whether HIGH/MEDIUM/LOW confidence labels actually correlate
with prediction accuracy. If LOW confidence predictions have better
Brier scores than HIGH confidence ones, the confidence labeling is broken.

### By-Odds Bucket Breakdown
Shows calibration across probability ranges (0-10%, 10-30%, etc.).
Most systems are worst-calibrated in the extremes (0-10% and 90-100%).

## Commands

```bash
# Build report (all time)
python tools/calibration_cli.py build-report --window all_time --print

# Print last report
python tools/calibration_cli.py print-report

# Export as JSON
python tools/calibration_cli.py json-export
```
