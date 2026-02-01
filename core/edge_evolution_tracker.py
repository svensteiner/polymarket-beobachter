# =============================================================================
# POLYMARKET BEOBACHTER - EDGE EVOLUTION TRACKER
# =============================================================================
#
# GOVERNANCE-FIRST ANALYTICS MODULE
#
# PURPOSE:
# Measure how the EDGE of a position evolves AFTER entry.
# This module is READ-ONLY with respect to trading.
# It NEVER triggers sells, buys, parameter changes, or signals.
#
# ABSOLUTE NON-NEGOTIABLE RULES (FAIL CLOSED):
# 1. No interaction with execution or decision logic
# 2. No order placement, no exit signals
# 3. Append-only storage: never overwrite historical data
# 4. Edge is MEASURED, not acted upon
# 5. If data is missing or inconsistent -> write NOTHING
# 6. Tracker must be removable without affecting trading behavior
#
# ISOLATION GUARANTEES:
# - NO imports from decision_engine
# - NO imports from execution_engine
# - NO imports from panic modules
# - NO imports from learning modules
#
# WHAT THIS MODULE DOES (AND ONLY THIS):
# For each OPEN position:
# - Periodically sample the current market probability
# - Compare it to the FAIR PROBABILITY AT ENTRY
# - Persist a time-series snapshot of edge evolution
#
# MENTAL MODEL:
# This module answers ONE question only:
# "How long was our advantage real?"
#
# If someone tries to use this for selling decisions,
# the design has failed.
#
# =============================================================================

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

# =============================================================================
# SAFETY: Forbidden imports declaration
# =============================================================================
# This module MUST NOT import from these modules:
# - decision_engine
# - execution_engine
# - panic_contrarian_engine
# - Any learning/training modules
#
# This is enforced by static analysis in tests.
# The following list defines forbidden modules for safety verification.

_FORBIDDEN_MODULES = frozenset([
    "core.decision_engine",
    "core.execution_engine",
    "core.panic_contrarian_engine",
    "execution.adapter",
])


def check_import_safety() -> bool:
    """
    Check that this module does not import forbidden modules.

    This performs a static analysis of the module's imports.
    It is used by tests to verify governance compliance.

    Returns:
        True if safe, raises ImportError if violation detected
    """
    import ast
    import inspect

    # Get source file of this module
    source_file = Path(__file__)
    source_code = source_file.read_text(encoding="utf-8")

    # Parse the AST
    tree = ast.parse(source_code)

    # Collect all import statements
    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.add(node.module)

    # Check for forbidden imports
    for forbidden in _FORBIDDEN_MODULES:
        for imp in imports:
            if imp == forbidden or imp.startswith(forbidden + "."):
                raise ImportError(
                    f"SAFETY VIOLATION: {__file__} imports {imp} "
                    f"which is forbidden. This module MUST NOT interact "
                    f"with execution or decision logic."
                )

    return True

# =============================================================================
# Safe imports
# =============================================================================

# Add project root to path for imports
BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR))

from core.edge_snapshot import (
    EdgeSnapshot,
    SCHEMA_VERSION,
    EDGE_EVOLUTION_DIR,
    EDGE_SNAPSHOTS_FILE,
    compute_hash,
    generate_snapshot_id,
    get_utc_timestamp,
    get_minute_bucket,
    create_edge_snapshot,
    calculate_time_since_entry_minutes,
)

# Paper trader imports for READ-ONLY position access
from paper_trader.position_manager import get_open_positions
from paper_trader.models import PaperPosition
from paper_trader.snapshot_client import get_market_snapshot, MarketSnapshotClient

logger = logging.getLogger(__name__)


# =============================================================================
# STORAGE CLASS
# =============================================================================


class EdgeEvolutionStorage:
    """
    Append-only storage for edge evolution snapshots.

    GUARANTEES:
    - Records are only appended, never modified
    - Each write includes a SHA256 hash for integrity
    - Atomic writes (write line + newline together)
    - Deduplication prevents duplicate records for same position/minute
    """

    def __init__(self, base_dir: Optional[Path] = None):
        """
        Initialize storage.

        Args:
            base_dir: Base directory for the project. Defaults to module parent.
        """
        if base_dir is None:
            base_dir = Path(__file__).parent.parent

        self.base_dir = Path(base_dir)
        self.edge_dir = self.base_dir / EDGE_EVOLUTION_DIR
        self.snapshots_file = self.edge_dir / EDGE_SNAPSHOTS_FILE

        # Ensure directory exists
        self.edge_dir.mkdir(parents=True, exist_ok=True)

        # Cache for deduplication: set of (position_id, minute_bucket)
        self._snapshot_keys: Optional[Set[str]] = None

    def _ensure_cache_loaded(self):
        """Load cache from files if not already loaded."""
        if self._snapshot_keys is None:
            self._snapshot_keys = set()

            # Load existing snapshots for dedup
            for snapshot in self.read_snapshots():
                key = self._snapshot_dedup_key(snapshot)
                self._snapshot_keys.add(key)

    def _snapshot_dedup_key(self, snapshot: EdgeSnapshot) -> str:
        """
        Generate deduplication key for a snapshot.

        Key components:
        - position_id
        - minute bucket of timestamp

        This prevents multiple snapshots for the same position
        within the same minute.
        """
        minute_bucket = get_minute_bucket(snapshot.timestamp_utc)
        return f"{snapshot.position_id}|{minute_bucket}"

    def _write_record(self, data: Dict[str, Any]) -> bool:
        """
        Write a single record to the JSONL file atomically.

        Returns True if successful, False otherwise.
        """
        try:
            line = json.dumps(data, separators=(",", ":")) + "\n"
            with open(self.snapshots_file, "a", encoding="utf-8") as f:
                f.write(line)
            return True
        except Exception as e:
            logger.error(f"Failed to write snapshot to {self.snapshots_file}: {e}")
            return False

    def write_snapshot(self, snapshot: EdgeSnapshot) -> Tuple[bool, str]:
        """
        Write an edge snapshot.

        Returns:
            Tuple of (success, message)

        DEDUPLICATION:
        If a snapshot for the same position_id and minute bucket
        already exists, the write is skipped.
        """
        self._ensure_cache_loaded()

        # Check for duplicate
        key = self._snapshot_dedup_key(snapshot)
        if key in self._snapshot_keys:
            return False, f"Duplicate snapshot skipped: {snapshot.position_id}"

        # Convert to dict (hash should already be computed)
        data = snapshot.to_dict()

        # Write atomically
        if self._write_record(data):
            self._snapshot_keys.add(key)
            logger.debug(f"Snapshot recorded: {snapshot.position_id} | edge={snapshot.edge_relative:.4f}")
            return True, f"Snapshot recorded: {snapshot.position_id}"
        else:
            return False, f"Failed to write snapshot: {snapshot.position_id}"

    def read_snapshots(self) -> List[EdgeSnapshot]:
        """Read all edge snapshots from the file."""
        snapshots = []
        if not self.snapshots_file.exists():
            return snapshots

        try:
            with open(self.snapshots_file, "r", encoding="utf-8") as f:
                for line_num, line in enumerate(f, 1):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                        # Skip header if present
                        if data.get("_type") == "LOG_HEADER":
                            continue
                        snapshot = EdgeSnapshot.from_dict(data)
                        snapshots.append(snapshot)
                    except (json.JSONDecodeError, ValueError) as e:
                        logger.warning(f"Invalid snapshot at line {line_num}: {e}")
        except Exception as e:
            logger.error(f"Error reading snapshots: {e}")

        return snapshots

    def get_snapshots_by_position(self, position_id: str) -> List[EdgeSnapshot]:
        """Get all snapshots for a specific position."""
        return [s for s in self.read_snapshots() if s.position_id == position_id]

    def get_stats(self) -> Dict[str, Any]:
        """
        Get storage statistics.

        Returns:
            Dict with counts and summaries
        """
        snapshots = self.read_snapshots()

        # Count by position
        positions = {}
        for s in snapshots:
            if s.position_id not in positions:
                positions[s.position_id] = {
                    "count": 0,
                    "market_id": s.market_id,
                    "first_snapshot": s.timestamp_utc,
                    "last_snapshot": s.timestamp_utc,
                    "min_edge": s.edge_relative,
                    "max_edge": s.edge_relative,
                }
            pos = positions[s.position_id]
            pos["count"] += 1
            if s.timestamp_utc > pos["last_snapshot"]:
                pos["last_snapshot"] = s.timestamp_utc
            if s.timestamp_utc < pos["first_snapshot"]:
                pos["first_snapshot"] = s.timestamp_utc
            if s.edge_relative < pos["min_edge"]:
                pos["min_edge"] = s.edge_relative
            if s.edge_relative > pos["max_edge"]:
                pos["max_edge"] = s.edge_relative

        return {
            "total_snapshots": len(snapshots),
            "unique_positions": len(positions),
            "positions": positions,
        }


# =============================================================================
# EDGE EVOLUTION TRACKER
# =============================================================================


class EdgeEvolutionTracker:
    """
    Tracks edge evolution for open positions.

    GOVERNANCE:
    - READ-ONLY regarding positions and market data
    - APPEND-ONLY regarding storage
    - NO exit signals, NO trading actions
    - FAIL-CLOSED: missing data = no write

    This module answers ONE question:
    "How long was our advantage real?"

    It is NOT an exit signal generator.
    """

    def __init__(self, base_dir: Optional[Path] = None):
        """
        Initialize the tracker.

        Args:
            base_dir: Base directory for the project
        """
        self.base_dir = base_dir or BASE_DIR
        self.storage = EdgeEvolutionStorage(self.base_dir)
        self._snapshot_client = MarketSnapshotClient()

    def run(self, source: str = "scheduler") -> Dict[str, Any]:
        """
        Run a snapshot cycle for all open positions.

        GOVERNANCE:
        - This is a READ-ONLY operation regarding positions
        - This APPENDS to storage (never overwrites)
        - If any data is missing, that position is SKIPPED

        NO return value is used for trading decisions.
        The return is for logging/monitoring only.

        Args:
            source: Source of the snapshot (scheduler, cli, manual)

        Returns:
            Summary dict with counts (for logging only)
        """
        logger.info("EdgeEvolutionTracker.run() starting")

        # Get open positions (READ-ONLY)
        try:
            open_positions = get_open_positions()
        except Exception as e:
            logger.error(f"Failed to get open positions: {e}")
            return {
                "success": False,
                "error": str(e),
                "positions_checked": 0,
                "snapshots_written": 0,
            }

        if not open_positions:
            logger.info("No open positions to track")
            return {
                "success": True,
                "positions_checked": 0,
                "snapshots_written": 0,
                "skipped": 0,
                "errors": 0,
            }

        logger.info(f"Found {len(open_positions)} open positions")

        # Process each position
        snapshots_written = 0
        skipped = 0
        errors = 0

        for position in open_positions:
            try:
                result = self._process_position(position, source)
                if result == "written":
                    snapshots_written += 1
                elif result == "skipped":
                    skipped += 1
                else:
                    errors += 1
            except Exception as e:
                logger.error(f"Error processing position {position.position_id}: {e}")
                errors += 1

        summary = {
            "success": True,
            "positions_checked": len(open_positions),
            "snapshots_written": snapshots_written,
            "skipped": skipped,
            "errors": errors,
        }

        logger.info(
            f"EdgeEvolutionTracker.run() complete: "
            f"{snapshots_written} written, {skipped} skipped, {errors} errors"
        )

        return summary

    def _process_position(self, position: PaperPosition, source: str) -> str:
        """
        Process a single position.

        FAIL-CLOSED: Any missing data results in no write.

        Args:
            position: The position to process
            source: Source of the snapshot

        Returns:
            "written", "skipped", or "error"
        """
        # =================================================================
        # FAIL-CLOSED: Validate all required data exists
        # =================================================================

        # 1. Position must have required fields
        if not position.position_id:
            logger.warning("Position missing position_id - skipping")
            return "error"

        if not position.market_id:
            logger.warning(f"Position {position.position_id} missing market_id - skipping")
            return "error"

        if not position.entry_price:
            logger.warning(f"Position {position.position_id} missing entry_price - skipping")
            return "error"

        if not position.entry_time:
            logger.warning(f"Position {position.position_id} missing entry_time - skipping")
            return "error"

        # 2. Get current market snapshot (READ-ONLY)
        snapshot = get_market_snapshot(position.market_id)

        if snapshot is None:
            logger.warning(f"Could not get market snapshot for {position.market_id} - skipping")
            return "error"

        if snapshot.mid_price is None:
            logger.warning(f"Market snapshot for {position.market_id} has no mid_price - skipping")
            return "error"

        # 3. Extract values for edge calculation
        market_probability_current = snapshot.mid_price

        # Entry price is the market price at entry
        market_probability_entry = position.entry_price

        # Fair probability at entry - we derive this from the entry edge
        # For paper positions, we assume we entered because we had an edge
        # The fair probability is what we believed the true probability was
        #
        # GOVERNANCE NOTE:
        # In a real system, this would be stored in the position record.
        # For now, we estimate it based on a typical edge threshold.
        # This is conservative - actual edge may have been larger.
        #
        # For a YES position: we thought fair > market, so fair = market + edge
        # For a NO position: we thought fair < market, so fair = market - edge
        #
        # We'll use the cost basis to infer the direction
        # and a minimum edge threshold of 15pp (from decision_engine thresholds)
        EDGE_THRESHOLD = 0.15  # 15 percentage points

        if position.side == "YES":
            # We bought YES because we thought it was undervalued
            # Fair probability was higher than market
            fair_probability_entry = min(market_probability_entry + EDGE_THRESHOLD, 1.0)
        else:
            # We bought NO because we thought YES was overvalued
            # Fair probability of YES was lower than market
            fair_probability_entry = max(market_probability_entry - EDGE_THRESHOLD, 0.0)

        # 4. Calculate time since entry
        time_since_entry = calculate_time_since_entry_minutes(position.entry_time)

        # 5. Validate all calculated values
        if market_probability_current <= 0 or market_probability_current > 1:
            logger.warning(f"Invalid current probability {market_probability_current} - skipping")
            return "error"

        if market_probability_entry <= 0 or market_probability_entry > 1:
            logger.warning(f"Invalid entry probability {market_probability_entry} - skipping")
            return "error"

        # =================================================================
        # Create and write snapshot
        # =================================================================

        try:
            edge_snapshot = create_edge_snapshot(
                position_id=position.position_id,
                market_id=position.market_id,
                time_since_entry_minutes=time_since_entry,
                market_probability_current=market_probability_current,
                fair_probability_entry=fair_probability_entry,
                market_probability_entry=market_probability_entry,
                source=source,
            )

            success, msg = self.storage.write_snapshot(edge_snapshot)

            if success:
                return "written"
            else:
                if "Duplicate" in msg:
                    return "skipped"
                return "error"

        except Exception as e:
            logger.error(f"Error creating snapshot for {position.position_id}: {e}")
            return "error"

    def get_stats(self) -> Dict[str, Any]:
        """Get tracker statistics."""
        return self.storage.get_stats()

    def get_position_history(self, position_id: str) -> List[EdgeSnapshot]:
        """
        Get edge evolution history for a position.

        ANALYTICS ONLY - not for trading decisions.

        Args:
            position_id: The position to get history for

        Returns:
            List of EdgeSnapshot records, chronologically ordered
        """
        snapshots = self.storage.get_snapshots_by_position(position_id)
        return sorted(snapshots, key=lambda s: s.timestamp_utc)


# =============================================================================
# MODULE-LEVEL CONVENIENCE
# =============================================================================

_tracker: Optional[EdgeEvolutionTracker] = None


def get_tracker(base_dir: Optional[Path] = None) -> EdgeEvolutionTracker:
    """Get or create the global tracker instance."""
    global _tracker
    if _tracker is None:
        _tracker = EdgeEvolutionTracker(base_dir)
    return _tracker


def run_snapshot_cycle(source: str = "scheduler") -> Dict[str, Any]:
    """
    Run a snapshot cycle.

    This is the main entry point for scheduled execution.

    GOVERNANCE:
    - If this fails, it MUST NOT block trading
    - If this fails, it MUST NOT retry automatically
    - The return value is for logging only

    Args:
        source: Source of the snapshot

    Returns:
        Summary dict (for logging only)
    """
    try:
        return get_tracker().run(source)
    except Exception as e:
        logger.error(f"EdgeEvolutionTracker failed: {e}")
        # FAIL-CLOSED: Return error summary, do not raise
        return {
            "success": False,
            "error": str(e),
            "positions_checked": 0,
            "snapshots_written": 0,
        }


def get_stats() -> Dict[str, Any]:
    """Get tracker statistics."""
    return get_tracker().get_stats()
