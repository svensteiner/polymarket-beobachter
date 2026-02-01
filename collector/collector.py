# =============================================================================
# POLYMARKET EU AI COLLECTOR
# Module: collector/collector.py
# Purpose: Main collector orchestrating discovery and storage pipeline
# =============================================================================
#
# PIPELINE:
# 1. Fetch markets from Polymarket API
# 2. Sanitize (strip forbidden fields)
# 3. Filter for EU + AI relevance
# 4. Normalize to standard format
# 5. Save raw, normalized, and candidate records
# 6. Generate run report
#
# =============================================================================

import logging
from datetime import datetime, date, timezone
from typing import Dict, Any, List, Optional
from dataclasses import dataclass

from .client import PolymarketClient
from .sanitizer import Sanitizer
from .filter import MarketFilter, FilterResult, FilteredMarket
from .normalizer import MarketNormalizer, NormalizedMarket
from .storage import StorageManager

logger = logging.getLogger(__name__)


@dataclass
class CollectorStats:
    """Statistics from a collector run."""
    total_fetched: int
    total_sanitized: int
    total_candidates: int
    filter_results: Dict[str, int]
    fields_removed: Dict[str, int]
    run_duration_seconds: float


class Collector:
    """
    Main collector class orchestrating the discovery pipeline.

    Coordinates:
    - API client for fetching
    - Sanitizer for removing forbidden fields
    - Filter for relevance matching
    - Normalizer for standardization
    - Storage for persistence
    """

    def __init__(
        self,
        output_dir: str = "data/collector",
        max_markets: int = 200,
        custom_keywords: Optional[List[str]] = None,
    ):
        """
        Initialize the collector.

        Args:
            output_dir: Base directory for output
            max_markets: Maximum markets to fetch
            custom_keywords: Optional custom keyword overrides
        """
        self.output_dir = output_dir
        self.max_markets = max_markets

        # Initialize components
        self.client = PolymarketClient()
        self.sanitizer = Sanitizer(log_removals=False)

        # Parse custom keywords if provided
        eu_keywords = None
        ai_keywords = None
        if custom_keywords:
            eu_keywords = [k for k in custom_keywords if "eu" in k.lower() or "european" in k.lower()]
            ai_keywords = [k for k in custom_keywords if k not in (eu_keywords or [])]

        self.filter = MarketFilter(
            custom_eu_keywords=eu_keywords,
            custom_ai_keywords=ai_keywords,
        )

        self.normalizer = MarketNormalizer()
        self.storage = StorageManager(base_dir=output_dir)

    def run(self, dry_run: bool = False) -> CollectorStats:
        """
        Execute the full collection pipeline.

        Args:
            dry_run: If True, don't write files

        Returns:
            CollectorStats with run statistics
        """
        start_time = datetime.now(timezone.utc)
        logger.info("=" * 60)
        logger.info("POLYMARKET EU AI COLLECTOR - Starting run")
        logger.info(f"Max markets: {self.max_markets}")
        logger.info(f"Output dir: {self.output_dir}")
        logger.info(f"Dry run: {dry_run}")
        logger.info("=" * 60)

        # Create directories
        if not dry_run:
            self.storage.ensure_directories()

        # Step 1: Fetch markets (only OPEN markets, not closed)
        logger.info("Step 1: Fetching markets from Polymarket API...")
        raw_markets = self.client.fetch_all_markets(
            max_markets=self.max_markets,
            closed=False,  # Only fetch active/open markets
        )
        logger.info(f"Fetched {len(raw_markets)} markets")

        # Step 2: Sanitize
        logger.info("Step 2: Sanitizing (removing forbidden fields)...")
        sanitized_markets, fields_removed = self.sanitizer.sanitize_markets(raw_markets)
        logger.info(f"Sanitized {len(sanitized_markets)} markets")
        if fields_removed:
            logger.info(f"Removed {sum(fields_removed.values())} forbidden field occurrences")

        # Save raw (sanitized) response
        if not dry_run:
            self.storage.save_raw_response(sanitized_markets)

        # Step 3: Filter for relevance
        logger.info("Step 3: Filtering for EU + AI relevance...")
        filtered_markets, filter_stats = self.filter.filter_markets(sanitized_markets)
        logger.info(f"Filter results: {filter_stats}")

        # Step 4: Normalize all markets
        logger.info("Step 4: Normalizing market data...")
        all_normalized: List[NormalizedMarket] = []
        candidates: List[NormalizedMarket] = []

        # Map FilterResult to category names
        RESULT_TO_CATEGORY = {
            FilterResult.INCLUDED: "EU_REGULATION",
            FilterResult.INCLUDED_CORPORATE: "CORPORATE_EVENT",
            FilterResult.INCLUDED_COURT: "COURT_RULING",
            FilterResult.INCLUDED_WEATHER: "WEATHER_EVENT",
            FilterResult.INCLUDED_POLITICAL: "POLITICAL_EVENT",
            FilterResult.INCLUDED_CRYPTO: "CRYPTO_EVENT",
            FilterResult.INCLUDED_FINANCE: "FINANCE_EVENT",
            FilterResult.INCLUDED_GENERAL: "GENERAL_EVENT",
        }

        for fm in filtered_markets:
            normalized = self.normalizer.normalize(
                market=fm.market,
                extracted_deadline=fm.extracted_deadline,
                notes=fm.notes,
            )

            # Override category based on filter result
            if fm.result in RESULT_TO_CATEGORY:
                # Create new NormalizedMarket with updated category
                normalized = NormalizedMarket(
                    market_id=normalized.market_id,
                    title=normalized.title,
                    resolution_text=normalized.resolution_text,
                    end_date=normalized.end_date,
                    created_time=normalized.created_time,
                    category=RESULT_TO_CATEGORY[fm.result],
                    tags=normalized.tags,
                    url=normalized.url,
                    collector_notes=normalized.collector_notes,
                    collected_at=normalized.collected_at,
                )

            all_normalized.append(normalized)

            # Include complete + relevant markets as candidates
            # Accept all INCLUDED_* filter results
            if fm.result in (
                FilterResult.INCLUDED,
                FilterResult.INCLUDED_CORPORATE,
                FilterResult.INCLUDED_COURT,
                FilterResult.INCLUDED_WEATHER,
                FilterResult.INCLUDED_POLITICAL,
                FilterResult.INCLUDED_CRYPTO,
                FilterResult.INCLUDED_FINANCE,
                FilterResult.INCLUDED_GENERAL,
            ) and normalized.is_complete():
                candidates.append(normalized)

        logger.info(f"Normalized {len(all_normalized)} markets")
        logger.info(f"Found {len(candidates)} candidates")

        # Step 5: Save outputs
        if not dry_run:
            logger.info("Step 5: Saving outputs...")
            self.storage.save_normalized_markets(all_normalized)
            self.storage.save_candidates(candidates)

        # Step 6: Generate report
        end_time = datetime.now(timezone.utc)
        duration = (end_time - start_time).total_seconds()

        stats = CollectorStats(
            total_fetched=len(raw_markets),
            total_sanitized=len(sanitized_markets),
            total_candidates=len(candidates),
            filter_results=filter_stats,
            fields_removed=fields_removed,
            run_duration_seconds=duration,
        )

        report = self._generate_report(stats, candidates, filtered_markets)

        if not dry_run:
            self.storage.save_report(report)

        # Print summary
        logger.info("=" * 60)
        logger.info("COLLECTION COMPLETE")
        logger.info(f"Duration: {duration:.1f}s")
        logger.info(f"Fetched: {stats.total_fetched}")
        logger.info(f"Candidates: {stats.total_candidates}")
        logger.info("=" * 60)

        return stats

    def _generate_report(
        self,
        stats: CollectorStats,
        candidates: List[NormalizedMarket],
        filtered: List[FilteredMarket],
    ) -> str:
        """
        Generate markdown run report.

        Args:
            stats: Run statistics
            candidates: List of candidate markets
            filtered: List of filtered market results

        Returns:
            Markdown report string
        """
        lines = [
            "# Polymarket EU AI Collector - Run Report",
            "",
            f"**Run Date:** {date.today().isoformat()}",
            f"**Run Time:** {datetime.now(timezone.utc).isoformat()}",
            f"**Duration:** {stats.run_duration_seconds:.1f} seconds",
            "",
            "## Summary",
            "",
            f"- **Total Fetched:** {stats.total_fetched}",
            f"- **Total Sanitized:** {stats.total_sanitized}",
            f"- **Total Candidates:** {stats.total_candidates}",
            "",
            "## Filter Results",
            "",
            "| Result | Count |",
            "|--------|-------|",
        ]

        for result, count in sorted(stats.filter_results.items()):
            lines.append(f"| {result} | {count} |")

        lines.extend([
            "",
            "## Forbidden Fields Removed",
            "",
        ])

        if stats.fields_removed:
            lines.append("| Field | Occurrences |")
            lines.append("|-------|-------------|")
            for field, count in sorted(stats.fields_removed.items(), key=lambda x: -x[1])[:20]:
                lines.append(f"| {field} | {count} |")
        else:
            lines.append("*No forbidden fields found in API response.*")

        lines.extend([
            "",
            "## Candidates Found",
            "",
        ])

        if candidates:
            for i, candidate in enumerate(candidates[:20], 1):
                lines.append(f"### {i}. {candidate.title[:80]}...")
                lines.append("")
                lines.append(f"- **ID:** `{candidate.market_id}`")
                lines.append(f"- **End Date:** {candidate.end_date}")
                lines.append(f"- **Category:** {candidate.category or 'N/A'}")
                lines.append(f"- **Tags:** {', '.join(candidate.tags) if candidate.tags else 'N/A'}")
                lines.append(f"- **URL:** {candidate.url}")
                if candidate.collector_notes:
                    lines.append(f"- **Notes:** {', '.join(candidate.collector_notes)}")
                lines.append("")

            if len(candidates) > 20:
                lines.append(f"*... and {len(candidates) - 20} more candidates*")
        else:
            lines.append("*No candidates found matching EU + AI criteria.*")

        lines.extend([
            "",
            "## Exclusion Reasons",
            "",
        ])

        # Sample excluded markets by reason
        exclusion_samples: Dict[str, List[str]] = {}
        for fm in filtered:
            if fm.result != FilterResult.INCLUDED:
                reason = fm.result.value
                title = fm.market.get("question", "Unknown")[:60]
                if reason not in exclusion_samples:
                    exclusion_samples[reason] = []
                if len(exclusion_samples[reason]) < 3:
                    exclusion_samples[reason].append(title)

        for reason, samples in sorted(exclusion_samples.items()):
            lines.append(f"### {reason}")
            lines.append("")
            for sample in samples:
                lines.append(f"- {sample}...")
            lines.append("")

        lines.extend([
            "",
            "---",
            "",
            "*This report was generated automatically by the Polymarket EU AI Collector.*",
            "*No price, volume, or probability data was collected or stored.*",
        ])

        return "\n".join(lines)
