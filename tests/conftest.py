"""Global test fixtures — reset singletons between tests."""
import pytest


@pytest.fixture(autouse=True)
def reset_singletons():
    """Reset module-level singletons before and after each test."""
    _do_reset()
    yield
    _do_reset()


def _do_reset():
    try:
        import paper_trader.simulator as sim_mod
        sim_mod._simulator = None
    except ImportError:
        pass
    try:
        import paper_trader.capital_manager as cm_mod
        cm_mod._capital_manager = None
    except ImportError:
        pass
    try:
        import paper_trader.snapshot_client as sc_mod
        sc_mod._snapshot_client = None
    except ImportError:
        pass
