# =============================================================================
# POLYMARKET EU AI COLLECTOR
# Module: collector/__main__.py
# Purpose: CLI entry point for running the collector
# =============================================================================
#
# USAGE:
# python -m collector.collect --out-dir data/collector --max 200
#
# OPTIONS:
# --out-dir    Base output directory (default: data/collector)
# --max        Maximum markets to fetch (default: 200)
# --since      Only markets created after this date (ISO format)
# --keywords   Override keyword list (comma-separated)
# --dry-run    Don't write files, just report
# --verbose    Enable debug logging
#
# =============================================================================

import argparse
import logging
import sys
from datetime import date

from .collector import Collector


def setup_logging(verbose: bool = False) -> None:
    """Configure logging for CLI."""
    level = logging.DEBUG if verbose else logging.INFO
    format_str = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"

    logging.basicConfig(
        level=level,
        format=format_str,
        handlers=[
            logging.StreamHandler(sys.stdout),
        ],
    )

    # Reduce noise from urllib3
    logging.getLogger("urllib3").setLevel(logging.WARNING)


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        prog="python -m collector",
        description="Polymarket EU AI Collector - Discover and store candidate markets",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m collector --max 100
  python -m collector --out-dir ./output --dry-run
  python -m collector --keywords "GDPR,DSA,DMA"
  python -m collector --verbose

Note: This collector does NOT fetch prices, volumes, or probabilities.
      It only discovers and stores market metadata.
        """,
    )

    parser.add_argument(
        "--out-dir",
        type=str,
        default="data/collector",
        help="Base output directory (default: data/collector)",
    )

    parser.add_argument(
        "--max",
        type=int,
        default=200,
        help="Maximum markets to fetch (default: 200)",
    )

    parser.add_argument(
        "--since",
        type=str,
        default=None,
        help="Only markets created after this date (ISO format, e.g., 2024-01-01)",
    )

    parser.add_argument(
        "--keywords",
        type=str,
        default=None,
        help="Override keyword list (comma-separated)",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Don't write files, just report what would be collected",
    )

    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable debug logging",
    )

    return parser.parse_args()


def main() -> int:
    """Main entry point."""
    args = parse_args()

    # Setup logging
    setup_logging(verbose=args.verbose)
    logger = logging.getLogger(__name__)

    # Parse keywords
    custom_keywords = None
    if args.keywords:
        custom_keywords = [k.strip() for k in args.keywords.split(",") if k.strip()]

    # Parse since date
    since_date = None
    if args.since:
        try:
            since_date = date.fromisoformat(args.since)
            logger.info(f"Filtering markets created since: {since_date}")
        except ValueError:
            logger.error(f"Invalid date format for --since: {args.since}")
            return 1

    # Create and run collector
    try:
        collector = Collector(
            output_dir=args.out_dir,
            max_markets=args.max,
            custom_keywords=custom_keywords,
        )

        stats = collector.run(dry_run=args.dry_run)

        # Print final summary
        print("\n" + "=" * 60)
        print("COLLECTION SUMMARY")
        print("=" * 60)
        print(f"Markets fetched:    {stats.total_fetched}")
        print(f"Markets sanitized:  {stats.total_sanitized}")
        print(f"Candidates found:   {stats.total_candidates}")
        print(f"Duration:           {stats.run_duration_seconds:.1f}s")
        print()
        print("Filter breakdown:")
        for result, count in sorted(stats.filter_results.items()):
            print(f"  {result}: {count}")
        print()

        if args.dry_run:
            print("[DRY RUN - No files written]")
        else:
            print(f"Output saved to: {args.out_dir}")

        print("=" * 60)

        return 0

    except KeyboardInterrupt:
        logger.info("Collection interrupted by user")
        return 130

    except Exception as e:
        logger.exception(f"Collection failed: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
