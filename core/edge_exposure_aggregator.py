# =============================================================================
# POLYMARKET BEOBACHTER - EDGE EXPOSURE AGGREGATOR
# =============================================================================
#
# GOVERNANCE-SAFE DASHBOARD AGGREGATION
#
# PURPOSE:
# Aggregate edge evolution data for dashboard display.
# This module is ANALYTICS ONLY.
#
# ABSOLUTE NON-NEGOTIABLE RULES (FAIL CLOSED):
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

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# =============================================================================
# SAFETY: Forbidden imports declaration
# =============================================================================

_FORBIDDEN_MODULES = frozenset([
    "core.decision_engine",
    "core.execution_engine",
    "core.panic_contrarian_engine",
    "execution.adapter",
])

# =============================================================================
# Setup paths
# =============================================================================

BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR))

from core.edge_exposure_metrics import (
    SCHEMA_VERSION,
    EDGE_EXPOSURE_DIR,
    EDGE_EXPOSURE_SUMMARY_FILE,
    TimeWindow,
    get_window_start,
    PositionEdgeMetrics,
    EdgeExposureSummary,
    calculate_edge_area,
    calculate_edge_duration,
    calculate_exposure_ratio,
    calculate_median_positive_duration,
)
from core.edge_snapshot import EdgeSnapshot

logger = logging.getLogger(__name__)


# =============================================================================
# EDGE EXPOSURE AGGREGATOR
# =============================================================================


class EdgeExposureAggregator:
    """
    Aggregates edge evolution data for dashboard display.

    GOVERNANCE:
    - READ-ONLY access to edge snapshots
    - DESCRIPTIVE metrics only
    - NO trading signals or suggestions
    - NO PnL calculations

    This module answers: "Did we consistently have an advantage?"
    It must NEVER answer: "What should we do now?"
    """

    def __init__(self, base_dir: Optional[Path] = None):
        """
        Initialize the aggregator.

        Args:
            base_dir: Base directory for the project
        """
        self.base_dir = base_dir or BASE_DIR
        self.edge_dir = self.base_dir / EDGE_EXPOSURE_DIR
        self.snapshots_file = self.edge_dir / "edge_snapshots.jsonl"
        self.summary_file = self.edge_dir / EDGE_EXPOSURE_SUMMARY_FILE

    def _load_snapshots(self) -> List[Dict[str, Any]]:
        """
        Load all edge snapshots from JSONL file.

        Returns:
            List of snapshot dictionaries
        """
        snapshots = []

        if not self.snapshots_file.exists():
            logger.warning(f"Snapshots file not found: {self.snapshots_file}")
            return snapshots

        try:
            with open(self.snapshots_file, "r", encoding="utf-8") as f:
                for line_num, line in enumerate(f, 1):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                        # Skip headers
                        if data.get("_type") == "LOG_HEADER":
                            continue
                        snapshots.append(data)
                    except json.JSONDecodeError as e:
                        logger.warning(f"Invalid JSON at line {line_num}: {e}")
        except Exception as e:
            logger.error(f"Error reading snapshots: {e}")

        return snapshots

    def _filter_by_window(
        self,
        snapshots: List[Dict[str, Any]],
        window: TimeWindow,
    ) -> List[Dict[str, Any]]:
        """
        Filter snapshots by time window.

        Args:
            snapshots: All snapshots
            window: Time window to filter by

        Returns:
            Filtered snapshots
        """
        window_start = get_window_start(window)

        if window_start is None:
            # All time - no filtering
            return snapshots

        filtered = []
        for snap in snapshots:
            try:
                ts = datetime.fromisoformat(
                    snap["timestamp_utc"].replace("Z", "+00:00")
                )
                if ts >= window_start:
                    filtered.append(snap)
            except (ValueError, KeyError):
                continue

        return filtered

    def _group_by_position(
        self,
        snapshots: List[Dict[str, Any]],
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        Group snapshots by position_id.

        Args:
            snapshots: List of snapshots

        Returns:
            Dict mapping position_id to list of snapshots
        """
        grouped: Dict[str, List[Dict[str, Any]]] = {}

        for snap in snapshots:
            pos_id = snap.get("position_id")
            if not pos_id:
                continue

            if pos_id not in grouped:
                grouped[pos_id] = []
            grouped[pos_id].append(snap)

        # Sort each group by timestamp
        for pos_id in grouped:
            grouped[pos_id].sort(key=lambda s: s.get("timestamp_utc", ""))

        return grouped

    def _compute_position_metrics(
        self,
        position_id: str,
        snapshots: List[Dict[str, Any]],
    ) -> Optional[PositionEdgeMetrics]:
        """
        Compute metrics for a single position.

        Args:
            position_id: The position ID
            snapshots: Snapshots for this position (sorted by time)

        Returns:
            PositionEdgeMetrics or None if insufficient data
        """
        if not snapshots:
            return None

        # Extract market_id from first snapshot
        market_id = snapshots[0].get("market_id", "unknown")

        # Timestamps
        first_ts = snapshots[0].get("timestamp_utc", "")
        last_ts = snapshots[-1].get("timestamp_utc", "")

        # Duration
        try:
            first_dt = datetime.fromisoformat(first_ts.replace("Z", "+00:00"))
            last_dt = datetime.fromisoformat(last_ts.replace("Z", "+00:00"))
            total_duration = int((last_dt - first_dt).total_seconds() / 60)
        except (ValueError, AttributeError):
            total_duration = 0

        # Edge area
        total_area, positive_area, negative_area = calculate_edge_area(snapshots)

        # Edge duration
        pos_duration, neg_duration = calculate_edge_duration(snapshots)

        # Edge range
        edges = [s.get("edge_relative", 0.0) for s in snapshots]
        min_edge = min(edges) if edges else 0.0
        max_edge = max(edges) if edges else 0.0
        avg_edge = sum(edges) / len(edges) if edges else 0.0

        return PositionEdgeMetrics(
            position_id=position_id,
            market_id=market_id,
            snapshot_count=len(snapshots),
            first_snapshot_utc=first_ts,
            last_snapshot_utc=last_ts,
            total_duration_minutes=total_duration,
            edge_area_minutes=total_area,
            positive_edge_area_minutes=positive_area,
            negative_edge_area_minutes=negative_area,
            positive_edge_duration_minutes=pos_duration,
            negative_edge_duration_minutes=neg_duration,
            min_edge_relative=min_edge,
            max_edge_relative=max_edge,
            avg_edge_relative=avg_edge,
        )

    def run(self, window: TimeWindow = TimeWindow.ALL_TIME) -> EdgeExposureSummary:
        """
        Run aggregation and produce summary.

        GOVERNANCE:
        This produces descriptive metrics only.
        The output MUST NOT be used for trading decisions.

        Args:
            window: Time window for aggregation

        Returns:
            EdgeExposureSummary
        """
        logger.info(f"EdgeExposureAggregator.run(window={window.value})")

        # Load snapshots
        all_snapshots = self._load_snapshots()
        logger.info(f"Loaded {len(all_snapshots)} total snapshots")

        # Filter by window
        filtered_snapshots = self._filter_by_window(all_snapshots, window)
        logger.info(f"After filtering: {len(filtered_snapshots)} snapshots")

        # Group by position
        by_position = self._group_by_position(filtered_snapshots)
        logger.info(f"Found {len(by_position)} positions")

        # Compute per-position metrics
        position_metrics: List[PositionEdgeMetrics] = []
        for pos_id, snaps in by_position.items():
            metrics = self._compute_position_metrics(pos_id, snaps)
            if metrics:
                position_metrics.append(metrics)

        # Aggregate totals
        total_edge_area_minutes = sum(p.edge_area_minutes for p in position_metrics)
        positive_area_minutes = sum(p.positive_edge_area_minutes for p in position_metrics)
        negative_area_minutes = sum(p.negative_edge_area_minutes for p in position_metrics)

        # Convert to hours for readability
        total_edge_exposure_hours = total_edge_area_minutes / 60
        positive_edge_exposure_hours = positive_area_minutes / 60
        negative_edge_exposure_hours = negative_area_minutes / 60

        # Calculate ratio
        exposure_ratio = calculate_exposure_ratio(
            positive_area_minutes,
            negative_area_minutes,
        )

        # Calculate median positive duration
        positive_durations = [p.positive_edge_duration_minutes for p in position_metrics]
        median_duration = calculate_median_positive_duration(positive_durations)

        # Build summary
        summary = EdgeExposureSummary(
            schema_version=SCHEMA_VERSION,
            generated_at_utc=datetime.now(timezone.utc).isoformat(),
            time_window=window.value,
            open_positions_count=len(position_metrics),
            snapshot_count=len(filtered_snapshots),
            total_edge_exposure_hours=total_edge_exposure_hours,
            positive_edge_exposure_hours=positive_edge_exposure_hours,
            negative_edge_exposure_hours=negative_edge_exposure_hours,
            edge_exposure_ratio=exposure_ratio,
            median_edge_duration_minutes=median_duration,
            position_metrics=position_metrics,
        )

        logger.info(
            f"Summary: {summary.open_positions_count} positions, "
            f"{summary.snapshot_count} snapshots, "
            f"exposure_ratio={summary.edge_exposure_ratio}"
        )

        return summary

    def save_summary(
        self,
        summary: EdgeExposureSummary,
        include_positions: bool = False,
    ) -> bool:
        """
        Save summary to JSON file.

        Args:
            summary: The summary to save
            include_positions: Include per-position breakdown

        Returns:
            True if saved successfully
        """
        try:
            self.edge_dir.mkdir(parents=True, exist_ok=True)

            with open(self.summary_file, "w", encoding="utf-8") as f:
                json.dump(summary.to_dict(include_positions), f, indent=2)

            logger.info(f"Summary saved to {self.summary_file}")
            return True

        except Exception as e:
            logger.error(f"Failed to save summary: {e}")
            return False

    def load_summary(self) -> Optional[EdgeExposureSummary]:
        """
        Load existing summary from JSON file.

        Returns:
            EdgeExposureSummary or None if not found
        """
        if not self.summary_file.exists():
            return None

        try:
            with open(self.summary_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            return EdgeExposureSummary(
                schema_version=data.get("schema_version", SCHEMA_VERSION),
                generated_at_utc=data.get("generated_at_utc", ""),
                time_window=data.get("time_window", "all_time"),
                open_positions_count=data.get("open_positions_count", 0),
                snapshot_count=data.get("snapshot_count", 0),
                total_edge_exposure_hours=data.get("total_edge_exposure_hours", 0.0),
                positive_edge_exposure_hours=data.get("positive_edge_exposure_hours", 0.0),
                negative_edge_exposure_hours=data.get("negative_edge_exposure_hours", 0.0),
                edge_exposure_ratio=data.get("edge_exposure_ratio"),
                median_edge_duration_minutes=data.get("median_edge_duration_minutes"),
                position_metrics=[],  # Don't load position details
            )

        except Exception as e:
            logger.error(f"Failed to load summary: {e}")
            return None


# =============================================================================
# MODULE-LEVEL CONVENIENCE
# =============================================================================

_aggregator: Optional[EdgeExposureAggregator] = None


def get_aggregator(base_dir: Optional[Path] = None) -> EdgeExposureAggregator:
    """Get or create the global aggregator instance."""
    global _aggregator
    if _aggregator is None:
        _aggregator = EdgeExposureAggregator(base_dir)
    return _aggregator


def build_summary(
    window: TimeWindow = TimeWindow.ALL_TIME,
    save: bool = True,
) -> EdgeExposureSummary:
    """
    Build and optionally save the edge exposure summary.

    Args:
        window: Time window for aggregation
        save: Whether to save the summary to file

    Returns:
        EdgeExposureSummary
    """
    aggregator = get_aggregator()
    summary = aggregator.run(window)

    if save:
        aggregator.save_summary(summary)

    return summary


def get_summary() -> Optional[EdgeExposureSummary]:
    """Get the latest saved summary."""
    return get_aggregator().load_summary()


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

    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.add(node.module)

    for forb in _FORBIDDEN_MODULES:
        for imp in imports:
            if imp == forb or imp.startswith(forb + "."):
                raise ImportError(
                    f"SAFETY VIOLATION: {__file__} imports {imp} "
                    f"which is forbidden."
                )

    return True
