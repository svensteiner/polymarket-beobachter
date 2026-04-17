"""Global test fixtures for pytest."""
import pytest


@pytest.fixture(autouse=True)
def reset_paper_trader_singletons():
    """Reset all paper_trader singletons before and after each test.

    Prevents test contamination where one test's patched singleton leaks
    into the next test, potentially causing writes to real data files.
    """
    def _reset():
        try:
            import paper_trader.capital_manager as cm
            cm._capital_manager = None
        except Exception:
            pass
        try:
            import paper_trader.logger as pl
            pl._paper_logger = None
        except Exception:
            pass
        try:
            import paper_trader.simulator as sim
            sim._simulator = None
        except Exception:
            pass
        try:
            import paper_trader.position_manager as pm
            pm._position_manager = None
        except Exception:
            pass

    _reset()
    yield
    _reset()
