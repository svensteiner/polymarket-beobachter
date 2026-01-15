# =============================================================================
# POLYMARKET EU AI COLLECTOR
# Module: collector/storage.py
# Purpose: File storage for raw, normalized, and candidate market data
# =============================================================================
#
# STORAGE STRUCTURE:
# data/collector/
# ├── raw/<date>/           - Raw API responses (sanitized)
# ├── normalized/<date>/    - Normalized records (all)
# ├── candidates/<date>/    - Clean + complete records only
# └── reports/<date>/       - Run reports
#
# FILE FORMATS:
# - Raw: markets_<timestamp>.json
# - Normalized: markets.jsonl
# - Candidates: candidates.jsonl
# - Reports: report.md
#
# =============================================================================

import os
import json
import logging
from datetime import datetime, date
from typing import Dict, Any, List, Optional
from pathlib import Path

from .normalizer import NormalizedMarket

logger = logging.getLogger(__name__)


class StorageManager:
    """
    Manages file storage for collector output.

    Creates date-partitioned directories and writes JSON/JSONL files.
    """

    def __init__(
        self,
        base_dir: str = "data/collector",
        run_date: Optional[date] = None,
    ):
        """
        Initialize storage manager.

        Args:
            base_dir: Base directory for all collector data
            run_date: Date for partitioning (defaults to today)
        """
        self.base_dir = Path(base_dir)
        self.run_date = run_date or date.today()
        self.date_str = self.run_date.isoformat()

        # Directory paths
        self.raw_dir = self.base_dir / "raw" / self.date_str
        self.normalized_dir = self.base_dir / "normalized" / self.date_str
        self.candidates_dir = self.base_dir / "candidates" / self.date_str
        self.reports_dir = self.base_dir / "reports" / self.date_str

    def ensure_directories(self) -> None:
        """Create all required directories if they don't exist."""
        for directory in [
            self.raw_dir,
            self.normalized_dir,
            self.candidates_dir,
            self.reports_dir,
        ]:
            directory.mkdir(parents=True, exist_ok=True)
            logger.debug(f"Ensured directory exists: {directory}")

    def save_raw_response(
        self,
        data: List[Dict[str, Any]],
        filename: Optional[str] = None,
    ) -> Path:
        """
        Save raw (sanitized) API response.

        Args:
            data: Sanitized market data
            filename: Optional custom filename

        Returns:
            Path to saved file
        """
        if filename is None:
            timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            filename = f"markets_{timestamp}.json"

        filepath = self.raw_dir / filename

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        logger.info(f"Saved raw response: {filepath} ({len(data)} markets)")
        return filepath

    def save_normalized_markets(
        self,
        markets: List[NormalizedMarket],
        filename: str = "markets.jsonl",
    ) -> Path:
        """
        Save normalized markets as JSONL.

        Args:
            markets: List of normalized market records
            filename: Output filename

        Returns:
            Path to saved file
        """
        filepath = self.normalized_dir / filename

        with open(filepath, "w", encoding="utf-8") as f:
            for market in markets:
                line = json.dumps(market.to_dict(), ensure_ascii=False)
                f.write(line + "\n")

        logger.info(f"Saved normalized markets: {filepath} ({len(markets)} records)")
        return filepath

    def save_candidates(
        self,
        candidates: List[NormalizedMarket],
        filename: str = "candidates.jsonl",
    ) -> Path:
        """
        Save candidate markets (clean + complete only).

        Args:
            candidates: List of candidate market records
            filename: Output filename

        Returns:
            Path to saved file
        """
        filepath = self.candidates_dir / filename

        with open(filepath, "w", encoding="utf-8") as f:
            for candidate in candidates:
                line = json.dumps(candidate.to_dict(), ensure_ascii=False)
                f.write(line + "\n")

        logger.info(f"Saved candidates: {filepath} ({len(candidates)} records)")
        return filepath

    def save_report(
        self,
        report_content: str,
        filename: str = "report.md",
    ) -> Path:
        """
        Save run report.

        Args:
            report_content: Markdown report content
            filename: Output filename

        Returns:
            Path to saved file
        """
        filepath = self.reports_dir / filename

        with open(filepath, "w", encoding="utf-8") as f:
            f.write(report_content)

        logger.info(f"Saved report: {filepath}")
        return filepath

    def load_raw_response(self, filename: str) -> List[Dict[str, Any]]:
        """
        Load a raw response file.

        Args:
            filename: Filename to load

        Returns:
            List of market dictionaries
        """
        filepath = self.raw_dir / filename

        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)

    def load_candidates(self, filename: str = "candidates.jsonl") -> List[Dict[str, Any]]:
        """
        Load candidates file.

        Args:
            filename: Filename to load

        Returns:
            List of candidate dictionaries
        """
        filepath = self.candidates_dir / filename
        candidates = []

        with open(filepath, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    candidates.append(json.loads(line))

        return candidates

    def get_storage_summary(self) -> Dict[str, Any]:
        """
        Get summary of stored files.

        Returns:
            Dictionary with file counts and paths
        """
        def count_files(directory: Path, pattern: str = "*") -> int:
            if directory.exists():
                return len(list(directory.glob(pattern)))
            return 0

        return {
            "base_dir": str(self.base_dir),
            "run_date": self.date_str,
            "raw_files": count_files(self.raw_dir, "*.json"),
            "normalized_files": count_files(self.normalized_dir, "*.jsonl"),
            "candidate_files": count_files(self.candidates_dir, "*.jsonl"),
            "report_files": count_files(self.reports_dir, "*.md"),
        }
