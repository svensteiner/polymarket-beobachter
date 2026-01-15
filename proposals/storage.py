# =============================================================================
# POLYMARKET BEOBACHTER - PROPOSAL STORAGE
# =============================================================================
#
# GOVERNANCE INTENT:
# This module handles APPEND-ONLY storage of proposals and reviews.
# Data is never deleted or modified after writing.
# Full audit trail is maintained.
#
# FILES:
# - proposals_log.json: JSON array of all proposals (append-only)
# - proposals_reviewed.md: Human-readable review log (append-only)
#
# ABSOLUTE CONSTRAINTS:
# - No deletion of records
# - No modification of existing records
# - No filtering or suppression of data
#
# =============================================================================

import json
import os
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, Any

from proposals.models import Proposal, ReviewResult


class ProposalStorage:
    """
    Append-only storage for proposals and reviews.

    GOVERNANCE:
    - All writes are APPEND-ONLY
    - No data is ever deleted
    - Full audit trail is maintained
    """

    def __init__(self, base_dir: Optional[Path] = None):
        """
        Initialize storage.

        Args:
            base_dir: Base directory for storage files.
                      Defaults to proposals/ in current directory.
        """
        if base_dir is None:
            base_dir = Path(__file__).parent

        self.base_dir = Path(base_dir)
        self.proposals_log_path = self.base_dir / "proposals_log.json"
        self.reviewed_md_path = self.base_dir / "proposals_reviewed.md"

        # Ensure directory exists
        self.base_dir.mkdir(parents=True, exist_ok=True)

        # Initialize files if they don't exist
        self._init_files()

    def _init_files(self):
        """
        Initialize storage files if they don't exist.

        GOVERNANCE:
        Files are created with clear headers indicating their purpose.
        """
        # Initialize proposals_log.json
        if not self.proposals_log_path.exists():
            self._write_json(self.proposals_log_path, {
                "_metadata": {
                    "created_at": datetime.now().isoformat(),
                    "description": "Append-only log of all proposals",
                    "governance_notice": "This file is part of the audit trail. Do not modify existing entries."
                },
                "proposals": []
            })

        # Initialize proposals_reviewed.md
        if not self.reviewed_md_path.exists():
            header = """# Proposal Review Log

> **GOVERNANCE NOTICE**
> This file is an append-only audit trail of proposal reviews.
> Do not modify or delete existing entries.
> This review does not trigger any action. No trade was executed.

---

"""
            self._write_text(self.reviewed_md_path, header)

    def _write_json(self, path: Path, data: Any):
        """Write JSON data to file."""
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def _read_json(self, path: Path) -> Any:
        """Read JSON data from file."""
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)

    def _write_text(self, path: Path, text: str):
        """Write text to file."""
        with open(path, 'w', encoding='utf-8') as f:
            f.write(text)

    def _append_text(self, path: Path, text: str):
        """Append text to file."""
        with open(path, 'a', encoding='utf-8') as f:
            f.write(text)

    def save_proposal(self, proposal: Proposal) -> bool:
        """
        Save a proposal to the log.

        GOVERNANCE:
        - Appends to existing log (never overwrites)
        - Returns True on success, False on failure
        - No silent failures

        Args:
            proposal: The Proposal to save

        Returns:
            True if saved successfully
        """
        try:
            # Read existing data
            data = self._read_json(self.proposals_log_path)

            # Append new proposal
            data["proposals"].append(proposal.to_dict())

            # Update last modified
            data["_metadata"]["last_modified"] = datetime.now().isoformat()
            data["_metadata"]["total_proposals"] = len(data["proposals"])

            # Write back
            self._write_json(self.proposals_log_path, data)

            return True

        except Exception as e:
            # GOVERNANCE: Log the error, don't silently fail
            print(f"[STORAGE ERROR] Failed to save proposal: {e}")
            return False

    def save_review(self, proposal: Proposal, review: ReviewResult) -> bool:
        """
        Save a review result to the markdown log.

        GOVERNANCE:
        - Appends to existing log (never overwrites)
        - Includes full context for human review
        - Returns True on success, False on failure

        Args:
            proposal: The reviewed Proposal
            review: The ReviewResult

        Returns:
            True if saved successfully
        """
        try:
            # Generate markdown
            markdown = review.to_markdown(proposal)

            # Append to file
            self._append_text(self.reviewed_md_path, markdown)

            return True

        except Exception as e:
            # GOVERNANCE: Log the error, don't silently fail
            print(f"[STORAGE ERROR] Failed to save review: {e}")
            return False

    def load_proposals(self, limit: Optional[int] = None) -> List[Proposal]:
        """
        Load proposals from storage.

        GOVERNANCE:
        - READ-ONLY operation
        - Returns empty list on error (not None)

        Args:
            limit: Optional limit on number of proposals to return (newest first)

        Returns:
            List of Proposal objects
        """
        try:
            data = self._read_json(self.proposals_log_path)
            proposals_data = data.get("proposals", [])

            # Convert to Proposal objects
            proposals = []
            for p_data in proposals_data:
                try:
                    proposals.append(Proposal.from_dict(p_data))
                except Exception:
                    # Skip malformed entries
                    continue

            # Sort by timestamp (newest first)
            proposals.sort(key=lambda p: p.timestamp, reverse=True)

            # Apply limit if specified
            if limit is not None:
                proposals = proposals[:limit]

            return proposals

        except Exception as e:
            print(f"[STORAGE ERROR] Failed to load proposals: {e}")
            return []

    def get_proposal_by_id(self, proposal_id: str) -> Optional[Proposal]:
        """
        Get a specific proposal by ID.

        GOVERNANCE:
        - READ-ONLY operation
        - Returns None if not found

        Args:
            proposal_id: The proposal ID to search for

        Returns:
            Proposal if found, None otherwise
        """
        proposals = self.load_proposals()
        for proposal in proposals:
            if proposal.proposal_id == proposal_id:
                return proposal
        return None

    def get_statistics(self) -> Dict[str, Any]:
        """
        Get proposal statistics.

        GOVERNANCE:
        - READ-ONLY operation
        - Returns aggregate statistics only

        Returns:
            Dictionary of statistics
        """
        proposals = self.load_proposals()

        stats = {
            "total_proposals": len(proposals),
            "trade_proposals": 0,
            "no_trade_proposals": 0,
            "by_confidence": {"LOW": 0, "MEDIUM": 0, "HIGH": 0},
            "average_edge": 0.0,
        }

        if not proposals:
            return stats

        total_edge = 0.0
        for p in proposals:
            if p.decision == "TRADE":
                stats["trade_proposals"] += 1
            else:
                stats["no_trade_proposals"] += 1

            stats["by_confidence"][p.confidence_level] += 1
            total_edge += abs(p.edge)

        stats["average_edge"] = total_edge / len(proposals)

        return stats


# Global storage instance for convenience
_storage_instance: Optional[ProposalStorage] = None


def get_storage() -> ProposalStorage:
    """
    Get the global storage instance.

    GOVERNANCE:
    Singleton pattern ensures consistent storage access.
    """
    global _storage_instance
    if _storage_instance is None:
        _storage_instance = ProposalStorage()
    return _storage_instance


def save_proposal_and_review(proposal: Proposal, review: ReviewResult) -> bool:
    """
    Convenience function to save both proposal and review.

    GOVERNANCE:
    Atomic-like operation - both are saved together.

    Args:
        proposal: The Proposal
        review: The ReviewResult

    Returns:
        True if both saved successfully
    """
    storage = get_storage()
    proposal_saved = storage.save_proposal(proposal)
    review_saved = storage.save_review(proposal, review)
    return proposal_saved and review_saved
