# =============================================================================
# SYSTEM MONITOR - COMPREHENSIVE HEALTH & PERFORMANCE TRACKING
# =============================================================================
#
# Centralized system monitoring for the weather betting system:
# - Health checks and alerts
# - Resource utilization tracking
# - Performance bottleneck detection
# - Automatic optimization triggers
#
# =============================================================================

import json
import logging
import psutil
import time
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, asdict
from collections import deque

logger = logging.getLogger(__name__)


@dataclass
class SystemMetrics:
    """System performance metrics snapshot."""
    timestamp: str
    cpu_percent: float
    memory_percent: float
    memory_used_mb: float
    memory_available_mb: float
    disk_usage_percent: float
    disk_free_gb: float
    network_bytes_sent: int
    network_bytes_recv: int
    process_count: int
    thread_count: int
    file_descriptors: int
    load_average: List[float]


@dataclass
class HealthCheck:
    """Individual health check result."""
    name: str
    status: str  # OK, WARNING, CRITICAL
    message: str
    value: Optional[float] = None
    threshold: Optional[float] = None
    timestamp: Optional[str] = None


class SystemMonitor:
    """
    Comprehensive system monitoring with alerting and optimization.

    Features:
    - Real-time resource monitoring
    - Health checks with configurable thresholds
    - Performance trend analysis
    - Automatic optimization triggers
    - Alert notifications
    """

    def __init__(self, check_interval: int = 30):
        self.check_interval = check_interval
        self.monitoring = False
        self._monitor_thread = None
        self._shutdown = threading.Event()

        # Metrics history (last 24 hours at 30s intervals = 2880 samples)
        self.metrics_history = deque(maxlen=2880)

        # Health check thresholds
        self.thresholds = {
            'cpu_warning': 80.0,
            'cpu_critical': 95.0,
            'memory_warning': 80.0,
            'memory_critical': 95.0,
            'disk_warning': 85.0,
            'disk_critical': 95.0,
            'load_warning': 2.0,
            'load_critical': 5.0
        }

        # Alert callbacks
        self.alert_callbacks: List[Callable] = []

        # Performance baselines (updated over time)
        self.baselines = {
            'avg_cpu': 0.0,
            'avg_memory': 0.0,
            'peak_cpu': 0.0,
            'peak_memory': 0.0
        }

        # Process-specific monitoring
        self.process = psutil.Process()
        self.process_metrics_history = deque(maxlen=1440)  # 12 hours

    def start_monitoring(self):
        """Start background system monitoring."""
        if self.monitoring:
            return

        self.monitoring = True
        self._shutdown.clear()

        self._monitor_thread = threading.Thread(
            target=self._monitoring_loop,
            daemon=True,
            name="SystemMonitor"
        )
        self._monitor_thread.start()

        logger.info("System monitoring started")

    def stop_monitoring(self):
        """Stop background monitoring."""
        if not self.monitoring:
            return

        self.monitoring = False
        self._shutdown.set()

        if self._monitor_thread and self._monitor_thread.is_alive():
            self._monitor_thread.join(timeout=5.0)

        logger.info("System monitoring stopped")

    def add_alert_callback(self, callback: Callable[[HealthCheck], None]):
        """Add callback for health alerts."""
        self.alert_callbacks.append(callback)

    def remove_alert_callback(self, callback: Callable):
        """Remove alert callback."""
        if callback in self.alert_callbacks:
            self.alert_callbacks.remove(callback)

    def get_current_metrics(self) -> SystemMetrics:
        """Get current system metrics snapshot."""
        # System-wide metrics
        cpu_percent = psutil.cpu_percent(interval=1)
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        network = psutil.net_io_counters()

        # Load average (Unix-like systems)
        try:
            load_avg = list(psutil.getloadavg())
        except AttributeError:
            # Windows doesn't have load average
            load_avg = [0.0, 0.0, 0.0]

        # Process counts
        process_count = len(psutil.pids())

        # Thread count for current process
        try:
            thread_count = self.process.num_threads()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            thread_count = 0

        # File descriptors (Unix-like systems)
        try:
            file_descriptors = self.process.num_fds()
        except (AttributeError, psutil.NoSuchProcess, psutil.AccessDenied):
            file_descriptors = 0

        return SystemMetrics(
            timestamp=datetime.now().isoformat(),
            cpu_percent=cpu_percent,
            memory_percent=memory.percent,
            memory_used_mb=memory.used / (1024 * 1024),
            memory_available_mb=memory.available / (1024 * 1024),
            disk_usage_percent=disk.percent,
            disk_free_gb=disk.free / (1024 * 1024 * 1024),
            network_bytes_sent=network.bytes_sent,
            network_bytes_recv=network.bytes_recv,
            process_count=process_count,
            thread_count=thread_count,
            file_descriptors=file_descriptors,
            load_average=load_avg
        )

    def get_health_checks(self) -> List[HealthCheck]:
        """Run all health checks."""
        checks = []
        metrics = self.get_current_metrics()

        # CPU health check
        if metrics.cpu_percent >= self.thresholds['cpu_critical']:
            status = "CRITICAL"
        elif metrics.cpu_percent >= self.thresholds['cpu_warning']:
            status = "WARNING"
        else:
            status = "OK"

        checks.append(HealthCheck(
            name="CPU Usage",
            status=status,
            message=f"CPU usage: {metrics.cpu_percent:.1f}%",
            value=metrics.cpu_percent,
            threshold=self.thresholds['cpu_warning'],
            timestamp=metrics.timestamp
        ))

        # Memory health check
        if metrics.memory_percent >= self.thresholds['memory_critical']:
            status = "CRITICAL"
        elif metrics.memory_percent >= self.thresholds['memory_warning']:
            status = "WARNING"
        else:
            status = "OK"

        checks.append(HealthCheck(
            name="Memory Usage",
            status=status,
            message=f"Memory usage: {metrics.memory_percent:.1f}% ({metrics.memory_used_mb:.0f} MB)",
            value=metrics.memory_percent,
            threshold=self.thresholds['memory_warning'],
            timestamp=metrics.timestamp
        ))

        # Disk health check
        if metrics.disk_usage_percent >= self.thresholds['disk_critical']:
            status = "CRITICAL"
        elif metrics.disk_usage_percent >= self.thresholds['disk_warning']:
            status = "WARNING"
        else:
            status = "OK"

        checks.append(HealthCheck(
            name="Disk Usage",
            status=status,
            message=f"Disk usage: {metrics.disk_usage_percent:.1f}% ({metrics.disk_free_gb:.1f} GB free)",
            value=metrics.disk_usage_percent,
            threshold=self.thresholds['disk_warning'],
            timestamp=metrics.timestamp
        ))

        # Load average health check (if available)
        if metrics.load_average[0] > 0:
            load_1min = metrics.load_average[0]
            if load_1min >= self.thresholds['load_critical']:
                status = "CRITICAL"
            elif load_1min >= self.thresholds['load_warning']:
                status = "WARNING"
            else:
                status = "OK"

            checks.append(HealthCheck(
                name="Load Average",
                status=status,
                message=f"Load average: {load_1min:.2f}",
                value=load_1min,
                threshold=self.thresholds['load_warning'],
                timestamp=metrics.timestamp
            ))

        return checks

    def get_performance_trends(self, hours: int = 1) -> Dict[str, Any]:
        """Analyze performance trends over specified time window."""
        if not self.metrics_history:
            return {}

        # Filter metrics to time window
        cutoff = datetime.now() - timedelta(hours=hours)
        recent_metrics = [
            m for m in self.metrics_history
            if datetime.fromisoformat(m.timestamp) > cutoff
        ]

        if not recent_metrics:
            return {}

        # Calculate trends
        cpu_values = [m.cpu_percent for m in recent_metrics]
        memory_values = [m.memory_percent for m in recent_metrics]

        trends = {
            'time_window_hours': hours,
            'sample_count': len(recent_metrics),
            'cpu': {
                'avg': round(sum(cpu_values) / len(cpu_values), 1),
                'min': round(min(cpu_values), 1),
                'max': round(max(cpu_values), 1),
                'trend': self._calculate_trend(cpu_values)
            },
            'memory': {
                'avg': round(sum(memory_values) / len(memory_values), 1),
                'min': round(min(memory_values), 1),
                'max': round(max(memory_values), 1),
                'trend': self._calculate_trend(memory_values)
            }
        }

        return trends

    def _calculate_trend(self, values: List[float]) -> str:
        """Calculate trend direction from values."""
        if len(values) < 2:
            return "stable"

        # Simple linear trend analysis
        first_half = sum(values[:len(values)//2]) / (len(values)//2)
        second_half = sum(values[len(values)//2:]) / (len(values) - len(values)//2)

        diff_percent = ((second_half - first_half) / first_half) * 100

        if diff_percent > 10:
            return "increasing"
        elif diff_percent < -10:
            return "decreasing"
        else:
            return "stable"

    def _monitoring_loop(self):
        """Main monitoring loop."""
        while self.monitoring and not self._shutdown.wait(self.check_interval):
            try:
                # Collect metrics
                metrics = self.get_current_metrics()
                self.metrics_history.append(metrics)

                # Update baselines
                self._update_baselines(metrics)

                # Run health checks
                health_checks = self.get_health_checks()

                # Send alerts for critical/warning conditions
                for check in health_checks:
                    if check.status in ['WARNING', 'CRITICAL']:
                        self._send_alert(check)

                # Log critical conditions
                critical_checks = [c for c in health_checks if c.status == 'CRITICAL']
                if critical_checks:
                    logger.warning(f"Critical system conditions detected: {len(critical_checks)} issues")

            except Exception as e:
                logger.error(f"Error in system monitoring: {e}")

    def _update_baselines(self, metrics: SystemMetrics):
        """Update performance baselines."""
        # Simple exponential moving average
        alpha = 0.1  # Smoothing factor

        self.baselines['avg_cpu'] = (
            alpha * metrics.cpu_percent +
            (1 - alpha) * self.baselines['avg_cpu']
        )

        self.baselines['avg_memory'] = (
            alpha * metrics.memory_percent +
            (1 - alpha) * self.baselines['avg_memory']
        )

        self.baselines['peak_cpu'] = max(self.baselines['peak_cpu'], metrics.cpu_percent)
        self.baselines['peak_memory'] = max(self.baselines['peak_memory'], metrics.memory_percent)

    def _send_alert(self, health_check: HealthCheck):
        """Send alert notifications."""
        for callback in self.alert_callbacks:
            try:
                callback(health_check)
            except Exception as e:
                logger.error(f"Error in alert callback: {e}")

    def get_system_report(self) -> Dict[str, Any]:
        """Get comprehensive system report."""
        metrics = self.get_current_metrics()
        health_checks = self.get_health_checks()
        trends = self.get_performance_trends()

        # Overall health status
        critical_count = sum(1 for c in health_checks if c.status == 'CRITICAL')
        warning_count = sum(1 for c in health_checks if c.status == 'WARNING')

        if critical_count > 0:
            overall_status = 'CRITICAL'
        elif warning_count > 0:
            overall_status = 'WARNING'
        else:
            overall_status = 'OK'

        return {
            'timestamp': datetime.now().isoformat(),
            'overall_status': overall_status,
            'current_metrics': asdict(metrics),
            'health_checks': [asdict(check) for check in health_checks],
            'performance_trends': trends,
            'baselines': self.baselines.copy(),
            'monitoring_stats': {
                'samples_collected': len(self.metrics_history),
                'monitoring_uptime_hours': round(
                    len(self.metrics_history) * self.check_interval / 3600, 1
                )
            }
        }

    def save_report(self, file_path: Path):
        """Save system report to file."""
        report = self.get_system_report()
        try:
            file_path.parent.mkdir(parents=True, exist_ok=True)
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(report, f, indent=2, ensure_ascii=False)
        except IOError as e:
            logger.error(f"Failed to save system report to {file_path}: {e}")


# Global monitor instance
_system_monitor = None


def get_system_monitor() -> SystemMonitor:
    """Get global system monitor instance."""
    global _system_monitor
    if _system_monitor is None:
        _system_monitor = SystemMonitor()
    return _system_monitor


def start_system_monitoring():
    """Start global system monitoring."""
    monitor = get_system_monitor()
    monitor.start_monitoring()


def stop_system_monitoring():
    """Stop global system monitoring."""
    global _system_monitor
    if _system_monitor:
        _system_monitor.stop_monitoring()


def get_system_health() -> Dict[str, Any]:
    """Get quick system health summary."""
    monitor = get_system_monitor()
    health_checks = monitor.get_health_checks()

    return {
        'status': 'CRITICAL' if any(c.status == 'CRITICAL' for c in health_checks)
                  else 'WARNING' if any(c.status == 'WARNING' for c in health_checks)
                  else 'OK',
        'checks': len(health_checks),
        'critical': sum(1 for c in health_checks if c.status == 'CRITICAL'),
        'warning': sum(1 for c in health_checks if c.status == 'WARNING'),
        'timestamp': datetime.now().isoformat()
    }