# =============================================================================
# POLYMARKET BEOBACHTER - MICROSTRUCTURE RESEARCH (LAYER 2)
# =============================================================================
#
# ██████╗ ███████╗███████╗███████╗ █████╗ ██████╗  ██████╗██╗  ██╗     ██████╗ ███╗   ██╗██╗  ██╗   ██╗
# ██╔══██╗██╔════╝██╔════╝██╔════╝██╔══██╗██╔══██╗██╔════╝██║  ██║    ██╔═══██╗████╗  ██║██║  ╚██╗ ██╔╝
# ██████╔╝█████╗  ███████╗█████╗  ███████║██████╔╝██║     ███████║    ██║   ██║██╔██╗ ██║██║   ╚████╔╝
# ██╔══██╗██╔══╝  ╚════██║██╔══╝  ██╔══██║██╔══██╗██║     ██╔══██║    ██║   ██║██║╚██╗██║██║    ╚██╔╝
# ██║  ██║███████╗███████║███████╗██║  ██║██║  ██║╚██████╗██║  ██║    ╚██████╔╝██║ ╚████║███████╗██║
# ╚═╝  ╚═╝╚══════╝╚══════╝╚══════╝╚═╝  ╚═╝╚═╝  ╚═╝ ╚═════╝╚═╝  ╚═╝     ╚═════╝ ╚═╝  ╚═══╝╚══════╝╚═╝
#
# =============================================================================
#
# LAYER 2 — MICROSTRUCTURE / EXECUTION RESEARCH (SATELLITE)
#
# ╔═══════════════════════════════════════════════════════════════════════════╗
# ║                                                                           ║
# ║                    THIS MODULE HAS ZERO DECISION AUTHORITY                ║
# ║                                                                           ║
# ║  This module exists ONLY for studying orderbook mechanics, spreads,       ║
# ║  liquidity patterns, and market microstructure. It provides NO trading    ║
# ║  recommendations and has NO influence on Layer 1 decisions.               ║
# ║                                                                           ║
# ╚═══════════════════════════════════════════════════════════════════════════╝
#
# PURPOSE:
# - Study orderbook mechanics
# - Analyze spreads and liquidity slop
# - Understand *how* Polymarket behaves (NOT *what to trade*)
#
# ABSOLUTE PROHIBITIONS:
# - NO decision authority
# - NO capital allocation logic
# - NO coupling to Layer 1
# - NO parameter optimization
# - NO automatic execution
# - NO trade recommendations
# - NO market rankings
# - NO allocation suggestions
#
# ALLOWED OUTPUTS:
# - Spread distributions
# - Liquidity observations
# - Orderbook behavior summaries
# - Statistical analysis of market mechanics
#
# =============================================================================

import sys

# Enforce layer isolation at import time
from shared.layer_guard import assert_layer_isolation, Layer
assert_layer_isolation(Layer.LAYER2_MICROSTRUCTURE)

# Version
__version__ = "1.0.0"

# This module intentionally exports nothing by default
# All research must be done through explicit CLI invocation
__all__ = []
