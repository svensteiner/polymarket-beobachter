# =============================================================================
# POLYMARKET BEOBACHTER - CALIBRATION ENGINE
# =============================================================================
#
# GOVERNANCE-SAFE ANALYTICS MODULE
#
# PURPOSE:
# Evaluate how accurate and well-calibrated the system's probability
# estimates were over time.
#
# THIS MODULE IS ANALYTICS ONLY.
# It NEVER influences trading, execution, thresholds, sizing, or decisions.
#
# NON-NEGOTIABLE RULES:
# 1. Read-only access to historical data.
# 2. No imports from decision_engine, execution_engine, or sizing logic.
# 3. No parameter tuning, no feedback loops.
# 4. No optimization, no suggestions like "increase/decrease threshold".
# 5. If data is missing or ambiguous -> exclude from analysis.
# 6. Better fewer data points than polluted statistics.
#
# ISOLATION GUARANTEES:
# - NO imports from: decision_engine, execution_engine, panic_contrarian_engine,
#   simulator, kelly, capital_manager, slippage, or any sizing/trading module.
# - Only reads from: data/outcomes/, data/edge_evolution/, proposals logs.
# - Only writes to: data/calibration/calibration_report.json
#
# =============================================================================

import json
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .calibration_metrics import (
    CalibrationPoint,
    MetricsBucket,
    compute_bucket,
    group_by_model,
    group_by_confidence,
    group_by_odds_bucket,
    is_valid_point,
)

logger = logging.getLogger(__name__)

# =============================================================================
# CONSTANTS
# =============================================================================

SCHEMA_VERSION = 1

# Data source paths (relative to base_dir)
PREDICTIONS_PATH = "data/outcomes/predictions.jsonl"
RESOLUTIONS_PATH = "data/outcomes/resolutions.jsonl"
EDGE_SNAPSHOTS_PATH = "data/edge_evolution/edge_snapshots.jsonl"
PROPOSALS_LOG_PATH = "proposals/proposals_log.json"

# Output path
REPORT_OUTPUT_PATH = "data/calibration/calibration_report.json"

# Valid resolutions that count as definitive outcomes
DEFINITIVE_RESOLUTIONS = {"YES", "NO"}

# Time window presets
TIME_WINDOWS = {
    "all_time": None,
    "last_7d": timedelta(days=7),
    "last_30d": timedelta(days=30),
    "last_90d": timedelta(days=90),
}


# =============================================================================
# DATA LOADING (READ-ONLY)
# =============================================================================


def _load_jsonl(path: Path) -> List[Dict[str, Any]]:
    """
    Load a JSONL file. Returns empty list if file doesn't exist or is empty.

    GOVERNANCE: Read-only. Never modifies the file.
    """
    if not path.exists():
        logger.info(f"File not found (OK): {path}")
        return []

    records = []
    with open(path, "r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as e:
                logger.warning(f"Skipping invalid JSON at {path}:{line_num}: {e}")
    return records


def _load_json(path: Path) -> Optional[Dict[str, Any]]:
    """Load a JSON file. Returns None if not found."""
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"Could not load {path}: {e}")
        return None


# =============================================================================
# RESOLUTION MATCHING
# =============================================================================


def _build_resolution_map(
    resolutions: List[Dict[str, Any]],
) -> Dict[str, int]:
    """
    Build a map of market_id -> binary outcome (1=YES, 0=NO).

    Only includes definitive resolutions (YES or NO).
    Excludes INVALID, CANCELLED, AMBIGUOUS — fail closed.

    Args:
        resolutions: Raw resolution records from resolutions.jsonl.

    Returns:
        Dict mapping market_id to outcome (0 or 1).
    """
    outcome_map: Dict[str, int] = {}
    for rec in resolutions:
        market_id = rec.get("market_id")
        resolution = rec.get("resolution")
        resolved = rec.get("resolved", False)

        if not market_id:
            continue
        if not resolved:
            continue
        if resolution not in DEFINITIVE_RESOLUTIONS:
            continue

        outcome_map[market_id] = 1 if resolution == "YES" else 0

    return outcome_map


# =============================================================================
# CALIBRATION POINT EXTRACTION
# =============================================================================


def _extract_points_from_predictions(
    predictions: List[Dict[str, Any]],
    resolution_map: Dict[str, int],
    time_window: Optional[timedelta] = None,
) -> List[CalibrationPoint]:
    """
    Match predictions to resolutions and create CalibrationPoints.

    EXCLUSION RULES (fail closed):
    - Prediction has no our_estimate_yes → exclude
    - our_estimate_yes is None or not in [0, 1] → exclude
    - Market has no definitive resolution → exclude
    - Prediction timestamp outside time window → exclude

    Args:
        predictions: Raw prediction records from predictions.jsonl.
        resolution_map: market_id → outcome mapping.
        time_window: Optional timedelta for filtering by recency.

    Returns:
        List of valid CalibrationPoints.
    """
    now_utc = datetime.now(timezone.utc)
    cutoff = (now_utc - time_window) if time_window else None

    points: List[CalibrationPoint] = []
    excluded_no_estimate = 0
    excluded_no_resolution = 0
    excluded_invalid_prob = 0
    excluded_time = 0

    for pred in predictions:
        market_id = pred.get("market_id")
        if not market_id:
            continue

        # Must have a definitive resolution
        if market_id not in resolution_map:
            excluded_no_resolution += 1
            continue

        # Must have our probability estimate
        estimate = pred.get("our_estimate_yes")
        if estimate is None:
            excluded_no_estimate += 1
            continue

        # Validate probability
        try:
            prob = float(estimate)
        except (TypeError, ValueError):
            excluded_invalid_prob += 1
            continue

        if not (0.0 <= prob <= 1.0):
            excluded_invalid_prob += 1
            continue

        # Time window filter
        timestamp_str = pred.get("timestamp_utc")
        if cutoff and timestamp_str:
            try:
                ts = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                if ts < cutoff:
                    excluded_time += 1
                    continue
            except (ValueError, TypeError):
                pass  # If we can't parse timestamp, include anyway

        # Extract model type and confidence
        engine_ctx = pred.get("engine_context", {})
        model_type = engine_ctx.get("engine", "UNKNOWN")
        confidence = pred.get("estimate_confidence")

        point = CalibrationPoint(
            market_id=market_id,
            probability_at_entry=prob,
            actual_outcome=resolution_map[market_id],
            model_type=model_type,
            confidence=confidence,
            entry_timestamp=timestamp_str,
        )

        if is_valid_point(point):
            points.append(point)

    logger.info(
        f"Calibration points: {len(points)} valid | "
        f"excluded: {excluded_no_resolution} no_resolution, "
        f"{excluded_no_estimate} no_estimate, "
        f"{excluded_invalid_prob} invalid_prob, "
        f"{excluded_time} outside_window"
    )

    return points


def _extract_points_from_positions(
    positions: List[Dict[str, Any]],
    proposals_by_id: Dict[str, Dict[str, Any]],
    resolution_map: Dict[str, int],
    time_window: Optional[timedelta] = None,
) -> List[CalibrationPoint]:
    """
    Extract CalibrationPoints from resolved paper positions matched to proposals.

    This is a secondary source — used when predictions.jsonl is empty or sparse.

    Args:
        positions: Raw position records from paper_positions.jsonl.
        proposals_by_id: Proposal dict keyed by proposal_id.
        resolution_map: market_id → outcome mapping.
        time_window: Optional timedelta for filtering.

    Returns:
        List of valid CalibrationPoints.
    """
    now_utc = datetime.now(timezone.utc)
    cutoff = (now_utc - time_window) if time_window else None

    points: List[CalibrationPoint] = []

    for pos in positions:
        status = pos.get("status", "")
        if status != "RESOLVED":
            continue

        market_id = pos.get("market_id")
        if not market_id or market_id not in resolution_map:
            continue

        proposal_id = pos.get("proposal_id", "")
        proposal = proposals_by_id.get(proposal_id, {})

        # Get model probability from proposal
        model_prob = proposal.get("model_probability")
        if model_prob is None:
            continue

        try:
            prob = float(model_prob)
        except (TypeError, ValueError):
            continue

        if not (0.0 <= prob <= 1.0):
            continue

        # Time window
        entry_time = pos.get("entry_time", "")
        if cutoff and entry_time:
            try:
                ts = datetime.fromisoformat(entry_time.replace("Z", "+00:00"))
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                if ts < cutoff:
                    continue
            except (ValueError, TypeError):
                pass

        confidence = proposal.get("confidence_level")

        point = CalibrationPoint(
            market_id=market_id,
            probability_at_entry=prob,
            actual_outcome=resolution_map[market_id],
            model_type="paper_trade",
            confidence=confidence,
            entry_timestamp=entry_time,
        )

        if is_valid_point(point):
            points.append(point)

    return points


# =============================================================================
# REPORT BUILDING
# =============================================================================


def _build_report(
    points: List[CalibrationPoint],
    time_window_name: str,
) -> Dict[str, Any]:
    """
    Build the full calibration report from valid points.

    Structure:
    {
        "schema_version": 1,
        "generated_at_utc": "<ISO8601>",
        "time_window": "<name>",
        "global": { MetricsBucket },
        "by_model": { model_name: MetricsBucket },
        "by_confidence": { level: MetricsBucket },
        "by_odds_bucket": { bucket: MetricsBucket },
        "governance_notice": "..."
    }

    Args:
        points: All valid calibration points.
        time_window_name: Name of the time window used.

    Returns:
        Report dictionary.
    """
    global_metrics = compute_bucket(points)

    # By model
    by_model = {}
    for model_name, model_points in group_by_model(points).items():
        by_model[model_name] = compute_bucket(model_points).to_dict()

    # By confidence
    by_confidence = {}
    for conf_level, conf_points in group_by_confidence(points).items():
        by_confidence[conf_level] = compute_bucket(conf_points).to_dict()

    # By odds bucket
    by_odds = {}
    for bucket_name, bucket_points in group_by_odds_bucket(points).items():
        by_odds[bucket_name] = compute_bucket(bucket_points).to_dict()

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "time_window": time_window_name,
        "global": global_metrics.to_dict(),
        "by_model": by_model,
        "by_confidence": by_confidence,
        "by_odds_bucket": by_odds,
        "points_excluded_from_analysis": "Points with missing estimates, unresolved markets, or invalid probabilities were excluded.",
        "governance_notice": (
            "This report is ANALYTICS ONLY. It does not influence trading, "
            "execution, thresholds, sizing, or decisions. If this module "
            "influences behavior, the system design has failed."
        ),
    }


# =============================================================================
# CALIBRATION ENGINE
# =============================================================================


class CalibrationEngine:
    """
    Governance-safe calibration engine.

    Answers ONE question: "When we said 60%, how often were we right?"
    Must NEVER answer: "What should we do next?"

    ISOLATION:
    - Reads from: data/outcomes/, data/edge_evolution/, proposals logs
    - Writes to: data/calibration/calibration_report.json
    - No imports from trading, execution, decision, or sizing modules

    FAIL-CLOSED:
    - Missing data → exclude from analysis
    - Ambiguous resolution → exclude
    - Invalid probability → exclude
    """

    def __init__(self, base_dir: Optional[Path] = None):
        """
        Initialize the calibration engine.

        Args:
            base_dir: Project root directory. Defaults to project root.
        """
        if base_dir is None:
            base_dir = Path(__file__).parent.parent
        self.base_dir = Path(base_dir)

    def run(
        self,
        time_window: str = "all_time",
    ) -> Dict[str, Any]:
        """
        Run calibration analysis and produce a report.

        Args:
            time_window: One of "all_time", "last_7d", "last_30d", "last_90d".

        Returns:
            Calibration report dictionary.
        """
        logger.info(f"CalibrationEngine.run | time_window={time_window}")

        window_delta = TIME_WINDOWS.get(time_window)
        if time_window != "all_time" and window_delta is None:
            logger.warning(f"Unknown time_window '{time_window}', using all_time")
            time_window = "all_time"
            window_delta = None

        # Load data (READ-ONLY)
        resolutions = _load_jsonl(self.base_dir / RESOLUTIONS_PATH)
        predictions = _load_jsonl(self.base_dir / PREDICTIONS_PATH)

        resolution_map = _build_resolution_map(resolutions)
        logger.info(f"Loaded {len(resolution_map)} definitive resolutions")

        # Primary source: predictions with our_estimate_yes
        points = _extract_points_from_predictions(
            predictions, resolution_map, window_delta
        )

        # Secondary source: resolved positions + proposals
        if len(points) == 0:
            logger.info("No points from predictions, trying positions + proposals")
            positions = _load_jsonl(
                self.base_dir / "paper_trader" / "logs" / "paper_positions.jsonl"
            )
            proposals_data = _load_json(
                self.base_dir / PROPOSALS_LOG_PATH
            )
            proposals_list = (proposals_data or {}).get("proposals", [])
            proposals_by_id = {
                p.get("proposal_id", ""): p for p in proposals_list
            }
            position_points = _extract_points_from_positions(
                positions, proposals_by_id, resolution_map, window_delta
            )
            points.extend(position_points)

        # Deduplicate by market_id (keep first occurrence)
        seen: set = set()
        deduped: List[CalibrationPoint] = []
        for p in points:
            if p.market_id not in seen:
                seen.add(p.market_id)
                deduped.append(p)
        points = deduped

        logger.info(f"Total calibration points after dedup: {len(points)}")

        # Build report
        report = _build_report(points, time_window)

        return report

    def run_and_save(
        self,
        time_window: str = "all_time",
    ) -> Tuple[Dict[str, Any], Path]:
        """
        Run calibration and save report to JSON file.

        Args:
            time_window: Time window for analysis.

        Returns:
            Tuple of (report dict, output path).
        """
        report = self.run(time_window)

        output_path = self.base_dir / REPORT_OUTPUT_PATH
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)

        logger.info(f"Calibration report saved to {output_path}")
        return report, output_path


# =============================================================================
# MODULE-LEVEL CONVENIENCE
# =============================================================================


def build_calibration_report(
    time_window: str = "all_time",
    base_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """
    Build and save a calibration report.

    Args:
        time_window: Time window for analysis.
        base_dir: Project root directory.

    Returns:
        Calibration report dictionary.
    """
    engine = CalibrationEngine(base_dir)
    report, _ = engine.run_and_save(time_window)
    return report
