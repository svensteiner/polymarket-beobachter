# =============================================================================
# POLYMARKET BEOBACHTER - PAPER TRADING MODULE ENTRY POINT
# =============================================================================
#
# GOVERNANCE:
# This file enables `python -m paper_trader` invocation.
# It delegates to run.py for all CLI functionality.
#
# PAPER TRADING ONLY:
# This module does NOT execute real trades.
#
# =============================================================================

from paper_trader.run import main
import sys

if __name__ == "__main__":
    sys.exit(main())
