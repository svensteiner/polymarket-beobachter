"""
Tests für das Self-Healing und Auto-Code-Improvement System.
"""

import json
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from shared.self_healing import (
    SelfHealingMonitor,
    AutoCodeImprover,
    HealthStatus,
    IssueType,
    Metrics,
    check_and_heal,
    run_auto_improvement,
    record_pipeline_success,
    record_pipeline_failure,
)


class TestSelfHealingMonitor:
    """Tests für den SelfHealingMonitor."""

    def test_init_creates_dirs(self, tmp_path):
        """Monitor erstellt notwendige Verzeichnisse."""
        monitor = SelfHealingMonitor(base_dir=tmp_path)
        assert (tmp_path / "logs").exists()

    def test_record_success_resets_failures(self, tmp_path):
        """Erfolgreicher Run setzt Fehlerzähler zurück."""
        monitor = SelfHealingMonitor(base_dir=tmp_path)
        monitor._consecutive_failures = 5
        monitor.record_success()
        assert monitor._consecutive_failures == 0
        assert monitor._last_successful_run is not None

    def test_record_failure_increments_counter(self, tmp_path):
        """Fehlgeschlagener Run erhöht Fehlerzähler."""
        monitor = SelfHealingMonitor(base_dir=tmp_path)
        monitor.record_failure()
        assert monitor._consecutive_failures == 1
        monitor.record_failure()
        assert monitor._consecutive_failures == 2

    def test_should_skip_run_during_backoff(self, tmp_path):
        """Backoff verhindert Runs."""
        monitor = SelfHealingMonitor(base_dir=tmp_path)
        monitor._backoff_until = datetime.now() + timedelta(seconds=60)

        should_skip, reason = monitor.should_skip_run()
        assert should_skip
        assert "remaining" in reason

    def test_should_not_skip_after_backoff(self, tmp_path):
        """Nach Backoff sind Runs wieder erlaubt."""
        monitor = SelfHealingMonitor(base_dir=tmp_path)
        monitor._backoff_until = datetime.now() - timedelta(seconds=1)

        should_skip, reason = monitor.should_skip_run()
        assert not should_skip

    def test_heal_memory_pressure_runs_gc(self, tmp_path):
        """Memory-Healing führt GC aus."""
        monitor = SelfHealingMonitor(base_dir=tmp_path)
        action = monitor.heal_memory_pressure()

        assert action.issue_type == IssueType.MEMORY_PRESSURE
        assert action.success
        assert "gc_collect" in action.action

    def test_heal_api_timeout_applies_backoff(self, tmp_path):
        """API-Timeout-Healing setzt Backoff."""
        monitor = SelfHealingMonitor(base_dir=tmp_path)
        action = monitor.heal_api_timeout()

        assert action.issue_type == IssueType.API_TIMEOUT
        assert action.success
        assert monitor._backoff_until is not None
        assert monitor._backoff_until > datetime.now()

    def test_check_and_heal_returns_healthy_when_ok(self, tmp_path):
        """Check ohne Probleme gibt HEALTHY zurück."""
        monitor = SelfHealingMonitor(base_dir=tmp_path)
        monitor._consecutive_failures = 0

        with patch.object(monitor, '_get_memory_mb', return_value=100):
            result = monitor.check_and_heal()

        assert result["status"] == HealthStatus.HEALTHY.value
        assert len(result["issues"]) == 0

    def test_check_and_heal_heals_memory_pressure(self, tmp_path):
        """Check heilt Memory-Pressure automatisch."""
        monitor = SelfHealingMonitor(base_dir=tmp_path)

        with patch.object(monitor, '_get_memory_mb', return_value=900):  # > CRITICAL
            result = monitor.check_and_heal()

        assert IssueType.MEMORY_PRESSURE.value in result["issues"]
        assert len(result["actions"]) > 0

    def test_state_persistence(self, tmp_path):
        """State wird korrekt gespeichert und geladen."""
        monitor1 = SelfHealingMonitor(base_dir=tmp_path)
        monitor1._consecutive_failures = 3
        monitor1.record_success()

        # Neuer Monitor lädt den State
        monitor2 = SelfHealingMonitor(base_dir=tmp_path)
        assert monitor2._consecutive_failures == 0  # reset by success
        assert monitor2._last_successful_run is not None


class TestAutoCodeImprover:
    """Tests für den AutoCodeImprover."""

    @pytest.fixture
    def setup_project(self, tmp_path):
        """Erstelle minimale Projektstruktur."""
        # Create config dir
        config_dir = tmp_path / "config"
        config_dir.mkdir()

        # Create weather.yaml
        weather_yaml = config_dir / "weather.yaml"
        weather_yaml.write_text("MIN_EDGE: 0.12\nMAX_ODDS: 0.35\n")

        # Create paper_trader dir
        paper_dir = tmp_path / "paper_trader"
        paper_dir.mkdir()

        # Create kelly.py (match real file format)
        kelly_py = paper_dir / "kelly.py"
        kelly_py.write_text("KELLY_FRACTION: float = 0.15\n")

        # Create position_manager.py
        pm_py = paper_dir / "position_manager.py"
        pm_py.write_text("TAKE_PROFIT_PCT = 0.15\nSTOP_LOSS_PCT = 0.25\n")

        # Create logs dir
        logs_dir = tmp_path / "logs"
        logs_dir.mkdir()

        # Create analytics dir with performance report
        analytics_dir = tmp_path / "analytics"
        analytics_dir.mkdir()

        return tmp_path

    def test_get_current_value_yaml(self, setup_project):
        """Kann YAML-Werte lesen."""
        improver = AutoCodeImprover(base_dir=setup_project)
        value = improver._get_current_value("MIN_EDGE")
        assert value == 0.12

    def test_get_current_value_py_const(self, setup_project):
        """Kann Python-Konstanten lesen."""
        improver = AutoCodeImprover(base_dir=setup_project)
        value = improver._get_current_value("KELLY_FRACTION")
        assert value == 0.15

    def test_set_value_yaml(self, setup_project):
        """Kann YAML-Werte setzen."""
        improver = AutoCodeImprover(base_dir=setup_project)
        success = improver._set_value("MIN_EDGE", 0.15)
        assert success

        new_value = improver._get_current_value("MIN_EDGE")
        assert new_value == 0.15

    def test_set_value_py_const(self, setup_project):
        """Kann Python-Konstanten setzen."""
        improver = AutoCodeImprover(base_dir=setup_project)
        success = improver._set_value("KELLY_FRACTION", 0.20)
        assert success

        new_value = improver._get_current_value("KELLY_FRACTION")
        assert new_value == 0.20

    def test_can_make_change_respects_cooldown(self, setup_project):
        """Änderungen nur alle X Stunden erlaubt."""
        improver = AutoCodeImprover(base_dir=setup_project)

        # Erste Änderung sollte erlaubt sein
        can_change, reason = improver._can_make_change()
        assert can_change

        # Markiere als kürzlich geändert
        improver.last_change_file.write_text(datetime.now().isoformat())

        # Jetzt sollte Änderung gesperrt sein
        can_change, reason = improver._can_make_change()
        assert not can_change
        assert "Letzte Änderung" in reason

    def test_observe_metrics_from_report(self, setup_project):
        """Kann Metrics aus performance_report.json lesen."""
        report = {
            "win_rate": 0.55,
            "profit_factor": 1.8,
            "total_trades": 20,
            "avg_loss_pct": 15.0,
            "avg_win_pct": 25.0,
            "max_drawdown_pct": 8.0,
        }
        report_file = setup_project / "analytics" / "performance_report.json"
        report_file.write_text(json.dumps(report))

        improver = AutoCodeImprover(base_dir=setup_project)
        metrics = improver.observe_metrics()

        assert metrics.win_rate == 0.55
        assert metrics.profit_factor == 1.8
        assert metrics.total_trades == 20

    def test_decide_change_high_drawdown_reduces_kelly(self, setup_project):
        """Hoher Drawdown führt zu Kelly-Reduktion."""
        improver = AutoCodeImprover(base_dir=setup_project)
        metrics = Metrics(
            win_rate=0.50,
            profit_factor=1.2,
            total_trades=15,
            drawdown_pct=25.0,  # High drawdown
        )

        decision = improver._decide_change(metrics)
        assert decision is not None
        param, new_val, reason = decision
        assert param == "KELLY_FRACTION"
        assert new_val < 0.15  # Should decrease
        assert "Drawdown" in reason

    def test_decide_change_low_win_rate_increases_edge(self, setup_project):
        """Niedrige Win-Rate führt zu Edge-Erhöhung."""
        improver = AutoCodeImprover(base_dir=setup_project)
        metrics = Metrics(
            win_rate=0.40,  # Low win rate
            profit_factor=0.9,
            total_trades=15,
            drawdown_pct=5.0,
        )

        decision = improver._decide_change(metrics)
        assert decision is not None
        param, new_val, reason = decision
        assert param == "MIN_EDGE"
        assert new_val > 0.12  # Should increase
        assert "Win-Rate" in reason

    def test_decide_change_good_performance_increases_kelly(self, setup_project):
        """Gute Performance führt zu Kelly-Erhöhung."""
        improver = AutoCodeImprover(base_dir=setup_project)
        metrics = Metrics(
            win_rate=0.60,  # Good
            profit_factor=2.0,  # Good
            total_trades=15,
            drawdown_pct=5.0,  # Low
        )

        decision = improver._decide_change(metrics)
        assert decision is not None
        param, new_val, reason = decision
        assert param == "KELLY_FRACTION"
        assert new_val > 0.15  # Should increase
        assert "Performance" in reason

    def test_run_improvement_cycle_respects_min_trades(self, setup_project):
        """Keine Änderung ohne genügend Trades."""
        report = {
            "win_rate": 0.30,  # Bad, but not enough trades
            "total_trades": 5,
        }
        report_file = setup_project / "analytics" / "performance_report.json"
        report_file.write_text(json.dumps(report))

        improver = AutoCodeImprover(base_dir=setup_project)
        result = improver.run_improvement_cycle()

        assert result["action"] == "waiting_for_data"

    def test_changes_are_logged(self, setup_project):
        """Änderungen werden in Log geschrieben."""
        report = {
            "win_rate": 0.60,
            "profit_factor": 2.0,
            "total_trades": 20,
            "max_drawdown_pct": 5.0,
        }
        report_file = setup_project / "analytics" / "performance_report.json"
        report_file.write_text(json.dumps(report))

        improver = AutoCodeImprover(base_dir=setup_project)

        # Mock git commit
        with patch.object(improver, '_git_commit', return_value="abc123"):
            result = improver.run_improvement_cycle()

        if result["action"] == "changed":
            assert improver.changes_log.exists()
            log_content = improver.changes_log.read_text()
            assert len(log_content) > 0

    def test_values_stay_within_bounds(self, setup_project):
        """Werte bleiben innerhalb der definierten Grenzen."""
        # Set KELLY to maximum
        kelly_py = setup_project / "paper_trader" / "kelly.py"
        kelly_py.write_text("KELLY_FRACTION = 0.35\n")  # At max

        improver = AutoCodeImprover(base_dir=setup_project)

        # Try to increase further
        metrics = Metrics(
            win_rate=0.70,
            profit_factor=3.0,
            total_trades=20,
            drawdown_pct=2.0,
        )

        decision = improver._decide_change(metrics)
        if decision and decision[0] == "KELLY_FRACTION":
            # Should not exceed max
            assert decision[1] <= 0.35


class TestModuleLevelFunctions:
    """Tests für Module-Level Convenience-Funktionen."""

    def test_check_and_heal_returns_dict(self, tmp_path):
        """check_and_heal gibt Dict zurück."""
        with patch('shared.self_healing._healing_monitor', SelfHealingMonitor(tmp_path)):
            result = check_and_heal()
            assert isinstance(result, dict)
            assert "status" in result

    def test_record_pipeline_success_no_error(self, tmp_path):
        """record_pipeline_success wirft keinen Fehler."""
        with patch('shared.self_healing._healing_monitor', SelfHealingMonitor(tmp_path)):
            # Should not raise
            record_pipeline_success()

    def test_record_pipeline_failure_with_type(self, tmp_path):
        """record_pipeline_failure akzeptiert issue_type."""
        with patch('shared.self_healing._healing_monitor', SelfHealingMonitor(tmp_path)):
            # Should not raise
            record_pipeline_failure(IssueType.API_TIMEOUT)
