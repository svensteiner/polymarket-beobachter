# =============================================================================
# POLYMARKET BEOBACHTER - ANALYSIS PACKAGE
# =============================================================================
#
# GOVERNANCE:
# This package contains ANALYTICAL tools ONLY.
# It does NOT affect trading logic or parameters.
# It does NOT execute trades.
# It does NOT modify engine behavior.
#
# PURPOSE:
# Post-mortem analysis of shadow mode results.
# Stress testing, not optimization.
#
# =============================================================================

from .panic_paper_pnl import (
    PaperPnLAnalyzer,
    run_paper_pnl_analysis,
)

__all__ = [
    "PaperPnLAnalyzer",
    "run_paper_pnl_analysis",
]
