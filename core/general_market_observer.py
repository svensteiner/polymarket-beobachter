# =============================================================================
# GENERAL MARKET OBSERVER
# =============================================================================
#
# Scans all non-weather Polymarket markets for LLM-computed edge.
# Paper trading enabled when config/modules.yaml → general_market_observer.settings.paper_trade=true
#
# Logs to: output/general_market_observations.jsonl
# Summary: output/general_market_summary.json
# =============================================================================

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

OBSERVATIONS_LOG = "output/general_market_observations.jsonl"
SUMMARY_FILE = "output/general_market_summary.json"

# Minimum edge to include in observations
MIN_EDGE_THRESHOLD = 0.12
# High-confidence threshold (flag for future paper trading)
HIGH_EDGE_THRESHOLD = 0.20


def _is_paper_trade_enabled() -> bool:
    """Read paper_trade flag from config/modules.yaml."""
    try:
        import yaml
        modules_path = Path(__file__).parents[1] / "config" / "modules.yaml"
        data = yaml.safe_load(modules_path.read_text(encoding="utf-8"))
        return bool(
            (data or {})
            .get("general_market_observer", {})
            .get("settings", {})
            .get("paper_trade", False)
        )
    except Exception:
        return False


def _load_collected_markets(base_dir: Path) -> List[Dict[str, Any]]:
    """Load the most recently collected markets from the collector's storage."""
    # Try multiple possible locations
    candidates = [
        base_dir / "data" / "markets_latest.json",
        base_dir / "data" / "collector_latest.json",
    ]

    # Also check for the latest collector run directory
    collector_dir = base_dir / "data" / "collector"
    if collector_dir.exists():
        run_dirs = sorted(
            [d for d in collector_dir.iterdir() if d.is_dir()],
            key=lambda d: d.stat().st_mtime,
            reverse=True,
        )
        for run_dir in run_dirs[:3]:
            candidates.append(run_dir / "markets.json")
            candidates.append(run_dir / "raw_markets.json")

    for path in candidates:
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    return data
                if isinstance(data, dict) and "markets" in data:
                    return data["markets"]
            except Exception as e:
                logger.debug("Could not load %s: %s", path, e)

    return []


def run_general_market_observation(
    base_dir: Path,
    markets: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    Run the general market observation pipeline.

    Args:
        base_dir: Bot root directory
        markets: Pre-loaded markets (optional). If None, loads from disk.

    Returns:
        Summary dict with counts and top observations.
    """
    from .llm_general_evaluator import evaluate_market_batch

    # Load markets if not provided
    if markets is None:
        markets = _load_collected_markets(base_dir)

    if not markets:
        logger.info("[GeneralMarket] No markets available for observation")
        return {"status": "no_markets", "evaluated": 0, "observations": 0}

    # Filter out weather markets before passing to evaluator
    non_weather = [
        m for m in markets
        if (m.get("category") or "").upper() not in {"WEATHER"}
    ]
    logger.info("[GeneralMarket] %d/%d non-weather markets to evaluate", len(non_weather), len(markets))

    if not non_weather:
        return {"status": "no_non_weather_markets", "evaluated": 0, "observations": 0}

    # Evaluate with LLM (capped at 15 markets to limit cost)
    results = evaluate_market_batch(non_weather, max_markets=15)

    # Log observations
    obs_path = base_dir / OBSERVATIONS_LOG
    obs_path.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).isoformat()

    written = 0
    for r in results:
        entry = {
            "ts": ts,
            "market_id": r.market_id,
            "question": r.question,
            "yes_price": r.market_yes_price,
            "llm_prob": r.llm_yes_probability,
            "edge": r.edge,
            "abs_edge": r.abs_edge,
            "side": r.side,
            "confidence": r.confidence,
            "category": r.category,
            "reasoning": r.reasoning,
            "high_edge": r.abs_edge >= HIGH_EDGE_THRESHOLD,
        }
        with (obs_path).open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
        written += 1

    # Paper trading: convert high-edge HIGH-confidence results to proposals
    high_edge = [r for r in results if r.abs_edge >= HIGH_EDGE_THRESHOLD]
    paper_trade_enabled = _is_paper_trade_enabled()
    proposals_written = 0
    if paper_trade_enabled and high_edge:
        try:
            from proposals.signal_adapter import general_eval_to_proposal
            from proposals.storage import get_storage
            storage = get_storage()
            for r in high_edge:
                proposal = general_eval_to_proposal(r)
                if proposal is not None:
                    storage.save_proposal(proposal)
                    proposals_written += 1
                    logger.info(
                        "[GeneralMarket] Paper proposal: %s (%s edge=%.2f)",
                        r.question[:60], r.side, r.abs_edge,
                    )
        except Exception as e:
            logger.warning("[GeneralMarket] Paper trade write failed: %s", e)

    summary = {
        "generated_at": ts,
        "total_markets_seen": len(markets),
        "non_weather_evaluated": len(non_weather),
        "observations_with_edge": written,
        "high_edge_count": len(high_edge),
        "paper_proposals_written": proposals_written,
        "mode": "PAPER_TRADE" if paper_trade_enabled else "OBSERVE_ONLY",
        "top_opportunities": [
            {
                "market_id": r.market_id,
                "question": r.question[:100],
                "yes_price": r.market_yes_price,
                "llm_prob": r.llm_yes_probability,
                "edge": r.edge,
                "side": r.side,
                "confidence": r.confidence,
                "category": r.category,
            }
            for r in results[:5]
        ],
    }

    summary_path = base_dir / SUMMARY_FILE
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    if high_edge:
        logger.info(
            "[GeneralMarket] %d high-edge opportunities found (>= %.0f%% edge): %s",
            len(high_edge),
            HIGH_EDGE_THRESHOLD * 100,
            ", ".join(f"{r.question[:40]}... ({r.side} edge={r.abs_edge:.2f})" for r in high_edge[:3]),
        )
    else:
        logger.info("[GeneralMarket] %d observations logged, no high-edge yet", written)

    return summary
