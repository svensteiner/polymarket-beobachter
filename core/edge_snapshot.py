# =============================================================================
# POLYMARKET BEOBACHTER - EDGE SNAPSHOT MODULE
# =============================================================================
#
# GOVERNANCE-FIRST ANALYTICS MODULE
#
# PURPOSE:
# Define the schema and validation for edge evolution snapshots.
# This module is READ-ONLY with respect to trading.
#
# ABSOLUTE NON-NEGOTIABLE RULES:
# 1. No interaction with execution or decision logic
# 2. No order placement, no exit signals
# 3. Append-only storage: never overwrite historical data
# 4. Edge is MEASURED, not acted upon
# 5. If data is missing or inconsistent -> write NOTHING
#
# ISOLATION GUARANTEES:
# - NO imports from decision_engine
# - NO imports from execution_engine
# - NO imports from panic modules
# - NO imports from learning modules
#
# =============================================================================

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# =============================================================================
# CONSTANTS
# =============================================================================

SCHEMA_VERSION = 1

# Storage paths
EDGE_EVOLUTION_DIR = "data/edge_evolution"
EDGE_SNAPSHOTS_FILE = "edge_snapshots.jsonl"

# Valid sources
VALID_SOURCES = {"scheduler", "cli", "manual"}


# =============================================================================
# HASHING & CANONICAL JSON
# =============================================================================


def canonical_json(data: Dict[str, Any]) -> str:
    """
    Convert dict to canonical JSON string for hashing.

    Canonical means:
    - Keys sorted alphabetically
    - No whitespace
    - Consistent float formatting
    """
    return json.dumps(data, sort_keys=True, separators=(",", ":"), default=str)


def compute_hash(data: Dict[str, Any]) -> str:
    """
    Compute SHA256 hash of canonical JSON.

    The record_hash field is excluded from the hash computation.
    """
    data_copy = {k: v for k, v in data.items() if k != "record_hash"}
    canonical = canonical_json(data_copy)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def generate_snapshot_id() -> str:
    """Generate a unique snapshot ID."""
    return str(uuid.uuid4())


def get_utc_timestamp() -> str:
    """Get current UTC timestamp in ISO format."""
    return datetime.now(timezone.utc).isoformat()


def get_minute_bucket(timestamp_utc: str) -> str:
    """
    Get minute-level bucket for deduplication.

    Truncates timestamp to the minute.
    """
    try:
        dt = datetime.fromisoformat(timestamp_utc.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%dT%H:%M")
    except (ValueError, AttributeError):
        return timestamp_utc[:16]  # Fallback: first 16 chars


# =============================================================================
# EDGE SNAPSHOT DATA CLASS
# =============================================================================


@dataclass(frozen=True)
class EdgeSnapshot:
    """
    A snapshot of edge evolution at a point in time.

    IMMUTABLE once created and written.

    GOVERNANCE:
    This is an ANALYTICS record only.
    It is NOT a trading signal.
    It MUST NOT be used to trigger exits or modify positions.

    SCHEMA:
    {
      "schema_version": 1,
      "snapshot_id": "<uuid4>",
      "position_id": "<uuid4>",
      "market_id": "<string>",
      "timestamp_utc": "<ISO8601>",
      "time_since_entry_minutes": <int>,
      "market_probability_current": <float>,
      "fair_probability_entry": <float>,
      "edge_relative": <float>,
      "edge_delta_since_entry": <float>,
      "source": "scheduler" | "cli",
      "record_hash": "<sha256 canonical json>"
    }

    DEFINITIONS:
    edge_relative =
      (fair_probability_entry - market_probability_current)
      / market_probability_current

    edge_delta_since_entry =
      edge_relative - edge_at_entry
    """
    schema_version: int
    snapshot_id: str
    position_id: str
    market_id: str
    timestamp_utc: str
    time_since_entry_minutes: int
    market_probability_current: float
    fair_probability_entry: float
    edge_relative: float
    edge_delta_since_entry: float
    source: str
    record_hash: str = field(default="", compare=False)

    # Hardcoded governance notice - this is analytics only
    governance_notice: str = field(
        default="This is an ANALYTICS record only. NOT a trading signal.",
        init=False,
        compare=False,
    )

    def __post_init__(self):
        """Validate fields after initialization."""
        errors = self.validate()
        if errors:
            raise ValueError(f"Invalid EdgeSnapshot: {'; '.join(errors)}")

    def validate(self) -> List[str]:
        """Validate all fields. Returns list of errors."""
        errors = []

        if self.schema_version != SCHEMA_VERSION:
            errors.append(f"schema_version must be {SCHEMA_VERSION}, got {self.schema_version}")

        if not self.snapshot_id:
            errors.append("snapshot_id is required")

        if not self.position_id:
            errors.append("position_id is required")

        if not self.market_id:
            errors.append("market_id is required")

        if not self.timestamp_utc:
            errors.append("timestamp_utc is required")

        if not isinstance(self.time_since_entry_minutes, int):
            errors.append(f"time_since_entry_minutes must be int, got {type(self.time_since_entry_minutes)}")
        elif self.time_since_entry_minutes < 0:
            errors.append(f"time_since_entry_minutes must be >= 0, got {self.time_since_entry_minutes}")

        # Validate probabilities are in valid range
        if not isinstance(self.market_probability_current, (int, float)):
            errors.append("market_probability_current must be numeric")
        elif not (0.0 <= self.market_probability_current <= 1.0):
            errors.append(f"market_probability_current must be 0-1, got {self.market_probability_current}")

        if not isinstance(self.fair_probability_entry, (int, float)):
            errors.append("fair_probability_entry must be numeric")
        elif not (0.0 <= self.fair_probability_entry <= 1.0):
            errors.append(f"fair_probability_entry must be 0-1, got {self.fair_probability_entry}")

        # edge_relative and edge_delta_since_entry can be any float
        if not isinstance(self.edge_relative, (int, float)):
            errors.append("edge_relative must be numeric")

        if not isinstance(self.edge_delta_since_entry, (int, float)):
            errors.append("edge_delta_since_entry must be numeric")

        if self.source not in VALID_SOURCES:
            errors.append(f"source must be one of {VALID_SOURCES}, got {self.source}")

        return errors

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "schema_version": self.schema_version,
            "snapshot_id": self.snapshot_id,
            "position_id": self.position_id,
            "market_id": self.market_id,
            "timestamp_utc": self.timestamp_utc,
            "time_since_entry_minutes": self.time_since_entry_minutes,
            "market_probability_current": self.market_probability_current,
            "fair_probability_entry": self.fair_probability_entry,
            "edge_relative": self.edge_relative,
            "edge_delta_since_entry": self.edge_delta_since_entry,
            "source": self.source,
            "record_hash": self.record_hash,
            "governance_notice": self.governance_notice,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EdgeSnapshot":
        """Create from dictionary."""
        return cls(
            schema_version=data.get("schema_version", SCHEMA_VERSION),
            snapshot_id=data.get("snapshot_id", ""),
            position_id=data.get("position_id", ""),
            market_id=data.get("market_id", ""),
            timestamp_utc=data.get("timestamp_utc", ""),
            time_since_entry_minutes=data.get("time_since_entry_minutes", 0),
            market_probability_current=data.get("market_probability_current", 0.0),
            fair_probability_entry=data.get("fair_probability_entry", 0.0),
            edge_relative=data.get("edge_relative", 0.0),
            edge_delta_since_entry=data.get("edge_delta_since_entry", 0.0),
            source=data.get("source", ""),
            record_hash=data.get("record_hash", ""),
        )


# =============================================================================
# EDGE CALCULATION FUNCTIONS
# =============================================================================


def calculate_edge_relative(
    fair_probability_entry: float,
    market_probability_current: float,
) -> float:
    """
    Calculate the relative edge.

    DEFINITION:
    edge_relative = (fair_probability_entry - market_probability_current)
                    / market_probability_current

    This measures how much our fair value differs from the current market,
    relative to the current market price.

    A positive value means the market has moved toward our estimate.
    A negative value means the market has moved away from our estimate.

    Args:
        fair_probability_entry: Our fair probability at position entry
        market_probability_current: Current market probability

    Returns:
        Relative edge as a float (can be negative)

    Raises:
        ValueError: If market_probability_current is zero
    """
    if market_probability_current == 0.0:
        raise ValueError("market_probability_current cannot be zero")

    return (fair_probability_entry - market_probability_current) / market_probability_current


def calculate_edge_at_entry(
    fair_probability_entry: float,
    market_probability_entry: float,
) -> float:
    """
    Calculate the edge at position entry.

    This is the baseline edge when we entered the position.

    Args:
        fair_probability_entry: Our fair probability at entry
        market_probability_entry: Market probability at entry

    Returns:
        Edge at entry as a float

    Raises:
        ValueError: If market_probability_entry is zero
    """
    if market_probability_entry == 0.0:
        raise ValueError("market_probability_entry cannot be zero")

    return (fair_probability_entry - market_probability_entry) / market_probability_entry


def calculate_edge_delta_since_entry(
    fair_probability_entry: float,
    market_probability_current: float,
    market_probability_entry: float,
) -> float:
    """
    Calculate how the edge has changed since entry.

    DEFINITION:
    edge_delta_since_entry = edge_relative - edge_at_entry

    A positive value means the edge has INCREASED since entry.
    A negative value means the edge has DECREASED since entry.

    Args:
        fair_probability_entry: Our fair probability at entry (unchanged)
        market_probability_current: Current market probability
        market_probability_entry: Market probability at entry

    Returns:
        Edge delta as a float (can be negative)

    Raises:
        ValueError: If market probabilities are zero
    """
    edge_at_entry = calculate_edge_at_entry(
        fair_probability_entry, market_probability_entry
    )
    edge_current = calculate_edge_relative(
        fair_probability_entry, market_probability_current
    )
    return edge_current - edge_at_entry


def calculate_time_since_entry_minutes(
    entry_time: str,
    current_time: Optional[str] = None,
) -> int:
    """
    Calculate minutes since position entry.

    Args:
        entry_time: ISO format timestamp of entry
        current_time: Current time (defaults to now)

    Returns:
        Minutes since entry as integer
    """
    try:
        entry_dt = datetime.fromisoformat(entry_time.replace("Z", "+00:00"))
        if current_time:
            current_dt = datetime.fromisoformat(current_time.replace("Z", "+00:00"))
        else:
            current_dt = datetime.now(timezone.utc)

        delta = current_dt - entry_dt
        return int(delta.total_seconds() / 60)
    except (ValueError, TypeError, AttributeError):
        return 0


# =============================================================================
# SNAPSHOT FACTORY
# =============================================================================


def create_edge_snapshot(
    position_id: str,
    market_id: str,
    time_since_entry_minutes: int,
    market_probability_current: float,
    fair_probability_entry: float,
    market_probability_entry: float,
    source: str = "scheduler",
) -> EdgeSnapshot:
    """
    Factory function to create an EdgeSnapshot.

    GOVERNANCE:
    This function creates an analytics record.
    It MUST NOT be used to trigger trading decisions.

    Args:
        position_id: Unique position identifier
        market_id: Unique market identifier
        time_since_entry_minutes: Minutes since position entry
        market_probability_current: Current market probability
        fair_probability_entry: Our fair probability at entry
        market_probability_entry: Market probability at entry
        source: Source of the snapshot (scheduler, cli, manual)

    Returns:
        A valid EdgeSnapshot
    """
    # Calculate edge metrics
    edge_relative = calculate_edge_relative(
        fair_probability_entry, market_probability_current
    )
    edge_delta = calculate_edge_delta_since_entry(
        fair_probability_entry, market_probability_current, market_probability_entry
    )

    snapshot = EdgeSnapshot(
        schema_version=SCHEMA_VERSION,
        snapshot_id=generate_snapshot_id(),
        position_id=position_id,
        market_id=market_id,
        timestamp_utc=get_utc_timestamp(),
        time_since_entry_minutes=time_since_entry_minutes,
        market_probability_current=market_probability_current,
        fair_probability_entry=fair_probability_entry,
        edge_relative=edge_relative,
        edge_delta_since_entry=edge_delta,
        source=source,
    )

    # Compute hash and create final snapshot
    data = snapshot.to_dict()
    record_hash = compute_hash(data)

    # Create new snapshot with hash (frozen dataclass requires this approach)
    return EdgeSnapshot(
        schema_version=snapshot.schema_version,
        snapshot_id=snapshot.snapshot_id,
        position_id=snapshot.position_id,
        market_id=snapshot.market_id,
        timestamp_utc=snapshot.timestamp_utc,
        time_since_entry_minutes=snapshot.time_since_entry_minutes,
        market_probability_current=snapshot.market_probability_current,
        fair_probability_entry=snapshot.fair_probability_entry,
        edge_relative=snapshot.edge_relative,
        edge_delta_since_entry=snapshot.edge_delta_since_entry,
        source=snapshot.source,
        record_hash=record_hash,
    )
