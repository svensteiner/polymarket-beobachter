# =============================================================================
# POLYMARKET EU AI COLLECTOR
# Module: collector/__init__.py
# Purpose: Market discovery and storage pipeline (NO analysis, NO prices)
# =============================================================================
#
# STRICT SEPARATION:
# This module ONLY discovers and stores candidate markets.
# It does NOT fetch or display: prices, volumes, implied probabilities, orderbook.
# It does NOT run the analyzer. It is a dumb, deterministic intake pipeline.
#
# DESIGN PRINCIPLES:
# - Fail-closed: missing/ambiguous fields → mark as "incomplete"
# - Deterministic: same input => same stored results
# - Audit-friendly: full logging and run summary reports
#
# =============================================================================

from .client import PolymarketClient
from .sanitizer import Sanitizer
from .filter import MarketFilter
from .normalizer import MarketNormalizer
from .storage import StorageManager
from .collector import Collector

__all__ = [
    "PolymarketClient",
    "Sanitizer",
    "MarketFilter",
    "MarketNormalizer",
    "StorageManager",
    "Collector",
]
