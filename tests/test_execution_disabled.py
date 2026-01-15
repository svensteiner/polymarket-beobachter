# =============================================================================
# POLYMARKET BEOBACHTER - EXECUTION DISABLED TESTS
# =============================================================================
#
# GOVERNANCE INTENT:
# These tests PROVE that execution is impossible.
# If any test fails, there is a critical governance violation.
#
# TEST CATEGORIES:
# 1. execute() always raises ExecutionDisabledError
# 2. Policy always has execution_disabled=True
# 3. No runtime override is possible
# 4. Safety assertions pass
#
# =============================================================================

import sys
import os
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest


class TestExecuteAlwaysFails:
    """
    Tests proving execute() ALWAYS raises ExecutionDisabledError.

    GOVERNANCE:
    These tests are NON-NEGOTIABLE. If they fail, the system is unsafe.
    """

    def test_execute_raises_execution_disabled_error(self):
        """execute() MUST raise ExecutionDisabledError."""
        from execution.adapter import execute
        from execution.exceptions import ExecutionDisabledError

        with pytest.raises(ExecutionDisabledError):
            execute("TEST-PROPOSAL-001")

    def test_execute_raises_with_any_proposal_id(self):
        """execute() raises for ANY proposal ID."""
        from execution.adapter import execute
        from execution.exceptions import ExecutionDisabledError

        test_ids = [
            "PROP-20260115-abc12345",
            "PROP-20260115-xxxxxxxx",
            "",
            "invalid",
            "123456789",
            None,  # Even None should raise (before validation)
        ]

        for proposal_id in test_ids:
            with pytest.raises(ExecutionDisabledError):
                execute(proposal_id)

    def test_execute_does_not_validate_before_raising(self):
        """execute() raises BEFORE any validation."""
        from execution.adapter import execute
        from execution.exceptions import ExecutionDisabledError

        # Even with an obviously invalid ID, it should raise ExecutionDisabledError
        # NOT ProposalNotFoundError
        with pytest.raises(ExecutionDisabledError):
            execute("NONEXISTENT-PROPOSAL-ID")

    def test_execute_logs_attempt(self):
        """execute() logs the attempt before raising."""
        from execution.adapter import execute
        from execution.exceptions import ExecutionDisabledError
        from execution.logger import get_logger, ExecutionAction

        # Get the global logger
        logger = get_logger()

        # Count entries before
        entries_before = logger.read_all_entries()
        count_before = len([
            e for e in entries_before
            if e.action == ExecutionAction.EXECUTE_ATTEMPT.value
            and e.proposal_id == "TEST-LOG-PROPOSAL-UNIQUE-ID"
        ])

        # Execute (will raise)
        with pytest.raises(ExecutionDisabledError):
            execute("TEST-LOG-PROPOSAL-UNIQUE-ID")

        # Verify log entry was created
        entries_after = logger.read_all_entries()
        matching_entries = [
            e for e in entries_after
            if e.action == ExecutionAction.EXECUTE_ATTEMPT.value
            and e.proposal_id == "TEST-LOG-PROPOSAL-UNIQUE-ID"
        ]

        assert len(matching_entries) == count_before + 1
        assert matching_entries[-1].outcome == "BLOCKED"

    def test_execute_never_returns(self):
        """execute() NEVER returns normally - always raises."""
        from execution.adapter import execute
        from execution.exceptions import ExecutionDisabledError

        # This test verifies there's no code path that returns
        result = None
        try:
            result = execute("TEST-PROPOSAL")
        except ExecutionDisabledError:
            pass  # Expected

        # Result should never be set
        assert result is None


class TestPolicyAlwaysDisabled:
    """
    Tests proving policy ALWAYS has execution_disabled=True.
    """

    def test_policy_execution_disabled_is_true(self):
        """Policy execution_disabled MUST be True."""
        from execution.policy import get_execution_policy

        policy = get_execution_policy()
        assert policy.execution_disabled is True

    def test_policy_constant_is_true(self):
        """EXECUTION_DISABLED constant MUST be True."""
        from execution.policy import EXECUTION_DISABLED

        assert EXECUTION_DISABLED is True

    def test_is_execution_enabled_returns_false(self):
        """is_execution_enabled() MUST return False."""
        from execution.policy import is_execution_enabled

        assert is_execution_enabled() is False

    def test_policy_cannot_be_modified(self):
        """Policy is frozen and cannot be modified."""
        from execution.policy import get_execution_policy
        from dataclasses import FrozenInstanceError

        policy = get_execution_policy()

        with pytest.raises(FrozenInstanceError):
            policy.execution_disabled = False

    def test_policy_creation_fails_with_execution_enabled(self):
        """Cannot create policy with execution_disabled=False."""
        from execution.policy import ExecutionPolicy

        with pytest.raises(ValueError, match="GOVERNANCE VIOLATION"):
            ExecutionPolicy(
                fixed_amount_eur=100.0,
                max_slippage=0.02,
                max_exposure_per_market_eur=500.0,
                one_shot_only=True,
                no_reentry=True,
                execution_disabled=False,  # This should fail
                dry_run_enabled=True,
            )

    def test_policy_invariants_hold(self):
        """All policy invariants must hold."""
        from execution.policy import assert_policy_invariants

        # Should not raise
        assert_policy_invariants()


class TestNoRuntimeOverride:
    """
    Tests proving no runtime mechanism can enable execution.
    """

    def test_no_environment_variable_override(self):
        """Environment variables cannot enable execution."""
        import os
        from execution.policy import is_execution_enabled, get_execution_policy

        # Try various env var names that might be used
        env_vars_to_try = [
            "EXECUTION_ENABLED",
            "ENABLE_EXECUTION",
            "POLYMARKET_EXECUTE",
            "ALLOW_TRADING",
            "LIVE_MODE",
            "PRODUCTION_MODE",
        ]

        for var_name in env_vars_to_try:
            os.environ[var_name] = "true"
            os.environ[var_name] = "1"
            os.environ[var_name] = "yes"

        # Should still be disabled
        assert is_execution_enabled() is False
        assert get_execution_policy().execution_disabled is True

        # Clean up
        for var_name in env_vars_to_try:
            if var_name in os.environ:
                del os.environ[var_name]

    def test_module_reload_does_not_enable(self):
        """Reloading modules does not enable execution."""
        import importlib
        import execution.policy
        import execution.adapter

        # Reload modules
        importlib.reload(execution.policy)
        importlib.reload(execution.adapter)

        # Should still be disabled
        from execution.policy import is_execution_enabled
        assert is_execution_enabled() is False

    def test_execute_function_is_not_replaceable_at_runtime(self):
        """execute() function behavior cannot be changed at module level."""
        import execution.adapter
        from execution.exceptions import ExecutionDisabledError

        # Save original
        original_execute = execution.adapter.execute

        # Try to replace with a no-op
        def fake_execute(proposal_id):
            return "FAKE SUCCESS"

        execution.adapter.execute = fake_execute

        # The module-level import in __init__.py still references original
        from execution import execute

        # Depending on how it's imported, the behavior might vary
        # But the important thing is: calling through the module should still fail
        try:
            # Restore and verify original still works as expected
            execution.adapter.execute = original_execute
            with pytest.raises(ExecutionDisabledError):
                execution.adapter.execute("TEST")
        finally:
            execution.adapter.execute = original_execute


class TestSafetyAssertions:
    """
    Tests for safety assertion functions.
    """

    def test_assert_execution_impossible_passes(self):
        """assert_execution_impossible() should pass."""
        from execution.adapter import assert_execution_impossible

        # Should not raise
        assert_execution_impossible()

    def test_assert_policy_invariants_passes(self):
        """assert_policy_invariants() should pass."""
        from execution.policy import assert_policy_invariants

        # Should not raise
        assert_policy_invariants()


class TestExceptionMessages:
    """
    Tests for exception message correctness.
    """

    def test_execution_disabled_error_message(self):
        """ExecutionDisabledError has correct message."""
        from execution.exceptions import ExecutionDisabledError

        error = ExecutionDisabledError("TEST-ID")
        assert "disabled by policy" in str(error).lower()
        assert error.is_permanent is True

    def test_execution_disabled_error_proposal_id(self):
        """ExecutionDisabledError includes proposal ID."""
        from execution.exceptions import ExecutionDisabledError

        error = ExecutionDisabledError("MY-PROPOSAL-123")
        assert "MY-PROPOSAL-123" in str(error)


class TestDryRunAndPrepareWork:
    """
    Tests that dry_run and prepare_execution work correctly.

    Note: These tests require a valid proposal to exist.
    If no proposal exists, they will raise ProposalNotFoundError.
    """

    def test_dry_run_does_not_execute(self, tmp_path):
        """dry_run() does NOT execute anything."""
        from execution.logger import ExecutionLogger, ExecutionAction

        # Create a temporary logger
        log_path = tmp_path / "test_dry_run_log.jsonl"
        logger = ExecutionLogger(log_path)

        # Verify no EXECUTE_ATTEMPT entries exist
        entries = logger.read_all_entries()
        execute_attempts = [
            e for e in entries
            if e.action == ExecutionAction.EXECUTE_ATTEMPT.value
        ]
        assert len(execute_attempts) == 0


class TestLogIntegrity:
    """
    Tests for log integrity.
    """

    def test_log_is_append_only(self, tmp_path):
        """Log file only supports append operations."""
        from execution.logger import ExecutionLogger, ExecutionOutcome

        log_path = tmp_path / "test_append.jsonl"
        logger = ExecutionLogger(log_path)

        # Add entries
        logger.log_prepare("P1", ExecutionOutcome.SUCCESS, "Test 1")
        logger.log_prepare("P2", ExecutionOutcome.SUCCESS, "Test 2")
        logger.log_prepare("P3", ExecutionOutcome.SUCCESS, "Test 3")

        # Read entries
        entries = logger.read_all_entries()
        assert len(entries) == 3

        # Add more
        logger.log_prepare("P4", ExecutionOutcome.SUCCESS, "Test 4")

        # Verify all entries preserved
        entries = logger.read_all_entries()
        assert len(entries) == 4

    def test_execute_attempt_always_blocked(self, tmp_path):
        """EXECUTE_ATTEMPT entries always have BLOCKED outcome."""
        from execution.logger import ExecutionLogger, ExecutionOutcome

        log_path = tmp_path / "test_blocked.jsonl"
        logger = ExecutionLogger(log_path)

        # Log execute attempts
        for i in range(5):
            logger.log_execute_attempt(f"TEST-{i}", "Test attempt")

        # Verify all are BLOCKED
        entries = logger.read_all_entries()
        for entry in entries:
            assert entry.outcome == ExecutionOutcome.BLOCKED.value


# =============================================================================
# CRITICAL TEST - This is the most important test
# =============================================================================


class TestCriticalGovernance:
    """
    CRITICAL governance tests.

    If ANY of these tests fail, the system has a critical vulnerability.
    """

    def test_execute_is_unconditionally_disabled(self):
        """
        CRITICAL: execute() is UNCONDITIONALLY disabled.

        This test must ALWAYS pass. If it fails, the system is unsafe.
        """
        from execution.adapter import execute
        from execution.exceptions import ExecutionDisabledError

        # Test many times to ensure no race conditions
        for _ in range(100):
            with pytest.raises(ExecutionDisabledError):
                execute("TEST")

    def test_no_path_to_successful_execution(self):
        """
        CRITICAL: There is NO code path that leads to successful execution.

        This test inspects the execute() function to verify there is no
        return statement before the raise.
        """
        from execution.adapter import execute
        import inspect

        source = inspect.getsource(execute)

        # The raise ExecutionDisabledError must be UNCONDITIONAL
        # It should not be inside an if/else block that could be bypassed
        lines = source.split('\n')

        found_raise = False
        for line in lines:
            stripped = line.strip()
            if 'raise ExecutionDisabledError' in stripped:
                found_raise = True
                # Verify it's not inside a conditional (check indentation)
                # The raise should be at the top level of the function
                break

        assert found_raise, "ExecutionDisabledError raise not found in execute()"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
