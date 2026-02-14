# =============================================================================
# WEATHER OBSERVER - COLLECTOR
# =============================================================================
#
# WEATHER-ONLY COLLECTOR
#
# PIPELINE:
# 1. Fetch markets from Polymarket API
# 2. Sanitize (strip forbidden fields)
# 3. Filter for weather relevance
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
    Weather-only collector class.

    Coordinates:
    - API client for fetching
    - Sanitizer for removing forbidden fields
    - Filter for weather relevance matching
    - Normalizer for standardization
    - Storage for persistence
    """

    def __init__(
        self,
        output_dir: str = "data/collector",
        max_markets: int = 200,
    ):
        """
        Initialize the collector.

        Args:
            output_dir: Base directory for output
            max_markets: Maximum markets to fetch
        """
        self.output_dir = output_dir
        self.max_markets = max_markets

        # Initialize components
        self.client = PolymarketClient()
        self.sanitizer = Sanitizer(log_removals=False)
        self.filter = MarketFilter()  # Weather-only filter
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
        logger.info("WEATHER OBSERVER COLLECTOR - Starting run")
        logger.info(f"Max markets: {self.max_markets}")
        logger.info(f"Output dir: {self.output_dir}")
        logger.info(f"Dry run: {dry_run}")
        logger.info("=" * 60)

        # Create directories
        if not dry_run:
            self.storage.ensure_directories()

        # Step 1: Fetch weather markets from events with weather/climate tags
        logger.info("Step 1: Fetching weather markets from Polymarket API...")
        logger.info("  (Using /events?tag_slug=weather and /events?tag_slug=climate)")
        raw_markets = self.client.fetch_weather_markets(
            max_markets=self.max_markets,
            include_closed=False,  # Only fetch active/open markets
        )
        logger.info(f"Fetched {len(raw_markets)} weather-tagged markets")

        # Step 2: Sanitize
        logger.info("Step 2: Sanitizing (removing forbidden fields)...")
        sanitized_markets, fields_removed = self.sanitizer.sanitize_markets(raw_markets)
        logger.info(f"Sanitized {len(sanitized_markets)} markets")
        if fields_removed:
            logger.info(f"Removed {sum(fields_removed.values())} forbidden field occurrences")

        # Save raw (sanitized) response
        if not dry_run:
            self.storage.save_raw_response(sanitized_markets)

        # Step 3: Filter for weather relevance
        logger.info("Step 3: Filtering for weather relevance...")
        filtered_markets, filter_stats = self.filter.filter_markets(sanitized_markets)
        logger.info(f"Filter results: {filter_stats}")

        # Step 4: Normalize all markets
        logger.info("Step 4: Normalizing market data...")
        all_normalized: List[NormalizedMarket] = []
        candidates: List[NormalizedMarket] = []

        for fm in filtered_markets:
            normalized = self.normalizer.normalize(
                market=fm.market,
                notes=fm.notes,
            )

            # Set category for weather markets
            if fm.result == FilterResult.INCLUDED_WEATHER:
                normalized = NormalizedMarket(
                    market_id=normalized.market_id,
                    title=normalized.title,
                    resolution_text=normalized.resolution_text,
                    end_date=normalized.end_date,
                    created_time=normalized.created_time,
                    category="WEATHER_EVENT",
                    tags=normalized.tags,
                    url=normalized.url,
                    collector_notes=normalized.collector_notes + fm.matched_keywords,
                    collected_at=normalized.collected_at,
                )

            all_normalized.append(normalized)

            # Include complete weather markets as candidates
            if fm.result == FilterResult.INCLUDED_WEATHER and normalized.is_complete():
                candidates.append(normalized)

        logger.info(f"Normalized {len(all_normalized)} markets")
        logger.info(f"Found {len(candidates)} weather candidates")

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
        logger.info(f"Weather Candidates: {stats.total_candidates}")
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
            "# Weather Observer Collector - Run Report",
            "",
            f"**Run Date:** {date.today().isoformat()}",
            f"**Run Time:** {datetime.now(timezone.utc).isoformat()}",
            f"**Duration:** {stats.run_duration_seconds:.1f} seconds",
            "",
            "## Summary",
            "",
            f"- **Total Fetched:** {stats.total_fetched}",
            f"- **Total Sanitized:** {stats.total_sanitized}",
            f"- **Weather Candidates:** {stats.total_candidates}",
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
            "## Weather Candidates Found",
            "",
        ])

        if candidates:
            for i, candidate in enumerate(candidates[:20], 1):
                title = candidate.title[:80] if candidate.title else "Unknown"
                lines.append(f"### {i}. {title}...")
                lines.append("")
                lines.append(f"- **ID:** `{candidate.market_id}`")
                lines.append(f"- **End Date:** {candidate.end_date}")
                lines.append(f"- **Category:** {candidate.category or 'N/A'}")
                lines.append(f"- **Tags:** {', '.join(candidate.tags) if candidate.tags else 'N/A'}")
                lines.append(f"- **URL:** {candidate.url}")
                if candidate.collector_notes:
                    lines.append(f"- **Weather Keywords:** {', '.join(candidate.collector_notes[:5])}")
                lines.append("")

            if len(candidates) > 20:
                lines.append(f"*... and {len(candidates) - 20} more candidates*")
        else:
            lines.append("*No weather candidates found.*")

        lines.extend([
            "",
            "## Exclusion Reasons",
            "",
        ])

        # Sample excluded markets by reason
        exclusion_samples: Dict[str, List[str]] = {}
        for fm in filtered:
            if fm.result != FilterResult.INCLUDED_WEATHER:
                reason = fm.result.value
                title = fm.market.get("question", fm.market.get("title", "Unknown"))[:60]
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
            "*This report was generated automatically by the Weather Observer Collector.*",
            "*No price, volume, or probability data was collected or stored.*",
        ])

        return "\n".join(lines)
