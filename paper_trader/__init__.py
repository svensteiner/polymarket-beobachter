# =============================================================================
# POLYMARKET BEOBACHTER - PAPER TRADING MODULE
# =============================================================================
#
# ╔═══════════════════════════════════════════════════════════════════════════╗
# ║                    PAPER TRADING ONLY - NO LIVE EXECUTION                 ║
# ╠═══════════════════════════════════════════════════════════════════════════╣
# ║  This module simulates trades for data collection purposes.               ║
# ║  NO real orders are placed. NO funds are at risk.                         ║
# ║  NO API keys are required or used for trading.                            ║
# ╚═══════════════════════════════════════════════════════════════════════════╝
#
# PURPOSE:
# Autonomous paper trading to collect "what would have happened" data.
#
# DATA FLOW (ONE-WAY ONLY):
#   Layer 1 (proposals)     ----------------------+
#                                                 +---> PaperTrader ---> Logs
#   Layer 2 (prices)        ----------------------+
#
#   [X] NO REVERSE FLOW TO LAYER 1
#
# ARCHITECTURE:
# - Consumes ONLY REVIEW_PASS proposals from proposals/ storage
# - Fetches price snapshots via Layer 2 infrastructure (read-only)
# - Simulates entry/exit with conservative slippage
# - Writes results to append-only logs
#
# ABSOLUTE CONSTRAINTS:
# - NO live trading endpoints
# - NO wallet functions
# - NO order placement code
# - NO API keys for trading
# - Price data NEVER flows back to Layer 1
#
# =============================================================================

"""
Paper Trading Module - Autonomous Simulation (NO LIVE TRADING)

This module runs unattended to collect "what would have happened" data.
It consumes approved proposals and simulates trades using market snapshots.

Usage:
    python -m paper_trader.run --once     # Process new proposals
    python -m paper_trader.run --daily-report  # Generate daily report

WARNING:
    This module does NOT execute real trades.
    It is for data collection and backtesting only.
"""

__version__ = "0.1.0"
__status__ = "PAPER_ONLY"

# Governance notice
GOVERNANCE_NOTICE = """
================================================================================
PAPER TRADING MODULE - GOVERNANCE NOTICE
================================================================================

This module is for PAPER TRADING ONLY.

- NO live orders are placed
- NO real funds are at risk
- NO API keys are used for trading
- Price data is used for simulation ONLY
- Results are logged for analysis

Data flow is ONE-WAY: Layer 1/2 -> PaperTrader -> Logs
There is NO reverse flow to Layer 1 decision-making.

================================================================================
"""
