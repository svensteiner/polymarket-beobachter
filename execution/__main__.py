# =============================================================================
# POLYMARKET BEOBACHTER - EXECUTION MODULE ENTRY POINT
# =============================================================================
#
# GOVERNANCE:
# This file enables `python -m execution` invocation.
# It delegates to run.py for all CLI functionality.
#
# =============================================================================

from execution.run import main
import sys

if __name__ == "__main__":
    sys.exit(main())
