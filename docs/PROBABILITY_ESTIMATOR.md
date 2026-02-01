# Probability Estimator - Honest Model Interface

## Overview

This document explains the probability estimation system for Polymarket Beobachter.
The system was forensically refactored to eliminate all placeholder/fake probability logic.

## The Problem: Why Placeholders Were Dangerous

### Before (The Bug)

The previous system contained hardcoded fallback values in `app/orchestrator.py`:

```python
# DANGEROUS: Hardcoded fake probabilities
analysis_dict = {
    "market_input": {
        "market_implied_probability": 0.5  # FAKE
    },
    "probability_estimate": {
        "probability_midpoint": 0.6,  # FAKE
    }
}
```

This created a **fake 10% edge on every market**, regardless of:
- Market category (politics, entertainment, sports, etc.)
- Actual market prices
- Any real analysis

### Consequences

1. **51 paper positions** opened with identical entry price (0.5278)
2. All positions showed **"Direction: UNKNOWN"**
3. Bot was effectively making **random bets** with imaginary edge
4. No way to distinguish real opportunities from noise
5. P&L was meaningless (negative from slippage simulation)

## The Solution: Honest Probability Interface

### Core Principle

> A probability is a CLAIM about reality.
> If you cannot explain it in one sentence, you are not allowed to return a number.

### New Interface: `HonestProbabilityEstimate`

```python
@dataclass
class HonestProbabilityEstimate:
    probability: Optional[float] = None  # Only set if valid
    valid: bool = False
    confidence: ModelConfidence = ModelConfidence.NONE
    model_type: Optional[ModelType] = None
    assumption: Optional[str] = None  # REQUIRED if valid
    data_sources: List[str] = field(default_factory=list)  # REQUIRED if valid
    warnings: List[str] = field(default_factory=list)
```

### Invariants (Enforced by Code)

1. `valid == True` requires:
   - `probability` in [0, 1]
   - Non-empty `assumption`
   - Non-empty `data_sources`
   - `confidence != NONE`

2. `valid == False` enforces:
   - `probability = None`
   - `confidence = NONE`

## What Constitutes a Valid Probability

### Valid: Has Defensible Model

| Model Type | Data Source | Assumption Example |
|------------|-------------|-------------------|
| WEATHER | tomorrow.io forecast | "Temperature follows normal distribution around forecast with sigma=3.5F" |
| EU_REGULATION | EUR-Lex stages | "Base rate 70% for full application, reduced by 5% per remaining step" |
| CORPORATE_EVENT | SEC filings | "Earnings date pattern analysis from historical filings" |
| COURT_RULING | Court schedule | "Supreme Court term schedule and historical timing" |

### Invalid: No Defensible Model

| Category | Why Invalid | Response |
|----------|-------------|----------|
| Politics | No quantifiable model for human behavior | `valid=False, NO_SIGNAL` |
| Entertainment | Speculative timelines (GTA VI, albums) | `valid=False, NO_SIGNAL` |
| Sports | Game outcomes beyond statistical reach | `valid=False, NO_SIGNAL` |
| Crypto prices | Requires market-making model | `valid=False, NO_SIGNAL` |

## Why Silence Is a Feature

### Before: False Confidence
```
Market: "GTA VI before June 2026?"
Model Probability: 0.6 (FAKE)
Market Probability: 0.5 (FAKE)
Edge: 10% (FAKE)
Decision: TRADE
Result: Random bet with imaginary edge
```

### After: Honest Silence
```
Market: "GTA VI before June 2026?"
Model: UNSUPPORTED
valid: false
probability: null
confidence: NONE
Decision: NO_SIGNAL
Result: No action, no false confidence
```

**Silence is better than noise.**

## Edge Calculation Rules

Edge may ONLY be computed if:

```python
def calculate_edge(estimate, market_probability):
    # Rule 1: Estimate must be valid
    if not estimate.valid:
        return invalid("probability estimate is invalid")

    # Rule 2: Market probability must be known and valid
    if market_probability is None or not (0 < market_probability < 1):
        return invalid("market probability invalid")

    # Rule 3: Confidence must not be NONE
    if estimate.confidence == ModelConfidence.NONE:
        return invalid("model confidence is NONE")

    # All rules pass -> calculate edge
    return valid_edge(estimate.probability - market_probability)
```

## Expected Behavior After Refactor

### Short-term (Immediate)

- **90%+ of previous "TRADE" proposals become NO_SIGNAL**
- Dashboard shows fewer candidates
- Edge Exposure drops to near zero
- Proposal generation nearly stops for unsupported categories

### Why This Is Success

1. **No more fake edges** - Every edge now has a documented model
2. **Honest reporting** - System admits what it doesn't know
3. **Clear signal** - When a TRADE appears, it has real backing
4. **Foundation for improvement** - Can add real models incrementally

## Adding New Models

To add a new probability model:

1. **Create model class** implementing `BaseProbabilityModel`:
```python
class MyNewModel(BaseProbabilityModel):
    @property
    def model_type(self) -> ModelType:
        return ModelType.MY_TYPE

    def can_estimate(self, market_data: Dict) -> bool:
        # Check if this model applies
        return "keyword" in market_data.get("title", "").lower()

    def estimate(self, market_data: Dict) -> HonestProbabilityEstimate:
        # Compute probability with EXPLICIT assumption
        return HonestProbabilityEstimate(
            valid=True,
            probability=computed_prob,
            confidence=ModelConfidence.HIGH,
            assumption="Clear explanation of WHY this number",
            data_sources=["source1", "source2"],
        )
```

2. **Register with router**:
```python
router = get_probability_router()
router.register_model(MyNewModel())
```

3. **Add unit tests** ensuring:
   - Model only activates for appropriate markets
   - All valid estimates have assumptions
   - Invalid cases properly return NO_SIGNAL

4. **Document** in this file

## File Reference

| File | Purpose |
|------|---------|
| `core/probability_models.py` | New honest interface and models |
| `core/probability_estimator.py` | EU Regulation model (existing, valid) |
| `core/weather_probability_model.py` | Weather model (existing, valid) |
| `app/orchestrator.py` | Pipeline integration |
| `tests/unit/test_probability_models.py` | Unit tests |

## Mental Model

```
                    +-------------------+
                    |   Market Data     |
                    +-------------------+
                            |
                            v
                    +-------------------+
                    | Model Router      |
                    +-------------------+
                            |
            +---------------+---------------+
            |               |               |
            v               v               v
     +-----------+   +-----------+   +-------------+
     | Weather   |   | EU Reg    |   | Unsupported |
     | Model     |   | Model     |   | (default)   |
     +-----------+   +-----------+   +-------------+
            |               |               |
            v               v               v
     +------------------+   +-------------------+
     | HonestEstimate   |   | HonestEstimate    |
     | valid=True       |   | valid=False       |
     | probability=0.65 |   | probability=null  |
     | assumption="..." |   | reason="..."      |
     +------------------+   +-------------------+
```

## Governance Notes

1. **NO changes** to `decision_engine.py` or `execution_engine.py`
2. **NO threshold modifications**
3. Probability estimator is **ISOLATED**
4. All invalid estimates propagate as **NO_SIGNAL**
5. **Better silence than false confidence**

---

*Last updated: 2026-01-25*
*Forensic refactor by Claude Code*
