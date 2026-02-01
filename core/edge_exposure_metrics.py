# =============================================================================
# POLYMARKET BEOBACHTER - EDGE EXPOSURE METRICS
# =============================================================================
#
# GOVERNANCE-SAFE DASHBOARD METRICS
#
# PURPOSE:
# Define metrics for aggregating edge evolution data.
# These metrics are DESCRIPTIVE, not PRESCRIPTIVE.
#
# ABSOLUTE NON-NEGOTIABLE RULES:
# 1. Read-only access to edge evolution data
# 2. No access to execution, decision, or signal modules
# 3. No PnL calculations
# 4. No "optimal exit", "sell now", or hypothetical profit metrics
# 5. All metrics are descriptive, not prescriptive
# 6. If data is inconsistent -> omit metric, do not infer
#
# ISOLATION GUARANTEES:
# - NO imports from decision_engine
# - NO imports from execution_engine
# - NO imports from panic modules
#
# MENTAL MODEL:
# This module answers: "Did we consistently have an advantage?"
# It must NEVER answer: "What should we do now?"
#
# =============================================================================

from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from enum import Enum
from pathlib import Path
from statistics import median
from typing import Any, Dict, List, Optional, Tuple
import json

# =============================================================================
# CONSTANTS
# =============================================================================

SCHEMA_VERSION = 1

# Output paths
EDGE_EXPOSURE_DIR = "data/edge_evolution"
EDGE_EXPOSURE_SUMMARY_FILE = "edge_exposure_summary.json"


# =============================================================================
# TIME WINDOW ENUM
# =============================================================================


class TimeWindow(Enum):
    """
    Supported time windows for aggregation.
    """
    LAST_24H = "last_24h"
    LAST_7D = "last_7d"
    ALL_TIME = "all_time"

    @classmethod
    def from_string(cls, value: str) -> "TimeWindow":
        """Parse string to TimeWindow."""
        for window in cls:
            if window.value == value:
                return window
        raise ValueError(f"Unknown time window: {value}")


def get_window_start(window: TimeWindow) -> Optional[datetime]:
    """
    Get the start datetime for a time window.

    Args:
        window: The time window

    Returns:
        Start datetime (UTC), or None for all_time
    """
    now = datetime.now(timezone.utc)

    if window == TimeWindow.LAST_24H:
        return now - timedelta(hours=24)
    elif window == TimeWindow.LAST_7D:
        return now - timedelta(days=7)
    elif window == TimeWindow.ALL_TIME:
        return None

    return None


# =============================================================================
# METRIC DATA CLASSES
# =============================================================================


@dataclass
class PositionEdgeMetrics:
    """
    Edge metrics for a single position.

    GOVERNANCE:
    These are descriptive metrics only.
    They MUST NOT be used for trading decisions.
    """
    position_id: str
    market_id: str
    snapshot_count: int
    first_snapshot_utc: str
    last_snapshot_utc: str
    total_duration_minutes: int

    # Edge Area (Σ edge_relative × Δt)
    # Units: edge-minutes
    edge_area_minutes: float

    # Positive edge area (where edge_relative > 0)
    positive_edge_area_minutes: float

    # Negative edge area (where edge_relative < 0)
    negative_edge_area_minutes: float

    # Duration with positive edge
    positive_edge_duration_minutes: int

    # Duration with negative edge
    negative_edge_duration_minutes: int

    # Edge range
    min_edge_relative: float
    max_edge_relative: float
    avg_edge_relative: float

    # Governance notice
    governance_notice: str = field(
        default="ANALYTICS ONLY - NOT a trading signal",
        init=False,
    )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "position_id": self.position_id,
            "market_id": self.market_id,
            "snapshot_count": self.snapshot_count,
            "first_snapshot_utc": self.first_snapshot_utc,
            "last_snapshot_utc": self.last_snapshot_utc,
            "total_duration_minutes": self.total_duration_minutes,
            "edge_area_minutes": self.edge_area_minutes,
            "positive_edge_area_minutes": self.positive_edge_area_minutes,
            "negative_edge_area_minutes": self.negative_edge_area_minutes,
            "positive_edge_duration_minutes": self.positive_edge_duration_minutes,
            "negative_edge_duration_minutes": self.negative_edge_duration_minutes,
            "min_edge_relative": self.min_edge_relative,
            "max_edge_relative": self.max_edge_relative,
            "avg_edge_relative": self.avg_edge_relative,
            "governance_notice": self.governance_notice,
        }


@dataclass
class EdgeExposureSummary:
    """
    Aggregated edge exposure summary for dashboard.

    GOVERNANCE:
    This summary is for DESCRIPTIVE analytics only.
    It MUST NOT be used to:
    - Trigger exits
    - Suggest trading actions
    - Color-code buy/sell urgency
    - Rank positions by "sell now"

    WHAT THIS ANSWERS:
    "Did we consistently have an advantage?"

    WHAT THIS MUST NEVER ANSWER:
    "What should we do now?"
    """
    schema_version: int
    generated_at_utc: str
    time_window: str

    # Position counts
    open_positions_count: int
    snapshot_count: int

    # Edge Exposure (in hours for readability)
    total_edge_exposure_hours: float
    positive_edge_exposure_hours: float
    negative_edge_exposure_hours: float

    # Edge Exposure Ratio = positive / (positive + |negative|)
    edge_exposure_ratio: Optional[float]

    # Median edge duration where edge > 0
    median_edge_duration_minutes: Optional[int]

    # Per-position breakdown (optional detail)
    position_metrics: List[PositionEdgeMetrics] = field(default_factory=list)

    # Governance notice
    governance_notice: str = field(
        default="ANALYTICS ONLY - This dashboard does NOT suggest trading actions",
        init=False,
    )

    def to_dict(self, include_positions: bool = False) -> Dict[str, Any]:
        """
        Convert to dictionary.

        Args:
            include_positions: Include per-position breakdown
        """
        result = {
            "schema_version": self.schema_version,
            "generated_at_utc": self.generated_at_utc,
            "time_window": self.time_window,
            "open_positions_count": self.open_positions_count,
            "snapshot_count": self.snapshot_count,
            "total_edge_exposure_hours": round(self.total_edge_exposure_hours, 2),
            "positive_edge_exposure_hours": round(self.positive_edge_exposure_hours, 2),
            "negative_edge_exposure_hours": round(self.negative_edge_exposure_hours, 2),
            "edge_exposure_ratio": round(self.edge_exposure_ratio, 4) if self.edge_exposure_ratio else None,
            "median_edge_duration_minutes": self.median_edge_duration_minutes,
            "governance_notice": self.governance_notice,
        }

        if include_positions and self.position_metrics:
            result["positions"] = [p.to_dict() for p in self.position_metrics]

        return result

    def to_json(self, include_positions: bool = False) -> str:
        """Convert to JSON string."""
        return json.dumps(self.to_dict(include_positions), indent=2)


# =============================================================================
# EDGE AREA CALCULATION
# =============================================================================


def calculate_edge_area(
    snapshots: List[Dict[str, Any]],
) -> Tuple[float, float, float]:
    """
    Calculate edge area (integral of edge over time).

    Edge Area = Σ [ edge_relative(t_i) × Δt_i ]

    This measures the cumulative "exposure" to edge over time.
    It is NOT a profit measure.

    Args:
        snapshots: List of snapshot dicts, sorted by timestamp

    Returns:
        Tuple of (total_area, positive_area, negative_area) in edge-minutes

    GOVERNANCE:
    This is a descriptive metric only.
    A high edge area does NOT mean "sell now".
    A low edge area does NOT mean "hold longer".
    """
    if len(snapshots) < 2:
        # Need at least 2 points for area
        if len(snapshots) == 1:
            # Single snapshot - use edge as instantaneous value, 1 minute default
            edge = snapshots[0].get("edge_relative", 0.0)
            if edge > 0:
                return edge, edge, 0.0
            elif edge < 0:
                return edge, 0.0, edge
            else:
                return 0.0, 0.0, 0.0
        return 0.0, 0.0, 0.0

    total_area = 0.0
    positive_area = 0.0
    negative_area = 0.0

    for i in range(1, len(snapshots)):
        prev = snapshots[i - 1]
        curr = snapshots[i]

        # Get timestamps
        try:
            prev_time = datetime.fromisoformat(
                prev["timestamp_utc"].replace("Z", "+00:00")
            )
            curr_time = datetime.fromisoformat(
                curr["timestamp_utc"].replace("Z", "+00:00")
            )
        except (ValueError, KeyError):
            continue

        # Calculate time delta in minutes
        delta_minutes = (curr_time - prev_time).total_seconds() / 60

        # Skip if delta is negative or too large (data error)
        if delta_minutes < 0 or delta_minutes > 60 * 24 * 7:  # Max 7 days between snapshots
            continue

        # Use average edge over the interval (trapezoidal rule)
        prev_edge = prev.get("edge_relative", 0.0)
        curr_edge = curr.get("edge_relative", 0.0)
        avg_edge = (prev_edge + curr_edge) / 2

        # Calculate area contribution
        area = avg_edge * delta_minutes
        total_area += area

        if avg_edge > 0:
            positive_area += area
        elif avg_edge < 0:
            negative_area += area

    return total_area, positive_area, negative_area


def calculate_edge_duration(
    snapshots: List[Dict[str, Any]],
) -> Tuple[int, int]:
    """
    Calculate duration with positive and negative edge.

    Args:
        snapshots: List of snapshot dicts, sorted by timestamp

    Returns:
        Tuple of (positive_minutes, negative_minutes)
    """
    if len(snapshots) < 2:
        return 0, 0

    positive_minutes = 0
    negative_minutes = 0

    for i in range(1, len(snapshots)):
        prev = snapshots[i - 1]
        curr = snapshots[i]

        try:
            prev_time = datetime.fromisoformat(
                prev["timestamp_utc"].replace("Z", "+00:00")
            )
            curr_time = datetime.fromisoformat(
                curr["timestamp_utc"].replace("Z", "+00:00")
            )
        except (ValueError, KeyError):
            continue

        delta_minutes = int((curr_time - prev_time).total_seconds() / 60)

        if delta_minutes < 0 or delta_minutes > 60 * 24 * 7:
            continue

        # Use average edge to classify the interval
        prev_edge = prev.get("edge_relative", 0.0)
        curr_edge = curr.get("edge_relative", 0.0)
        avg_edge = (prev_edge + curr_edge) / 2

        if avg_edge > 0:
            positive_minutes += delta_minutes
        elif avg_edge < 0:
            negative_minutes += delta_minutes

    return positive_minutes, negative_minutes


def calculate_exposure_ratio(
    positive_exposure: float,
    negative_exposure: float,
) -> Optional[float]:
    """
    Calculate edge exposure ratio.

    Ratio = positive / (positive + |negative|)

    Range: 0.0 to 1.0
    - 1.0 = all positive edge
    - 0.5 = equal positive and negative
    - 0.0 = all negative edge

    Args:
        positive_exposure: Positive edge exposure (should be >= 0)
        negative_exposure: Negative edge exposure (should be <= 0)

    Returns:
        Ratio between 0 and 1, or None if no exposure
    """
    total = positive_exposure + abs(negative_exposure)
    if total == 0:
        return None
    return positive_exposure / total


def calculate_median_positive_duration(
    position_durations: List[int],
) -> Optional[int]:
    """
    Calculate median duration with positive edge across positions.

    Args:
        position_durations: List of positive edge durations (minutes) per position

    Returns:
        Median duration in minutes, or None if no data
    """
    # Filter out zeros
    valid = [d for d in position_durations if d > 0]
    if not valid:
        return None
    return int(median(valid))


# =============================================================================
# SAFETY CHECK
# =============================================================================


def check_import_safety() -> bool:
    """
    Check that this module does not import forbidden modules.

    Returns:
        True if safe, raises ImportError if violation detected
    """
    import ast

    source_file = Path(__file__)
    source_code = source_file.read_text(encoding="utf-8")
    tree = ast.parse(source_code)

    forbidden = {
        "core.decision_engine",
        "core.execution_engine",
        "core.panic_contrarian_engine",
        "execution.adapter",
    }

    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.add(node.module)

    for forb in forbidden:
        for imp in imports:
            if imp == forb or imp.startswith(forb + "."):
                raise ImportError(
                    f"SAFETY VIOLATION: {__file__} imports {imp} "
                    f"which is forbidden."
                )

    return True
