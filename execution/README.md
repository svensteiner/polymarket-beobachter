# Execution Layer - Pre-Flight Module

## GOVERNANCE NOTICE

**This module exists for READINESS ONLY.**

**Live execution is FORBIDDEN.**

Any attempt to call `execute()` will raise `ExecutionDisabledError`. This is:
- **NOT** a bug
- **NOT** a limitation
- **NOT** temporary
- **INTENTIONAL** by design

---

## Purpose

This module prepares the execution layer WITHOUT enabling live trading. It provides:

1. **Proposal Validation** - Verify proposals meet all execution prerequisites
2. **Dry-Run Simulation** - See what WOULD happen without any risk
3. **Audit Logging** - Complete append-only audit trail of all actions

---

## Architecture

```
execution/
├── __init__.py        # Module exports and governance notice
├── __main__.py        # CLI entry point (python -m execution)
├── adapter.py         # Main functions: prepare_execution, dry_run, execute
├── exceptions.py      # Governance exception classes
├── logger.py          # Append-only JSONL audit logging
├── policy.py          # Immutable execution parameters
├── run.py             # CLI implementation
├── validator.py       # Proposal validation gate
└── README.md          # This file
```

---

## Layer Separation

This module is **COMPLETELY ISOLATED** from:
- `core_analyzer/` - Analysis layer
- `proposals/` - Proposal generation and review
- `collector/` - Data collection
- `shared/` - Shared utilities

It **MAY ONLY CONSUME**:
- `proposal_id`
- `review_status == REVIEW_PASS`
- Static execution parameters (from `policy.py`)

---

## Usage

### CLI Commands

```bash
# Dry-run (default) - simulate execution
python -m execution --proposal PROP-20260115-abc12345

# Explicit dry-run
python -m execution --proposal PROP-20260115-abc12345 --dry-run

# Prepare only (validation)
python -m execution --proposal PROP-20260115-abc12345 --prepare

# Status check
python -m execution --status

# Execute (ALWAYS FAILS)
python -m execution --proposal PROP-20260115-abc12345 --execute
# Output: "Execution disabled by policy. No action taken."
```

### Python API

```python
from execution import prepare_execution, dry_run, execute

# Prepare a proposal
result = prepare_execution("PROP-20260115-abc12345")
print(result.format_summary())

# Dry-run simulation
result = dry_run("PROP-20260115-abc12345")
print(result.format_output())

# Execute (ALWAYS FAILS)
try:
    execute("PROP-20260115-abc12345")
except ExecutionDisabledError:
    print("Execution is disabled by policy")
```

---

## Execution Policy (Immutable)

These values are **CONSTANTS** defined in `policy.py`:

| Parameter | Value | Description |
|-----------|-------|-------------|
| `fixed_amount_eur` | 100.00 | Maximum risk per trade |
| `max_slippage` | 2% | Maximum allowed slippage |
| `max_exposure_per_market_eur` | 500.00 | Maximum position per market |
| `one_shot_only` | True | Each proposal executes at most once |
| `no_reentry` | True | Cannot re-enter after exit |
| `execution_disabled` | **True** | **ALWAYS True - cannot be changed** |

**These values cannot be changed at runtime.** To modify them:
1. Stop the system
2. Edit `policy.py` source code
3. Conduct code review
4. Re-run all tests
5. Restart

---

## Validation Gate

Before ANY preparation, the following checks are performed:

1. **Proposal exists** - Must be in storage
2. **Not already executed** - One-shot-only enforcement
3. **Decision is TRADE** - Not NO_TRADE
4. **Review passed** - `review_result == REVIEW_PASS`
5. **Core criteria passed** - All criteria must be satisfied

If ANY check fails:
- Specific exception is raised
- Failure is logged to audit log
- Operation is aborted

---

## Audit Logging

All actions are logged to `execution_log.jsonl`:

```jsonl
{"timestamp": "2026-01-15T...", "proposal_id": "PROP-...", "action": "PREPARE", "outcome": "SUCCESS", ...}
{"timestamp": "2026-01-15T...", "proposal_id": "PROP-...", "action": "DRY_RUN", "outcome": "SUCCESS", ...}
{"timestamp": "2026-01-15T...", "proposal_id": "PROP-...", "action": "EXECUTE_ATTEMPT", "outcome": "BLOCKED", ...}
```

**Log characteristics:**
- **Append-only** - Entries cannot be deleted or modified
- **JSONL format** - One JSON object per line
- **Complete trail** - All actions logged before execution

---

## Kill Switch

The `execute()` function contains a **hard kill switch**:

```python
def execute(proposal_id: str) -> None:
    # Log the attempt
    log_execute_attempt(proposal_id, ...)

    # ALWAYS raise - no conditions, no bypasses
    raise ExecutionDisabledError(proposal_id)
```

This code:
- Has **NO** conditional checks
- Has **NO** environment variable overrides
- Has **NO** configuration file options
- **ALWAYS** raises `ExecutionDisabledError`

---

## Exception Hierarchy

```
ExecutionError (base)
├── ExecutionDisabledError    # PERMANENT: execution disabled by policy
├── GovernanceViolationError  # Proposal failed governance checks
├── ProposalNotFoundError     # Proposal does not exist
├── ProposalAlreadyExecutedError # Already executed (one-shot)
└── ProposalNotApprovedError  # Review did not pass
```

---

## To Enable Execution (Future Manual Process)

**This module is intentionally non-operational.**

To enable execution in the future:

1. **STOP** the entire system
2. Conduct a **full governance review**
3. **MODIFY** the source code in `adapter.py`:
   - Remove the `raise ExecutionDisabledError` line
   - Implement actual execution logic
4. **MODIFY** `policy.py`:
   - Change `EXECUTION_DISABLED = True` to `False`
   - Update `__post_init__` validation
5. **Re-run ALL tests** including new execution tests
6. Get **explicit operator approval**
7. **Restart** with new code

There are **NO shortcuts**. This process is intentionally manual.

---

## Test Verification

Run tests to verify execution is impossible:

```bash
python -m pytest tests/test_execution_disabled.py -v
```

Expected output:
```
test_execute_always_raises ... PASSED
test_policy_execution_disabled ... PASSED
test_no_runtime_override ... PASSED
```

---

## Files Generated

| File | Description |
|------|-------------|
| `execution_log.jsonl` | Append-only audit log |
| `executed_proposals.json` | Tracking of executed/attempted proposals |

---

## Summary

This module provides **execution readiness** without enabling live trading:

- Proposals can be **validated**
- Execution can be **simulated** (dry-run)
- All actions are **logged**
- Actual execution is **impossible**

The system is ready to trade when governance review is complete and source code is modified.
