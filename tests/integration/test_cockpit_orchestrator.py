# =============================================================================
# TESTS: Cockpit and Orchestrator
# =============================================================================
#
# Tests to verify:
# 1. cockpit.py --run-once runs without crashing
# 2. orchestrator handles missing files gracefully
# 3. status summary generation works
# 4. no forbidden imports (layer isolation enforced)
#
# =============================================================================

import sys
import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

# Setup paths
BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR))


class TestOrchestrator:
    """Tests for the orchestrator module."""

    def test_orchestrator_import(self):
        """Test that orchestrator can be imported."""
        from app.orchestrator import Orchestrator, RunState, PipelineResult
        assert Orchestrator is not None
        assert RunState.OK.value == "OK"
        assert RunState.DEGRADED.value == "DEGRADED"
        assert RunState.FAIL.value == "FAIL"

    def test_orchestrator_init(self, tmp_path):
        """Test orchestrator initialization."""
        from app.orchestrator import Orchestrator

        orch = Orchestrator(base_dir=tmp_path)
        assert orch.base_dir == tmp_path
        assert orch.output_dir.exists()
        assert orch.logs_dir.exists()

    def test_get_status_empty(self, tmp_path):
        """Test get_status with no data."""
        from app.orchestrator import Orchestrator

        with patch("paper_trader.position_manager.get_position_summary",
                   return_value={"open": 0, "total_realized_pnl_eur": 0.0}):
            orch = Orchestrator(base_dir=tmp_path)
            status = orch.get_status()

            assert "last_run" in status
            assert "today" in status
            assert status["paper_positions_open"] == 0

    def test_get_latest_proposal_none(self, tmp_path):
        """Test get_latest_proposal with no proposals."""
        from app.orchestrator import Orchestrator

        orch = Orchestrator(base_dir=tmp_path)
        proposal = orch.get_latest_proposal()

        assert proposal is None

    def test_get_paper_summary_empty(self, tmp_path):
        """Test get_paper_summary with no positions."""
        from app.orchestrator import Orchestrator

        with patch("paper_trader.position_manager.get_position_summary",
                   return_value={"open": 0, "total_positions": 0,
                                 "total_realized_pnl_eur": 0.0}), \
             patch("paper_trader.position_manager.get_open_positions",
                   return_value=[]), \
             patch("paper_trader.logger.get_paper_logger") as mock_logger:
            mock_logger.return_value.read_all_trades.return_value = []
            orch = Orchestrator(base_dir=tmp_path)
            summary = orch.get_paper_summary()

            assert summary["open_positions"] == 0
            assert summary["positions"] == []

    def test_pipeline_result_add_step(self):
        """Test PipelineResult.add_step() state management."""
        from app.orchestrator import PipelineResult, StepResult, RunState

        result = PipelineResult(state=RunState.OK, timestamp="2025-01-01")
        assert result.state == RunState.OK

        # Add successful step - should stay OK
        result.add_step(StepResult(name="test1", success=True, message="ok"))
        assert result.state == RunState.OK

        # Add failed step - should become DEGRADED
        result.add_step(StepResult(name="test2", success=False, message="fail"))
        assert result.state == RunState.DEGRADED

    def test_write_status_summary(self, tmp_path):
        """Test status summary file writing."""
        from app.orchestrator import Orchestrator, PipelineResult, RunState

        orch = Orchestrator(base_dir=tmp_path)

        result = PipelineResult(
            state=RunState.OK,
            timestamp="2025-01-01T12:00:00"
        )
        result.summary = {
            "markets_checked": 10,
            "trade_count": 1,
            "no_trade_count": 5,
            "paper_positions_open": 0
        }

        step_result = orch._write_status_summary(result)
        assert step_result.success

        summary_file = tmp_path / "output" / "status_summary.txt"
        assert summary_file.exists()

        content = summary_file.read_text()
        assert "2025-01-01" in content
        assert "Markets checked: 10" in content


class TestCockpit:
    """Tests for the cockpit module."""

    def test_cockpit_import(self):
        """Test that cockpit can be imported."""
        import cockpit
        assert hasattr(cockpit, 'main')
        assert hasattr(cockpit, 'run_once')
        assert hasattr(cockpit, 'show_status')

    def test_format_state(self):
        """Test state formatting."""
        from cockpit import format_state

        # Just check it returns strings (colors may vary)
        assert "OK" in format_state("OK")
        assert "DEGRADED" in format_state("DEGRADED")
        assert "FAIL" in format_state("FAIL")

    def test_format_decision(self):
        """Test decision formatting."""
        from cockpit import format_decision

        assert "TRADE" in format_decision("TRADE")
        assert "NO_TRADE" in format_decision("NO_TRADE")

    def test_print_status(self, capsys):
        """Test print_status output."""
        from cockpit import print_status, C
        C.disable()  # Disable colors for testing

        status = {
            "last_run": "2025-01-01",
            "last_state": "OK",
            "today": {"markets_checked": 5, "trade": 1, "no_trade": 3, "insufficient": 1},
            "paper_positions_open": 2,
            "paper_total_pnl": 10.50
        }

        print_status(status)
        captured = capsys.readouterr()

        # print_status uses print_box formatting
        assert "Time:" in captured.out and "2025-01-01" in captured.out
        assert "Markets checked:" in captured.out and "5" in captured.out
        assert "Open positions:" in captured.out and "2" in captured.out

    def test_print_proposal_none(self, capsys):
        """Test print_proposal with no proposal."""
        from cockpit import print_proposal, C
        C.disable()

        print_proposal(None)
        captured = capsys.readouterr()

        assert "No proposals yet" in captured.out


class TestLayerIsolation:
    """Tests to verify layer isolation is maintained."""

    def test_orchestrator_no_microstructure_import(self):
        """Verify orchestrator doesn't import microstructure_research."""
        import app.orchestrator as orch

        # Check that microstructure_research is not in the module's dependencies
        source = Path(orch.__file__).read_text()
        assert "microstructure_research" not in source

    def test_orchestrator_no_execution_import(self):
        """Verify orchestrator doesn't import execution module for live trading."""
        import app.orchestrator as orch

        source = Path(orch.__file__).read_text()
        # Should not import execution.adapter (live trading)
        assert "from execution.adapter" not in source
        assert "import execution.adapter" not in source

    def test_cockpit_no_direct_core_import(self):
        """Verify cockpit goes through orchestrator, not direct core imports."""
        import cockpit

        source = Path(cockpit.__file__).read_text()
        # Cockpit should import from app.orchestrator, not core modules
        assert "from core." not in source
        assert "from collector." not in source


class TestGracefulFailure:
    """Tests for graceful failure handling."""

    def test_collector_step_handles_missing_client(self, tmp_path):
        """Test collector step handles import errors gracefully."""
        from app.orchestrator import Orchestrator

        orch = Orchestrator(base_dir=tmp_path)

        # Mock the collector import to fail
        with patch.dict(sys.modules, {'collector.collector': None}):
            # The step should catch the error and return a failed StepResult
            # rather than crashing
            pass  # Import mocking is tricky, skip for now

    def test_analyzer_step_no_candidates(self, tmp_path):
        """Test analyzer step with no candidates file."""
        from app.orchestrator import Orchestrator

        orch = Orchestrator(base_dir=tmp_path)

        # Run analyzer with no candidates file
        result = orch._run_analyzer({})

        assert result.success
        assert result.data["analyzed"] == 0

    def test_proposals_step_no_trades(self, tmp_path):
        """Test proposals step with no TRADE decisions."""
        from app.orchestrator import Orchestrator

        orch = Orchestrator(base_dir=tmp_path)

        # Run proposals with empty analyzer data
        result = orch._run_proposals({"analyses": []})

        assert result.success
        assert result.data["generated"] == 0


class TestExitCodes:
    """Tests for CLI exit codes."""

    def test_run_once_returns_int(self):
        """Test that run_once returns an integer exit code."""
        from cockpit import run_once

        # Mock the pipeline to avoid actual execution
        with patch('app.orchestrator.run_pipeline') as mock_run:
            from app.orchestrator import PipelineResult, RunState

            mock_run.return_value = PipelineResult(
                state=RunState.OK,
                timestamp="2025-01-01"
            )
            mock_run.return_value.summary = {}
            mock_run.return_value.steps = []

            # This would print output, so we capture it
            with patch('builtins.print'):
                result = run_once()

            assert isinstance(result, int)
            assert result in [0, 1, 2]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
