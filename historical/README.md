# Historical / Counterfactual Testing Module

## Purpose

This module evaluates **ANALYZER DISCIPLINE**, not profitability.

The core question:
> Would the analyzer have REJECTED markets where the real-world outcome
> later proved that timelines were impossible or misinterpreted?

## What This Module Is NOT

- NOT a trading backtest
- NOT a PnL calculator
- NOT a probability estimator
- NOT a learning/tuning system

## Strict Constraints

| Constraint | Rationale |
|------------|-----------|
| No prices | We don't have historical market prices |
| No probabilities | We don't infer from historical markets |
| No PnL | We're testing discipline, not profits |
| No hindsight | Analyzer sees only past information |
| No optimization | Results inform, not adjust |
| Fail closed | Ambiguity → rejection |

## Outcome Classification

The analyzer makes a TRADE/NO_TRADE decision. We compare this to the known
real-world outcome:

| Classification | Analyzer | Outcome | Interpretation |
|----------------|----------|---------|----------------|
| **CORRECT_REJECTION** | NO_TRADE | NO | Correctly protected against bad trade |
| **SAFE_PASS** | NO_TRADE | YES | Missed opportunity, but stayed safe |
| **FALSE_ADMISSION** | TRADE | NO | **CRITICAL FAILURE** - would have lost |
| **RARE_SUCCESS** | TRADE | YES | Found valid edge (rare) |

### Severity Ranking (worst to best)

1. **FALSE_ADMISSION** - Structural failure, must be reviewed
2. **SAFE_PASS** - Acceptable conservatism
3. **CORRECT_REJECTION** - Working as intended
4. **RARE_SUCCESS** - Best outcome, but rare by design

## Usage

```bash
# Run all historical cases
python -m historical --all

# Run a specific case
python -m historical --case CASE_001

# List available cases
python -m historical --list

# With verbose logging
python -m historical --all --verbose

# Custom output directory
python -m historical --all --output-dir my_output
```

## Output Structure

```
output/historical/
├── cases/
│   ├── CASE_001.json
│   ├── CASE_002.json
│   └── ...
├── aggregate_report.md
└── run_summary.json
```

### Case Report (JSON)

Each case report contains:
- Original case definition
- Analyzer decision (TRADE/NO_TRADE)
- Blocking criteria (if NO_TRADE)
- Timeline conflicts detected
- Classification vs. known outcome
- Full reasoning

### Aggregate Report (Markdown)

The aggregate report contains:
- Classification summary table
- Discipline metrics
- Detailed analysis of FALSE_ADMISSION cases
- All cases summary
- Recurring failure pattern analysis

## Historical Cases Included

### CASE_001: EU AI Act Prohibited Practices (2024)
**Common Error:** Confusing adoption with enforcement start

The AI Act was adopted August 2024, but Article 5 (prohibited practices)
only applies from February 2, 2025. A market asking for enforcement by
December 2024 would have been structurally impossible.

### CASE_002: GDPR Enforcement (2016)
**Common Error:** Expecting immediate enforcement after adoption

GDPR was adopted April 2016 but had a mandatory 2-year transition period.
Enforcement only began May 25, 2018. A market asking for fines in 2016
would have been impossible.

### CASE_003: DMA Gatekeeper Compliance (2024)
**Common Error:** Underestimating procedural timelines

The DMA required gatekeeper designation (September 2023) followed by
a 6-month compliance period (ending March 6, 2024). A market asking
for compliance by March 1, 2024 was impossible.

### CASE_004: EU AI Act Full Application (2025)
**Common Error:** Not accounting for staggered application

The AI Act has application dates spanning from February 2025 to
August 2027. A market asking for "full" application by 2025 was
structurally impossible.

### CASE_005: EU AI Act Delegated Acts (2025)
**Common Error:** Assuming fixed delegated act timelines

Delegated acts depend on Commission discretion. A market asking for
all high-risk classification delegated acts by June 2025 had
ambiguous resolution criteria.

## Adding New Cases

To add a new historical case:

1. Edit `historical/cases.py`
2. Create a new function following the pattern:

```python
def case_my_new_case() -> HistoricalCase:
    return HistoricalCase(
        case_id="CASE_XXX",
        title="Clear title",
        description="What this tests",
        synthetic_resolution_text="How Polymarket would phrase it",
        hypothetical_target_date=date(YYYY, M, D),
        referenced_regulation="EU Regulation Name",
        authority_involved="Relevant authorities",
        analysis_as_of_date=date(YYYY, M, D),
        formal_timeline=FormalTimeline(
            proposal_date=date(...),
            adoption_date=date(...),
            # ... actual timeline
        ),
        known_outcome=KnownOutcome.YES or KnownOutcome.NO,
        notes="Additional context",
        failure_explanation="Why outcome was NO (if applicable)",
    )
```

3. Add the function to `get_all_cases()` list

## Methodology

### Blind Execution

The analyzer receives ONLY information that would have been available
at the hypothetical analysis date:

- `synthetic_resolution_text` (as market resolution)
- `hypothetical_target_date` (as market deadline)
- `referenced_regulation`
- `authority_involved`
- `analysis_as_of_date` (NOT today)

The analyzer does NOT receive:
- `known_outcome`
- `formal_timeline` (actual dates)
- `failure_explanation`

### Neutral Probability

Since we have no historical market prices, we use a NEUTRAL probability
(0.50) as a placeholder. This means the delta threshold check will not
find a tradeable edge, which is CORRECT for this test.

We are testing structural discipline (would it reject structurally
unsound markets?), not price-based opportunity detection.

## Interpreting Results

### FALSE_ADMISSION Cases

These are **critical failures**. The analyzer would have allowed trading
on a market that ultimately proved impossible or incorrect.

Review these cases to understand:
1. What blocking criteria should have triggered?
2. Was the timeline assessment incorrect?
3. Was the resolution text ambiguous?

### SAFE_PASS Cases

These are **acceptable**. The analyzer was conservative and rejected
a market that actually resolved favorably. This is the cost of
fail-closed design.

### Discipline Rate

```
Discipline Rate = (CORRECT_REJECTION + SAFE_PASS + RARE_SUCCESS) / Total
```

A high discipline rate indicates the analyzer correctly rejects
structurally unsound markets. The target should be 100% discipline
(no FALSE_ADMISSION cases).

## Design Principles

1. **Clarity > Cleverness**: Code is written for auditability
2. **Discipline > Coverage**: Better to over-reject than under-reject
3. **Determinism**: Same inputs always produce same outputs
4. **No Learning**: Results inform humans, not tune the analyzer

---

*This module exists to justify why a system REFUSED to trade.*
