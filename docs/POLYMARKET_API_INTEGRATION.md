# Polymarket API Integration

## Overview

This document describes the integration of the Polymarket CLOB (Central Limit Order Book) API into the Polymarket Beobachter execution engine.

**CRITICAL: This is a SAFETY-CRITICAL system that handles real money.**

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        EXECUTION ENGINE                              │
│                                                                      │
│   ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────┐ │
│   │ DISABLED │→ │  SHADOW  │→ │  PAPER   │→ │  ARMED   │→ │ LIVE │ │
│   └──────────┘  └──────────┘  └──────────┘  └──────────┘  └──────┘ │
│        │             │              │             │            │     │
│        │             │              │             │            ▼     │
│        │             │              │             │     ┌──────────┐ │
│        │             │              │             │     │ API      │ │
│        └─────────────┴──────────────┴─────────────┘     │ CLIENT   │ │
│                  ▲                                       └──────────┘ │
│                  │                                            │      │
│          NEVER TOUCH API                              ONLY IN LIVE   │
└─────────────────────────────────────────────────────────────────────┘
```

## Safety Hierarchy

The execution engine enforces a strict safety hierarchy:

| Mode | Description | API Access | Default |
|------|-------------|------------|---------|
| DISABLED | No orders accepted | NEVER | YES |
| SHADOW | Log only | NEVER | - |
| PAPER | Paper positions | NEVER | - |
| ARMED | Validate only | NEVER | - |
| LIVE | Real trading | YES | - |

## Transition Rules

1. **Startup**: ALWAYS starts in `DISABLED` mode
2. **DISABLED → SHADOW/PAPER**: Allowed
3. **DISABLED → ARMED**: Requires 2-step confirmation
4. **ARMED → LIVE**: Requires:
   - Environment variable: `POLYMARKET_LIVE=1`
   - Valid API credentials (see below)
5. **Any Error → DISABLED**: Automatic emergency disable

## Required Environment Variables

For LIVE mode, the following environment variables MUST be set:

| Variable | Description | Required |
|----------|-------------|----------|
| `POLYMARKET_LIVE` | Must be `1` | YES |
| `POLYMARKET_PRIVATE_KEY` | Wallet private key | YES |
| `POLYMARKET_API_KEY` | API key | YES |
| `POLYMARKET_API_SECRET` | API secret | YES |
| `POLYMARKET_API_PASSPHRASE` | API passphrase | For some endpoints |
| `POLYMARKET_FUNDER_ADDRESS` | Funder address | For POLY_PROXY |

## API Client Design

### Fail-Closed Principle

The API client follows a strict **fail-closed** design:

- Any network error → Order REJECTED
- Any parse error → Order REJECTED
- Any unexpected response → Order REJECTED
- Any exception → Emergency DISABLE

There are **NO retries**. If an order fails, it fails permanently.

### Minimal Interface

The API client exposes only three methods:

```python
class PolymarketApiClient:
    def submit_order(payload: OrderPayload) -> ApiResponse
    def cancel_order(order_id: str) -> ApiResponse
    def get_order_status(order_id: str) -> ApiResponse
```

### Lazy Initialization

The API client is **lazily initialized**:
- The `py_clob_client` module is only imported when LIVE mode is entered
- The client is only created on first API call
- This prevents any API interaction in non-LIVE modes

## Usage

### CLI Controller

Use the CLI to manage execution modes:

```bash
# Check current status
python -m tools.execution_mode_cli status

# Set SHADOW mode (log only)
python -m tools.execution_mode_cli shadow

# Set PAPER mode (paper trading)
python -m tools.execution_mode_cli paper

# Initiate ARM (2-step process)
python -m tools.execution_mode_cli arm

# Confirm ARM with challenge code
python -m tools.execution_mode_cli confirm ABC123

# Go LIVE (requires env vars + ARMED state)
python -m tools.execution_mode_cli live

# Emergency disable
python -m tools.execution_mode_cli disarm
```

### Programmatic Usage

```python
from core.execution_engine import get_execution_engine, OrderRequest
from shared.enums import OrderSide

engine = get_execution_engine()

# Create order request
order = OrderRequest(
    market_id="market_123",
    token_id="token_abc",
    side=OrderSide.BUY,
    price=0.5,
    size=100.0,
)

# Submit order (behavior depends on mode)
result = engine.submit_order(order)

# Check result
if result.status == OrderStatus.REJECTED:
    print(f"Rejected: {result.rejection_message}")
elif result.status == OrderStatus.SUBMITTED:
    print(f"Order submitted: {result.order_id}")
```

## Error Handling

### Emergency Disable

Any error during LIVE trading triggers an immediate emergency disable:

```python
# Automatic on any error:
engine._emergency_disable("API error: connection timeout")

# State after emergency:
state = engine.get_state()
assert state["mode"] == "DISABLED"
assert state["emergency_disabled"] == True
assert state["emergency_reason"] == "API error: connection timeout"
```

### Recovery

After an emergency disable:

1. Investigate the error in logs
2. Fix the underlying issue
3. Restart the execution engine (new instance)
4. Re-arm and go live only after verification

## Testing

### Unit Tests

```bash
# Run API client unit tests
pytest tests/test_polymarket_api_client.py -v
```

### Integration Tests

```bash
# Run execution safety tests
pytest tests/test_execution_safety_integration.py -v
```

### Key Test Coverage

1. **OrderPayload validation**: Price, size, side constraints
2. **Credential validation**: Missing keys raise errors
3. **Mode isolation**: Non-LIVE modes never touch API
4. **API error handling**: All errors mapped to structured responses
5. **Emergency disable**: Triggers on any unexpected error
6. **State persistence**: Restarts always begin DISABLED

## Security Considerations

### Credential Storage

- NEVER commit credentials to version control
- Use environment variables or secure secret management
- Private keys should be stored with restricted permissions

### Rate Limiting

- Built-in rate limiting: max 10 orders/minute
- Exceeding rate limit rejects orders (does not queue)

### Audit Trail

- All orders logged to `logs/execution/orders_YYYYMMDD.jsonl`
- Mode transitions logged with timestamps
- Emergency events logged at CRITICAL level

## Dependencies

### Required

- `py-clob-client`: Polymarket CLOB client library

### Installation

```bash
pip install py-clob-client
```

## Governance Notes

1. **Default Safe**: System starts DISABLED by design
2. **2-Step Arm**: Prevents accidental LIVE trading
3. **Env Var Gate**: `POLYMARKET_LIVE=1` is a deliberate action
4. **Fail Closed**: Any uncertainty results in rejection
5. **No Retries**: Failed orders fail permanently
6. **Emergency Stop**: Any error immediately disables trading

## Changelog

### v1.0.0 (2026-01-23)
- Initial API client integration
- Strict fail-closed error handling
- Lazy client initialization
- Comprehensive test coverage
