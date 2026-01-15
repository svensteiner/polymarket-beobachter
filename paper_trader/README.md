# Paper Trading Module

## GOVERNANCE NOTICE

**This module is for PAPER TRADING ONLY.**

- NO real orders are placed
- NO real funds are at risk
- NO API keys are used for trading
- All trades are SIMULATED for data collection

---

## Purpose

This module runs autonomously to collect "what would have happened" data. It:

1. Consumes REVIEW_PASS proposals from the proposals/ storage
2. Simulates trade entry using market price snapshots
3. Tracks simulated positions
4. Closes positions on market resolution
5. Logs all activity for analysis

---

## Architecture

```
paper_trader/
├── __init__.py          # Module exports and governance notice
├── __main__.py          # CLI entry point (python -m paper_trader)
├── models.py            # Data models (PaperPosition, PaperTradeRecord)
├── slippage.py          # Conservative slippage model
├── snapshot_client.py   # Layer 2 price access (read-only)
├── intake.py            # Proposal filtering (REVIEW_PASS only)
├── simulator.py         # Entry/exit simulation
├── position_manager.py  # Position lifecycle management
├── logger.py            # Append-only JSONL logging
├── reporter.py          # Daily report generation
├── run.py               # CLI implementation
├── README.md            # This file
├── logs/
│   ├── paper_trades.jsonl   # All trade actions
│   └── paper_positions.jsonl # Position state changes
└── reports/
    └── daily_report_YYYY-MM-DD.md
```

---

## Data Flow (ONE-WAY ONLY)

```
┌─────────────────────────┐
│  Layer 1 (proposals/)   │
│  - Proposal generation  │
│  - Review gate          │
└───────────┬─────────────┘
            │ READ-ONLY
            ▼
┌─────────────────────────┐     ┌─────────────────────────┐
│     Paper Trader        │ ◄───│ Layer 2 (prices)        │
│  - Intake filtering     │     │ - Market snapshots      │
│  - Entry simulation     │     │ - Resolution status     │
│  - Position tracking    │     └─────────────────────────┘
│  - Exit simulation      │              READ-ONLY
└───────────┬─────────────┘
            │ APPEND-ONLY
            ▼
┌─────────────────────────┐
│    Logs & Reports       │
│  - paper_trades.jsonl   │
│  - paper_positions.jsonl│
│  - daily_report.md      │
└─────────────────────────┘

❌ NO REVERSE FLOW TO LAYER 1
```

**Critical**: Price data in paper trading logs NEVER flows back to Layer 1 decision-making.

---

## CLI Usage

### Run One Cycle

```bash
python -m paper_trader.run --once
```

This:
1. Fetches eligible REVIEW_PASS proposals
2. Simulates entry for new proposals
3. Checks open positions for resolution
4. Logs all activity

### Generate Daily Report

```bash
python -m paper_trader.run --daily-report
```

### Check Status

```bash
python -m paper_trader.run --status
```

---

## Windows Task Scheduler Setup

To run paper trading automatically, create a scheduled task:

**Command:**
```
cd /d "C:\Chatgpt_Codex\polymarket Beobachter" && python -m paper_trader.run --once
```

**Recommended Schedule:**
- Every 4 hours for position checking
- Daily at midnight for report generation

**Task Scheduler Steps (command line):**
```cmd
schtasks /create /tn "PaperTrader-Hourly" /tr "cmd /c cd /d \"C:\Chatgpt_Codex\polymarket Beobachter\" && python -m paper_trader.run --once" /sc hourly /mo 4
```

---

## Proposal Eligibility Criteria

A proposal is paper-traded ONLY if ALL conditions are met:

1. `decision == "TRADE"`
2. `review_result == REVIEW_PASS` (passes review gate)
3. Not already paper-executed (idempotency check)

---

## Slippage Model

The simulator uses a CONSERVATIVE slippage model:

| Liquidity Bucket | Slippage Rate |
|------------------|---------------|
| HIGH (< 2% spread) | 0.5% |
| MEDIUM (2-5% spread) | 1.5% |
| LOW (> 5% spread) | 3.0% |
| UNKNOWN | 5.0% |

**Entry**: Price = Ask + Slippage (worst case for buyer)
**Exit**: Price = Bid - Slippage (worst case for seller)

This intentionally underestimates performance to avoid optimistic bias.

---

## Exit Conditions

### Resolution-Based Exit (Primary)

When a market resolves:
- Winning side receives 1.0 per contract
- Losing side receives 0.0 per contract
- No slippage on resolution

### Time Stop (Future)

Optional time-based exit after N days can be added using current mid-price minus slippage.

---

## Log Format

### paper_trades.jsonl

```json
{"record_id": "REC-...", "timestamp": "...", "proposal_id": "PROP-...", "action": "PAPER_ENTER", "entry_price": 0.65, "slippage_applied": 0.01, ...}
{"record_id": "REC-...", "timestamp": "...", "proposal_id": "PROP-...", "action": "PAPER_EXIT", "exit_price": 1.0, "pnl_eur": 53.85, ...}
{"record_id": "REC-...", "timestamp": "...", "proposal_id": "PROP-...", "action": "SKIP", "reason": "Market snapshot unavailable", ...}
```

### paper_positions.jsonl

```json
{"position_id": "PAPER-...", "status": "OPEN", "side": "YES", "entry_price": 0.65, "cost_basis_eur": 100.0, ...}
{"position_id": "PAPER-...", "status": "RESOLVED", "exit_price": 1.0, "realized_pnl_eur": 53.85, ...}
```

---

## Assumptions and Limitations

### Assumptions

1. **No market impact**: Paper trades don't affect prices
2. **Instant fills**: Orders fill immediately at simulated price
3. **Unlimited liquidity**: Can always enter/exit at calculated price
4. **Fixed position size**: Always 100 EUR per trade

### Limitations

1. **No partial fills**: Always full or nothing
2. **No fee modeling**: Transaction fees not simulated
3. **No multi-leg positions**: One position per market
4. **Resolution only exit**: No stop-loss or take-profit

### Conservative Choices

1. **Entry at ask + slippage**: Worst case for buyer
2. **Exit at bid - slippage**: Worst case for seller
3. **Unknown liquidity = 5% slippage**: Penalize uncertainty
4. **No best-price selection**: Uses current snapshot only

---

## Safety Guarantees

This module is designed with hard constraints:

| Constraint | Implementation |
|------------|----------------|
| No trading endpoints | No imports from trading libraries |
| No wallet functions | No wallet/balance code exists |
| No order placement | No order submission logic |
| No API keys for trading | Only uses public market data |
| Layer isolation | Import guards prevent Layer 1 contamination |
| Idempotency | Proposals tracked to prevent re-execution |
| Append-only logs | Logs cannot be deleted or modified |

---

## Testing

Run governance tests:

```bash
python -m pytest tests/test_paper_trader_governance.py -v
```

Tests verify:
1. No imports from paper_trader into core_analyzer
2. Price fields never appear in Layer 1 outputs
3. Idempotency: same proposal not executed twice
4. All models include governance notices

---

## Maintenance

### Log Rotation

Logs grow indefinitely. For long-term operation:
1. Archive old JSONL files periodically
2. Keep at least 90 days of history
3. Never delete - move to archive folder

### Monitoring

Check daily reports for:
- Unexpected skip rates
- Slippage anomalies
- P&L drift from expectations
