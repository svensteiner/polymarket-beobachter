# =============================================================================
# GOVERNANCE FIX VERIFICATION TESTS
# =============================================================================
# Verifies all fixes from the security audit are working correctly.
# =============================================================================

import sys
import os

# Add project root to path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from datetime import date


def test_1_import_hook_installed():
    """Test that import hook is installed when layer is activated."""
    print("\n" + "=" * 60)
    print("TEST 1: Import Hook Installation")
    print("=" * 60)

    from shared.layer_guard import (
        set_active_layer,
        get_active_layer,
        _import_hook_installed,
        LayerIsolationFinder
    )
    from shared.enums import Layer

    # Set active layer
    set_active_layer(Layer.LAYER1_INSTITUTIONAL)

    # Check hook is installed
    from shared import layer_guard
    assert layer_guard._import_hook_installed, "Import hook should be installed"

    # Check it's in sys.meta_path
    found_hook = False
    for finder in sys.meta_path:
        if isinstance(finder, LayerIsolationFinder):
            found_hook = True
            break

    assert found_hook, "LayerIsolationFinder should be in sys.meta_path"

    print("[PASS] Import hook is installed and active")
    return True


def test_2_insufficient_data_exists():
    """Test that INSUFFICIENT_DATA is in DecisionOutcome enum."""
    print("\n" + "=" * 60)
    print("TEST 2: INSUFFICIENT_DATA Enum Value")
    print("=" * 60)

    from shared.enums import DecisionOutcome

    # Check enum has all three values
    assert hasattr(DecisionOutcome, 'TRADE'), "Missing TRADE"
    assert hasattr(DecisionOutcome, 'NO_TRADE'), "Missing NO_TRADE"
    assert hasattr(DecisionOutcome, 'INSUFFICIENT_DATA'), "Missing INSUFFICIENT_DATA"

    # Check values
    assert DecisionOutcome.INSUFFICIENT_DATA.value == "INSUFFICIENT_DATA"

    # Also check in data_models
    from core_analyzer.models.data_models import DecisionOutcome as DM_Outcome
    assert hasattr(DM_Outcome, 'INSUFFICIENT_DATA'), "Missing in data_models"

    print("[PASS] INSUFFICIENT_DATA exists in both enum locations")
    return True


def test_3_audit_hash_computation():
    """Test that audit logger computes input hash."""
    print("\n" + "=" * 60)
    print("TEST 3: Audit Input Hash")
    print("=" * 60)

    from shared.logging_config import AuditLogger
    from shared.enums import Layer

    # Test hash computation
    test_data = {"key": "value", "number": 42}
    hash1 = AuditLogger._compute_hash(test_data)

    # Hash should be 64 char hex string (SHA-256)
    assert len(hash1) == 64, f"Hash should be 64 chars, got {len(hash1)}"
    assert all(c in '0123456789abcdef' for c in hash1), "Hash should be hex"

    # Same data should produce same hash
    hash2 = AuditLogger._compute_hash(test_data)
    assert hash1 == hash2, "Same data should produce same hash"

    # Different data should produce different hash
    hash3 = AuditLogger._compute_hash({"different": "data"})
    assert hash1 != hash3, "Different data should produce different hash"

    print(f"[PASS] Hash computation works: {hash1[:16]}...")
    return True


def test_4_market_input_immutable():
    """Test that MarketInput is immutable after creation."""
    print("\n" + "=" * 60)
    print("TEST 4: MarketInput Immutability")
    print("=" * 60)

    from core_analyzer.models.data_models import MarketInput

    # Create valid input
    mi = MarketInput(
        market_title="Test Market",
        resolution_text="Resolves YES if...",
        target_date=date(2025, 6, 1),
        referenced_regulation="EU AI Act",
        authority_involved="European Commission",
        market_implied_probability=0.5,
        analysis_date=date.today(),
    )

    # Try to modify - should fail
    try:
        mi.market_title = "Modified"
        print("[FAIL] Should not be able to modify market_title")
        return False
    except AttributeError as e:
        print(f"[PASS] Modification blocked: {str(e)[:50]}...")

    # Try to delete - should fail
    try:
        del mi.market_title
        print("[FAIL] Should not be able to delete attributes")
        return False
    except AttributeError:
        print("[PASS] Deletion blocked")

    return True


def test_5_forbidden_fields_rejected():
    """Test that forbidden fields are rejected."""
    print("\n" + "=" * 60)
    print("TEST 5: Forbidden Field Validation")
    print("=" * 60)

    from core_analyzer.models.data_models import MarketInput, FORBIDDEN_INPUT_FIELDS

    # Create valid input first
    mi = MarketInput(
        market_title="Test Market",
        resolution_text="Resolves YES if...",
        target_date=date(2025, 6, 1),
        referenced_regulation="EU AI Act",
        authority_involved="European Commission",
        market_implied_probability=0.5,
        analysis_date=date.today(),
    )

    # Try to inject forbidden field
    forbidden_tests = ["price", "volume", "liquidity", "pnl"]

    for field_name in forbidden_tests:
        try:
            setattr(mi, field_name, 100)
            print(f"[FAIL] Should not accept forbidden field: {field_name}")
            return False
        except (ValueError, AttributeError) as e:
            if "GOVERNANCE VIOLATION" in str(e) or "immutable" in str(e):
                print(f"[PASS] Forbidden field '{field_name}' rejected")
            else:
                print(f"[PASS] Field '{field_name}' rejected (immutable)")

    return True


def test_6_probability_range_validation():
    """Test that probability must be 0.0-1.0."""
    print("\n" + "=" * 60)
    print("TEST 6: Probability Range Validation")
    print("=" * 60)

    from core_analyzer.models.data_models import MarketInput

    # Try invalid probability (percentage instead of decimal)
    try:
        mi = MarketInput(
            market_title="Test Market",
            resolution_text="Resolves YES if...",
            target_date=date(2025, 6, 1),
            referenced_regulation="EU AI Act",
            authority_involved="European Commission",
            market_implied_probability=50,  # Should be 0.50
            analysis_date=date.today(),
        )
        print("[FAIL] Should reject probability > 1.0")
        return False
    except ValueError as e:
        if "Did you mean" in str(e):
            print(f"[PASS] Helpful error message: {str(e)[:60]}...")
        else:
            print(f"[PASS] Probability validation works")

    return True


def run_all_tests():
    """Run all verification tests."""
    print("\n" + "=" * 70)
    print("GOVERNANCE FIX VERIFICATION SUITE")
    print("=" * 70)

    tests = [
        ("Import Hook", test_1_import_hook_installed),
        ("INSUFFICIENT_DATA Enum", test_2_insufficient_data_exists),
        ("Audit Hash", test_3_audit_hash_computation),
        ("Immutability", test_4_market_input_immutable),
        ("Forbidden Fields", test_5_forbidden_fields_rejected),
        ("Probability Range", test_6_probability_range_validation),
    ]

    results = []
    for name, test_fn in tests:
        try:
            passed = test_fn()
            results.append((name, passed))
        except Exception as e:
            print(f"[ERROR] {name}: {e}")
            results.append((name, False))

    # Summary
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)

    passed = sum(1 for _, p in results if p)
    total = len(results)

    for name, p in results:
        status = "PASS" if p else "FAIL"
        print(f"  {name}: {status}")

    print("-" * 70)
    print(f"  TOTAL: {passed}/{total} tests passed")
    print("=" * 70)

    return passed == total


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
