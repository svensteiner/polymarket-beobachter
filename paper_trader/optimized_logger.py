# =============================================================================
# OPTIMIZED PAPER TRADER LOGGER
# =============================================================================
#
# Resource-optimized logging for paper trading operations:
# - Batch writes for performance
# - Memory-efficient position loading
# - Automatic log rotation
# - Background compression
#
# =============================================================================

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any, Iterator
from dataclasses import asdict

# Import optimized log manager
try:
    from shared.log_manager import get_log_manager
    HAS_LOG_MANAGER = True
except ImportError:
    HAS_LOG_MANAGER = False

logger = logging.getLogger(__name__)


class OptimizedPositionLogger:
    """
    Resource-optimized position logger using the shared log manager.

    Features:
    - Batched writes for better I/O performance
    - Memory-efficient position loading
    - Automatic rotation for large logs
    - Background compression
    """

    def __init__(self, log_file: Path):
        self.log_file = Path(log_file)
        self.log_file.parent.mkdir(parents=True, exist_ok=True)

        # Use optimized log manager if available
        if HAS_LOG_MANAGER:
            self.log_manager = get_log_manager(self.log_file.parent)
        else:
            self.log_manager = None
            logger.warning("Optimized log manager not available, using fallback")

        # Write header if file doesn't exist
        if not self.log_file.exists():
            self._write_header()

    def _write_header(self):
        """Write JSONL header."""
        header = {
            "_type": "LOG_HEADER",
            "created_at": datetime.now().isoformat(),
            "description": "Optimized paper position records with batching",
            "format": "JSONL (one JSON object per line)",
            "governance_notice": "This log contains PAPER positions only. No real funds were allocated."
        }
        self._write_entry(header)

    def _write_entry(self, data: Dict[str, Any]):
        """Write a single entry to log."""
        if self.log_manager:
            # Use optimized log manager with batching
            self.log_manager.append_jsonl(self.log_file, data, auto_rotate=True)
        else:
            # Fallback to direct file writing
            try:
                with open(self.log_file, 'a', encoding='utf-8') as f:
                    f.write(json.dumps(data, ensure_ascii=False) + '\n')
                    f.flush()
            except IOError as e:
                logger.error(f"Failed to write to {self.log_file}: {e}")

    def log_position_entry(self, position_data: Dict[str, Any]):
        """Log a new position entry."""
        # Add timestamp if not present
        if 'entry_time' not in position_data:
            position_data['entry_time'] = datetime.now().isoformat()

        # Add governance notice
        position_data['governance_notice'] = "This is a PAPER position. No real funds were used."

        self._write_entry(position_data)

    def log_position_update(self, position_id: str, update_data: Dict[str, Any]):
        """Log a position update/exit."""
        update_entry = {
            'position_id': position_id,
            'update_time': datetime.now().isoformat(),
            'update_type': update_data.get('status', 'UPDATE'),
            **update_data
        }
        self._write_entry(update_entry)

    def get_recent_positions(self, max_positions: int = 50,
                           status_filter: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Get recent positions efficiently.

        Args:
            max_positions: Maximum number of positions to return
            status_filter: Filter by position status (e.g., 'OPEN', 'CLOSED')

        Returns:
            List of position dictionaries
        """
        if self.log_manager:
            # Use optimized streaming reader
            return self._get_positions_optimized(max_positions, status_filter)
        else:
            # Fallback to direct file reading
            return self._get_positions_fallback(max_positions, status_filter)

    def _get_positions_optimized(self, max_positions: int,
                               status_filter: Optional[str]) -> List[Dict[str, Any]]:
        """Get positions using optimized log manager."""
        positions = []
        seen_ids = set()

        # Read recent entries in reverse order
        for entry in self.log_manager.read_jsonl_stream(
            self.log_file,
            max_lines=max_positions * 3,  # Read more to account for updates
            reverse=True
        ):
            # Skip header entries
            if entry.get('_type') == 'LOG_HEADER':
                continue

            position_id = entry.get('position_id')
            if not position_id or position_id in seen_ids:
                continue

            # Apply status filter
            if status_filter and entry.get('status') != status_filter:
                continue

            positions.append(entry)
            seen_ids.add(position_id)

            if len(positions) >= max_positions:
                break

        return positions

    def _get_positions_fallback(self, max_positions: int,
                              status_filter: Optional[str]) -> List[Dict[str, Any]]:
        """Fallback method for getting positions."""
        positions = []
        seen_ids = set()

        try:
            # Read file in reverse (approximate)
            with open(self.log_file, 'r', encoding='utf-8') as f:
                lines = f.readlines()

            # Process from end backwards
            for line in reversed(lines[-max_positions * 3:]):
                line = line.strip()
                if not line:
                    continue

                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue

                # Skip header entries
                if entry.get('_type') == 'LOG_HEADER':
                    continue

                position_id = entry.get('position_id')
                if not position_id or position_id in seen_ids:
                    continue

                # Apply status filter
                if status_filter and entry.get('status') != status_filter:
                    continue

                positions.append(entry)
                seen_ids.add(position_id)

                if len(positions) >= max_positions:
                    break

            return positions

        except (IOError, OSError) as e:
            logger.error(f"Error reading positions from {self.log_file}: {e}")
            return []

    def get_position_by_id(self, position_id: str) -> Optional[Dict[str, Any]]:
        """Get a specific position by ID."""
        if self.log_manager:
            # Use streaming reader
            for entry in self.log_manager.read_jsonl_stream(self.log_file):
                if entry.get('position_id') == position_id:
                    return entry
        else:
            # Fallback method
            try:
                with open(self.log_file, 'r', encoding='utf-8') as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            entry = json.loads(line)
                            if entry.get('position_id') == position_id:
                                return entry
                        except json.JSONDecodeError:
                            continue
            except (IOError, OSError):
                pass

        return None

    def count_positions_by_status(self) -> Dict[str, int]:
        """Count positions by status efficiently."""
        status_counts = {}

        if self.log_manager:
            # Use streaming reader
            for entry in self.log_manager.read_jsonl_stream(self.log_file):
                if entry.get('_type') == 'LOG_HEADER':
                    continue

                status = entry.get('status', 'UNKNOWN')
                status_counts[status] = status_counts.get(status, 0) + 1
        else:
            # Fallback method with limited memory usage
            try:
                with open(self.log_file, 'r', encoding='utf-8') as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            entry = json.loads(line)
                            if entry.get('_type') == 'LOG_HEADER':
                                continue

                            status = entry.get('status', 'UNKNOWN')
                            status_counts[status] = status_counts.get(status, 0) + 1
                        except json.JSONDecodeError:
                            continue
            except (IOError, OSError) as e:
                logger.error(f"Error counting positions: {e}")

        return status_counts

    def get_performance_stats(self) -> Dict[str, Any]:
        """Get performance statistics."""
        stats = {
            'total_positions': 0,
            'open_positions': 0,
            'closed_positions': 0,
            'total_pnl_eur': 0.0,
            'win_rate': 0.0,
            'file_size_mb': 0.0
        }

        # File size
        if self.log_file.exists():
            stats['file_size_mb'] = round(self.log_file.stat().st_size / (1024 * 1024), 2)

        # Position stats
        status_counts = self.count_positions_by_status()
        stats['total_positions'] = sum(status_counts.values())
        stats['open_positions'] = status_counts.get('OPEN', 0)
        stats['closed_positions'] = (stats['total_positions'] -
                                   stats['open_positions'] -
                                   status_counts.get('UNKNOWN', 0))

        # Calculate PnL and win rate from recent closed positions
        closed_positions = self.get_recent_positions(
            max_positions=100,
            status_filter='CLOSED'
        )

        if closed_positions:
            total_pnl = sum(pos.get('realized_pnl_eur', 0) for pos in closed_positions)
            wins = sum(1 for pos in closed_positions if pos.get('realized_pnl_eur', 0) > 0)

            stats['total_pnl_eur'] = round(total_pnl, 2)
            stats['win_rate'] = round((wins / len(closed_positions)) * 100, 1)

        return stats


# Global instances for different log types
_position_logger = None
_trade_logger = None


def get_position_logger(log_file: Optional[Path] = None) -> OptimizedPositionLogger:
    """Get global position logger instance."""
    global _position_logger
    if _position_logger is None:
        if log_file is None:
            log_file = Path(__file__).parent / "logs" / "paper_positions.jsonl"
        _position_logger = OptimizedPositionLogger(log_file)
    return _position_logger


def get_trade_logger(log_file: Optional[Path] = None) -> OptimizedPositionLogger:
    """Get global trade logger instance."""
    global _trade_logger
    if _trade_logger is None:
        if log_file is None:
            log_file = Path(__file__).parent / "logs" / "paper_trades.jsonl"
        _trade_logger = OptimizedPositionLogger(log_file)
    return _trade_logger