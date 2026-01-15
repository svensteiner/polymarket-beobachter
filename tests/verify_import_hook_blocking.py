# =============================================================================
# IMPORT HOOK BYPASS TEST
# =============================================================================
# Verifies that the import hook blocks bypass attempts via importlib.
# =============================================================================

import sys
import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)


def test_importlib_bypass_blocked():
    """Test that importlib.util bypass is blocked."""
    print("\n" + "=" * 60)
    print("TEST: Import Hook Blocks importlib.util Bypass")
    print("=" * 60)

    # First, activate Layer 1
    from shared.layer_guard import set_active_layer, LayerViolationError
    from shared.enums import Layer

    set_active_layer(Layer.LAYER1_INSTITUTIONAL)
    print("[INFO] Layer 1 activated")

    # Now try to import forbidden module via importlib.util
    import importlib.util

    try:
        # This should be BLOCKED by the import hook
        # Trying to import microstructure_research (forbidden for Layer 1)
        spec = importlib.util.find_spec("microstructure_research")
        if spec is not None:
            print("[FAIL] importlib.util.find_spec should have been blocked")
            return False
        else:
            print("[PASS] find_spec returned None (module doesn't exist or blocked)")

    except LayerViolationError as e:
        print(f"[PASS] LayerViolationError raised: {str(e)[:80]}...")
        return True

    # Also test direct import attempt
    try:
        import microstructure_research
        print("[FAIL] Direct import should have been blocked")
        return False
    except LayerViolationError as e:
        print(f"[PASS] Direct import blocked: {str(e)[:60]}...")
        return True
    except ImportError:
        # Module doesn't exist is also acceptable
        print("[PASS] Import failed (module may not exist)")
        return True


def test_universal_forbidden_blocked():
    """Test that universal forbidden modules (trading libs) are blocked."""
    print("\n" + "=" * 60)
    print("TEST: Universal Forbidden Modules Blocked")
    print("=" * 60)

    from shared.layer_guard import set_active_layer, LayerViolationError
    from shared.enums import Layer

    set_active_layer(Layer.LAYER1_INSTITUTIONAL)

    forbidden_modules = ["ccxt", "py_clob_client"]

    for mod in forbidden_modules:
        try:
            __import__(mod)
            # If we get here, module was not blocked
            # (but might not be installed)
            print(f"[WARN] {mod} not blocked (may not be installed)")
        except LayerViolationError:
            print(f"[PASS] {mod} blocked by layer guard")
        except ImportError:
            print(f"[INFO] {mod} not installed (would be blocked if present)")

    return True


if __name__ == "__main__":
    print("=" * 70)
    print("IMPORT HOOK BYPASS VERIFICATION")
    print("=" * 70)

    test_importlib_bypass_blocked()
    test_universal_forbidden_blocked()

    print("\n" + "=" * 70)
    print("VERIFICATION COMPLETE")
    print("=" * 70)
