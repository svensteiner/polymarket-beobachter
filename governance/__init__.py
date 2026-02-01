# =============================================================================
# POLYMARKET BEOBACHTER - GOVERNANCE PACKAGE
# =============================================================================
#
# AUTHORITY:
# This package acts as an INDEPENDENT RISK COMMITTEE.
# It has VETO POWER over live trading decisions.
#
# PRINCIPLES:
# 1. Does NOT execute trades
# 2. Does NOT modify parameters
# 3. Does NOT override kill switches
# 4. CONSERVATIVE by design
# 5. If in doubt → NO-GO
#
# GOVERNANCE HIERARCHY:
# - Kill Switch (automatic) → OVERRIDES all
# - Governance Gate (this) → VETO power
# - Trading Engine → ONLY executes if BOTH approve
#
# =============================================================================

from .panic_governance_gate import (
    GovernanceGate,
    GovernanceDecision,
    run_governance_check,
)

__all__ = [
    "GovernanceGate",
    "GovernanceDecision",
    "run_governance_check",
]
