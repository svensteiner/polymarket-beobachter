# =============================================================================
# CROSS-MARKET CONSISTENCY ENGINE
# =============================================================================
#
# ISOLATED RESEARCH MODULE
#
# This engine detects logical inconsistencies between prediction markets.
# It is STRICTLY READ-ONLY and has NO influence on trading decisions.
#
# ISOLATION GUARANTEES:
# - Zero imports from trading, execution, or decision code
# - No side effects beyond logging
# - No callbacks into any other system
# - Cannot emit BUY/SELL/TRADE signals
# - Cannot modify thresholds or confidence scores
#
# MENTAL MODEL:
# This is a research microscope. It observes. It never acts.
# If this engine disappeared, the trading system behaves IDENTICALLY.
#
# =============================================================================

__version__ = "0.1.0"
__author__ = "Polymarket Beobachter"

# Explicit statement of isolation
ISOLATION_STATEMENT = """
THIS MODULE IS INTENTIONALLY SANDBOXED.

It has:
- No imports from core/, execution/, governance/, or panic engines
- No ability to place trades
- No ability to modify trading parameters
- No callbacks or hooks into trading logic

It can only:
- Read market probabilities (passed as input)
- Check logical consistency
- Log findings to a separate file

If any code attempts to import trading functionality into this module,
that is a CRITICAL VIOLATION of the architecture.
"""
