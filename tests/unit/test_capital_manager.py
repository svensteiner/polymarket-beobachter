"""
Unit Tests for CapitalManager - Atomic Write and Reconciliation
"""
import json
import pytest
import tempfile
import shutil
from pathlib import Path


class TestCapitalManagerAtomicWrite:
    """Test atomic write functionality."""

    def test_atomic_write_creates_file(self, tmp_path):
        """Atomic write should create file correctly."""
        from paper_trader.capital_manager import CapitalManager

        config_path = tmp_path / "data" / "capital_config.json"
        config_path.parent.mkdir(parents=True, exist_ok=True)

        # Create initial config
        CapitalManager._atomic_write(config_path, {"test": "value"})

        assert config_path.exists()
        with open(config_path) as f:
            data = json.load(f)
        assert data["test"] == "value"

    def test_atomic_write_no_temp_file_left(self, tmp_path):
        """Atomic write should not leave .tmp files."""
        from paper_trader.capital_manager import CapitalManager

        config_path = tmp_path / "data" / "capital_config.json"
        config_path.parent.mkdir(parents=True, exist_ok=True)

        CapitalManager._atomic_write(config_path, {"test": "value"})

        tmp_files = list(tmp_path.rglob("*.tmp"))
        assert len(tmp_files) == 0

    def test_atomic_write_overwrites_existing(self, tmp_path):
        """Atomic write should overwrite existing file."""
        from paper_trader.capital_manager import CapitalManager

        config_path = tmp_path / "data" / "capital_config.json"
        config_path.parent.mkdir(parents=True, exist_ok=True)

        # Write initial value
        CapitalManager._atomic_write(config_path, {"version": 1})

        # Overwrite
        CapitalManager._atomic_write(config_path, {"version": 2})

        with open(config_path) as f:
            data = json.load(f)
        assert data["version"] == 2


class TestCapitalManagerBackup:
    """Test backup functionality."""

    def test_save_creates_backup(self, tmp_path):
        """Saving config should create .bak file."""
        from paper_trader.capital_manager import CapitalManager

        # Setup temp directory structure
        data_dir = tmp_path / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        pt_logs = tmp_path / "paper_trader" / "logs"
        pt_logs.mkdir(parents=True, exist_ok=True)
        pt_reports = tmp_path / "paper_trader" / "reports"
        pt_reports.mkdir(parents=True, exist_ok=True)

        config_path = data_dir / "capital_config.json"

        # Create initial config manually
        initial_config = {
            "governance_notice": "PAPER TRADING",
            "initial_capital_eur": 5000.0,
            "available_capital_eur": 5000.0,
            "allocated_capital_eur": 0.0,
            "realized_pnl_eur": 0.0,
            "position_size_eur": 100.0,
            "max_position_pct": 2.0,
            "max_open_positions": 10,
            "max_daily_trades": 5,
        }
        with open(config_path, "w") as f:
            json.dump(initial_config, f)

        # Initialize manager (will trigger reconcile)
        cm = CapitalManager(config_path=config_path, auto_reconcile=False)

        # Allocate capital (triggers save with backup)
        cm.allocate_capital(100.0, "Test allocation")

        # Check backup exists
        backup_path = Path(str(config_path) + ".bak")
        assert backup_path.exists()


class TestCapitalManagerReconciliation:
    """Test capital reconciliation logic."""

    def test_reconcile_no_positions_no_change(self, tmp_path):
        """Reconcile with no positions should not change anything."""
        from paper_trader.capital_manager import CapitalManager

        # Setup
        data_dir = tmp_path / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        pt_logs = tmp_path / "paper_trader" / "logs"
        pt_logs.mkdir(parents=True, exist_ok=True)
        pt_reports = tmp_path / "paper_trader" / "reports"
        pt_reports.mkdir(parents=True, exist_ok=True)

        config_path = data_dir / "capital_config.json"

        initial_config = {
            "governance_notice": "PAPER TRADING",
            "initial_capital_eur": 5000.0,
            "available_capital_eur": 5000.0,
            "allocated_capital_eur": 0.0,
            "realized_pnl_eur": 0.0,
            "position_size_eur": 100.0,
            "max_position_pct": 2.0,
            "max_open_positions": 10,
            "max_daily_trades": 5,
        }
        with open(config_path, "w") as f:
            json.dump(initial_config, f)

        cm = CapitalManager(config_path=config_path, auto_reconcile=True)

        state = cm.get_state()
        assert state.available_capital_eur == 5000.0
        assert state.allocated_capital_eur == 0.0

    def test_get_state_returns_state(self, tmp_path):
        """get_state should return CapitalState."""
        from paper_trader.capital_manager import CapitalManager, CapitalState

        data_dir = tmp_path / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        pt_logs = tmp_path / "paper_trader" / "logs"
        pt_logs.mkdir(parents=True, exist_ok=True)
        pt_reports = tmp_path / "paper_trader" / "reports"
        pt_reports.mkdir(parents=True, exist_ok=True)

        config_path = data_dir / "capital_config.json"

        initial_config = {
            "initial_capital_eur": 5000.0,
            "available_capital_eur": 4500.0,
            "allocated_capital_eur": 500.0,
            "realized_pnl_eur": 0.0,
            "position_size_eur": 100.0,
            "max_position_pct": 2.0,
            "max_open_positions": 10,
            "max_daily_trades": 5,
        }
        with open(config_path, "w") as f:
            json.dump(initial_config, f)

        cm = CapitalManager(config_path=config_path, auto_reconcile=False)
        state = cm.get_state()

        assert isinstance(state, CapitalState)
        assert state.initial_capital_eur == 5000.0
        assert state.available_capital_eur == 4500.0
        assert state.allocated_capital_eur == 500.0


class TestCapitalManagerAllocation:
    """Test capital allocation and release."""

    def test_allocate_reduces_available(self, tmp_path):
        """Allocation should reduce available capital."""
        from paper_trader.capital_manager import CapitalManager

        data_dir = tmp_path / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        pt_logs = tmp_path / "paper_trader" / "logs"
        pt_logs.mkdir(parents=True, exist_ok=True)
        pt_reports = tmp_path / "paper_trader" / "reports"
        pt_reports.mkdir(parents=True, exist_ok=True)

        config_path = data_dir / "capital_config.json"

        initial_config = {
            "initial_capital_eur": 1000.0,
            "available_capital_eur": 1000.0,
            "allocated_capital_eur": 0.0,
            "realized_pnl_eur": 0.0,
            "position_size_eur": 100.0,
            "max_position_pct": 2.0,
            "max_open_positions": 10,
            "max_daily_trades": 5,
        }
        with open(config_path, "w") as f:
            json.dump(initial_config, f)

        cm = CapitalManager(config_path=config_path, auto_reconcile=False)

        result = cm.allocate_capital(100.0, "Test")

        assert result is True
        state = cm.get_state()
        assert state.available_capital_eur == 900.0
        assert state.allocated_capital_eur == 100.0

    def test_allocate_fails_insufficient(self, tmp_path):
        """Allocation should fail if insufficient capital."""
        from paper_trader.capital_manager import CapitalManager

        data_dir = tmp_path / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        pt_logs = tmp_path / "paper_trader" / "logs"
        pt_logs.mkdir(parents=True, exist_ok=True)
        pt_reports = tmp_path / "paper_trader" / "reports"
        pt_reports.mkdir(parents=True, exist_ok=True)

        config_path = data_dir / "capital_config.json"

        initial_config = {
            "initial_capital_eur": 100.0,
            "available_capital_eur": 50.0,
            "allocated_capital_eur": 50.0,
            "realized_pnl_eur": 0.0,
            "position_size_eur": 100.0,
            "max_position_pct": 2.0,
            "max_open_positions": 10,
            "max_daily_trades": 5,
        }
        with open(config_path, "w") as f:
            json.dump(initial_config, f)

        cm = CapitalManager(config_path=config_path, auto_reconcile=False)

        result = cm.allocate_capital(100.0, "Test")

        assert result is False
        state = cm.get_state()
        assert state.available_capital_eur == 50.0  # Unchanged

    def test_release_increases_available(self, tmp_path):
        """Release should increase available capital."""
        from paper_trader.capital_manager import CapitalManager

        data_dir = tmp_path / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        pt_logs = tmp_path / "paper_trader" / "logs"
        pt_logs.mkdir(parents=True, exist_ok=True)
        pt_reports = tmp_path / "paper_trader" / "reports"
        pt_reports.mkdir(parents=True, exist_ok=True)

        config_path = data_dir / "capital_config.json"

        initial_config = {
            "initial_capital_eur": 1000.0,
            "available_capital_eur": 900.0,
            "allocated_capital_eur": 100.0,
            "realized_pnl_eur": 0.0,
            "position_size_eur": 100.0,
            "max_position_pct": 2.0,
            "max_open_positions": 10,
            "max_daily_trades": 5,
        }
        with open(config_path, "w") as f:
            json.dump(initial_config, f)

        cm = CapitalManager(config_path=config_path, auto_reconcile=False)

        # Release with profit
        cm.release_capital(cost_basis_eur=100.0, pnl_eur=20.0, reason="Test win")

        state = cm.get_state()
        assert state.available_capital_eur == 1020.0  # 900 + 100 + 20
        assert state.allocated_capital_eur == 0.0
        assert state.realized_pnl_eur == 20.0


class TestCapitalManagerSummary:
    """Test summary generation."""

    def test_summary_includes_all_fields(self, tmp_path):
        """Summary should include all required fields."""
        from paper_trader.capital_manager import CapitalManager

        data_dir = tmp_path / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        pt_logs = tmp_path / "paper_trader" / "logs"
        pt_logs.mkdir(parents=True, exist_ok=True)
        pt_reports = tmp_path / "paper_trader" / "reports"
        pt_reports.mkdir(parents=True, exist_ok=True)

        config_path = data_dir / "capital_config.json"

        initial_config = {
            "initial_capital_eur": 5000.0,
            "available_capital_eur": 5000.0,
            "allocated_capital_eur": 0.0,
            "realized_pnl_eur": 0.0,
            "position_size_eur": 100.0,
            "max_position_pct": 2.0,
            "max_open_positions": 10,
            "max_daily_trades": 5,
        }
        with open(config_path, "w") as f:
            json.dump(initial_config, f)

        cm = CapitalManager(config_path=config_path, auto_reconcile=False)
        summary = cm.get_summary()

        assert "initial_capital_eur" in summary
        assert "available_capital_eur" in summary
        assert "allocated_capital_eur" in summary
        assert "total_equity_eur" in summary
        assert "realized_pnl_eur" in summary
        assert "roi_pct" in summary
        assert "governance_notice" in summary


# ============================================================
# TEST RUNNER
# ============================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
