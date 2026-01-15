# =============================================================================
# POLYMARKET BEOBACHTER - EXECUTION AUDIT LOGGER
# =============================================================================
#
# GOVERNANCE INTENT:
# This module provides APPEND-ONLY audit logging for all execution actions.
# Logs are IMMUTABLE - no deletion, no modification.
#
# LOG FORMAT:
# JSONL (JSON Lines) - one JSON object per line.
# This format is append-only friendly and easy to parse.
#
# LOG ENTRIES:
# Each entry contains:
# - timestamp: ISO format timestamp
# - proposal_id: The proposal being acted upon
# - action: PREPARE / DRY_RUN / EXECUTE_ATTEMPT
# - outcome: SUCCESS / BLOCKED / FAILED
# - reason: Human-readable explanation
# - metadata: Additional context (policy, validation, etc.)
#
# ABSOLUTE CONSTRAINTS:
# - No deletion of log entries
# - No modification of log entries
# - All actions must be logged BEFORE execution
#
# =============================================================================

import json
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional, Dict, Any


# =============================================================================
# LOG CONSTANTS
# =============================================================================

# Default log file path
DEFAULT_LOG_PATH = Path(__file__).parent / "execution_log.jsonl"


# =============================================================================
# LOG ENUMS
# =============================================================================


class ExecutionAction(Enum):
    """
    Types of execution actions that can be logged.

    GOVERNANCE:
    All action types are EXPLICIT and NAMED.
    """
    PREPARE = "PREPARE"          # Preparing execution (validation)
    DRY_RUN = "DRY_RUN"          # Simulated execution
    EXECUTE_ATTEMPT = "EXECUTE_ATTEMPT"  # Attempted (but blocked) execution


class ExecutionOutcome(Enum):
    """
    Outcomes of execution actions.

    GOVERNANCE:
    - SUCCESS: Action completed as expected
    - BLOCKED: Action prevented by policy/validation
    - FAILED: Action failed due to error
    """
    SUCCESS = "SUCCESS"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"


# =============================================================================
# LOG ENTRY
# =============================================================================


@dataclass
class LogEntry:
    """
    Immutable log entry for execution actions.

    GOVERNANCE:
    All fields are explicit. No hidden state.
    """
    timestamp: str
    proposal_id: str
    action: str
    outcome: str
    reason: str
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> str:
        """Serialize to JSON string (single line)."""
        return json.dumps(asdict(self), ensure_ascii=False)

    @classmethod
    def from_json(cls, json_str: str) -> "LogEntry":
        """Deserialize from JSON string."""
        data = json.loads(json_str)
        return cls(**data)


# =============================================================================
# EXECUTION LOGGER
# =============================================================================


class ExecutionLogger:
    """
    Append-only audit logger for execution actions.

    GOVERNANCE:
    - All writes are APPEND-ONLY
    - No log entry can be deleted
    - No log entry can be modified
    - Log file is JSONL format
    """

    def __init__(self, log_path: Optional[Path] = None):
        """
        Initialize logger.

        Args:
            log_path: Path to log file. Defaults to execution_log.jsonl
        """
        self.log_path = log_path or DEFAULT_LOG_PATH
        self._ensure_log_exists()

    def _ensure_log_exists(self):
        """Ensure log file exists with header comment."""
        if not self.log_path.exists():
            # Create parent directories if needed
            self.log_path.parent.mkdir(parents=True, exist_ok=True)

            # Write header as first line (JSON object with metadata)
            header = {
                "_type": "LOG_HEADER",
                "created_at": datetime.now().isoformat(),
                "description": "Append-only execution audit log",
                "format": "JSONL (one JSON object per line)",
                "governance_notice": (
                    "This log is part of the audit trail. "
                    "Do not delete or modify entries."
                )
            }
            with open(self.log_path, 'w', encoding='utf-8') as f:
                f.write(json.dumps(header, ensure_ascii=False) + '\n')

    def _append_entry(self, entry: LogEntry):
        """
        Append a log entry to the file.

        GOVERNANCE:
        This is the ONLY write method. It ONLY appends.

        Args:
            entry: The LogEntry to append
        """
        with open(self.log_path, 'a', encoding='utf-8') as f:
            f.write(entry.to_json() + '\n')

    def log_prepare(
        self,
        proposal_id: str,
        outcome: ExecutionOutcome,
        reason: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> LogEntry:
        """
        Log a PREPARE action.

        Args:
            proposal_id: The proposal being prepared
            outcome: SUCCESS or BLOCKED
            reason: Explanation of outcome
            metadata: Additional context

        Returns:
            The logged entry
        """
        entry = LogEntry(
            timestamp=datetime.now().isoformat(),
            proposal_id=proposal_id,
            action=ExecutionAction.PREPARE.value,
            outcome=outcome.value,
            reason=reason,
            metadata=metadata or {}
        )
        self._append_entry(entry)
        return entry

    def log_dry_run(
        self,
        proposal_id: str,
        outcome: ExecutionOutcome,
        reason: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> LogEntry:
        """
        Log a DRY_RUN action.

        Args:
            proposal_id: The proposal being dry-run
            outcome: SUCCESS (dry-run completed)
            reason: Summary of dry-run
            metadata: Dry-run details

        Returns:
            The logged entry
        """
        entry = LogEntry(
            timestamp=datetime.now().isoformat(),
            proposal_id=proposal_id,
            action=ExecutionAction.DRY_RUN.value,
            outcome=outcome.value,
            reason=reason,
            metadata=metadata or {}
        )
        self._append_entry(entry)
        return entry

    def log_execute_attempt(
        self,
        proposal_id: str,
        reason: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> LogEntry:
        """
        Log an EXECUTE_ATTEMPT action.

        GOVERNANCE:
        Execute attempts are ALWAYS blocked.
        The outcome is ALWAYS BLOCKED.

        Args:
            proposal_id: The proposal that attempted execution
            reason: Why execution was attempted
            metadata: Additional context

        Returns:
            The logged entry
        """
        entry = LogEntry(
            timestamp=datetime.now().isoformat(),
            proposal_id=proposal_id,
            action=ExecutionAction.EXECUTE_ATTEMPT.value,
            outcome=ExecutionOutcome.BLOCKED.value,
            reason="Execution blocked by policy: " + reason,
            metadata={
                **(metadata or {}),
                "governance_notice": "Live execution is disabled by policy"
            }
        )
        self._append_entry(entry)
        return entry

    def read_all_entries(self) -> list:
        """
        Read all log entries.

        GOVERNANCE:
        This is a READ-ONLY operation.

        Returns:
            List of LogEntry objects
        """
        entries = []
        if not self.log_path.exists():
            return entries

        with open(self.log_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    # Skip header
                    if data.get("_type") == "LOG_HEADER":
                        continue
                    entries.append(LogEntry.from_json(line))
                except (json.JSONDecodeError, TypeError):
                    continue

        return entries

    def get_entries_for_proposal(self, proposal_id: str) -> list:
        """
        Get all log entries for a specific proposal.

        Args:
            proposal_id: The proposal ID to filter by

        Returns:
            List of LogEntry objects for that proposal
        """
        all_entries = self.read_all_entries()
        return [e for e in all_entries if e.proposal_id == proposal_id]

    def count_execute_attempts(self) -> int:
        """
        Count the number of execute attempts.

        GOVERNANCE:
        This is for audit purposes - tracking how often
        execution was attempted (and blocked).

        Returns:
            Number of EXECUTE_ATTEMPT entries
        """
        all_entries = self.read_all_entries()
        return sum(
            1 for e in all_entries
            if e.action == ExecutionAction.EXECUTE_ATTEMPT.value
        )


# =============================================================================
# MODULE-LEVEL LOGGER INSTANCE
# =============================================================================

_logger_instance: Optional[ExecutionLogger] = None


def get_logger() -> ExecutionLogger:
    """
    Get the global logger instance.

    GOVERNANCE:
    Singleton pattern ensures consistent logging.
    """
    global _logger_instance
    if _logger_instance is None:
        _logger_instance = ExecutionLogger()
    return _logger_instance


def log_prepare(
    proposal_id: str,
    outcome: ExecutionOutcome,
    reason: str,
    metadata: Optional[Dict[str, Any]] = None
) -> LogEntry:
    """Convenience function for logging PREPARE."""
    return get_logger().log_prepare(proposal_id, outcome, reason, metadata)


def log_dry_run(
    proposal_id: str,
    outcome: ExecutionOutcome,
    reason: str,
    metadata: Optional[Dict[str, Any]] = None
) -> LogEntry:
    """Convenience function for logging DRY_RUN."""
    return get_logger().log_dry_run(proposal_id, outcome, reason, metadata)


def log_execute_attempt(
    proposal_id: str,
    reason: str,
    metadata: Optional[Dict[str, Any]] = None
) -> LogEntry:
    """Convenience function for logging EXECUTE_ATTEMPT."""
    return get_logger().log_execute_attempt(proposal_id, reason, metadata)
