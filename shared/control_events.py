# =============================================================================
# POLYMARKET BEOBACHTER - CONTROL EVENTS
# =============================================================================
#
# GOVERNANCE INTENT:
# This module logs control events for audit and debugging.
# Control events track system state changes, guardrail activations, etc.
#
# =============================================================================

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


# Default control events log path
CONTROL_EVENTS_PATH = Path(__file__).parent.parent / "logs" / "control_events.jsonl"


def append_control_event(
    event_type: str,
    data: Optional[Dict[str, Any]] = None,
    log_path: Optional[Path] = None,
) -> None:
    """
    Append a control event to the audit log.

    Args:
        event_type: Type of control event (e.g., "guardrail_activated")
        data: Additional event data
        log_path: Optional custom log path
    """
    path = log_path or CONTROL_EVENTS_PATH
    path.parent.mkdir(parents=True, exist_ok=True)

    event = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event_type": event_type,
        "data": data or {},
    }

    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
    except Exception as e:
        logger.warning("Failed to log control event: %s", e)


def get_recent_events(
    event_type: Optional[str] = None,
    limit: int = 100,
    log_path: Optional[Path] = None,
) -> list:
    """
    Get recent control events from the log.

    Args:
        event_type: Filter by event type (optional)
        limit: Maximum number of events to return
        log_path: Optional custom log path

    Returns:
        List of event dicts
    """
    path = log_path or CONTROL_EVENTS_PATH

    if not path.exists():
        return []

    events = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    event = json.loads(line)
                    if event_type is None or event.get("event_type") == event_type:
                        events.append(event)
    except Exception as e:
        logger.warning("Failed to read control events: %s", e)

    return events[-limit:]
