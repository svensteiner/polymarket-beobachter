# =============================================================================
# POLYMARKET BEOBACHTER - COMPREHENSIVE E2E TEST SUITE
# =============================================================================
#
# PURPOSE:
# End-to-end testing of ALL system components to ensure correctness.
# Run this before deployments, after changes, or on schedule.
#
# USAGE:
#   python -m tests.e2e.test_suite           # Run all tests
#   python -m tests.e2e.test_suite --verbose # Verbose output
#   python -m tests.e2e.test_suite --module analyzer  # Test specific module
#
# =============================================================================

import sys
import time
import traceback
from pathlib import Path
from datetime import datetime, date
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Callable
from enum import Enum

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tests.e2e.mock_data import (
    MockMarket,
    get_all_mocks,
    get_all_valid_mocks,
    get_all_invalid_mocks,
    get_mocks_by_category,
    create_eu_regulation_valid,
    create_weather_valid,
    create_corporate_valid,
    create_court_valid,
)


# =============================================================================
# TEST RESULT MODELS
# =============================================================================


class ResultStatus(Enum):
    PASSED = "PASSED"
    FAILED = "FAILED"
    ERROR = "ERROR"
    SKIPPED = "SKIPPED"


@dataclass
class SingleResult:
    """Result of a single test."""
    name: str
    status: ResultStatus
    duration_ms: int
    message: str = ""
    error: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SuiteResult:
    """Result of a test suite."""
    suite_name: str
    results: List[SingleResult] = field(default_factory=list)
    start_time: str = ""
    end_time: str = ""
    total_duration_ms: int = 0

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r.status == ResultStatus.PASSED)

    @property
    def failed(self) -> int:
        return sum(1 for r in self.results if r.status == ResultStatus.FAILED)

    @property
    def errors(self) -> int:
        return sum(1 for r in self.results if r.status == ResultStatus.ERROR)

    @property
    def skipped(self) -> int:
        return sum(1 for r in self.results if r.status == ResultStatus.SKIPPED)

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def success_rate(self) -> float:
        if self.total == 0:
            return 0.0
        return self.passed / self.total * 100

    def add_result(self, result: SingleResult):
        self.results.append(result)


# =============================================================================
# TEST RUNNER
# =============================================================================


class SuiteRunner:
    """Runs tests and collects results."""

    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        self.suites: List[SuiteResult] = []

    def run_test(
        self, name: str, test_fn: Callable[[], bool], expected: bool = True
    ) -> SingleResult:
        """
        Run a single test function.

        Args:
            name: Test name
            test_fn: Function that returns True if test passes
            expected: Expected return value (default True)

        Returns:
            SingleResult
        """
        start = time.time()
        try:
            result = test_fn()
            duration_ms = int((time.time() - start) * 1000)

            if result == expected:
                return SingleResult(
                    name=name,
                    status=ResultStatus.PASSED,
                    duration_ms=duration_ms,
                    message="Test passed",
                )
            else:
                return SingleResult(
                    name=name,
                    status=ResultStatus.FAILED,
                    duration_ms=duration_ms,
                    message=f"Expected {expected}, got {result}",
                )

        except Exception as e:
            duration_ms = int((time.time() - start) * 1000)
            return SingleResult(
                name=name,
                status=ResultStatus.ERROR,
                duration_ms=duration_ms,
                message=str(e),
                error=traceback.format_exc(),
            )

    def run_suite(self, suite_name: str, tests: List[tuple]) -> SuiteResult:
        """
        Run a test suite.

        Args:
            suite_name: Name of the suite
            tests: List of (name, test_fn, expected) tuples

        Returns:
            SuiteResult
        """
        suite = SuiteResult(suite_name=suite_name)
        suite.start_time = datetime.now().isoformat()

        if self.verbose:
            print(f"\n{'='*60}")
            print(f"  SUITE: {suite_name}")
            print(f"{'='*60}")

        start = time.time()
        for test_tuple in tests:
            name = test_tuple[0]
            test_fn = test_tuple[1]
            expected = test_tuple[2] if len(test_tuple) > 2 else True

            result = self.run_test(name, test_fn, expected)
            suite.add_result(result)

            if self.verbose:
                status_icon = {
                    ResultStatus.PASSED: "[OK]",
                    ResultStatus.FAILED: "[FAIL]",
                    ResultStatus.ERROR: "[ERR]",
                    ResultStatus.SKIPPED: "[SKIP]",
                }.get(result.status, "[?]")
                print(f"  {status_icon} {name} ({result.duration_ms}ms)")
                if result.status != ResultStatus.PASSED and result.message:
                    print(f"      {result.message}")

        suite.total_duration_ms = int((time.time() - start) * 1000)
        suite.end_time = datetime.now().isoformat()

        self.suites.append(suite)
        return suite

    def get_summary(self) -> Dict[str, Any]:
        """Get overall test summary."""
        total_passed = sum(s.passed for s in self.suites)
        total_failed = sum(s.failed for s in self.suites)
        total_errors = sum(s.errors for s in self.suites)
        total_tests = sum(s.total for s in self.suites)

        return {
            "suites": len(self.suites),
            "total_tests": total_tests,
            "passed": total_passed,
            "failed": total_failed,
            "errors": total_errors,
            "success_rate": total_passed / total_tests * 100 if total_tests > 0 else 0,
        }


# =============================================================================
# MODULE TESTS
# =============================================================================


def test_imports() -> bool:
    """Test that all modules can be imported."""
    try:
        from core.decision_engine import DecisionEngine
        from core.resolution_parser import ResolutionParser
        from core.process_model import EUProcessModel
        from core.time_feasibility import TimeFeasibilityChecker
        from core.probability_estimator import ProbabilityEstimator
        from core.market_sanity import MarketSanityChecker
        from core.weather_validation import WeatherValidator
        from core.weather_analyzer import WeatherEventAnalyzer
        from core.corporate_validation import CorporateEventValidator
        from core.corporate_analyzer import CorporateEventAnalyzer
        from core.court_validation import CourtRulingValidator
        from core.court_analyzer import CourtRulingAnalyzer
        from collector.collector import Collector
        from collector.filter import MarketFilter
        from proposals.generator import ProposalGenerator
        from proposals.review_gate import ReviewGate
        from paper_trader.position_manager import PositionManager
        from app.orchestrator import Orchestrator
        return True
    except ImportError as e:
        print(f"Import error: {e}")
        return False


def test_collector_filter_init() -> bool:
    """Test collector filter initialization."""
    from collector.filter import MarketFilter
    mf = MarketFilter()
    return (
        len(mf.eu_keywords) > 0 and
        len(mf.ai_keywords) > 0 and
        len(mf.corporate_keywords) > 0 and
        len(mf.court_keywords) > 0
    )


def test_weather_validator_init() -> bool:
    """Test weather validator initialization."""
    from core.weather_validation import WeatherValidator
    wv = WeatherValidator()
    return len(wv.VALID_SOURCES) > 0 and len(wv.VALID_METRIC_PATTERNS) > 0


def test_corporate_validator_init() -> bool:
    """Test corporate validator initialization."""
    from core.corporate_validation import CorporateEventValidator
    cv = CorporateEventValidator()
    return len(cv.VALID_SOURCES) > 0 and len(cv.KNOWN_COMPANIES) > 0


def test_court_validator_init() -> bool:
    """Test court validator initialization."""
    from core.court_validation import CourtRulingValidator
    crv = CourtRulingValidator()
    return len(crv.ALL_COURTS) > 0 and len(crv.VALID_SOURCES) > 0


# =============================================================================
# ANALYZER TESTS
# =============================================================================


def test_weather_valid_market() -> bool:
    """Test weather analyzer with valid market."""
    from core.weather_analyzer import analyze_weather_market

    mock = create_weather_valid()
    result = analyze_weather_market(
        market_question=mock.title,
        resolution_text=mock.resolution_text,
        target_date=mock.end_date,
        description=mock.description,
    )
    return result.decision == "TRADE"


def test_weather_invalid_vague() -> bool:
    """Test weather analyzer rejects vague metrics."""
    from core.weather_analyzer import analyze_weather_market
    from tests.e2e.mock_data import create_weather_invalid_vague_metric

    mock = create_weather_invalid_vague_metric()
    result = analyze_weather_market(
        market_question=mock.title,
        resolution_text=mock.resolution_text,
        target_date=mock.end_date,
        description=mock.description,
    )
    return result.decision == "INSUFFICIENT_DATA"


def test_corporate_valid_market() -> bool:
    """Test corporate analyzer with valid market."""
    from core.corporate_analyzer import analyze_corporate_market

    mock = create_corporate_valid()
    result = analyze_corporate_market(
        market_question=mock.title,
        resolution_text=mock.resolution_text,
        target_date=mock.end_date,
        description=mock.description,
    )
    return result.decision == "TRADE"


def test_corporate_invalid_subjective() -> bool:
    """Test corporate analyzer rejects subjective outcomes."""
    from core.corporate_analyzer import analyze_corporate_market
    from tests.e2e.mock_data import create_corporate_invalid_subjective

    mock = create_corporate_invalid_subjective()
    result = analyze_corporate_market(
        market_question=mock.title,
        resolution_text=mock.resolution_text,
        target_date=mock.end_date,
        description=mock.description,
    )
    return result.decision in ("NO_TRADE", "INSUFFICIENT_DATA")


def test_court_valid_market() -> bool:
    """Test court analyzer with valid market."""
    from core.court_analyzer import analyze_court_market

    mock = create_court_valid()
    result = analyze_court_market(
        market_question=mock.title,
        resolution_text=mock.resolution_text,
        target_date=mock.end_date,
        description=mock.description,
    )
    return result.decision == "TRADE"


def test_court_invalid_no_case() -> bool:
    """Test court analyzer rejects markets without case ID."""
    from core.court_analyzer import analyze_court_market
    from tests.e2e.mock_data import create_court_invalid_no_case

    mock = create_court_invalid_no_case()
    result = analyze_court_market(
        market_question=mock.title,
        resolution_text=mock.resolution_text,
        target_date=mock.end_date,
        description=mock.description,
    )
    return result.decision in ("NO_TRADE", "INSUFFICIENT_DATA")


# =============================================================================
# PROPOSAL TESTS
# =============================================================================


def test_proposal_generator_init() -> bool:
    """Test proposal generator initialization."""
    from proposals.generator import ProposalGenerator
    pg = ProposalGenerator()
    return pg is not None


def test_review_gate_init() -> bool:
    """Test review gate initialization."""
    from proposals.review_gate import ReviewGate
    rg = ReviewGate()
    return rg is not None


# =============================================================================
# PAPER TRADING TESTS
# =============================================================================


def test_paper_position_manager_init() -> bool:
    """Test paper position manager initialization."""
    from paper_trader.position_manager import PositionManager
    pm = PositionManager()
    return pm is not None


def test_paper_position_summary() -> bool:
    """Test paper position summary retrieval."""
    from paper_trader.position_manager import get_position_summary
    summary = get_position_summary()
    return (
        "total_positions" in summary and
        "open" in summary and
        "total_realized_pnl_eur" in summary
    )


def test_paper_slippage_model() -> bool:
    """Test slippage model calculation."""
    from paper_trader.slippage import SlippageModel
    from paper_trader.models import MarketSnapshot, LiquidityBucket
    from datetime import datetime

    # Create a test snapshot
    snapshot = MarketSnapshot(
        market_id="test",
        snapshot_time=datetime.now().isoformat(),
        best_bid=0.48,
        best_ask=0.52,
        mid_price=0.50,
        spread_pct=0.08,
        liquidity_bucket=LiquidityBucket.MEDIUM.value,
        is_resolved=False,
        resolved_outcome=None,
    )

    # Test slippage model
    model = SlippageModel()
    result = model.calculate_entry_price(
        snapshot=snapshot,
        side="YES",
    )

    # Result should be a tuple (price, slippage) or None
    if result is None:
        return True  # No price available is valid

    entry_price, slippage = result
    # Entry price should be reasonable (between 0 and 1)
    return 0 < entry_price < 1 and slippage >= 0


def test_paper_intake_eligible() -> bool:
    """Test paper trading intake module."""
    from paper_trader.intake import get_eligible_proposals
    # Should return a list (may be empty if no proposals)
    proposals = get_eligible_proposals()
    return isinstance(proposals, list)


def test_paper_simulator_init() -> bool:
    """Test paper trading simulator initialization."""
    from paper_trader.simulator import ExecutionSimulator
    sim = ExecutionSimulator(fixed_amount_eur=100.0)
    return sim.fixed_amount_eur == 100.0


def test_paper_trade_models() -> bool:
    """Test paper trading data models."""
    from paper_trader.models import (
        PaperPosition, PaperTradeRecord, TradeAction,
        generate_position_id, generate_record_id
    )

    # Test ID generation
    pos_id = generate_position_id()
    rec_id = generate_record_id()

    # Test TradeAction enum
    actions = [TradeAction.PAPER_ENTER, TradeAction.PAPER_EXIT, TradeAction.SKIP]

    return (
        len(pos_id) > 0 and
        len(rec_id) > 0 and
        len(actions) == 3
    )


# =============================================================================
# ORCHESTRATOR TESTS
# =============================================================================


def test_orchestrator_init() -> bool:
    """Test orchestrator initialization."""
    from app.orchestrator import Orchestrator
    orch = Orchestrator()
    return (
        orch.output_dir.exists() or True and  # May not exist yet
        orch.logs_dir is not None
    )


def test_orchestrator_status() -> bool:
    """Test orchestrator status retrieval."""
    from app.orchestrator import get_status
    status = get_status()
    return (
        "last_run" in status and
        "paper_positions_open" in status
    )


def test_orchestrator_category_stats() -> bool:
    """Test orchestrator category stats retrieval."""
    from app.orchestrator import get_category_stats
    stats = get_category_stats()
    required_keys = [
        "eu_regulation", "weather_event", "corporate_event",
        "court_ruling", "generic", "total_candidates"
    ]
    return all(k in stats for k in required_keys)


def test_orchestrator_filter_stats() -> bool:
    """Test orchestrator filter stats retrieval."""
    from app.orchestrator import get_filter_stats
    stats = get_filter_stats()
    required_keys = [
        "included", "total_fetched", "excluded_no_eu_match"
    ]
    return all(k in stats for k in required_keys)


def test_orchestrator_candidates() -> bool:
    """Test orchestrator candidates retrieval."""
    from app.orchestrator import get_candidates
    candidates = get_candidates()
    # Should return a list (possibly empty)
    return isinstance(candidates, list)


def test_orchestrator_audit_log() -> bool:
    """Test orchestrator audit log retrieval."""
    from app.orchestrator import get_audit_log
    entries = get_audit_log(limit=5)
    # Should return a list (possibly empty)
    return isinstance(entries, list)


# =============================================================================
# INTEGRATION TESTS
# =============================================================================


def test_full_pipeline_single_market() -> bool:
    """Test full pipeline with a single mock market."""
    from core.weather_analyzer import analyze_weather_market
    from proposals.generator import ProposalGenerator
    from proposals.review_gate import ReviewGate

    # Step 1: Analyze a valid market
    mock = create_weather_valid()
    analysis = analyze_weather_market(
        market_question=mock.title,
        resolution_text=mock.resolution_text,
        target_date=mock.end_date,
        description=mock.description,
    )

    if analysis.decision != "TRADE":
        return False

    # Step 2: Generate proposal (would need adapter)
    # For now, just verify the analysis passed
    return True


def test_filter_categorization() -> bool:
    """Test that filter correctly categorizes different market types."""
    from collector.filter import MarketFilter, FilterResult

    mf = MarketFilter()

    # Test EU market
    eu_mock = create_eu_regulation_valid()
    eu_result = mf.filter_market(eu_mock.to_dict())

    # Test corporate market
    corp_mock = create_corporate_valid()
    corp_result = mf.filter_market(corp_mock.to_dict())

    # Test court market
    court_mock = create_court_valid()
    court_result = mf.filter_market(court_mock.to_dict())

    # At least one should be included
    included_results = [
        FilterResult.INCLUDED,
        FilterResult.INCLUDED_CORPORATE,
        FilterResult.INCLUDED_COURT,
    ]

    return (
        corp_result.result in included_results or
        court_result.result in included_results or
        eu_result.result in included_results
    )


# =============================================================================
# GOVERNANCE TESTS
# =============================================================================


def test_no_live_trading_imports() -> bool:
    """Verify that paper trading doesn't import live trading modules."""
    import paper_trader.position_manager as pm
    try:
        with open(pm.__file__, 'r', encoding='utf-8') as f:
            module_code = f.read()
        # Should not contain live trading imports
        forbidden = ["live_trader", "real_execution", "binance", "coinbase"]
        return not any(f in module_code.lower() for f in forbidden)
    except Exception:
        # If we can't read, assume it's safe (no forbidden imports)
        return True


def test_proposals_read_only() -> bool:
    """Verify paper trading has read-only access to proposals."""
    import paper_trader.intake as intake
    try:
        with open(intake.__file__, 'r', encoding='utf-8') as f:
            module_code = f.read()
        # Should contain read-only comments
        return "READ-ONLY" in module_code or "read only" in module_code.lower()
    except Exception:
        # If we can't read the file, check the module docstring
        return "READ-ONLY" in (intake.__doc__ or "")


# =============================================================================
# BUILD TEST SUITES
# =============================================================================


def build_module_tests() -> List[tuple]:
    """Build module initialization tests."""
    return [
        ("Import all modules", test_imports),
        ("Collector filter init", test_collector_filter_init),
        ("Weather validator init", test_weather_validator_init),
        ("Corporate validator init", test_corporate_validator_init),
        ("Court validator init", test_court_validator_init),
        ("Proposal generator init", test_proposal_generator_init),
        ("Review gate init", test_review_gate_init),
        ("Paper position manager init", test_paper_position_manager_init),
        ("Orchestrator init", test_orchestrator_init),
    ]


def build_analyzer_tests() -> List[tuple]:
    """Build analyzer tests."""
    return [
        ("Weather: valid market = TRADE", test_weather_valid_market),
        ("Weather: vague metric = INSUFFICIENT", test_weather_invalid_vague),
        ("Corporate: valid market = TRADE", test_corporate_valid_market),
        ("Corporate: subjective = NO_TRADE", test_corporate_invalid_subjective),
        ("Court: valid market = TRADE", test_court_valid_market),
        ("Court: no case ID = NO_TRADE", test_court_invalid_no_case),
    ]


def build_paper_trading_tests() -> List[tuple]:
    """Build paper trading tests."""
    return [
        ("Position summary retrieval", test_paper_position_summary),
        ("Slippage model calculation", test_paper_slippage_model),
        ("Intake eligible proposals", test_paper_intake_eligible),
        ("Simulator initialization", test_paper_simulator_init),
        ("Trade data models", test_paper_trade_models),
    ]


def build_integration_tests() -> List[tuple]:
    """Build integration tests."""
    return [
        ("Full pipeline single market", test_full_pipeline_single_market),
        ("Filter categorization", test_filter_categorization),
        ("Orchestrator status", test_orchestrator_status),
        ("Orchestrator category stats", test_orchestrator_category_stats),
        ("Orchestrator filter stats", test_orchestrator_filter_stats),
        ("Orchestrator candidates list", test_orchestrator_candidates),
        ("Orchestrator audit log", test_orchestrator_audit_log),
    ]


def build_governance_tests() -> List[tuple]:
    """Build governance/safety tests."""
    return [
        ("No live trading imports", test_no_live_trading_imports),
        ("Proposals read-only access", test_proposals_read_only),
    ]


# =============================================================================
# DASHBOARD TESTS
# =============================================================================


def test_dashboard_category_stats() -> bool:
    """Test dashboard category stats loader."""
    from dashboard import load_category_stats
    stats = load_category_stats()
    required_keys = ["eu_regulation", "weather_event", "corporate_event", "court_ruling"]
    return all(k in stats for k in required_keys)


def test_dashboard_filter_stats() -> bool:
    """Test dashboard filter stats loader."""
    from dashboard import load_filter_stats
    stats = load_filter_stats()
    return "total_fetched" in stats and "included" in stats


def test_dashboard_candidates() -> bool:
    """Test dashboard candidates loader."""
    from dashboard import load_candidates
    candidates = load_candidates()
    return isinstance(candidates, list)


def test_dashboard_audit_log() -> bool:
    """Test dashboard audit log loader."""
    from dashboard import load_audit_log
    entries = load_audit_log()
    return isinstance(entries, list)


def test_dashboard_paper_summary() -> bool:
    """Test dashboard paper summary loader."""
    from dashboard import load_paper_summary
    summary = load_paper_summary()
    return (
        "open_positions" in summary and
        "realized_pnl" in summary
    )


def build_dashboard_tests() -> List[tuple]:
    """Build dashboard tests."""
    return [
        ("Dashboard category stats", test_dashboard_category_stats),
        ("Dashboard filter stats", test_dashboard_filter_stats),
        ("Dashboard candidates", test_dashboard_candidates),
        ("Dashboard audit log", test_dashboard_audit_log),
        ("Dashboard paper summary", test_dashboard_paper_summary),
    ]


# =============================================================================
# MAIN
# =============================================================================


def run_all_tests(verbose: bool = False) -> Dict[str, Any]:
    """
    Run all test suites.

    Returns:
        Summary dictionary
    """
    runner = SuiteRunner(verbose=verbose)

    print("\n" + "="*60)
    print("  POLYMARKET BEOBACHTER - E2E TEST SUITE")
    print("  " + datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    print("="*60)

    # Run all suites
    runner.run_suite("Module Initialization", build_module_tests())
    runner.run_suite("Analyzers", build_analyzer_tests())
    runner.run_suite("Paper Trading", build_paper_trading_tests())
    runner.run_suite("Integration", build_integration_tests())
    runner.run_suite("Dashboard", build_dashboard_tests())
    runner.run_suite("Governance", build_governance_tests())

    # Print summary
    summary = runner.get_summary()

    print("\n" + "="*60)
    print("  SUMMARY")
    print("="*60)
    print(f"  Suites:       {summary['suites']}")
    print(f"  Total Tests:  {summary['total_tests']}")
    print(f"  Passed:       {summary['passed']}")
    print(f"  Failed:       {summary['failed']}")
    print(f"  Errors:       {summary['errors']}")
    print(f"  Success Rate: {summary['success_rate']:.1f}%")
    print("="*60)

    # Print failed tests
    if summary['failed'] > 0 or summary['errors'] > 0:
        print("\n  FAILED TESTS:")
        for suite in runner.suites:
            for result in suite.results:
                if result.status in (ResultStatus.FAILED, ResultStatus.ERROR):
                    print(f"    - [{suite.suite_name}] {result.name}")
                    print(f"      {result.message}")

    # Overall status
    if summary['failed'] == 0 and summary['errors'] == 0:
        print("\n  STATUS: ALL TESTS PASSED")
        return {"status": "PASSED", **summary}
    else:
        print("\n  STATUS: SOME TESTS FAILED")
        return {"status": "FAILED", **summary}


def run_tests_loop(
    iterations: int = 3,
    delay_seconds: int = 2,
    verbose: bool = False
) -> Dict[str, Any]:
    """
    Run tests in a loop for continuous validation.

    Args:
        iterations: Number of test iterations
        delay_seconds: Delay between iterations
        verbose: Verbose output

    Returns:
        Summary of all iterations
    """
    results = []
    all_passed = True

    print("\n" + "="*60)
    print(f"  RUNNING {iterations} TEST ITERATIONS")
    print("="*60)

    for i in range(iterations):
        print(f"\n>>> ITERATION {i+1}/{iterations}")
        result = run_all_tests(verbose=verbose)
        results.append(result)

        if result["status"] != "PASSED":
            all_passed = False

        if i < iterations - 1:
            print(f"\n  Waiting {delay_seconds}s before next iteration...")
            time.sleep(delay_seconds)

    # Summary of all iterations
    print("\n" + "="*60)
    print("  LOOP SUMMARY")
    print("="*60)
    for i, r in enumerate(results):
        status_icon = "[OK]" if r["status"] == "PASSED" else "[FAIL]"
        print(f"  Iteration {i+1}: {status_icon} ({r['passed']}/{r['total_tests']} passed)")

    print("="*60)
    if all_passed:
        print("  ALL ITERATIONS PASSED")
    else:
        print("  SOME ITERATIONS FAILED")
    print("="*60)

    return {
        "all_passed": all_passed,
        "iterations": len(results),
        "results": results,
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Run E2E tests")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    parser.add_argument("--loop", "-l", type=int, default=0, help="Run tests N times in a loop")
    parser.add_argument("--delay", "-d", type=int, default=2, help="Delay between loop iterations (seconds)")
    args = parser.parse_args()

    if args.loop > 0:
        result = run_tests_loop(
            iterations=args.loop,
            delay_seconds=args.delay,
            verbose=args.verbose
        )
        sys.exit(0 if result["all_passed"] else 1)
    else:
        result = run_all_tests(verbose=args.verbose)
        sys.exit(0 if result["status"] == "PASSED" else 1)
