#!/usr/bin/env python3
# =============================================================================
# POLYMARKET BEOBACHTER - TEST RUNNER
# =============================================================================
#
# USAGE:
#   python run_tests.py              # Run all tests
#   python run_tests.py -v           # Verbose mode
#   python run_tests.py --quick      # Quick smoke test only
#
# =============================================================================

import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Polymarket Beobachter Test Runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python run_tests.py              Run all tests
  python run_tests.py -v           Verbose output
  python run_tests.py --quick      Quick smoke test
"""
    )

    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Verbose output")
    parser.add_argument("--quick", action="store_true",
                        help="Quick smoke test only")

    args = parser.parse_args()

    if args.quick:
        # Quick smoke test
        print("\n" + "="*50)
        print("  QUICK SMOKE TEST")
        print("="*50 + "\n")

        errors = []

        # Test 1: Imports
        print("Testing imports...", end=" ")
        try:
            from core.decision_engine import DecisionEngine
            from core.weather_analyzer import WeatherEventAnalyzer
            from core.corporate_analyzer import CorporateEventAnalyzer
            from core.court_analyzer import CourtRulingAnalyzer
            from app.orchestrator import Orchestrator
            print("OK")
        except Exception as e:
            print(f"FAIL: {e}")
            errors.append(("imports", str(e)))

        # Test 2: Orchestrator status
        print("Testing orchestrator...", end=" ")
        try:
            from app.orchestrator import get_status
            status = get_status()
            assert "last_run" in status
            print("OK")
        except Exception as e:
            print(f"FAIL: {e}")
            errors.append(("orchestrator", str(e)))

        # Test 3: Paper trading
        print("Testing paper trading...", end=" ")
        try:
            from paper_trader.position_manager import get_position_summary
            summary = get_position_summary()
            assert "total_positions" in summary
            print("OK")
        except Exception as e:
            print(f"FAIL: {e}")
            errors.append(("paper_trading", str(e)))

        # Test 4: Weather analyzer
        print("Testing weather analyzer...", end=" ")
        try:
            from core.weather_analyzer import analyze_weather_market
            result = analyze_weather_market(
                market_question="Test temperature at KJFK exceed 40°C?",
                resolution_text="NOAA METAR data. 11:59 PM EST.",
                target_date="2026-07-31",
            )
            assert result.decision in ("TRADE", "NO_TRADE", "INSUFFICIENT_DATA")
            print("OK")
        except Exception as e:
            print(f"FAIL: {e}")
            errors.append(("weather_analyzer", str(e)))

        # Test 5: Corporate analyzer
        print("Testing corporate analyzer...", end=" ")
        try:
            from core.corporate_analyzer import analyze_corporate_market
            result = analyze_corporate_market(
                market_question="Will Apple (AAPL) file 10-K with SEC?",
                resolution_text="SEC EDGAR database. Binary resolution.",
                target_date="2026-01-31",
            )
            assert result.decision in ("TRADE", "NO_TRADE", "INSUFFICIENT_DATA")
            print("OK")
        except Exception as e:
            print(f"FAIL: {e}")
            errors.append(("corporate_analyzer", str(e)))

        # Test 6: Court analyzer
        print("Testing court analyzer...", end=" ")
        try:
            from core.court_analyzer import analyze_court_market
            result = analyze_court_market(
                market_question="Will SCOTUS affirm in case 23-719?",
                resolution_text="supremecourt.gov official opinions.",
                target_date="2026-06-30",
            )
            assert result.decision in ("TRADE", "NO_TRADE", "INSUFFICIENT_DATA")
            print("OK")
        except Exception as e:
            print(f"FAIL: {e}")
            errors.append(("court_analyzer", str(e)))

        print("\n" + "="*50)
        if errors:
            print(f"  SMOKE TEST: {len(errors)} ERRORS")
            for name, err in errors:
                print(f"    - {name}: {err}")
            sys.exit(1)
        else:
            print("  SMOKE TEST: ALL PASSED")
        print("="*50 + "\n")
        sys.exit(0)

    else:
        # Full test suite
        from tests.e2e.test_suite import run_all_tests
        result = run_all_tests(verbose=args.verbose)
        sys.exit(0 if result["status"] == "PASSED" else 1)


if __name__ == "__main__":
    main()
