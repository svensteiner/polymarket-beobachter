# =============================================================================
# POLYMARKET EU AI REGULATION ANALYZER
# Module: historical/run.py
# Purpose: Alternative CLI entry point for historical testing
# =============================================================================
#
# This module provides a direct entry point for:
#   python -m historical.run --all
#
# It simply delegates to the __main__ module.
#
# =============================================================================

from .__main__ import main

if __name__ == "__main__":
    import sys
    sys.exit(main())
