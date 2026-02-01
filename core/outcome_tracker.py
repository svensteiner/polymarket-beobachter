# =============================================================================
# POLYMARKET BEOBACHTER - OUTCOME TRACKER
# =============================================================================
#
# MODULE #1 OF THE LEARNING SYSTEM
#
# PURPOSE:
# Track predictions and their outcomes to enable calibration analysis.
# This module records FACTS only - it does NOT influence trading decisions.
#
# ISOLATION GUARANTEES:
# - NO imports from decision_engine or panic_contrarian_engine
# - NO network writes (only reads for resolution checking)
# - NO parameter changes or threshold modifications
# - READ-ONLY regarding strategy and execution
#
# STORAGE:
# - Append-only JSONL files (once written, never edited)
# - Corrections are separate records, not overwrites
# - Full audit trail with hashes
#
# FAIL-CLOSED PRINCIPLE:
# If anything is unclear, ambiguous, or invalid -> write nothing.
#
# =============================================================================

import hashlib
import json
import logging
import os
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

# =============================================================================
# CONSTANTS
# =============================================================================

SCHEMA_VERSION = 1

# Storage paths (relative to BASE_DIR)
OUTCOMES_DIR = "data/outcomes"
PREDICTIONS_FILE = "predictions.jsonl"
RESOLUTIONS_FILE = "resolutions.jsonl"
CORRECTIONS_FILE = "corrections.jsonl"
INDEX_FILE = "index.json"

# Valid resolution values
VALID_RESOLUTIONS = {"YES", "NO", "INVALID", "CANCELLED", "AMBIGUOUS"}

# Valid decision values
VALID_DECISIONS = {"TRADE", "NO_TRADE", "INSUFFICIENT_DATA"}

# Valid confidence levels
VALID_CONFIDENCE_LEVELS = {"LOW", "MEDIUM", "HIGH", None}


# =============================================================================
# ENUMS (local to avoid importing from decision_engine)
# =============================================================================


class RecordType(Enum):
    """Type of record in the outcome tracker."""
    PREDICTION = "PREDICTION"
    RESOLUTION = "RESOLUTION"
    CORRECTION = "CORRECTION"


# =============================================================================
# DATA CLASSES
# =============================================================================


@dataclass
class EngineContext:
    """Context about which engine produced the prediction."""
    engine: str  # e.g., "baseline", "panic_contrarian_engine"
    mode: str  # e.g., "DISABLED", "SHADOW", "PAPER", "ARMED", "LIVE"
    run_id: str  # Unique identifier for the run

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class PredictionSnapshot:
    """
    A snapshot of a prediction at a point in time.

    IMMUTABLE once created and written.
    """
    schema_version: int
    event_id: str
    timestamp_utc: str
    market_id: str
    question: str
    outcomes: List[str]  # e.g., ["YES", "NO"]
    market_price_yes: Optional[float]
    market_price_no: Optional[float]
    our_estimate_yes: Optional[float]
    estimate_confidence: Optional[str]  # "LOW", "MEDIUM", "HIGH", or None
    decision: str  # "TRADE", "NO_TRADE", "INSUFFICIENT_DATA"
    decision_reasons: List[str]
    engine_context: EngineContext
    source: str  # "scheduler" or "cli"
    record_hash: str = ""

    def __post_init__(self):
        """Validate fields after initialization."""
        errors = self.validate()
        if errors:
            raise ValueError(f"Invalid PredictionSnapshot: {'; '.join(errors)}")

    def validate(self) -> List[str]:
        """Validate all fields. Returns list of errors."""
        errors = []

        if self.schema_version != SCHEMA_VERSION:
            errors.append(f"schema_version must be {SCHEMA_VERSION}, got {self.schema_version}")

        if not self.event_id:
            errors.append("event_id is required")

        if not self.timestamp_utc:
            errors.append("timestamp_utc is required")

        if not self.market_id:
            errors.append("market_id is required")

        if not self.question:
            errors.append("question is required")

        if not self.outcomes or not isinstance(self.outcomes, list):
            errors.append("outcomes must be a non-empty list")

        # Validate probabilities are in valid range
        if self.market_price_yes is not None:
            if not isinstance(self.market_price_yes, (int, float)):
                errors.append("market_price_yes must be numeric or null")
            elif not (0.0 <= self.market_price_yes <= 1.0):
                errors.append(f"market_price_yes must be 0-1, got {self.market_price_yes}")

        if self.market_price_no is not None:
            if not isinstance(self.market_price_no, (int, float)):
                errors.append("market_price_no must be numeric or null")
            elif not (0.0 <= self.market_price_no <= 1.0):
                errors.append(f"market_price_no must be 0-1, got {self.market_price_no}")

        if self.our_estimate_yes is not None:
            if not isinstance(self.our_estimate_yes, (int, float)):
                errors.append("our_estimate_yes must be numeric or null")
            elif not (0.0 <= self.our_estimate_yes <= 1.0):
                errors.append(f"our_estimate_yes must be 0-1, got {self.our_estimate_yes}")

        if self.estimate_confidence not in VALID_CONFIDENCE_LEVELS:
            errors.append(f"estimate_confidence must be one of {VALID_CONFIDENCE_LEVELS}")

        if self.decision not in VALID_DECISIONS:
            errors.append(f"decision must be one of {VALID_DECISIONS}")

        if not isinstance(self.decision_reasons, list):
            errors.append("decision_reasons must be a list")

        if self.source not in ("scheduler", "cli", "manual"):
            errors.append(f"source must be 'scheduler', 'cli', or 'manual', got {self.source}")

        return errors

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "schema_version": self.schema_version,
            "event_id": self.event_id,
            "timestamp_utc": self.timestamp_utc,
            "market_id": self.market_id,
            "question": self.question,
            "outcomes": self.outcomes,
            "market_price_yes": self.market_price_yes,
            "market_price_no": self.market_price_no,
            "our_estimate_yes": self.our_estimate_yes,
            "estimate_confidence": self.estimate_confidence,
            "decision": self.decision,
            "decision_reasons": self.decision_reasons,
            "engine_context": self.engine_context.to_dict(),
            "source": self.source,
            "record_hash": self.record_hash,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PredictionSnapshot":
        """Create from dictionary."""
        engine_ctx = EngineContext(**data.get("engine_context", {}))
        return cls(
            schema_version=data.get("schema_version", SCHEMA_VERSION),
            event_id=data.get("event_id", ""),
            timestamp_utc=data.get("timestamp_utc", ""),
            market_id=data.get("market_id", ""),
            question=data.get("question", ""),
            outcomes=data.get("outcomes", []),
            market_price_yes=data.get("market_price_yes"),
            market_price_no=data.get("market_price_no"),
            our_estimate_yes=data.get("our_estimate_yes"),
            estimate_confidence=data.get("estimate_confidence"),
            decision=data.get("decision", ""),
            decision_reasons=data.get("decision_reasons", []),
            engine_context=engine_ctx,
            source=data.get("source", ""),
            record_hash=data.get("record_hash", ""),
        )


@dataclass
class ResolutionRecord:
    """
    Record of a market resolution.

    IMMUTABLE once created and written.
    """
    schema_version: int
    event_id: str
    timestamp_utc: str
    market_id: str
    resolved: bool
    resolution: str  # "YES", "NO", "INVALID", "CANCELLED", "AMBIGUOUS"
    resolution_source: str  # API field/path or URL
    resolved_timestamp_utc: Optional[str]
    record_hash: str = ""

    def __post_init__(self):
        """Validate fields after initialization."""
        errors = self.validate()
        if errors:
            raise ValueError(f"Invalid ResolutionRecord: {'; '.join(errors)}")

    def validate(self) -> List[str]:
        """Validate all fields. Returns list of errors."""
        errors = []

        if self.schema_version != SCHEMA_VERSION:
            errors.append(f"schema_version must be {SCHEMA_VERSION}")

        if not self.event_id:
            errors.append("event_id is required")

        if not self.timestamp_utc:
            errors.append("timestamp_utc is required")

        if not self.market_id:
            errors.append("market_id is required")

        if not isinstance(self.resolved, bool):
            errors.append("resolved must be a boolean")

        if self.resolved and self.resolution not in VALID_RESOLUTIONS:
            errors.append(f"resolution must be one of {VALID_RESOLUTIONS}")

        if not self.resolution_source:
            errors.append("resolution_source is required")

        return errors

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "schema_version": self.schema_version,
            "event_id": self.event_id,
            "timestamp_utc": self.timestamp_utc,
            "market_id": self.market_id,
            "resolved": self.resolved,
            "resolution": self.resolution,
            "resolution_source": self.resolution_source,
            "resolved_timestamp_utc": self.resolved_timestamp_utc,
            "record_hash": self.record_hash,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ResolutionRecord":
        """Create from dictionary."""
        return cls(
            schema_version=data.get("schema_version", SCHEMA_VERSION),
            event_id=data.get("event_id", ""),
            timestamp_utc=data.get("timestamp_utc", ""),
            market_id=data.get("market_id", ""),
            resolved=data.get("resolved", False),
            resolution=data.get("resolution", ""),
            resolution_source=data.get("resolution_source", ""),
            resolved_timestamp_utc=data.get("resolved_timestamp_utc"),
            record_hash=data.get("record_hash", ""),
        )


@dataclass
class CorrectionRecord:
    """
    Record of a correction to a previous record.

    Corrections do NOT modify the original record.
    They are applied during index rebuild.
    """
    schema_version: int
    event_id: str
    timestamp_utc: str
    target_event_id: str  # The event_id being corrected
    reason: str
    patch: Dict[str, Any]  # Fields to override
    record_hash: str = ""

    def __post_init__(self):
        """Validate fields after initialization."""
        errors = self.validate()
        if errors:
            raise ValueError(f"Invalid CorrectionRecord: {'; '.join(errors)}")

    def validate(self) -> List[str]:
        """Validate all fields. Returns list of errors."""
        errors = []

        if self.schema_version != SCHEMA_VERSION:
            errors.append(f"schema_version must be {SCHEMA_VERSION}")

        if not self.event_id:
            errors.append("event_id is required")

        if not self.timestamp_utc:
            errors.append("timestamp_utc is required")

        if not self.target_event_id:
            errors.append("target_event_id is required")

        if not self.reason:
            errors.append("reason is required")

        if not isinstance(self.patch, dict):
            errors.append("patch must be a dictionary")

        return errors

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "schema_version": self.schema_version,
            "event_id": self.event_id,
            "timestamp_utc": self.timestamp_utc,
            "target_event_id": self.target_event_id,
            "reason": self.reason,
            "patch": self.patch,
            "record_hash": self.record_hash,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CorrectionRecord":
        """Create from dictionary."""
        return cls(
            schema_version=data.get("schema_version", SCHEMA_VERSION),
            event_id=data.get("event_id", ""),
            timestamp_utc=data.get("timestamp_utc", ""),
            target_event_id=data.get("target_event_id", ""),
            reason=data.get("reason", ""),
            patch=data.get("patch", {}),
            record_hash=data.get("record_hash", ""),
        )


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

    The hash field is excluded from the hash computation.
    """
    # Create copy without hash fields
    data_copy = {k: v for k, v in data.items() if k != "record_hash"}
    canonical = canonical_json(data_copy)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def generate_event_id() -> str:
    """Generate a unique event ID."""
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
# STORAGE CLASS
# =============================================================================


class OutcomeStorage:
    """
    Append-only storage for outcome tracking.

    GUARANTEES:
    - Records are only appended, never modified
    - Each write includes a SHA256 hash for integrity
    - Atomic writes (write line + newline together)
    - Deduplication prevents duplicate records
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
        self.outcomes_dir = self.base_dir / OUTCOMES_DIR
        self.predictions_file = self.outcomes_dir / PREDICTIONS_FILE
        self.resolutions_file = self.outcomes_dir / RESOLUTIONS_FILE
        self.corrections_file = self.outcomes_dir / CORRECTIONS_FILE
        self.index_file = self.outcomes_dir / INDEX_FILE

        # Ensure directory exists
        self.outcomes_dir.mkdir(parents=True, exist_ok=True)

        # Caches for deduplication
        self._prediction_keys: Optional[Set[str]] = None
        self._resolved_markets: Optional[Set[str]] = None

    def _ensure_cache_loaded(self):
        """Load caches from files if not already loaded."""
        if self._prediction_keys is None:
            self._prediction_keys = set()
            self._resolved_markets = set()

            # Load existing predictions for dedup
            for pred in self.read_predictions():
                key = self._prediction_dedup_key(pred)
                self._prediction_keys.add(key)

            # Load existing resolutions for dedup
            for res in self.read_resolutions():
                self._resolved_markets.add(res.market_id)

    def _prediction_dedup_key(self, pred: PredictionSnapshot) -> str:
        """
        Generate deduplication key for a prediction.

        Key components:
        - market_id
        - minute bucket of timestamp
        - engine
        - decision
        """
        minute_bucket = get_minute_bucket(pred.timestamp_utc)
        return f"{pred.market_id}|{minute_bucket}|{pred.engine_context.engine}|{pred.decision}"

    def _write_record(self, file_path: Path, data: Dict[str, Any]) -> bool:
        """
        Write a single record to a JSONL file atomically.

        Returns True if successful, False otherwise.
        """
        try:
            line = json.dumps(data, separators=(",", ":")) + "\n"
            with open(file_path, "a", encoding="utf-8") as f:
                f.write(line)
            return True
        except Exception as e:
            logger.error(f"Failed to write record to {file_path}: {e}")
            return False

    def write_prediction(self, snapshot: PredictionSnapshot) -> Tuple[bool, str]:
        """
        Write a prediction snapshot.

        Returns:
            Tuple of (success, message)

        DEDUPLICATION:
        If an identical prediction (same market_id, minute bucket, engine, decision)
        already exists, the write is skipped.
        """
        self._ensure_cache_loaded()

        # Check for duplicate
        key = self._prediction_dedup_key(snapshot)
        if key in self._prediction_keys:
            return False, f"Duplicate prediction skipped: {snapshot.market_id}"

        # Convert to dict and compute hash
        data = snapshot.to_dict()
        data["record_hash"] = compute_hash(data)

        # Write atomically
        if self._write_record(self.predictions_file, data):
            self._prediction_keys.add(key)
            logger.info(f"Prediction recorded: {snapshot.market_id} | {snapshot.decision}")
            return True, f"Prediction recorded: {snapshot.market_id}"
        else:
            return False, f"Failed to write prediction: {snapshot.market_id}"

    def write_resolution(self, resolution: ResolutionRecord) -> Tuple[bool, str]:
        """
        Write a resolution record.

        Returns:
            Tuple of (success, message)

        DEDUPLICATION:
        If a resolution for this market_id already exists, the write is skipped.
        """
        self._ensure_cache_loaded()

        # Check for duplicate
        if resolution.market_id in self._resolved_markets:
            return False, f"Resolution already exists for: {resolution.market_id}"

        # Convert to dict and compute hash
        data = resolution.to_dict()
        data["record_hash"] = compute_hash(data)

        # Write atomically
        if self._write_record(self.resolutions_file, data):
            self._resolved_markets.add(resolution.market_id)
            logger.info(f"Resolution recorded: {resolution.market_id} | {resolution.resolution}")
            return True, f"Resolution recorded: {resolution.market_id}"
        else:
            return False, f"Failed to write resolution: {resolution.market_id}"

    def write_correction(self, correction: CorrectionRecord) -> Tuple[bool, str]:
        """
        Write a correction record.

        Returns:
            Tuple of (success, message)
        """
        # Convert to dict and compute hash
        data = correction.to_dict()
        data["record_hash"] = compute_hash(data)

        # Write atomically
        if self._write_record(self.corrections_file, data):
            logger.info(f"Correction recorded for: {correction.target_event_id}")
            return True, f"Correction recorded for: {correction.target_event_id}"
        else:
            return False, f"Failed to write correction for: {correction.target_event_id}"

    def read_predictions(self) -> List[PredictionSnapshot]:
        """Read all prediction records."""
        predictions = []
        if not self.predictions_file.exists():
            return predictions

        try:
            with open(self.predictions_file, "r", encoding="utf-8") as f:
                for line_num, line in enumerate(f, 1):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                        pred = PredictionSnapshot.from_dict(data)
                        predictions.append(pred)
                    except (json.JSONDecodeError, ValueError) as e:
                        logger.warning(f"Invalid prediction at line {line_num}: {e}")
        except Exception as e:
            logger.error(f"Error reading predictions: {e}")

        return predictions

    def read_resolutions(self) -> List[ResolutionRecord]:
        """Read all resolution records."""
        resolutions = []
        if not self.resolutions_file.exists():
            return resolutions

        try:
            with open(self.resolutions_file, "r", encoding="utf-8") as f:
                for line_num, line in enumerate(f, 1):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                        res = ResolutionRecord.from_dict(data)
                        resolutions.append(res)
                    except (json.JSONDecodeError, ValueError) as e:
                        logger.warning(f"Invalid resolution at line {line_num}: {e}")
        except Exception as e:
            logger.error(f"Error reading resolutions: {e}")

        return resolutions

    def read_corrections(self) -> List[CorrectionRecord]:
        """Read all correction records."""
        corrections = []
        if not self.corrections_file.exists():
            return corrections

        try:
            with open(self.corrections_file, "r", encoding="utf-8") as f:
                for line_num, line in enumerate(f, 1):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                        corr = CorrectionRecord.from_dict(data)
                        corrections.append(corr)
                    except (json.JSONDecodeError, ValueError) as e:
                        logger.warning(f"Invalid correction at line {line_num}: {e}")
        except Exception as e:
            logger.error(f"Error reading corrections: {e}")

        return corrections

    def get_unresolved_market_ids(self) -> Set[str]:
        """
        Get market IDs that have predictions but no resolution.

        Returns:
            Set of market IDs
        """
        self._ensure_cache_loaded()

        # Get all market IDs with predictions
        prediction_market_ids = set()
        for pred in self.read_predictions():
            prediction_market_ids.add(pred.market_id)

        # Subtract resolved ones
        return prediction_market_ids - self._resolved_markets

    def get_stats(self) -> Dict[str, Any]:
        """
        Get basic statistics.

        Returns:
            Dict with counts and coverage
        """
        predictions = self.read_predictions()
        resolutions = self.read_resolutions()
        corrections = self.read_corrections()

        # Count unique markets
        prediction_markets = {p.market_id for p in predictions}
        resolved_markets = {r.market_id for r in resolutions}
        unresolved = prediction_markets - resolved_markets

        # Count by decision
        decisions = {}
        for p in predictions:
            decisions[p.decision] = decisions.get(p.decision, 0) + 1

        # Count by resolution
        resolution_counts = {}
        for r in resolutions:
            resolution_counts[r.resolution] = resolution_counts.get(r.resolution, 0) + 1

        return {
            "total_predictions": len(predictions),
            "total_resolutions": len(resolutions),
            "total_corrections": len(corrections),
            "unique_markets_predicted": len(prediction_markets),
            "resolved_markets": len(resolved_markets),
            "unresolved_markets": len(unresolved),
            "coverage_pct": (len(resolved_markets) / len(prediction_markets) * 100)
                           if prediction_markets else 0.0,
            "decisions": decisions,
            "resolutions": resolution_counts,
        }


# =============================================================================
# INDEX BUILDER
# =============================================================================


class IndexBuilder:
    """
    Builds a derived index from JSONL files.

    The index is a convenience structure for quick lookups.
    It can always be rebuilt from the source JSONL files.
    """

    def __init__(self, storage: OutcomeStorage):
        self.storage = storage

    def rebuild(self) -> Dict[str, Any]:
        """
        Rebuild the index from JSONL files.

        Applies corrections during the build.

        Returns:
            The rebuilt index
        """
        predictions = self.storage.read_predictions()
        resolutions = self.storage.read_resolutions()
        corrections = self.storage.read_corrections()

        # Build correction map (target_event_id -> list of patches)
        correction_map: Dict[str, List[Dict[str, Any]]] = {}
        for corr in corrections:
            if corr.target_event_id not in correction_map:
                correction_map[corr.target_event_id] = []
            correction_map[corr.target_event_id].append(corr.patch)

        # Build prediction index by market_id
        predictions_by_market: Dict[str, List[Dict[str, Any]]] = {}
        for pred in predictions:
            pred_dict = pred.to_dict()

            # Apply corrections
            if pred.event_id in correction_map:
                for patch in correction_map[pred.event_id]:
                    pred_dict.update(patch)

            if pred.market_id not in predictions_by_market:
                predictions_by_market[pred.market_id] = []
            predictions_by_market[pred.market_id].append(pred_dict)

        # Build resolution index by market_id
        resolutions_by_market: Dict[str, Dict[str, Any]] = {}
        for res in resolutions:
            res_dict = res.to_dict()

            # Apply corrections
            if res.event_id in correction_map:
                for patch in correction_map[res.event_id]:
                    res_dict.update(patch)

            resolutions_by_market[res.market_id] = res_dict

        # Build combined entries
        entries = []
        all_market_ids = set(predictions_by_market.keys()) | set(resolutions_by_market.keys())

        for market_id in sorted(all_market_ids):
            entry = {
                "market_id": market_id,
                "predictions": predictions_by_market.get(market_id, []),
                "resolution": resolutions_by_market.get(market_id),
                "has_resolution": market_id in resolutions_by_market,
            }
            entries.append(entry)

        index = {
            "schema_version": SCHEMA_VERSION,
            "built_at": get_utc_timestamp(),
            "stats": self.storage.get_stats(),
            "entries": entries,
        }

        # Write index
        try:
            with open(self.storage.index_file, "w", encoding="utf-8") as f:
                json.dump(index, f, indent=2)
            logger.info(f"Index rebuilt: {len(entries)} markets")
        except Exception as e:
            logger.error(f"Failed to write index: {e}")

        return index


# =============================================================================
# SNAPSHOT CREATOR
# =============================================================================


def create_prediction_snapshot(
    market_id: str,
    question: str,
    decision: str,
    decision_reasons: List[str],
    engine: str,
    mode: str,
    run_id: str,
    source: str = "scheduler",
    market_price_yes: Optional[float] = None,
    market_price_no: Optional[float] = None,
    our_estimate_yes: Optional[float] = None,
    estimate_confidence: Optional[str] = None,
    outcomes: Optional[List[str]] = None,
) -> PredictionSnapshot:
    """
    Factory function to create a PredictionSnapshot.

    Args:
        market_id: Unique market identifier
        question: Market question text
        decision: The decision made (TRADE, NO_TRADE, INSUFFICIENT_DATA)
        decision_reasons: List of reasons for the decision
        engine: Engine that made the decision
        mode: Execution mode (DISABLED, SHADOW, PAPER, etc.)
        run_id: Unique run identifier
        source: Source of the snapshot (scheduler, cli, manual)
        market_price_yes: Market price for YES outcome (0-1)
        market_price_no: Market price for NO outcome (0-1)
        our_estimate_yes: Our probability estimate for YES (0-1)
        estimate_confidence: Confidence level (LOW, MEDIUM, HIGH)
        outcomes: List of possible outcomes (default: ["YES", "NO"])

    Returns:
        A valid PredictionSnapshot
    """
    return PredictionSnapshot(
        schema_version=SCHEMA_VERSION,
        event_id=generate_event_id(),
        timestamp_utc=get_utc_timestamp(),
        market_id=market_id,
        question=question,
        outcomes=outcomes or ["YES", "NO"],
        market_price_yes=market_price_yes,
        market_price_no=market_price_no,
        our_estimate_yes=our_estimate_yes,
        estimate_confidence=estimate_confidence,
        decision=decision,
        decision_reasons=decision_reasons,
        engine_context=EngineContext(
            engine=engine,
            mode=mode,
            run_id=run_id,
        ),
        source=source,
    )


def create_resolution_record(
    market_id: str,
    resolution: str,
    resolution_source: str,
    resolved_timestamp_utc: Optional[str] = None,
) -> ResolutionRecord:
    """
    Factory function to create a ResolutionRecord.

    Args:
        market_id: Unique market identifier
        resolution: Resolution value (YES, NO, INVALID, CANCELLED, AMBIGUOUS)
        resolution_source: Source of the resolution (API path, URL, etc.)
        resolved_timestamp_utc: When the market resolved (optional)

    Returns:
        A valid ResolutionRecord
    """
    return ResolutionRecord(
        schema_version=SCHEMA_VERSION,
        event_id=generate_event_id(),
        timestamp_utc=get_utc_timestamp(),
        market_id=market_id,
        resolved=True,
        resolution=resolution,
        resolution_source=resolution_source,
        resolved_timestamp_utc=resolved_timestamp_utc,
    )


# =============================================================================
# RESOLUTION CHECKER (READ-ONLY)
# =============================================================================


class ResolutionChecker:
    """
    Checks for market resolutions via API.

    READ-ONLY: Only fetches resolution status, never writes to API.
    """

    def __init__(self, storage: OutcomeStorage):
        self.storage = storage

    def check_market_resolution(self, market_id: str) -> Optional[ResolutionRecord]:
        """
        Check if a market has resolved via the Gamma API single-market endpoint.

        Returns:
            ResolutionRecord if resolved, None otherwise

        FAIL-CLOSED: Any error or ambiguity returns None (not resolved).
        """
        try:
            import json as _json
            import ssl
            from urllib.request import urlopen, Request

            url = f"https://gamma-api.polymarket.com/markets/{market_id}"
            ctx = ssl.create_default_context()
            req = Request(url, headers={"User-Agent": "PolymarketBeobachter/1.0"})
            resp = urlopen(req, timeout=10, context=ctx)
            market = _json.loads(resp.read())

            if not market.get("closed"):
                return None

            # Parse outcomePrices and outcomes (both are stringified JSON arrays)
            outcome_prices_raw = market.get("outcomePrices", "[]")
            outcomes_raw = market.get("outcomes", "[]")

            if isinstance(outcome_prices_raw, str):
                outcome_prices = _json.loads(outcome_prices_raw)
            else:
                outcome_prices = outcome_prices_raw

            if isinstance(outcomes_raw, str):
                outcomes = _json.loads(outcomes_raw)
            else:
                outcomes = outcomes_raw

            if not outcome_prices or not outcomes:
                logger.debug(f"Market {market_id} closed but missing price/outcome data")
                return None

            # Find the winning outcome: price closest to 1.0
            prices = [float(p) for p in outcome_prices]
            max_price = max(prices)
            if max_price < 0.9:
                # Not clearly settled (e.g. all prices near 0 = voided/cancelled)
                logger.debug(f"Market {market_id} closed but max price {max_price:.4f} < 0.9, skipping")
                return None

            winner_idx = prices.index(max_price)
            if winner_idx >= len(outcomes):
                return None

            winner = outcomes[winner_idx].strip().upper()
            if winner not in VALID_RESOLUTIONS:
                logger.debug(f"Unknown resolution value for {market_id}: {winner}")
                return None

            return create_resolution_record(
                market_id=market_id,
                resolution=winner,
                resolution_source=f"gamma-api.polymarket.com/markets/{market_id}",
                resolved_timestamp_utc=market.get("updatedAt"),
            )

        except Exception as e:
            logger.warning(f"Failed to check resolution for {market_id}: {e}")
            return None

    def update_resolutions(self, max_checks: int = 50) -> Dict[str, Any]:
        """
        Check unresolved markets and record any new resolutions.

        Args:
            max_checks: Maximum number of markets to check per run

        Returns:
            Summary of the update operation
        """
        unresolved = list(self.storage.get_unresolved_market_ids())

        if not unresolved:
            return {
                "checked": 0,
                "new_resolutions": 0,
                "message": "No unresolved markets to check",
            }

        # Limit checks
        to_check = unresolved[:max_checks]
        new_resolutions = 0
        errors = 0

        for market_id in to_check:
            try:
                resolution = self.check_market_resolution(market_id)
                if resolution:
                    success, _ = self.storage.write_resolution(resolution)
                    if success:
                        new_resolutions += 1
            except Exception as e:
                logger.warning(f"Error checking {market_id}: {e}")
                errors += 1

        return {
            "checked": len(to_check),
            "new_resolutions": new_resolutions,
            "errors": errors,
            "remaining_unresolved": len(unresolved) - new_resolutions,
        }


# =============================================================================
# MODULE-LEVEL CONVENIENCE
# =============================================================================

_storage: Optional[OutcomeStorage] = None


def get_storage(base_dir: Optional[Path] = None) -> OutcomeStorage:
    """Get or create the global storage instance."""
    global _storage
    if _storage is None:
        _storage = OutcomeStorage(base_dir)
    return _storage


def get_stats() -> Dict[str, Any]:
    """Get outcome tracking statistics."""
    return get_storage().get_stats()
