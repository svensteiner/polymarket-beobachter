#!/usr/bin/env python3
# =============================================================================
# OUTCOME TRACKER CLI
# =============================================================================
#
# Command-line interface for the Outcome Tracker module.
#
# COMMANDS:
#   snapshot-now       - Capture prediction snapshots for recent evaluations
#   update-resolutions - Check unresolved markets and record new resolutions
#   rebuild-index      - Rebuild the derived index from JSONL files
#   stats              - Show basic statistics
#   list-unresolved    - List markets with predictions but no resolution
#
# USAGE:
#   python tools/outcome_tracker_cli.py stats
#   python tools/outcome_tracker_cli.py snapshot-now
#   python tools/outcome_tracker_cli.py update-resolutions
#   python tools/outcome_tracker_cli.py rebuild-index
#
# =============================================================================

import argparse
import json
import logging
import sys
from datetime import datetime, date
from pathlib import Path

# Setup paths
BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR))

from core.outcome_tracker import (
    OutcomeStorage,
    IndexBuilder,
    ResolutionChecker,
    create_prediction_snapshot,
    get_stats,
    get_storage,
    generate_event_id,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger(__name__)


# =============================================================================
# CLI COMMANDS
# =============================================================================


def cmd_stats(args):
    """Show basic statistics."""
    storage = get_storage(BASE_DIR)
    stats = storage.get_stats()

    print("\n" + "=" * 50)
    print("OUTCOME TRACKER STATISTICS")
    print("=" * 50)
    print(f"\nTotal Predictions:  {stats['total_predictions']}")
    print(f"Total Resolutions:  {stats['total_resolutions']}")
    print(f"Total Corrections:  {stats['total_corrections']}")
    print(f"\nUnique Markets Predicted: {stats['unique_markets_predicted']}")
    print(f"Resolved Markets:         {stats['resolved_markets']}")
    print(f"Unresolved Markets:       {stats['unresolved_markets']}")
    print(f"Coverage:                 {stats['coverage_pct']:.1f}%")

    if stats['decisions']:
        print("\nDecisions:")
        for decision, count in sorted(stats['decisions'].items()):
            print(f"  {decision}: {count}")

    if stats['resolutions']:
        print("\nResolutions:")
        for resolution, count in sorted(stats['resolutions'].items()):
            print(f"  {resolution}: {count}")

    print()
    return 0


def cmd_snapshot_now(args):
    """Capture prediction snapshots for recent evaluations."""
    storage = get_storage(BASE_DIR)

    print("\n" + "=" * 50)
    print("SNAPSHOT CAPTURE")
    print("=" * 50)

    # Load today's candidates from collector output
    today_str = date.today().isoformat()
    candidates_file = BASE_DIR / "data" / "collector" / "candidates" / today_str / "candidates.jsonl"

    if not candidates_file.exists():
        print(f"\nNo candidates file found for today: {candidates_file}")
        print("Run the collector first to generate candidates.")
        return 1

    # Load candidates
    candidates = []
    try:
        with open(candidates_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    candidates.append(json.loads(line))
    except Exception as e:
        print(f"\nError loading candidates: {e}")
        return 1

    print(f"\nFound {len(candidates)} candidates from today")

    if not candidates:
        print("No candidates to snapshot.")
        return 0

    # Load today's audit log to get decision information
    audit_file = BASE_DIR / "logs" / "audit" / f"pipeline_{today_str}.jsonl"
    analyses = {}

    if audit_file.exists():
        try:
            with open(audit_file, "r", encoding="utf-8") as f:
                for line in f:
                    entry = json.loads(line.strip())
                    if entry.get("event") == "PIPELINE_RUN":
                        steps = entry.get("steps", [])
                        for step in steps:
                            if step.get("name") == "analyzer":
                                for analysis in step.get("data", {}).get("analyses", []):
                                    market_id = analysis.get("market_id")
                                    if market_id:
                                        analyses[market_id] = analysis
        except Exception as e:
            logger.warning(f"Could not load audit log: {e}")

    # Generate run_id for this snapshot session
    run_id = f"cli_snapshot_{generate_event_id()[:8]}"

    # Snapshot each candidate
    recorded = 0
    skipped = 0
    errors = 0

    for candidate in candidates[:args.limit]:
        market_id = candidate.get("market_id") or candidate.get("condition_id")
        if not market_id:
            errors += 1
            continue

        # Get analysis if available
        analysis = analyses.get(market_id, {})
        decision = analysis.get("decision", "INSUFFICIENT_DATA")
        confidence = analysis.get("confidence")
        blocking = analysis.get("blocking_criteria", [])

        # Build reasons
        reasons = []
        if blocking:
            reasons = [f"Blocked: {c}" for c in blocking[:3]]
        elif decision == "TRADE":
            reasons = ["All criteria passed"]
        else:
            reasons = ["Analyzed by baseline engine"]

        try:
            snapshot = create_prediction_snapshot(
                market_id=market_id,
                question=candidate.get("title", "Unknown"),
                decision=decision,
                decision_reasons=reasons,
                engine="baseline",
                mode="SHADOW",  # CLI snapshots are always informational
                run_id=run_id,
                source="cli",
                market_price_yes=candidate.get("probability"),
                our_estimate_yes=None,  # We don't have estimates in basic mode
                estimate_confidence=confidence,
            )

            success, msg = storage.write_prediction(snapshot)
            if success:
                recorded += 1
            else:
                skipped += 1
                if args.verbose:
                    print(f"  Skipped: {msg}")

        except Exception as e:
            errors += 1
            if args.verbose:
                print(f"  Error for {market_id}: {e}")

    print(f"\nResults:")
    print(f"  Recorded: {recorded}")
    print(f"  Skipped (duplicates): {skipped}")
    print(f"  Errors: {errors}")
    print()

    return 0


def cmd_update_resolutions(args):
    """Check unresolved markets and record new resolutions."""
    storage = get_storage(BASE_DIR)
    checker = ResolutionChecker(storage)

    print("\n" + "=" * 50)
    print("RESOLUTION UPDATE")
    print("=" * 50)

    unresolved = storage.get_unresolved_market_ids()
    print(f"\nUnresolved markets: {len(unresolved)}")

    if not unresolved:
        print("No unresolved markets to check.")
        return 0

    print(f"Checking up to {args.limit} markets...\n")

    result = checker.update_resolutions(max_checks=args.limit)

    print(f"Results:")
    print(f"  Checked: {result['checked']}")
    print(f"  New resolutions: {result['new_resolutions']}")
    print(f"  Errors: {result.get('errors', 0)}")
    print(f"  Remaining unresolved: {result.get('remaining_unresolved', 0)}")
    print()

    return 0


def cmd_rebuild_index(args):
    """Rebuild the derived index from JSONL files."""
    storage = get_storage(BASE_DIR)
    builder = IndexBuilder(storage)

    print("\n" + "=" * 50)
    print("INDEX REBUILD")
    print("=" * 50)

    print("\nRebuilding index from JSONL files...")
    index = builder.rebuild()

    print(f"\nIndex rebuilt successfully:")
    print(f"  Entries: {len(index.get('entries', []))}")
    print(f"  Built at: {index.get('built_at', 'unknown')}")
    print(f"  Output: {storage.index_file}")
    print()

    return 0


def cmd_list_unresolved(args):
    """List markets with predictions but no resolution."""
    storage = get_storage(BASE_DIR)
    predictions = storage.read_predictions()

    # Group by market_id
    by_market = {}
    for pred in predictions:
        if pred.market_id not in by_market:
            by_market[pred.market_id] = []
        by_market[pred.market_id].append(pred)

    # Get resolved
    resolved_ids = {r.market_id for r in storage.read_resolutions()}

    # Filter unresolved
    unresolved = {k: v for k, v in by_market.items() if k not in resolved_ids}

    print("\n" + "=" * 50)
    print("UNRESOLVED MARKETS")
    print("=" * 50)
    print(f"\nTotal unresolved: {len(unresolved)}")

    if not unresolved:
        print("All predicted markets have been resolved.")
        return 0

    # Calculate age
    now = datetime.utcnow()
    entries = []
    for market_id, preds in unresolved.items():
        oldest = min(p.timestamp_utc for p in preds)
        try:
            oldest_dt = datetime.fromisoformat(oldest.replace("Z", "+00:00").replace("+00:00", ""))
            age_days = (now - oldest_dt).days
        except (ValueError, TypeError):
            age_days = -1

        # Get question from first prediction
        question = preds[0].question[:50] if preds else "Unknown"
        entries.append((market_id, question, age_days, len(preds)))

    # Sort by age (oldest first)
    entries.sort(key=lambda x: x[2], reverse=True)

    print("\n{:<16} {:<50} {:>8} {:>6}".format("Market ID", "Question", "Age (d)", "Preds"))
    print("-" * 84)

    for market_id, question, age, count in entries[:args.limit]:
        age_str = str(age) if age >= 0 else "?"
        print(f"{market_id[:16]:<16} {question:<50} {age_str:>8} {count:>6}")

    if len(entries) > args.limit:
        print(f"\n... and {len(entries) - args.limit} more")

    print()
    return 0


def cmd_verify_hashes(args):
    """Verify record hashes for integrity."""
    from core.outcome_tracker import compute_hash

    storage = get_storage(BASE_DIR)

    print("\n" + "=" * 50)
    print("HASH VERIFICATION")
    print("=" * 50)

    # Check predictions
    predictions = storage.read_predictions()
    pred_valid = 0
    pred_invalid = 0

    for pred in predictions:
        expected = compute_hash(pred.to_dict())
        if pred.record_hash == expected:
            pred_valid += 1
        else:
            pred_invalid += 1
            if args.verbose:
                print(f"  Invalid hash: prediction {pred.event_id}")

    # Check resolutions
    resolutions = storage.read_resolutions()
    res_valid = 0
    res_invalid = 0

    for res in resolutions:
        expected = compute_hash(res.to_dict())
        if res.record_hash == expected:
            res_valid += 1
        else:
            res_invalid += 1
            if args.verbose:
                print(f"  Invalid hash: resolution {res.event_id}")

    print(f"\nPredictions:")
    print(f"  Valid: {pred_valid}")
    print(f"  Invalid: {pred_invalid}")

    print(f"\nResolutions:")
    print(f"  Valid: {res_valid}")
    print(f"  Invalid: {res_invalid}")

    total_invalid = pred_invalid + res_invalid
    if total_invalid > 0:
        print(f"\n{total_invalid} records have invalid hashes!")
        return 1
    else:
        print(f"\nAll {pred_valid + res_valid} records verified.")
        return 0


# =============================================================================
# MAIN
# =============================================================================


def main():
    parser = argparse.ArgumentParser(
        description="Outcome Tracker CLI - Record predictions and resolutions",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
ISOLATION STATEMENT:
This tool records FACTS only. It does NOT influence trading decisions.
It has NO imports from decision_engine or panic_contrarian_engine.

Examples:
  python tools/outcome_tracker_cli.py stats
  python tools/outcome_tracker_cli.py snapshot-now
  python tools/outcome_tracker_cli.py update-resolutions --limit 20
  python tools/outcome_tracker_cli.py rebuild-index
  python tools/outcome_tracker_cli.py list-unresolved
  python tools/outcome_tracker_cli.py verify-hashes
        """
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # stats
    stats_parser = subparsers.add_parser("stats", help="Show basic statistics")
    stats_parser.set_defaults(func=cmd_stats)

    # snapshot-now
    snapshot_parser = subparsers.add_parser(
        "snapshot-now",
        help="Capture prediction snapshots for recent evaluations"
    )
    snapshot_parser.add_argument(
        "--limit", type=int, default=100,
        help="Maximum candidates to snapshot (default: 100)"
    )
    snapshot_parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Show verbose output"
    )
    snapshot_parser.set_defaults(func=cmd_snapshot_now)

    # update-resolutions
    update_parser = subparsers.add_parser(
        "update-resolutions",
        help="Check unresolved markets and record new resolutions"
    )
    update_parser.add_argument(
        "--limit", type=int, default=50,
        help="Maximum markets to check (default: 50)"
    )
    update_parser.set_defaults(func=cmd_update_resolutions)

    # rebuild-index
    rebuild_parser = subparsers.add_parser(
        "rebuild-index",
        help="Rebuild the derived index from JSONL files"
    )
    rebuild_parser.set_defaults(func=cmd_rebuild_index)

    # list-unresolved
    list_parser = subparsers.add_parser(
        "list-unresolved",
        help="List markets with predictions but no resolution"
    )
    list_parser.add_argument(
        "--limit", type=int, default=20,
        help="Maximum entries to show (default: 20)"
    )
    list_parser.set_defaults(func=cmd_list_unresolved)

    # verify-hashes
    verify_parser = subparsers.add_parser(
        "verify-hashes",
        help="Verify record hashes for integrity"
    )
    verify_parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Show verbose output"
    )
    verify_parser.set_defaults(func=cmd_verify_hashes)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
