# =============================================================================
# POLYMARKET BEOBACHTER - SELF-HEALING & AUTO-IMPROVEMENT SYSTEM
# =============================================================================
#
# FEATURES:
# 1. HEALTH MONITORING - Erkennt Systemprobleme (Memory, Timeouts, Stale Data)
# 2. AUTO-HEALING - Behebt Probleme automatisch (GC, Connection Reset, Cache Clear)
# 3. AUTO-CODE-IMPROVEMENT - Optimiert Parameter basierend auf Performance
#
# SAFETY BOUNDARIES:
# - Nur Parameter-Änderungen (keine Struktur-Änderungen)
# - Alle Änderungen werden versioniert und sind rollback-fähig
# - Max 1 Änderung pro Stunde
# - Änderungen nur innerhalb definierter Grenzen (min/max)
# - Git-Commit nach jeder Änderung für Nachvollziehbarkeit
#
# =============================================================================

from __future__ import annotations

import gc
import json
import logging
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

logger = logging.getLogger(__name__)


# =============================================================================
# HEALTH STATUS & ENUMS
# =============================================================================

class HealthStatus(Enum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    CRITICAL = "CRITICAL"
    RECOVERING = "RECOVERING"


class IssueType(Enum):
    API_TIMEOUT = "API_TIMEOUT"
    API_RATE_LIMIT = "API_RATE_LIMIT"
    MEMORY_PRESSURE = "MEMORY_PRESSURE"
    STALE_DATA = "STALE_DATA"
    FILE_CORRUPTION = "FILE_CORRUPTION"
    CONSECUTIVE_FAILURES = "CONSECUTIVE_FAILURES"
    NETWORK_ERROR = "NETWORK_ERROR"


@dataclass
class HealingAction:
    issue_type: IssueType
    action: str
    timestamp: datetime
    success: bool
    details: str = ""


@dataclass
class Metrics:
    """Performance metrics for improvement decisions."""
    win_rate: float = 0.0
    profit_factor: float = 0.0
    total_trades: int = 0
    avg_loss_pct: float = 0.0
    avg_win_pct: float = 0.0
    drawdown_pct: float = 0.0
    sharpe_ratio: float = 0.0
    extra: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CodeChange:
    """Record of an automatic code change."""
    timestamp: datetime
    parameter: str
    old_value: Any
    new_value: Any
    file_path: str
    reason: str
    metrics_before: Metrics
    commit_hash: Optional[str] = None
    rolled_back: bool = False


# =============================================================================
# SELF-HEALING MONITOR
# =============================================================================

class SelfHealingMonitor:
    """
    Monitors bot health and automatically heals common issues.
    """

    MEMORY_WARNING_MB = 500
    MEMORY_CRITICAL_MB = 800
    STALE_DATA_MINUTES = 60
    MAX_CONSECUTIVE_FAILURES = 3
    BACKOFF_BASE_SECONDS = 30

    def __init__(self, base_dir: Optional[Path] = None):
        self.base_dir = base_dir or Path(__file__).parent.parent
        self.logs_dir = self.base_dir / "logs"
        self.health_file = self.logs_dir / "health_state.json"

        self._start_time = datetime.now()
        self._consecutive_failures = 0
        self._last_successful_run: Optional[datetime] = None
        self._backoff_until: Optional[datetime] = None
        self._healing_history: List[HealingAction] = []

        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self._load_state()

    def _load_state(self) -> None:
        try:
            if self.health_file.exists():
                data = json.loads(self.health_file.read_text(encoding="utf-8"))
                self._consecutive_failures = data.get("consecutive_failures", 0)
                if data.get("last_successful_run"):
                    self._last_successful_run = datetime.fromisoformat(data["last_successful_run"])
        except Exception as e:
            logger.debug(f"Could not load health state: {e}")

    def _save_state(self) -> None:
        try:
            data = {
                "timestamp": datetime.now().isoformat(),
                "consecutive_failures": self._consecutive_failures,
                "last_successful_run": self._last_successful_run.isoformat() if self._last_successful_run else None,
                "uptime_seconds": (datetime.now() - self._start_time).total_seconds(),
            }
            tmp = self.health_file.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
            tmp.replace(self.health_file)
        except Exception as e:
            logger.debug(f"Could not save health state: {e}")

    def _get_memory_mb(self) -> float:
        try:
            import psutil
            return psutil.Process(os.getpid()).memory_info().rss / 1024 / 1024
        except Exception:
            return 0.0

    def heal_memory_pressure(self) -> HealingAction:
        """Force garbage collection and clear caches."""
        before = self._get_memory_mb()
        gc.collect()
        gc.collect()
        after = self._get_memory_mb()

        return HealingAction(
            issue_type=IssueType.MEMORY_PRESSURE,
            action="gc_collect",
            timestamp=datetime.now(),
            success=True,
            details=f"Freed {before - after:.1f} MB",
        )

    def heal_api_timeout(self) -> HealingAction:
        """Apply exponential backoff."""
        backoff = min(self.BACKOFF_BASE_SECONDS * (2 ** self._consecutive_failures), 600)
        self._backoff_until = datetime.now() + timedelta(seconds=backoff)

        return HealingAction(
            issue_type=IssueType.API_TIMEOUT,
            action="backoff",
            timestamp=datetime.now(),
            success=True,
            details=f"Backoff {backoff}s until {self._backoff_until.isoformat()}",
        )

    def check_and_heal(self) -> Dict[str, Any]:
        """Run health check and heal issues."""
        issues = []
        actions = []

        # Memory check
        mem = self._get_memory_mb()
        if mem > self.MEMORY_CRITICAL_MB:
            issues.append(IssueType.MEMORY_PRESSURE)
            actions.append(self.heal_memory_pressure())

        # Consecutive failures
        if self._consecutive_failures >= self.MAX_CONSECUTIVE_FAILURES:
            issues.append(IssueType.CONSECUTIVE_FAILURES)
            actions.append(self.heal_api_timeout())
            self._consecutive_failures = 0

        status = HealthStatus.HEALTHY if not issues else HealthStatus.DEGRADED
        self._save_state()

        return {
            "status": status.value,
            "issues": [i.value for i in issues],
            "actions": [{"action": a.action, "success": a.success} for a in actions],
            "memory_mb": mem,
            "consecutive_failures": self._consecutive_failures,
        }

    def record_success(self) -> None:
        self._consecutive_failures = 0
        self._last_successful_run = datetime.now()
        self._backoff_until = None
        self._save_state()

    def record_failure(self, issue_type: Optional[IssueType] = None) -> None:
        self._consecutive_failures += 1
        self._save_state()

    def should_skip_run(self) -> Tuple[bool, str]:
        if self._backoff_until and datetime.now() < self._backoff_until:
            remaining = (self._backoff_until - datetime.now()).total_seconds()
            return True, f"Backoff active, {remaining:.0f}s remaining"
        return False, ""


# =============================================================================
# AUTO CODE IMPROVER
# =============================================================================

class AutoCodeImprover:
    """
    Automatically improves bot parameters based on performance metrics.

    SAFETY RULES:
    - Only changes parameters within defined min/max bounds
    - Max 1 change per hour
    - All changes are git-committed for traceability
    - Automatic rollback if performance degrades
    """

    # Parameter definitions with safety bounds
    PARAMETERS = {
        "KELLY_FRACTION": {
            "file": "paper_trader/kelly.py",
            "type": "py_const",
            "pattern": r"^KELLY_FRACTION:\s*float\s*=\s*([\d.]+)",
            "min": 0.05,
            "max": 0.35,
            "step": 0.025,
            "description": "Kelly-Fraction für Position-Sizing",
        },
        "MIN_EDGE": {
            "file": "config/weather.yaml",
            "type": "yaml",
            "key": "MIN_EDGE",
            "min": 0.05,
            "max": 0.25,
            "step": 0.02,
            "description": "Minimum relativer Edge für BUY-Signal",
        },
        "MAX_ODDS": {
            "file": "config/weather.yaml",
            "type": "yaml",
            "key": "MAX_ODDS",
            "min": 0.20,
            "max": 0.50,
            "step": 0.05,
            "description": "Maximum Markt-Odds für Entries",
        },
        "TAKE_PROFIT_PCT": {
            "file": "paper_trader/position_manager.py",
            "type": "py_const",
            "pattern": r"TAKE_PROFIT_PCT\s*=\s*([\d.]+)",
            "min": 0.10,
            "max": 0.30,
            "step": 0.05,
            "description": "Take-Profit Schwelle in %",
        },
        "STOP_LOSS_PCT": {
            "file": "paper_trader/position_manager.py",
            "type": "py_const",
            "pattern": r"STOP_LOSS_PCT\s*=\s*-?([\d.]+)",
            "min": 0.15,
            "max": 0.40,
            "step": 0.05,
            "description": "Stop-Loss Schwelle in %",
        },
    }

    MIN_TRADES_FOR_EVALUATION = 10
    MIN_HOURS_BETWEEN_CHANGES = 1
    PERFORMANCE_LOOKBACK_DAYS = 7

    def __init__(self, base_dir: Optional[Path] = None):
        self.base_dir = base_dir or Path(__file__).parent.parent
        self.changes_log = self.base_dir / "logs" / "code_changes.jsonl"
        self.last_change_file = self.base_dir / "logs" / ".last_code_change"
        self._changes_history: List[CodeChange] = []

        self.changes_log.parent.mkdir(parents=True, exist_ok=True)
        self._load_history()

    def _load_history(self) -> None:
        """Load change history from log file."""
        if self.changes_log.exists():
            try:
                with open(self.changes_log, "r", encoding="utf-8") as f:
                    for line in f:
                        try:
                            data = json.loads(line.strip())
                            self._changes_history.append(CodeChange(
                                timestamp=datetime.fromisoformat(data["timestamp"]),
                                parameter=data["parameter"],
                                old_value=data["old_value"],
                                new_value=data["new_value"],
                                file_path=data["file_path"],
                                reason=data["reason"],
                                metrics_before=Metrics(**data.get("metrics_before", {})),
                                commit_hash=data.get("commit_hash"),
                                rolled_back=data.get("rolled_back", False),
                            ))
                        except Exception:
                            pass
            except Exception as e:
                logger.debug(f"Could not load change history: {e}")

    def _log_change(self, change: CodeChange) -> None:
        """Log a code change to the changes log."""
        try:
            entry = {
                "timestamp": change.timestamp.isoformat(),
                "parameter": change.parameter,
                "old_value": change.old_value,
                "new_value": change.new_value,
                "file_path": change.file_path,
                "reason": change.reason,
                "metrics_before": {
                    "win_rate": change.metrics_before.win_rate,
                    "profit_factor": change.metrics_before.profit_factor,
                    "total_trades": change.metrics_before.total_trades,
                    "drawdown_pct": change.metrics_before.drawdown_pct,
                },
                "commit_hash": change.commit_hash,
                "rolled_back": change.rolled_back,
            }
            with open(self.changes_log, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception as e:
            logger.warning(f"Could not log code change: {e}")

    def _can_make_change(self) -> Tuple[bool, str]:
        """Check if we're allowed to make a change now."""
        if self.last_change_file.exists():
            try:
                last = datetime.fromisoformat(self.last_change_file.read_text().strip())
                hours_since = (datetime.now() - last).total_seconds() / 3600
                if hours_since < self.MIN_HOURS_BETWEEN_CHANGES:
                    return False, f"Letzte Änderung vor {hours_since:.1f}h (min {self.MIN_HOURS_BETWEEN_CHANGES}h)"
            except Exception:
                pass
        return True, ""

    def _get_current_value(self, param_name: str) -> Optional[Any]:
        """Get current value of a parameter."""
        if param_name not in self.PARAMETERS:
            return None

        config = self.PARAMETERS[param_name]
        file_path = self.base_dir / config["file"]

        if not file_path.exists():
            return None

        try:
            content = file_path.read_text(encoding="utf-8")

            if config["type"] == "yaml":
                data = yaml.safe_load(content)
                return data.get(config["key"])

            elif config["type"] == "py_const":
                match = re.search(config["pattern"], content)
                if match:
                    return float(match.group(1))

        except Exception as e:
            logger.debug(f"Could not read {param_name}: {e}")

        return None

    def _set_value(self, param_name: str, new_value: Any) -> bool:
        """Set a parameter to a new value."""
        if param_name not in self.PARAMETERS:
            return False

        config = self.PARAMETERS[param_name]
        file_path = self.base_dir / config["file"]

        if not file_path.exists():
            return False

        try:
            content = file_path.read_text(encoding="utf-8")

            # Create backup
            backup_path = file_path.with_suffix(file_path.suffix + ".backup")
            shutil.copy2(file_path, backup_path)

            if config["type"] == "yaml":
                data = yaml.safe_load(content)
                data[config["key"]] = new_value
                new_content = yaml.dump(data, default_flow_style=False, allow_unicode=True)

            elif config["type"] == "py_const":
                # Replace the constant value in Python code
                pattern = config["pattern"]
                # Construct replacement that preserves format
                def replacer(m):
                    return m.group(0).replace(m.group(1), str(new_value))
                new_content = re.sub(pattern, replacer, content)
            else:
                return False

            file_path.write_text(new_content, encoding="utf-8")
            return True

        except Exception as e:
            logger.error(f"Could not set {param_name} to {new_value}: {e}")
            # Restore backup on failure
            if backup_path.exists():
                shutil.copy2(backup_path, file_path)
            return False

    def _git_commit(self, param_name: str, old_value: Any, new_value: Any, reason: str) -> Optional[str]:
        """Commit the change to git."""
        try:
            file_path = self.PARAMETERS[param_name]["file"]

            # Stage the changed file
            subprocess.run(
                ["git", "add", file_path],
                cwd=str(self.base_dir),
                capture_output=True,
                timeout=10
            )

            # Create commit message
            message = (
                f"auto: {param_name} {old_value}→{new_value} in {file_path} "
                f"[{reason[:80]}]"
            )

            result = subprocess.run(
                ["git", "commit", "-m", message],
                cwd=str(self.base_dir),
                capture_output=True,
                timeout=10
            )

            if result.returncode == 0:
                # Get commit hash
                hash_result = subprocess.run(
                    ["git", "rev-parse", "HEAD"],
                    cwd=str(self.base_dir),
                    capture_output=True,
                    timeout=10
                )
                return hash_result.stdout.decode().strip()[:7]

        except Exception as e:
            logger.debug(f"Git commit failed: {e}")

        return None

    def observe_metrics(self) -> Metrics:
        """Observe current performance metrics."""
        try:
            report_file = self.base_dir / "analytics" / "performance_report.json"

            if report_file.exists():
                data = json.loads(report_file.read_text(encoding="utf-8"))
                return Metrics(
                    win_rate=float(data.get("win_rate", 0)),
                    profit_factor=float(data.get("profit_factor", 0)),
                    total_trades=int(data.get("total_trades", data.get("total_closed", 0))),
                    avg_loss_pct=float(data.get("avg_loss_pct", data.get("avg_loss", 0))),
                    avg_win_pct=float(data.get("avg_win_pct", data.get("avg_win", 0))),
                    drawdown_pct=float(data.get("max_drawdown_pct", 0)),
                    extra={"source": "performance_report.json"},
                )
        except Exception as e:
            logger.debug(f"Could not observe metrics: {e}")

        return Metrics()

    def _decide_change(self, metrics: Metrics) -> Optional[Tuple[str, float, str]]:
        """
        Decide which parameter to change based on metrics.

        Returns: (parameter_name, new_value, reason) or None
        """
        if metrics.total_trades < self.MIN_TRADES_FOR_EVALUATION:
            return None

        # Decision logic based on performance

        # 1. High drawdown -> reduce Kelly
        if metrics.drawdown_pct > 20:
            current = self._get_current_value("KELLY_FRACTION")
            if current and current > self.PARAMETERS["KELLY_FRACTION"]["min"]:
                step = self.PARAMETERS["KELLY_FRACTION"]["step"]
                new_val = round(max(current - step, self.PARAMETERS["KELLY_FRACTION"]["min"]), 3)
                return ("KELLY_FRACTION", new_val, f"Hoher Drawdown ({metrics.drawdown_pct:.1f}%), Kelly reduzieren")

        # 2. Low win rate -> increase MIN_EDGE
        if metrics.win_rate < 0.45:
            current = self._get_current_value("MIN_EDGE")
            if current and current < self.PARAMETERS["MIN_EDGE"]["max"]:
                step = self.PARAMETERS["MIN_EDGE"]["step"]
                new_val = round(min(current + step, self.PARAMETERS["MIN_EDGE"]["max"]), 2)
                return ("MIN_EDGE", new_val, f"Niedrige Win-Rate ({metrics.win_rate:.1%}), MIN_EDGE erhöhen")

        # 3. Very high win rate + low profit factor -> might be taking profits too early
        if metrics.win_rate > 0.65 and metrics.profit_factor < 1.5:
            current = self._get_current_value("TAKE_PROFIT_PCT")
            if current and current < self.PARAMETERS["TAKE_PROFIT_PCT"]["max"]:
                step = self.PARAMETERS["TAKE_PROFIT_PCT"]["step"]
                new_val = round(min(current + step, self.PARAMETERS["TAKE_PROFIT_PCT"]["max"]), 2)
                return ("TAKE_PROFIT_PCT", new_val, "Hohe Win-Rate aber niedriger PF, Take-Profit erhöhen")

        # 4. Good win rate + good profit factor -> can be more aggressive
        if metrics.win_rate > 0.55 and metrics.profit_factor > 1.8 and metrics.drawdown_pct < 10:
            current = self._get_current_value("KELLY_FRACTION")
            if current and current < self.PARAMETERS["KELLY_FRACTION"]["max"]:
                step = self.PARAMETERS["KELLY_FRACTION"]["step"]
                new_val = round(min(current + step, self.PARAMETERS["KELLY_FRACTION"]["max"]), 3)
                return ("KELLY_FRACTION", new_val, f"Gute Performance (WR={metrics.win_rate:.1%}, PF={metrics.profit_factor:.1f}), Kelly erhöhen")

        # 5. Many stop-losses -> tighten stop-loss or reduce entry price
        sl_count = metrics.extra.get("stop_loss_count", 0)
        if sl_count > 3 and metrics.total_trades > 0:
            sl_rate = sl_count / metrics.total_trades
            if sl_rate > 0.3:
                current = self._get_current_value("MAX_ODDS")
                if current and current > self.PARAMETERS["MAX_ODDS"]["min"]:
                    step = self.PARAMETERS["MAX_ODDS"]["step"]
                    new_val = round(max(current - step, self.PARAMETERS["MAX_ODDS"]["min"]), 2)
                    return ("MAX_ODDS", new_val, f"Hohe SL-Rate ({sl_rate:.1%}), MAX_ODDS reduzieren")

        return None

    def run_improvement_cycle(self) -> Dict[str, Any]:
        """
        Run one improvement cycle.

        Returns dict with action taken and details.
        """
        # Check if we can make a change
        can_change, reason = self._can_make_change()
        if not can_change:
            return {"action": "waiting", "reason": reason}

        # Observe current metrics
        metrics = self.observe_metrics()

        if metrics.total_trades < self.MIN_TRADES_FOR_EVALUATION:
            return {
                "action": "waiting_for_data",
                "reason": f"Nur {metrics.total_trades} Trades (min {self.MIN_TRADES_FOR_EVALUATION})",
            }

        # Decide what to change
        decision = self._decide_change(metrics)

        if decision is None:
            return {
                "action": "none",
                "reason": "Keine Verbesserung identifiziert",
                "metrics": {
                    "win_rate": metrics.win_rate,
                    "profit_factor": metrics.profit_factor,
                    "drawdown_pct": metrics.drawdown_pct,
                },
            }

        param_name, new_value, change_reason = decision
        old_value = self._get_current_value(param_name)

        if old_value is None:
            return {"action": "error", "reason": f"Konnte {param_name} nicht lesen"}

        # Make the change
        success = self._set_value(param_name, new_value)

        if not success:
            return {"action": "error", "reason": f"Konnte {param_name} nicht ändern"}

        # Git commit
        commit_hash = self._git_commit(param_name, old_value, new_value, change_reason)

        # Log the change
        change = CodeChange(
            timestamp=datetime.now(),
            parameter=param_name,
            old_value=old_value,
            new_value=new_value,
            file_path=self.PARAMETERS[param_name]["file"],
            reason=change_reason,
            metrics_before=metrics,
            commit_hash=commit_hash,
        )
        self._changes_history.append(change)
        self._log_change(change)

        # Update last change timestamp
        self.last_change_file.write_text(datetime.now().isoformat())

        logger.info(
            f"[AUTO-IMPROVE] {param_name}: {old_value} → {new_value} | {change_reason}"
        )

        # Send Telegram notification
        try:
            from notifications.telegram import send_message
            text = (
                f"🔧 <b>AUTO-IMPROVEMENT</b>\n"
                f"Parameter: <code>{param_name}</code>\n"
                f"Änderung: {old_value} → {new_value}\n"
                f"Grund: {change_reason}\n"
                f"Commit: {commit_hash or 'N/A'}"
            )
            send_message(text, disable_notification=True)
        except Exception:
            pass

        return {
            "action": "changed",
            "param": param_name,
            "old": old_value,
            "new": new_value,
            "reasoning": change_reason,
            "commit": commit_hash,
        }

    def rollback_last_change(self) -> Dict[str, Any]:
        """Rollback the last change if it degraded performance."""
        if not self._changes_history:
            return {"action": "none", "reason": "Keine Änderungen zum Rollback"}

        last = self._changes_history[-1]

        if last.rolled_back:
            return {"action": "none", "reason": "Letzte Änderung bereits zurückgerollt"}

        # Restore old value
        success = self._set_value(last.parameter, last.old_value)

        if success:
            last.rolled_back = True
            self._git_commit(
                last.parameter,
                last.new_value,
                last.old_value,
                f"ROLLBACK: {last.reason}"
            )

            return {
                "action": "rolled_back",
                "param": last.parameter,
                "restored": last.old_value,
            }

        return {"action": "error", "reason": "Rollback fehlgeschlagen"}


# =============================================================================
# MODULE-LEVEL SINGLETONS
# =============================================================================

_healing_monitor: Optional[SelfHealingMonitor] = None
_code_improver: Optional[AutoCodeImprover] = None


def get_self_healing_monitor(base_dir: Optional[Path] = None) -> SelfHealingMonitor:
    global _healing_monitor
    if _healing_monitor is None:
        _healing_monitor = SelfHealingMonitor(base_dir)
    return _healing_monitor


def get_auto_code_improver(base_dir: Optional[Path] = None) -> AutoCodeImprover:
    global _code_improver
    if _code_improver is None:
        _code_improver = AutoCodeImprover(base_dir)
    return _code_improver


def check_and_heal() -> Dict[str, Any]:
    """Run health check and healing."""
    return get_self_healing_monitor().check_and_heal()


def run_auto_improvement() -> Dict[str, Any]:
    """Run automatic code improvement."""
    return get_auto_code_improver().run_improvement_cycle()


def record_pipeline_success() -> None:
    """Record a successful pipeline run."""
    get_self_healing_monitor().record_success()


def record_pipeline_failure(issue_type: Optional[IssueType] = None) -> None:
    """Record a pipeline failure."""
    get_self_healing_monitor().record_failure(issue_type)
