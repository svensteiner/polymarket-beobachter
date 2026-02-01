#!/usr/bin/env python3
"""
Proposal Notifier - Überwacht neue Proposals und sendet Telegram-Benachrichtigungen.

GOVERNANCE:
===========
- Telegram ist INFORMATION ONLY - keine Approve/Deny Buttons
- Nachrichten sind zur AWARENESS, nicht zur Aktion
- Humans müssen Proposals AUSSERHALB des laufenden Systems reviewen
- Proposal-Anwendung erfordert Bot-Shutdown + Restart

USAGE:
    python governance/proposal_notifier.py          # Kontinuierlich
    python governance/proposal_notifier.py --once   # Einmal prüfen
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from shared.telegram_bot import send_message

# =============================================================================
# CONFIGURATION
# =============================================================================

logger = logging.getLogger("proposal_notifier")

# Project root
PROJECT_ROOT = Path(__file__).parent.parent

# Directory where proposals are written
PROPOSALS_DIR = PROJECT_ROOT / "proposals"

# State file to track notified proposals
STATE_FILE = PROJECT_ROOT / "data" / ".notified_proposals.json"

# Check interval in seconds
CHECK_INTERVAL = 60


# =============================================================================
# DATA STRUCTURES
# =============================================================================

@dataclass
class NotifierState:
    """Tracks which proposals have been notified."""
    notified_ids: set[str] = field(default_factory=set)
    last_check: str = ""

    def to_dict(self) -> dict:
        return {
            "notified_ids": list(self.notified_ids),
            "last_check": self.last_check,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "NotifierState":
        return cls(
            notified_ids=set(data.get("notified_ids", [])),
            last_check=data.get("last_check", ""),
        )


# =============================================================================
# STATE MANAGEMENT
# =============================================================================

def load_state() -> NotifierState:
    """Load the notifier state from disk."""
    try:
        if STATE_FILE.exists():
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return NotifierState.from_dict(data)
    except Exception as e:
        logger.warning(f"Could not load state: {e}")
    return NotifierState()


def save_state(state: NotifierState) -> None:
    """Save the notifier state to disk."""
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        state.last_check = datetime.now(timezone.utc).isoformat()
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state.to_dict(), f, indent=2)
    except Exception as e:
        logger.error(f"Could not save state: {e}")


# =============================================================================
# PROPOSAL DISCOVERY
# =============================================================================

def find_proposals() -> list[Path]:
    """Find all proposal JSON files."""
    if not PROPOSALS_DIR.exists():
        return []

    proposals = []

    # Main proposals directory
    for path in PROPOSALS_DIR.glob("*.json"):
        if path.name.startswith("proposal_"):
            proposals.append(path)

    # Also check proposals_log.json
    log_file = PROPOSALS_DIR / "proposals_log.json"
    if log_file.exists():
        proposals.append(log_file)

    return proposals


def get_proposal_id(path: Path) -> str:
    """Extract a unique ID for a proposal file."""
    try:
        mtime = path.stat().st_mtime
        return f"{path.name}_{int(mtime)}"
    except OSError:
        return path.name


def parse_proposal(path: Path) -> Optional[dict[str, Any]]:
    """Parse a proposal JSON file."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"Could not parse {path}: {e}")
        return None


# =============================================================================
# TELEGRAM NOTIFICATION
# =============================================================================

def format_message(path: Path, data: dict[str, Any]) -> str:
    """Format a Telegram notification message."""
    # Determine source
    source = data.get("source", "unknown")
    if "generator" in path.name.lower():
        source = "Generator"
    elif "review" in path.name.lower():
        source = "Review Gate"
    elif "log" in path.name.lower():
        source = "Proposals Log"

    lines = [f"NEW PROPOSAL: {source}"]
    lines.append(f"File: {path.name}")

    # Extract key info from proposal
    if isinstance(data, dict):
        # Single proposal
        if "market_id" in data:
            lines.append(f"Market: {data.get('market_id', 'unknown')[:30]}")
        if "decision" in data:
            lines.append(f"Decision: {data.get('decision')}")
        if "confidence" in data:
            lines.append(f"Confidence: {data.get('confidence')}")
        if "edge" in data:
            lines.append(f"Edge: {data.get('edge'):.1%}")

        # List of proposals
        if "proposals" in data and isinstance(data["proposals"], list):
            lines.append(f"Contains: {len(data['proposals'])} proposals")

        # Reason
        reason = data.get("reason") or data.get("reasoning")
        if reason and isinstance(reason, str):
            lines.append(f"Reason: {reason[:50]}...")

    lines.append("")
    lines.append("HUMAN REVIEW REQUIRED")
    lines.append("Run: python cockpit.py")

    return "\n".join(lines)


def notify_proposal(path: Path, data: dict[str, Any]) -> bool:
    """Send a Telegram notification for a proposal."""
    try:
        message = format_message(path, data)
        send_message(message)
        logger.info(f"Notified: {path.name}")
        return True
    except Exception as e:
        logger.error(f"Notification failed for {path.name}: {e}")
        return False


# =============================================================================
# MAIN LOGIC
# =============================================================================

def check_new_proposals(state: NotifierState) -> int:
    """Check for new proposals and send notifications."""
    proposals = find_proposals()
    new_count = 0

    for path in proposals:
        proposal_id = get_proposal_id(path)

        # Skip if already notified
        if proposal_id in state.notified_ids:
            continue

        # Parse proposal
        data = parse_proposal(path)
        if data is None:
            continue

        # Send notification
        logger.info(f"New proposal: {path.name}")
        if notify_proposal(path, data):
            state.notified_ids.add(proposal_id)
            new_count += 1

    return new_count


def run_notifier(once: bool = False) -> None:
    """Run the proposal notifier."""
    logger.info("=" * 50)
    logger.info("PROPOSAL NOTIFIER STARTED")
    logger.info(f"Watching: {PROPOSALS_DIR}")
    logger.info(f"Mode: {'Single check' if once else 'Continuous'}")
    logger.info("=" * 50)

    state = load_state()

    if once:
        new_count = check_new_proposals(state)
        save_state(state)
        logger.info(f"Check complete. New: {new_count}")
        return

    # Continuous mode
    try:
        while True:
            new_count = check_new_proposals(state)
            if new_count > 0:
                save_state(state)
                logger.info(f"Notified {new_count} new proposal(s)")

            time.sleep(CHECK_INTERVAL)

    except KeyboardInterrupt:
        logger.info("Stopped by user")
        save_state(state)


# =============================================================================
# CLI
# =============================================================================

def main() -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Proposal Notifier - Telegram notifications for new proposals"
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Check once and exit"
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
    )

    try:
        run_notifier(once=args.once)
        return 0
    except Exception as e:
        logger.error(f"Error: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
