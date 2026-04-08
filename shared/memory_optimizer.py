# =============================================================================
# MEMORY OPTIMIZER - RESOURCE MANAGEMENT & GARBAGE COLLECTION
# =============================================================================
#
# Proactive memory management for the weather betting system:
# - Memory leak detection
# - Object lifecycle tracking
# - Garbage collection optimization
# - Resource cleanup
#
# =============================================================================

import gc
import logging
import psutil
import threading
import time
import weakref
from datetime import datetime
from typing import Dict, List, Any, Set
from collections import defaultdict, deque

logger = logging.getLogger(__name__)


class MemoryMonitor:
    """
    Proactive memory monitoring and optimization.

    Features:
    - Real-time memory usage tracking
    - Leak detection via object counting
    - Automatic garbage collection triggers
    - Memory pressure response
    """

    def __init__(self, check_interval: int = 60, max_memory_mb: int = 1024):
        self.check_interval = check_interval
        self.max_memory_mb = max_memory_mb
        self.max_memory_bytes = max_memory_mb * 1024 * 1024

        # Monitoring state
        self._monitoring = False
        self._monitor_thread = None
        self._shutdown = threading.Event()

        # Memory tracking
        self.memory_history = deque(maxlen=60)  # Last hour of samples
        self.peak_memory = 0
        self.gc_count_history = deque(maxlen=20)

        # Object tracking for leak detection
        self.object_counters = defaultdict(int)
        self.tracked_objects: Set[Any] = weakref.WeakSet()

        # Performance metrics
        self.gc_stats = {
            'forced_collections': 0,
            'memory_freed_mb': 0.0,
            'last_collection': None
        }

        # Memory pressure thresholds
        self.pressure_thresholds = {
            'low': 0.7,      # 70% of max memory
            'medium': 0.85,  # 85% of max memory
            'high': 0.95     # 95% of max memory
        }

    def start_monitoring(self):
        """Start background memory monitoring."""
        if self._monitoring:
            return

        self._monitoring = True
        self._shutdown.clear()

        self._monitor_thread = threading.Thread(
            target=self._monitoring_loop,
            daemon=True,
            name="MemoryMonitor"
        )
        self._monitor_thread.start()
        logger.info("Memory monitoring started")

    def stop_monitoring(self):
        """Stop background monitoring."""
        if not self._monitoring:
            return

        self._monitoring = False
        self._shutdown.set()

        if self._monitor_thread and self._monitor_thread.is_alive():
            self._monitor_thread.join(timeout=5.0)

        logger.info("Memory monitoring stopped")

    def get_memory_stats(self) -> Dict[str, Any]:
        """Get current memory statistics."""
        process = psutil.Process()
        memory_info = process.memory_info()

        # Current usage
        current_mb = memory_info.rss / (1024 * 1024)
        pressure = current_mb / self.max_memory_mb

        # GC stats
        gc_counts = gc.get_count()

        return {
            'current_mb': round(current_mb, 1),
            'peak_mb': round(self.peak_memory / (1024 * 1024), 1),
            'pressure_ratio': round(pressure, 3),
            'pressure_level': self._get_pressure_level(pressure),
            'gc_counts': gc_counts,
            'gc_stats': self.gc_stats.copy(),
            'object_counts': dict(self.object_counters),
            'tracked_objects': len(self.tracked_objects)
        }

    def force_garbage_collection(self) -> Dict[str, Any]:
        """Force garbage collection and return results."""
        start_time = time.time()

        # Get memory before
        process = psutil.Process()
        memory_before = process.memory_info().rss

        # Force collection
        collected = gc.collect()

        # Get memory after
        memory_after = process.memory_info().rss
        memory_freed = max(0, memory_before - memory_after)

        duration = time.time() - start_time

        # Update stats
        self.gc_stats['forced_collections'] += 1
        self.gc_stats['memory_freed_mb'] += memory_freed / (1024 * 1024)
        self.gc_stats['last_collection'] = datetime.now().isoformat()

        result = {
            'objects_collected': collected,
            'memory_freed_mb': round(memory_freed / (1024 * 1024), 2),
            'duration_ms': round(duration * 1000, 1),
            'memory_before_mb': round(memory_before / (1024 * 1024), 1),
            'memory_after_mb': round(memory_after / (1024 * 1024), 1)
        }

        logger.info(f"Forced GC: {collected} objects, {result['memory_freed_mb']} MB freed")
        return result

    def track_object(self, obj: Any, category: str = "unknown") -> None:
        """Track an object for leak detection."""
        self.tracked_objects.add(obj)
        self.object_counters[category] += 1

    def untrack_object(self, obj: Any, category: str = "unknown") -> None:
        """Remove object from tracking."""
        try:
            self.tracked_objects.remove(obj)
            self.object_counters[category] = max(0, self.object_counters[category] - 1)
        except KeyError:
            pass  # Object wasn't tracked

    def detect_memory_leaks(self) -> List[Dict[str, Any]]:
        """Detect potential memory leaks."""
        leaks = []

        # Check for rapidly growing object types
        if len(self.memory_history) >= 10:
            recent_growth = (self.memory_history[-1]['memory_mb'] -
                           self.memory_history[-10]['memory_mb'])

            if recent_growth > 50:  # 50MB growth in 10 samples
                leaks.append({
                    'type': 'rapid_growth',
                    'growth_mb': round(recent_growth, 1),
                    'description': f"Memory grew by {recent_growth:.1f}MB in last 10 samples"
                })

        # Check for object count anomalies
        for category, count in self.object_counters.items():
            if count > 1000:  # Arbitrary threshold
                leaks.append({
                    'type': 'object_accumulation',
                    'category': category,
                    'count': count,
                    'description': f"High object count for {category}: {count}"
                })

        # Check GC efficiency
        gc_counts = gc.get_count()
        if gc_counts[0] > 500:  # Generation 0 collection threshold
            leaks.append({
                'type': 'gc_pressure',
                'gen0_count': gc_counts[0],
                'description': "High garbage collection pressure"
            })

        return leaks

    def _monitoring_loop(self):
        """Main monitoring loop."""
        while self._monitoring and not self._shutdown.wait(self.check_interval):
            try:
                self._check_memory()
            except Exception as e:
                logger.error(f"Error in memory monitoring: {e}")

    def _check_memory(self):
        """Perform memory check and take action if needed."""
        process = psutil.Process()
        memory_info = process.memory_info()
        current_memory = memory_info.rss

        # Update peak
        if current_memory > self.peak_memory:
            self.peak_memory = current_memory

        # Record sample
        sample = {
            'timestamp': datetime.now().isoformat(),
            'memory_mb': current_memory / (1024 * 1024),
            'gc_counts': gc.get_count()
        }
        self.memory_history.append(sample)

        # Check pressure and respond
        pressure = current_memory / self.max_memory_bytes
        pressure_level = self._get_pressure_level(pressure)

        if pressure_level == 'high':
            logger.warning(f"High memory pressure: {pressure:.1%} of limit")
            self._respond_to_pressure('high')
        elif pressure_level == 'medium':
            logger.info(f"Medium memory pressure: {pressure:.1%} of limit")
            self._respond_to_pressure('medium')

    def _get_pressure_level(self, pressure_ratio: float) -> str:
        """Get pressure level from ratio."""
        if pressure_ratio >= self.pressure_thresholds['high']:
            return 'high'
        elif pressure_ratio >= self.pressure_thresholds['medium']:
            return 'medium'
        elif pressure_ratio >= self.pressure_thresholds['low']:
            return 'low'
        else:
            return 'normal'

    def _respond_to_pressure(self, level: str):
        """Respond to memory pressure."""
        if level == 'high':
            # Aggressive response
            logger.warning("Forcing garbage collection due to high memory pressure")
            self.force_garbage_collection()

            # Clear caches if available
            if hasattr(gc, 'set_debug'):
                gc.set_debug(0)  # Disable GC debugging to save memory

        elif level == 'medium':
            # Moderate response
            logger.info("Triggering garbage collection due to medium memory pressure")
            gc.collect()


class ObjectPool:
    """
    Object pool for frequently created/destroyed objects.
    Reduces GC pressure by reusing objects.
    """

    def __init__(self, factory_func, max_size: int = 100):
        self.factory_func = factory_func
        self.max_size = max_size
        self.pool = deque()
        self.lock = threading.Lock()
        self.created_count = 0
        self.reused_count = 0

    def acquire(self):
        """Get an object from the pool."""
        with self.lock:
            if self.pool:
                self.reused_count += 1
                return self.pool.popleft()
            else:
                self.created_count += 1
                return self.factory_func()

    def release(self, obj):
        """Return an object to the pool."""
        with self.lock:
            if len(self.pool) < self.max_size:
                # Reset object state if it has a reset method
                if hasattr(obj, 'reset'):
                    obj.reset()
                self.pool.append(obj)

    def get_stats(self) -> Dict[str, int]:
        """Get pool statistics."""
        with self.lock:
            return {
                'pool_size': len(self.pool),
                'max_size': self.max_size,
                'created_count': self.created_count,
                'reused_count': self.reused_count,
                'efficiency_pct': round(
                    (self.reused_count / max(1, self.created_count + self.reused_count)) * 100, 1
                )
            }


# Global memory monitor instance
_memory_monitor = None


def get_memory_monitor() -> MemoryMonitor:
    """Get global memory monitor instance."""
    global _memory_monitor
    if _memory_monitor is None:
        _memory_monitor = MemoryMonitor()
    return _memory_monitor


def start_memory_monitoring():
    """Start global memory monitoring."""
    monitor = get_memory_monitor()
    monitor.start_monitoring()


def stop_memory_monitoring():
    """Stop global memory monitoring."""
    global _memory_monitor
    if _memory_monitor:
        _memory_monitor.stop_monitoring()


def get_memory_report() -> Dict[str, Any]:
    """Get comprehensive memory report."""
    monitor = get_memory_monitor()
    stats = monitor.get_memory_stats()

    # Add system info
    stats['system'] = {
        'total_memory_gb': round(psutil.virtual_memory().total / (1024**3), 1),
        'available_memory_gb': round(psutil.virtual_memory().available / (1024**3), 1),
        'cpu_count': psutil.cpu_count()
    }

    # Add leak detection
    stats['potential_leaks'] = monitor.detect_memory_leaks()

    return stats