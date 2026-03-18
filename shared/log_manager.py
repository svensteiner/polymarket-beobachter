# =============================================================================
# LOG MANAGER - PERFORMANCE & MEMORY OPTIMIZED
# =============================================================================
#
# Centralized log management with:
# - Automatic log rotation by size/age
# - Memory-efficient streaming reads
# - Background compression
# - File I/O optimization
#
# =============================================================================

import json
import logging
import os
import gzip
import time
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Iterator, Any
from collections import deque
import weakref

logger = logging.getLogger(__name__)


class LogManager:
    """
    High-performance log manager with automatic rotation and optimization.

    Features:
    - Size-based rotation (default: 50MB)
    - Age-based rotation (default: 7 days)
    - Background compression of old logs
    - Memory-efficient streaming for large files
    - Write batching for performance
    """

    def __init__(self, base_dir: Path, max_size_mb: int = 50, max_age_days: int = 7):
        self.base_dir = Path(base_dir)
        self.max_size_bytes = max_size_mb * 1024 * 1024
        self.max_age = timedelta(days=max_age_days)
        self.write_buffers: Dict[str, deque] = {}
        self.buffer_locks: Dict[str, threading.Lock] = {}
        self.last_flush = {}
        self.flush_interval = 30  # seconds

        # Background cleanup thread
        self._cleanup_thread = None
        self._shutdown = threading.Event()

        # Weak references to avoid memory leaks
        self._file_handles = weakref.WeakValueDictionary()

    def start_background_tasks(self):
        """Start background cleanup and compression."""
        if self._cleanup_thread is None or not self._cleanup_thread.is_alive():
            self._cleanup_thread = threading.Thread(
                target=self._background_cleanup,
                daemon=True
            )
            self._cleanup_thread.start()

    def stop_background_tasks(self):
        """Stop background tasks and flush buffers."""
        self._shutdown.set()
        if self._cleanup_thread and self._cleanup_thread.is_alive():
            self._cleanup_thread.join(timeout=5.0)
        self._flush_all_buffers()

    def append_jsonl(self, file_path: Path, data: Dict[str, Any],
                    auto_rotate: bool = True) -> None:
        """
        High-performance JSONL append with batching and rotation.

        Args:
            file_path: Target JSONL file
            data: Data to append
            auto_rotate: Whether to check rotation on write
        """
        file_key = str(file_path)

        # Initialize buffer if needed
        if file_key not in self.write_buffers:
            self.write_buffers[file_key] = deque()
            self.buffer_locks[file_key] = threading.Lock()
            self.last_flush[file_key] = time.time()

        # Add to buffer
        with self.buffer_locks[file_key]:
            self.write_buffers[file_key].append(json.dumps(data, ensure_ascii=False))

        # Check if flush needed
        now = time.time()
        if (now - self.last_flush[file_key] > self.flush_interval or
            len(self.write_buffers[file_key]) >= 100):
            self._flush_buffer(file_path)

        # Check rotation if enabled
        if auto_rotate and file_path.exists():
            self._check_rotation(file_path)

    def read_jsonl_stream(self, file_path: Path,
                         max_lines: Optional[int] = None,
                         reverse: bool = False) -> Iterator[Dict[str, Any]]:
        """
        Memory-efficient streaming JSONL reader.

        Args:
            file_path: JSONL file to read
            max_lines: Maximum lines to read (None = all)
            reverse: Read from end (for recent entries)

        Yields:
            Parsed JSON objects
        """
        if not file_path.exists():
            return

        if reverse and max_lines:
            # For reverse + limited reads, use tail-like approach
            yield from self._read_tail_lines(file_path, max_lines)
        else:
            # Forward streaming read
            count = 0
            try:
                with open(file_path, 'r', encoding='utf-8', buffering=8192) as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            yield json.loads(line)
                            count += 1
                            if max_lines and count >= max_lines:
                                break
                        except json.JSONDecodeError as e:
                            logger.warning(f"Invalid JSON in {file_path}: {e}")
                            continue
            except IOError as e:
                logger.error(f"Error reading {file_path}: {e}")

    def _read_tail_lines(self, file_path: Path, max_lines: int) -> Iterator[Dict[str, Any]]:
        """Memory-efficient tail reading for large files."""
        try:
            with open(file_path, 'rb') as f:
                # Seek to end
                f.seek(0, 2)
                file_size = f.tell()

                # Read chunks backwards to find lines
                chunk_size = min(8192, file_size)
                lines = deque(maxlen=max_lines)
                pos = file_size
                buffer = b''

                while pos > 0 and len(lines) < max_lines:
                    # Calculate chunk position
                    chunk_start = max(0, pos - chunk_size)
                    chunk_len = pos - chunk_start

                    # Read chunk
                    f.seek(chunk_start)
                    chunk = f.read(chunk_len)

                    # Process chunk
                    full_data = chunk + buffer
                    parts = full_data.split(b'\n')

                    # Keep incomplete line for next iteration
                    buffer = parts[0] if pos > chunk_len else b''

                    # Process complete lines (in reverse order)
                    for line_bytes in reversed(parts[1:]):
                        if line_bytes.strip():
                            try:
                                line_str = line_bytes.decode('utf-8')
                                obj = json.loads(line_str)
                                lines.appendleft(obj)
                                if len(lines) >= max_lines:
                                    break
                            except (UnicodeDecodeError, json.JSONDecodeError):
                                continue

                    pos = chunk_start

                # Yield in correct order
                yield from lines

        except IOError as e:
            logger.error(f"Error reading tail of {file_path}: {e}")

    def _flush_buffer(self, file_path: Path) -> None:
        """Flush write buffer to disk."""
        file_key = str(file_path)
        if file_key not in self.write_buffers:
            return

        with self.buffer_locks[file_key]:
            buffer = self.write_buffers[file_key]
            if not buffer:
                return

            # Collect all buffered lines
            lines = []
            while buffer:
                lines.append(buffer.popleft())

            self.last_flush[file_key] = time.time()

        if not lines:
            return

        # Write to file
        try:
            file_path.parent.mkdir(parents=True, exist_ok=True)
            with open(file_path, 'a', encoding='utf-8', buffering=8192) as f:
                for line in lines:
                    f.write(line + '\n')
                f.flush()
                os.fsync(f.fileno())  # Ensure data hits disk
        except IOError as e:
            logger.error(f"Error flushing buffer to {file_path}: {e}")
            # Re-add lines to buffer for retry
            with self.buffer_locks[file_key]:
                for line in reversed(lines):
                    self.write_buffers[file_key].appendleft(line)

    def _flush_all_buffers(self) -> None:
        """Flush all write buffers."""
        for file_path_str in list(self.write_buffers.keys()):
            file_path = Path(file_path_str)
            self._flush_buffer(file_path)

    def _check_rotation(self, file_path: Path) -> None:
        """Check if file needs rotation."""
        try:
            stat = file_path.stat()

            # Size-based rotation
            if stat.st_size > self.max_size_bytes:
                self._rotate_file(file_path, 'size')
                return

            # Age-based rotation
            file_age = datetime.now() - datetime.fromtimestamp(stat.st_mtime)
            if file_age > self.max_age:
                self._rotate_file(file_path, 'age')

        except OSError:
            pass  # File might not exist or be accessible

    def _rotate_file(self, file_path: Path, reason: str) -> None:
        """Rotate a log file."""
        # Flush any pending writes first
        self._flush_buffer(file_path)

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        rotated_path = file_path.with_suffix(f'.{timestamp}{file_path.suffix}')

        try:
            file_path.rename(rotated_path)
            logger.info(f"Rotated {file_path.name} -> {rotated_path.name} (reason: {reason})")

            # Schedule compression in background
            threading.Thread(
                target=self._compress_file,
                args=(rotated_path,),
                daemon=True
            ).start()

        except OSError as e:
            logger.error(f"Failed to rotate {file_path}: {e}")

    def _compress_file(self, file_path: Path) -> None:
        """Compress a rotated log file."""
        if not file_path.exists():
            return

        compressed_path = file_path.with_suffix(file_path.suffix + '.gz')

        try:
            with open(file_path, 'rb') as f_in:
                with gzip.open(compressed_path, 'wb', compresslevel=6) as f_out:
                    # Copy in chunks to avoid memory issues
                    while chunk := f_in.read(8192):
                        f_out.write(chunk)

            # Remove original after successful compression
            file_path.unlink()
            logger.info(f"Compressed {file_path.name} -> {compressed_path.name}")

        except (OSError, IOError) as e:
            logger.error(f"Failed to compress {file_path}: {e}")
            # Remove partial compressed file
            compressed_path.unlink(missing_ok=True)

    def _background_cleanup(self) -> None:
        """Background thread for cleanup tasks."""
        while not self._shutdown.wait(300):  # Check every 5 minutes
            try:
                # Flush buffers
                self._flush_all_buffers()

                # Clean up old compressed files
                self._cleanup_old_files()

            except Exception as e:
                logger.error(f"Error in background cleanup: {e}")

    def _cleanup_old_files(self) -> None:
        """Remove very old compressed log files."""
        cutoff = datetime.now() - timedelta(days=30)  # Keep 30 days of compressed logs

        for log_file in self.base_dir.rglob('*.gz'):
            try:
                if datetime.fromtimestamp(log_file.stat().st_mtime) < cutoff:
                    log_file.unlink()
                    logger.debug(f"Cleaned up old compressed log: {log_file}")
            except OSError:
                continue


# Global instance
_log_manager = None


def get_log_manager(base_dir: Optional[Path] = None) -> LogManager:
    """Get global log manager instance."""
    global _log_manager
    if _log_manager is None:
        if base_dir is None:
            base_dir = Path(__file__).parent.parent / "logs"
        _log_manager = LogManager(base_dir)
        _log_manager.start_background_tasks()
    return _log_manager


def shutdown_log_manager():
    """Shutdown global log manager."""
    global _log_manager
    if _log_manager:
        _log_manager.stop_background_tasks()
        _log_manager = None