#!/usr/bin/env python3
"""
POLYMARKET BEOBACHTER - TEST ENGINE RUNNER
==========================================
Fuehrt alle Tests aus und generiert Reports.

Usage:
    python -m test_engine.run_all              # Alle Tests
    python -m test_engine.run_all --unit       # Nur Unit Tests
    python -m test_engine.run_all --integration # Nur Integration Tests
    python -m test_engine.run_all --stress     # Nur Stress Tests
    python -m test_engine.run_all --quick      # Schnelle Tests (kein Stress)
    python -m test_engine.run_all --verbose    # Ausfuehrliche Ausgabe
    python -m test_engine.run_all --html       # HTML Report generieren
"""

import sys
import os
import time
import json
import argparse
import traceback
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List, Tuple, Callable
from dataclasses import dataclass, field
from enum import Enum

# Setup paths
BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR))

TEST_ENGINE_DIR = Path(__file__).parent
REPORTS_DIR = TEST_ENGINE_DIR / "reports"


# =============================================================================
# TEST RESULT TYPES
# =============================================================================

class TestStatus(Enum):
    PASSED = "PASSED"
    FAILED = "FAILED"
    ERROR = "ERROR"
    SKIPPED = "SKIPPED"


@dataclass
class TestResult:
    """Result of a single test."""
    name: str
    status: TestStatus
    duration_ms: float
    message: str = ""
    error: str = ""
    traceback: str = ""


@dataclass
class TestSuiteResult:
    """Result of a test suite."""
    name: str
    tests: List[TestResult] = field(default_factory=list)
    start_time: str = ""
    end_time: str = ""
    duration_seconds: float = 0.0

    @property
    def passed(self) -> int:
        return sum(1 for t in self.tests if t.status == TestStatus.PASSED)

    @property
    def failed(self) -> int:
        return sum(1 for t in self.tests if t.status == TestStatus.FAILED)

    @property
    def errors(self) -> int:
        return sum(1 for t in self.tests if t.status == TestStatus.ERROR)

    @property
    def skipped(self) -> int:
        return sum(1 for t in self.tests if t.status == TestStatus.SKIPPED)

    @property
    def total(self) -> int:
        return len(self.tests)

    @property
    def success_rate(self) -> float:
        if self.total == 0:
            return 100.0
        return (self.passed / self.total) * 100


@dataclass
class FullTestReport:
    """Complete test report."""
    suites: List[TestSuiteResult] = field(default_factory=list)
    start_time: str = ""
    end_time: str = ""
    duration_seconds: float = 0.0

    @property
    def total_passed(self) -> int:
        return sum(s.passed for s in self.suites)

    @property
    def total_failed(self) -> int:
        return sum(s.failed for s in self.suites)

    @property
    def total_errors(self) -> int:
        return sum(s.errors for s in self.suites)

    @property
    def total_tests(self) -> int:
        return sum(s.total for s in self.suites)

    @property
    def overall_success_rate(self) -> float:
        if self.total_tests == 0:
            return 100.0
        return (self.total_passed / self.total_tests) * 100

    def to_dict(self) -> Dict[str, Any]:
        return {
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration_seconds": self.duration_seconds,
            "total_tests": self.total_tests,
            "passed": self.total_passed,
            "failed": self.total_failed,
            "errors": self.total_errors,
            "success_rate": self.overall_success_rate,
            "suites": [
                {
                    "name": s.name,
                    "total": s.total,
                    "passed": s.passed,
                    "failed": s.failed,
                    "duration_seconds": s.duration_seconds,
                    "tests": [
                        {
                            "name": t.name,
                            "status": t.status.value,
                            "duration_ms": t.duration_ms,
                            "message": t.message,
                            "error": t.error,
                        }
                        for t in s.tests
                    ]
                }
                for s in self.suites
            ]
        }


# =============================================================================
# TERMINAL COLORS
# =============================================================================

class C:
    """Terminal colors."""
    RESET = "\033[0m"
    BOLD = "\033[1m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    CYAN = "\033[96m"
    DIM = "\033[2m"

    @classmethod
    def disable(cls):
        for attr in dir(cls):
            if attr.isupper():
                setattr(cls, attr, "")


# Windows color support
if sys.platform == "win32":
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
    except Exception:
        C.disable()


# =============================================================================
# TEST RUNNER
# =============================================================================

class TestRunner:
    """Main test runner."""

    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        self.report = FullTestReport()

    def run_test(self, name: str, test_func: Callable) -> TestResult:
        """Run a single test function."""
        start_time = time.time()

        try:
            test_func()
            duration_ms = (time.time() - start_time) * 1000
            return TestResult(
                name=name,
                status=TestStatus.PASSED,
                duration_ms=duration_ms,
                message="OK"
            )

        except AssertionError as e:
            duration_ms = (time.time() - start_time) * 1000
            return TestResult(
                name=name,
                status=TestStatus.FAILED,
                duration_ms=duration_ms,
                message=str(e),
                error=str(e),
                traceback=traceback.format_exc()
            )

        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            return TestResult(
                name=name,
                status=TestStatus.ERROR,
                duration_ms=duration_ms,
                message=f"Exception: {type(e).__name__}",
                error=str(e),
                traceback=traceback.format_exc()
            )

    def run_suite(self, name: str, tests: List[Tuple[str, Callable]]) -> TestSuiteResult:
        """Run a test suite."""
        suite = TestSuiteResult(name=name)
        suite.start_time = datetime.now().isoformat()

        print(f"\n{C.BOLD}{C.CYAN}{'='*60}{C.RESET}")
        print(f"{C.BOLD}{C.CYAN}  TEST SUITE: {name}{C.RESET}")
        print(f"{C.BOLD}{C.CYAN}{'='*60}{C.RESET}\n")

        start_time = time.time()

        for test_name, test_func in tests:
            result = self.run_test(test_name, test_func)
            suite.tests.append(result)

            # Print result
            if result.status == TestStatus.PASSED:
                icon = f"{C.GREEN}PASS{C.RESET}"
            elif result.status == TestStatus.FAILED:
                icon = f"{C.RED}FAIL{C.RESET}"
            elif result.status == TestStatus.ERROR:
                icon = f"{C.RED}ERROR{C.RESET}"
            else:
                icon = f"{C.YELLOW}SKIP{C.RESET}"

            time_str = f"{C.DIM}({result.duration_ms:.1f}ms){C.RESET}"
            print(f"  [{icon}] {test_name} {time_str}")

            if result.status != TestStatus.PASSED and self.verbose:
                print(f"        {C.DIM}{result.error[:100]}{C.RESET}")

        suite.duration_seconds = time.time() - start_time
        suite.end_time = datetime.now().isoformat()

        # Summary
        print(f"\n  {C.DIM}{'-'*50}{C.RESET}")
        print(f"  {C.GREEN}{suite.passed} passed{C.RESET}, ", end="")
        print(f"{C.RED}{suite.failed} failed{C.RESET}, ", end="")
        print(f"{C.YELLOW}{suite.errors} errors{C.RESET} ", end="")
        print(f"({suite.duration_seconds:.2f}s)")

        return suite

    def print_final_report(self):
        """Print final test report."""
        print(f"\n\n{C.BOLD}{'='*60}{C.RESET}")
        print(f"{C.BOLD}  FINAL TEST REPORT{C.RESET}")
        print(f"{C.BOLD}{'='*60}{C.RESET}\n")

        for suite in self.report.suites:
            rate = suite.success_rate
            if rate == 100:
                color = C.GREEN
            elif rate >= 80:
                color = C.YELLOW
            else:
                color = C.RED

            print(f"  {suite.name:<30} {color}{suite.passed}/{suite.total}{C.RESET} ({rate:.0f}%)")

        print(f"\n  {C.DIM}{'-'*50}{C.RESET}")

        total = self.report.total_tests
        passed = self.report.total_passed
        failed = self.report.total_failed
        errors = self.report.total_errors
        rate = self.report.overall_success_rate

        if rate == 100:
            status_color = C.GREEN
            status_text = "ALL TESTS PASSED"
        elif rate >= 80:
            status_color = C.YELLOW
            status_text = "SOME TESTS FAILED"
        else:
            status_color = C.RED
            status_text = "TESTS FAILED"

        print(f"\n  {C.BOLD}Total:{C.RESET} {total} tests")
        print(f"  {C.GREEN}Passed:{C.RESET} {passed}")
        print(f"  {C.RED}Failed:{C.RESET} {failed}")
        print(f"  {C.YELLOW}Errors:{C.RESET} {errors}")
        print(f"  Duration: {self.report.duration_seconds:.2f}s")

        print(f"\n  {status_color}{C.BOLD}{status_text} ({rate:.1f}%){C.RESET}")
        print()

    def save_json_report(self):
        """Save JSON report."""
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_path = REPORTS_DIR / f"test_report_{timestamp}.json"

        with open(report_path, 'w') as f:
            json.dump(self.report.to_dict(), f, indent=2)

        print(f"  {C.DIM}Report saved: {report_path}{C.RESET}")

    def save_html_report(self):
        """Save HTML report."""
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_path = REPORTS_DIR / f"test_report_{timestamp}.html"

        html = self._generate_html_report()
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write(html)

        print(f"  {C.DIM}HTML Report: {report_path}{C.RESET}")

    def _generate_html_report(self) -> str:
        """Generate HTML report."""
        rate = self.report.overall_success_rate
        status_color = "#4CAF50" if rate == 100 else "#FFC107" if rate >= 80 else "#F44336"

        suites_html = ""
        for suite in self.report.suites:
            tests_html = ""
            for test in suite.tests:
                if test.status == TestStatus.PASSED:
                    status_class = "passed"
                    status_text = "PASS"
                elif test.status == TestStatus.FAILED:
                    status_class = "failed"
                    status_text = "FAIL"
                else:
                    status_class = "error"
                    status_text = "ERROR"

                error_html = ""
                if test.error:
                    error_html = f'<div class="error-msg">{test.error[:200]}</div>'

                tests_html += f'''
                <tr class="{status_class}">
                    <td>{test.name}</td>
                    <td class="status">{status_text}</td>
                    <td>{test.duration_ms:.1f}ms</td>
                    <td>{error_html}</td>
                </tr>
                '''

            suites_html += f'''
            <div class="suite">
                <h3>{suite.name}</h3>
                <p class="stats">{suite.passed}/{suite.total} passed ({suite.success_rate:.0f}%)</p>
                <table>
                    <tr><th>Test</th><th>Status</th><th>Time</th><th>Details</th></tr>
                    {tests_html}
                </table>
            </div>
            '''

        return f'''<!DOCTYPE html>
<html>
<head>
    <title>Test Report - Polymarket Beobachter</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; margin: 40px; background: #1a1a2e; color: #eee; }}
        h1 {{ color: #00d4ff; }}
        h3 {{ color: #00d4ff; margin-top: 30px; }}
        .summary {{ background: #16213e; padding: 20px; border-radius: 10px; margin-bottom: 30px; }}
        .summary-stat {{ display: inline-block; margin-right: 30px; }}
        .summary-stat .value {{ font-size: 32px; font-weight: bold; }}
        .summary-stat.passed .value {{ color: #4CAF50; }}
        .summary-stat.failed .value {{ color: #F44336; }}
        .suite {{ background: #16213e; padding: 20px; border-radius: 10px; margin-bottom: 20px; }}
        .stats {{ color: #888; }}
        table {{ width: 100%; border-collapse: collapse; margin-top: 10px; }}
        th, td {{ text-align: left; padding: 10px; border-bottom: 1px solid #333; }}
        th {{ color: #00d4ff; }}
        .passed .status {{ color: #4CAF50; }}
        .failed .status {{ color: #F44336; }}
        .error .status {{ color: #F44336; }}
        .error-msg {{ font-size: 12px; color: #F44336; max-width: 300px; }}
        .overall {{ font-size: 24px; font-weight: bold; color: {status_color}; margin-top: 20px; }}
    </style>
</head>
<body>
    <h1>Test Report - Polymarket Beobachter</h1>
    <p style="color: #888;">Generated: {self.report.end_time}</p>

    <div class="summary">
        <div class="summary-stat passed">
            <div class="value">{self.report.total_passed}</div>
            <div>Passed</div>
        </div>
        <div class="summary-stat failed">
            <div class="value">{self.report.total_failed}</div>
            <div>Failed</div>
        </div>
        <div class="summary-stat">
            <div class="value">{self.report.total_tests}</div>
            <div>Total</div>
        </div>
        <div class="summary-stat">
            <div class="value">{self.report.duration_seconds:.1f}s</div>
            <div>Duration</div>
        </div>
        <div class="overall">{rate:.1f}% Success Rate</div>
    </div>

    {suites_html}
</body>
</html>
'''


# =============================================================================
# MAIN
# =============================================================================

def main():
    parser = argparse.ArgumentParser(description="Polymarket Test Engine")
    parser.add_argument("--unit", action="store_true", help="Run only unit tests")
    parser.add_argument("--integration", action="store_true", help="Run only integration tests")
    parser.add_argument("--stress", action="store_true", help="Run only stress tests")
    parser.add_argument("--quick", action="store_true", help="Quick tests (skip stress)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    parser.add_argument("--html", action="store_true", help="Generate HTML report")
    parser.add_argument("--no-color", action="store_true", help="Disable colors")

    args = parser.parse_args()

    if args.no_color:
        C.disable()

    runner = TestRunner(verbose=args.verbose)

    print(f"\n{C.BOLD}{C.CYAN}")
    print("  +======================================================+")
    print("  |     POLYMARKET BEOBACHTER - TEST ENGINE              |")
    print("  +======================================================+")
    print(f"{C.RESET}")
    print(f"  {C.DIM}Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}{C.RESET}")

    runner.report.start_time = datetime.now().isoformat()
    start_time = time.time()

    # Determine which tests to run
    run_all = not (args.unit or args.integration or args.stress)

    # Import and run test suites
    if run_all or args.unit:
        from tests.unit import test_weather_signal
        from tests.unit import test_weather_filter
        from tests.unit import test_weather_probability
        from tests.unit import test_weather_engine
        from tests.unit import test_module_loader

        runner.report.suites.append(runner.run_suite(
            "Weather Signal",
            test_weather_signal.get_tests()
        ))

        runner.report.suites.append(runner.run_suite(
            "Weather Market Filter",
            test_weather_filter.get_tests()
        ))

        runner.report.suites.append(runner.run_suite(
            "Weather Probability Model",
            test_weather_probability.get_tests()
        ))

        runner.report.suites.append(runner.run_suite(
            "Weather Engine",
            test_weather_engine.get_tests()
        ))

        runner.report.suites.append(runner.run_suite(
            "Module Loader",
            test_module_loader.get_tests()
        ))

    if run_all or args.integration:
        from tests.integration import test_full_pipeline
        runner.report.suites.append(runner.run_suite(
            "Full Pipeline Integration",
            test_full_pipeline.get_tests()
        ))

    if (run_all or args.stress) and not args.quick:
        from tests.stress import test_performance
        runner.report.suites.append(runner.run_suite(
            "Performance & Stress",
            test_performance.get_tests()
        ))

    runner.report.duration_seconds = time.time() - start_time
    runner.report.end_time = datetime.now().isoformat()

    # Print and save reports
    runner.print_final_report()
    runner.save_json_report()

    if args.html:
        runner.save_html_report()

    # Return exit code
    if runner.report.total_failed > 0 or runner.report.total_errors > 0:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
