# =============================================================================
# PERFORMANCE MONITORING AND BENCHMARKING
# =============================================================================
#
# Überwacht und sammelt Performance-Metriken für das Trading System:
# - Function-level Timing
# - Memory Usage Tracking
# - API Call Latency
# - Cache Hit/Miss Ratios
# - Bottleneck Detection
#
# =============================================================================

import logging
import time
import psutil
import functools
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Callable
from collections import defaultdict, deque
from threading import Lock

logger = logging.getLogger(__name__)

# =============================================================================
# PERFORMANCE METRICS DATA MODEL
# =============================================================================

@dataclass
class PerformanceMetric:
    """Single performance measurement."""
    name: str
    execution_time: float
    memory_usage_mb: float
    timestamp: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class FunctionStats:
    """Aggregated statistics for a function."""
    call_count: int = 0
    total_time: float = 0.0
    min_time: float = float('inf')
    max_time: float = 0.0
    avg_time: float = 0.0
    recent_times: deque = field(default_factory=lambda: deque(maxlen=100))

    def add_measurement(self, execution_time: float):
        """Add a new timing measurement."""
        self.call_count += 1
        self.total_time += execution_time
        self.min_time = min(self.min_time, execution_time)
        self.max_time = max(self.max_time, execution_time)
        self.avg_time = self.total_time / self.call_count
        self.recent_times.append(execution_time)

    def get_recent_avg(self, n: int = 10) -> float:
        """Get average of last N measurements."""
        if not self.recent_times:
            return 0.0
        recent = list(self.recent_times)[-n:]
        return sum(recent) / len(recent)

# =============================================================================
# GLOBAL PERFORMANCE MONITOR
# =============================================================================

class PerformanceMonitor:
    """Global performance monitoring system."""

    def __init__(self):
        self._metrics: List[PerformanceMetric] = []
        self._function_stats: Dict[str, FunctionStats] = defaultdict(FunctionStats)
        self._cache_stats: Dict[str, Dict[str, int]] = defaultdict(lambda: {'hits': 0, 'misses': 0})
        self._lock = Lock()
        self._enabled = True

    def enable(self):
        """Enable performance monitoring."""
        self._enabled = True

    def disable(self):
        """Disable performance monitoring."""
        self._enabled = False

    def record_metric(self, metric: PerformanceMetric):
        """Record a performance metric."""
        if not self._enabled:
            return

        with self._lock:
            self._metrics.append(metric)
            # Keep only last 10000 metrics to prevent memory growth
            if len(self._metrics) > 10000:
                self._metrics = self._metrics[-5000:]

    def record_function_timing(self, function_name: str, execution_time: float, metadata: Optional[Dict] = None):
        """Record function execution timing."""
        if not self._enabled:
            return

        with self._lock:
            self._function_stats[function_name].add_measurement(execution_time)

        # Also record as general metric
        memory_mb = psutil.Process().memory_info().rss / 1024 / 1024
        metric = PerformanceMetric(
            name=f"function.{function_name}",
            execution_time=execution_time,
            memory_usage_mb=memory_mb,
            metadata=metadata or {}
        )
        self.record_metric(metric)

    def record_cache_hit(self, cache_name: str):
        """Record cache hit."""
        if not self._enabled:
            return

        with self._lock:
            self._cache_stats[cache_name]['hits'] += 1

    def record_cache_miss(self, cache_name: str):
        """Record cache miss."""
        if not self._enabled:
            return

        with self._lock:
            self._cache_stats[cache_name]['misses'] += 1

    def get_function_stats(self, function_name: str) -> Optional[FunctionStats]:
        """Get statistics for a specific function."""
        with self._lock:
            return self._function_stats.get(function_name)

    def get_all_function_stats(self) -> Dict[str, FunctionStats]:
        """Get statistics for all monitored functions."""
        with self._lock:
            return dict(self._function_stats)

    def get_cache_stats(self) -> Dict[str, Dict[str, Any]]:
        """Get cache hit/miss statistics."""
        with self._lock:
            stats = {}
            for cache_name, data in self._cache_stats.items():
                total = data['hits'] + data['misses']
                hit_rate = data['hits'] / total if total > 0 else 0.0
                stats[cache_name] = {
                    'hits': data['hits'],
                    'misses': data['misses'],
                    'hit_rate': hit_rate,
                    'total_requests': total
                }
            return stats

    def get_performance_summary(self) -> Dict[str, Any]:
        """Get comprehensive performance summary."""
        with self._lock:
            # Top 10 slowest functions
            func_stats = sorted(
                self._function_stats.items(),
                key=lambda x: x[1].avg_time,
                reverse=True
            )[:10]

            # Recent memory usage
            recent_metrics = self._metrics[-100:] if self._metrics else []
            memory_usage = [m.memory_usage_mb for m in recent_metrics]
            avg_memory = sum(memory_usage) / len(memory_usage) if memory_usage else 0

            return {
                'total_functions_monitored': len(self._function_stats),
                'total_metrics_recorded': len(self._metrics),
                'average_memory_mb': round(avg_memory, 2),
                'slowest_functions': [
                    {
                        'name': name,
                        'avg_time_ms': round(stats.avg_time * 1000, 2),
                        'call_count': stats.call_count,
                        'total_time_s': round(stats.total_time, 2)
                    }
                    for name, stats in func_stats
                ],
                'cache_performance': self.get_cache_stats()
            }

    def reset_stats(self):
        """Reset all performance statistics."""
        with self._lock:
            self._metrics.clear()
            self._function_stats.clear()
            self._cache_stats.clear()

# Global monitor instance
monitor = PerformanceMonitor()

# =============================================================================
# DECORATORS AND CONTEXT MANAGERS
# =============================================================================

def performance_monitor(func_name: Optional[str] = None):
    """
    Decorator to monitor function performance.

    Usage:
        @performance_monitor()
        def my_function():
            pass

        @performance_monitor("custom_name")
        def another_function():
            pass
    """
    def decorator(func: Callable) -> Callable:
        name = func_name or f"{func.__module__}.{func.__name__}"

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            if not monitor._enabled:
                return func(*args, **kwargs)

            start_time = time.time()
            try:
                result = func(*args, **kwargs)
                return result
            finally:
                execution_time = time.time() - start_time
                monitor.record_function_timing(name, execution_time)

        return wrapper
    return decorator

@contextmanager
def performance_context(operation_name: str, metadata: Optional[Dict] = None):
    """
    Context manager for monitoring code blocks.

    Usage:
        with performance_context("weather_api_call"):
            response = api.get_weather(...)
    """
    if not monitor._enabled:
        yield
        return

    start_time = time.time()
    start_memory = psutil.Process().memory_info().rss / 1024 / 1024

    try:
        yield
    finally:
        execution_time = time.time() - start_time
        end_memory = psutil.Process().memory_info().rss / 1024 / 1024

        metric = PerformanceMetric(
            name=operation_name,
            execution_time=execution_time,
            memory_usage_mb=end_memory,
            metadata={
                **(metadata or {}),
                'memory_delta_mb': round(end_memory - start_memory, 2)
            }
        )
        monitor.record_metric(metric)

def monitor_cache_performance(cache_name: str):
    """
    Decorator to monitor cache hit/miss ratios.

    Usage:
        @monitor_cache_performance("weather_cache")
        @lru_cache(maxsize=1000)
        def cached_function():
            pass
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            if not monitor._enabled:
                return func(*args, **kwargs)

            # Try to determine if this is a cache hit or miss
            # This is a simplified approach - in practice, you'd integrate with the cache implementation
            result = func(*args, **kwargs)

            # For LRU cache, we can check cache_info if available
            if hasattr(func, 'cache_info'):
                cache_info = func.cache_info()
                # This is a rough estimate - cache_info gives cumulative stats
                if cache_info.hits > getattr(wrapper, '_last_hits', 0):
                    monitor.record_cache_hit(cache_name)
                    wrapper._last_hits = cache_info.hits
                elif cache_info.misses > getattr(wrapper, '_last_misses', 0):
                    monitor.record_cache_miss(cache_name)
                    wrapper._last_misses = cache_info.misses

            return result
        return wrapper
    return decorator

# =============================================================================
# SYSTEM RESOURCE MONITORING
# =============================================================================

def get_system_resources() -> Dict[str, Any]:
    """Get current system resource usage."""
    process = psutil.Process()

    return {
        'cpu_percent': psutil.cpu_percent(),
        'memory_percent': psutil.virtual_memory().percent,
        'process_memory_mb': process.memory_info().rss / 1024 / 1024,
        'process_cpu_percent': process.cpu_percent(),
        'open_files': len(process.open_files()),
        'threads': process.num_threads(),
    }

def log_performance_summary():
    """Log current performance summary to logger."""
    if not monitor._enabled:
        return

    summary = monitor.get_performance_summary()
    system_resources = get_system_resources()

    logger.info("Performance Summary:")
    logger.info(f"  Functions monitored: {summary['total_functions_monitored']}")
    logger.info(f"  Average memory: {summary['average_memory_mb']:.2f} MB")
    logger.info(f"  System CPU: {system_resources['cpu_percent']:.1f}%")
    logger.info(f"  System Memory: {system_resources['memory_percent']:.1f}%")

    if summary['slowest_functions']:
        logger.info("  Slowest functions:")
        for func_info in summary['slowest_functions'][:5]:
            logger.info(f"    {func_info['name']}: {func_info['avg_time_ms']:.2f}ms avg ({func_info['call_count']} calls)")

    if summary['cache_performance']:
        logger.info("  Cache performance:")
        for cache_name, stats in summary['cache_performance'].items():
            logger.info(f"    {cache_name}: {stats['hit_rate']:.1%} hit rate ({stats['total_requests']} requests)")

# =============================================================================
# BENCHMARKING UTILITIES
# =============================================================================

def benchmark_function(func: Callable, iterations: int = 100, *args, **kwargs) -> Dict[str, float]:
    """
    Benchmark a function with multiple iterations.

    Returns timing statistics in milliseconds.
    """
    times = []

    for _ in range(iterations):
        start_time = time.time()
        func(*args, **kwargs)
        times.append((time.time() - start_time) * 1000)  # Convert to ms

    return {
        'min_ms': min(times),
        'max_ms': max(times),
        'avg_ms': sum(times) / len(times),
        'median_ms': sorted(times)[len(times) // 2],
        'total_ms': sum(times),
        'iterations': iterations
    }