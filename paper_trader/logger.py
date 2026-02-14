# =============================================================================
# POLYMARKET BEOBACHTER - PAPER TRADING LOGGER
# =============================================================================
#
# GOVERNANCE INTENT:
# This module provides APPEND-ONLY logging for paper trading records.
# All logs are IMMUTABLE - no deletion, no modification.
#
# LOG FORMAT:
# - JSONL (JSON Lines) - one JSON object per line
# - Append-only for audit trail integrity
# - Contains price data (used ONLY in paper logs, NEVER in Layer 1)
#
# FILES:
# - logs/paper_trades.jsonl: All trade actions (ENTER/EXIT/SKIP)
# - logs/paper_positions.jsonl: Position state changes
#
# =============================================================================

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any

_logger = logging.getLogger(__name__)

from paper_trader.models import (
    PaperPosition,
    PaperTradeRecord,
    TradeAction,
)


# =============================================================================
# LOG PATHS
# =============================================================================

PAPER_TRADER_DIR = Path(__file__).parent
LOGS_DIR = PAPER_TRADER_DIR / "logs"
REPORTS_DIR = PAPER_TRADER_DIR / "reports"

TRADES_LOG_PATH = LOGS_DIR / "paper_trades.jsonl"
POSITIONS_LOG_PATH = LOGS_DIR / "paper_positions.jsonl"


# =============================================================================
# PAPER TRADING LOGGER
# =============================================================================


class PaperTradingLogger:
    """
    Append-only logger for paper trading records.

    GOVERNANCE:
    - All writes are APPEND-ONLY
    - No log entry can be deleted
    - No log entry can be modified
    - Log files are JSONL format
    - Price data appears ONLY in these logs

    DATA ISOLATION:
    These logs contain price/P&L data that must NEVER
    be read by Layer 1 (core_analyzer).
    """

    def __init__(
        self,
        logs_dir: Optional[Path] = None,
        reports_dir: Optional[Path] = None
    ):
        """
        Initialize the logger.

        Args:
            logs_dir: Directory for log files
            reports_dir: Directory for report files
        """
        self.logs_dir = logs_dir or LOGS_DIR
        self.reports_dir = reports_dir or REPORTS_DIR

        # Ensure directories exist
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.reports_dir.mkdir(parents=True, exist_ok=True)

        self.trades_log_path = self.logs_dir / "paper_trades.jsonl"
        self.positions_log_path = self.logs_dir / "paper_positions.jsonl"

        # In-memory cache for open positions (FIX K6)
        self._open_positions_cache: Optional[List[PaperPosition]] = None
        self._cache_dirty: bool = True

        # Initialize files with headers
        self._init_files()

    def _init_files(self):
        """Initialize log files with metadata headers."""
        # Trades log
        if not self.trades_log_path.exists():
            header = {
                "_type": "LOG_HEADER",
                "created_at": datetime.now().isoformat(),
                "description": "Append-only paper trade records",
                "format": "JSONL (one JSON object per line)",
                "governance_notice": (
                    "This log contains PAPER trades only. "
                    "No real trades were executed. "
                    "Price data in this log must NEVER be used by Layer 1."
                )
            }
            self._append_json(self.trades_log_path, header)

        # Positions log
        if not self.positions_log_path.exists():
            header = {
                "_type": "LOG_HEADER",
                "created_at": datetime.now().isoformat(),
                "description": "Append-only paper position records",
                "format": "JSONL (one JSON object per line)",
                "governance_notice": (
                    "This log contains PAPER positions only. "
                    "No real funds were allocated. "
                    "Price data in this log must NEVER be used by Layer 1."
                )
            }
            self._append_json(self.positions_log_path, header)

    def _append_json(self, path: Path, data: Dict[str, Any]):
        """Append a JSON object as a single line."""
        with open(path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(data, ensure_ascii=False) + '\n')
            f.flush()
            os.fsync(f.fileno())

    def log_trade(self, record: PaperTradeRecord) -> bool:
        """
        Log a paper trade record.

        GOVERNANCE:
        This is an APPEND-ONLY operation.
        The record cannot be deleted or modified.

        Args:
            record: The trade record to log

        Returns:
            True if logged successfully
        """
        try:
            self._append_json(self.trades_log_path, record.to_dict())
            return True
        except (IOError, OSError, TypeError, ValueError) as e:
            _logger.error(f"Failed to log trade: {e}")
            return False

    def log_position(self, position: PaperPosition) -> bool:
        """
        Log a paper position state.

        GOVERNANCE:
        This is an APPEND-ONLY operation.
        Each position state change creates a new record.

        Args:
            position: The position to log

        Returns:
            True if logged successfully
        """
        try:
            self._append_json(self.positions_log_path, position.to_dict())
            self._cache_dirty = True
            return True
        except (IOError, OSError, TypeError, ValueError) as e:
            _logger.error(f"Failed to log position: {e}")
            return False

    def read_all_trades(self) -> List[PaperTradeRecord]:
        """
        Read all trade records from log.

        GOVERNANCE:
        This is a READ-ONLY operation.

        Returns:
            List of PaperTradeRecord objects
        """
        records = []
        if not self.trades_log_path.exists():
            return records

        try:
            with open(self.trades_log_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                        # Skip header
                        if data.get("_type") == "LOG_HEADER":
                            continue
                        records.append(PaperTradeRecord(
                            record_id=data["record_id"],
                            timestamp=data["timestamp"],
                            proposal_id=data["proposal_id"],
                            market_id=data["market_id"],
                            action=data["action"],
                            reason=data["reason"],
                            position_id=data.get("position_id"),
                            snapshot_time=data.get("snapshot_time"),
                            entry_price=data.get("entry_price"),
                            exit_price=data.get("exit_price"),
                            slippage_applied=data.get("slippage_applied"),
                            pnl_eur=data.get("pnl_eur"),
                        ))
                    except (json.JSONDecodeError, KeyError):
                        continue
        except (IOError, OSError) as e:
            _logger.error(f"Failed to read trades: {e}")

        return records

    def read_all_positions(self) -> List[PaperPosition]:
        """
        Read all position records from log.

        GOVERNANCE:
        This is a READ-ONLY operation.

        Returns:
            List of PaperPosition objects
        """
        positions = []
        if not self.positions_log_path.exists():
            return positions

        try:
            with open(self.positions_log_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                        # Skip header
                        if data.get("_type") == "LOG_HEADER":
                            continue
                        positions.append(PaperPosition.from_dict(data))
                    except (json.JSONDecodeError, KeyError):
                        continue
        except (IOError, OSError) as e:
            _logger.error(f"Failed to read positions: {e}")

        return positions

    def get_open_positions(self) -> List[PaperPosition]:
        """
        Get all currently open positions.

        Uses an in-memory cache with a dirty-flag to avoid re-reading
        the entire JSONL file on every call (FIX K6).

        Returns:
            List of OPEN PaperPosition objects
        """
        if not self._cache_dirty and self._open_positions_cache is not None:
            return self._open_positions_cache

        all_positions = self.read_all_positions()

        # Build latest state for each position
        position_states: Dict[str, PaperPosition] = {}
        for pos in all_positions:
            position_states[pos.position_id] = pos

        # Filter to open only
        self._open_positions_cache = [p for p in position_states.values() if p.status == "OPEN"]
        self._cache_dirty = False
        return self._open_positions_cache

    def get_executed_proposal_ids(self) -> set:
        """
        Get set of proposal IDs that have been paper-executed.

        Used for idempotency - to avoid re-executing the same proposal.

        Returns:
            Set of proposal_id strings
        """
        trades = self.read_all_trades()
        return {
            t.proposal_id for t in trades
            if t.action == TradeAction.PAPER_ENTER.value
        }

    def get_statistics(self) -> Dict[str, Any]:
        """
        Get paper trading statistics.

        Returns:
            Dictionary of statistics
        """
        trades = self.read_all_trades()
        positions = self.read_all_positions()

        # Count by action
        enter_count = sum(1 for t in trades if t.action == TradeAction.PAPER_ENTER.value)
        exit_count = sum(1 for t in trades if t.action == TradeAction.PAPER_EXIT.value)
        skip_count = sum(1 for t in trades if t.action == TradeAction.SKIP.value)

        # Get latest position states
        position_states: Dict[str, PaperPosition] = {}
        for pos in positions:
            position_states[pos.position_id] = pos

        open_count = sum(1 for p in position_states.values() if p.status == "OPEN")
        closed_count = sum(1 for p in position_states.values() if p.status in ["CLOSED", "RESOLVED"])

        # Calculate P&L
        total_pnl = 0.0
        pnl_count = 0
        for p in position_states.values():
            if p.realized_pnl_eur is not None:
                total_pnl += p.realized_pnl_eur
                pnl_count += 1

        return {
            "total_trades": len(trades),
            "paper_enters": enter_count,
            "paper_exits": exit_count,
            "skips": skip_count,
            "open_positions": open_count,
            "closed_positions": closed_count,
            "total_realized_pnl_eur": total_pnl,
            "positions_with_pnl": pnl_count,
        }


# =============================================================================
# MODULE-LEVEL LOGGER
# =============================================================================

_paper_logger: Optional[PaperTradingLogger] = None


def get_paper_logger() -> PaperTradingLogger:
    """Get the global paper trading logger instance."""
    global _paper_logger
    if _paper_logger is None:
        _paper_logger = PaperTradingLogger()
    return _paper_logger


def log_trade(record: PaperTradeRecord) -> bool:
    """Convenience function to log a trade."""
    return get_paper_logger().log_trade(record)


def log_position(position: PaperPosition) -> bool:
    """Convenience function to log a position."""
    return get_paper_logger().log_position(position)
