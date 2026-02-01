# =============================================================================
# POLYMARKET BEOBACHTER - TEST SUITE
# =============================================================================
#
# Konsolidierte Test-Suite fuer alle Module.
#
# Struktur:
#   tests/
#     unit/           - Unit Tests (Weather, Module Loader, Collector)
#     integration/    - Integration Tests (Pipeline, Paper Trader, API)
#     e2e/            - End-to-End Tests
#     stress/         - Performance & Stress Tests
#     reports/        - Test-Reports (HTML, JSON)
#
# Usage:
#   python -m tests.run_all              # Alle Tests
#   python -m tests.run_all --unit       # Nur Unit Tests
#   python -m tests.run_all --integration # Nur Integration Tests
#   python -m tests.run_all --stress     # Nur Stress Tests
#   python -m tests.run_all --quick      # Ohne Stress Tests
#   python -m tests.run_all --html       # Mit HTML Report
#
# Fuer pytest (alte Tests):
#   pytest tests/integration/            # pytest-kompatible Tests
#
# =============================================================================

__version__ = "2.0.0"
