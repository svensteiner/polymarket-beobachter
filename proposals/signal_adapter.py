# =============================================================================
# SIGNAL-TO-PROPOSAL ADAPTER
# =============================================================================
#
# Converts signals from specialized engines (Weather, Arbitrage) into
# analysis dicts that the ProposalGenerator can consume.
#
# This is the WIRING between isolated signal engines and the paper trader.
# Signals become proposals, proposals get reviewed, eligible ones paper-trade.
#
# GOVERNANCE:
# - Read-only on signals (does not modify signal logs)
# - Creates proposals with source tracking (model_type identifies origin)
# - All proposals still go through ReviewGate before paper trading
#
# =============================================================================

import json
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent.parent


# =============================================================================
# WEATHER SIGNAL ADAPTER
# =============================================================================


def weather_signal_to_analysis(signal: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Convert a WeatherSignal (as dict) to an analysis dict for ProposalGenerator.

    Args:
        signal: WeatherSignal dict from logs/weather_signals.jsonl

    Returns:
        Analysis dict or None if signal is not actionable.
    """
    action = signal.get("recommended_action", "")
    if action != "BUY":
        return None

    market_id = signal.get("market_id", "")
    if not market_id:
        return None

    fair_prob = signal.get("fair_probability")
    market_prob = signal.get("market_probability")
    if fair_prob is None or market_prob is None:
        return None

    # Clamp probabilities to valid range
    fair_prob = max(0.0, min(1.0, float(fair_prob)))
    market_prob = max(0.0, min(1.0, float(market_prob)))

    confidence = signal.get("confidence", "MEDIUM")
    city = signal.get("city", "Unknown")
    description = signal.get("event_description", f"Weather signal for {city}")

    return {
        "final_decision": {"outcome": "TRADE"},
        "market_input": {
            "market_id": market_id,
            "market_title": description,
            "market_implied_probability": market_prob,
        },
        "probability_estimate": {
            "probability_midpoint": fair_prob,
            "probability_low": max(0.0, fair_prob - 0.05),
            "probability_high": min(1.0, fair_prob + 0.05),
            "confidence_level": confidence,
            "model_type": "WEATHER_MODEL",
            "assumption": f"NOAA forecast for {city}",
            "data_sources": [signal.get("forecast_source", "NOAA")],
        },
        "market_sanity": {
            "direction": "BUY_YES",
        },
        "edge_calculation": {
            "valid": True,
            "edge": fair_prob - market_prob,
            "direction": "BUY_YES",
        },
    }


# =============================================================================
# ARBITRAGE SIGNAL ADAPTER
# =============================================================================


def arbitrage_signal_to_analysis(signal: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Convert an ArbitrageSignal (as dict) to an analysis dict.

    For BUY_B: we trade the underpriced market B.
    For BUY_A: we trade the underpriced market A.

    Args:
        signal: ArbitrageSignal dict from logs/arbitrage_signals.jsonl

    Returns:
        Analysis dict or None if not actionable.
    """
    if not signal.get("is_actionable", True):
        return None

    action = signal.get("action", "")
    if action not in ("BUY_B", "BUY_A"):
        return None

    if action == "BUY_B":
        target_id = signal.get("market_b_id", "")
        target_question = signal.get("market_b_question", "")
        implied_prob = signal.get("p_b", 0.0)
        # A implies B, so B should be >= A. Use p_a as fair estimate for B.
        model_prob = signal.get("p_a", 0.0)
    else:
        target_id = signal.get("market_a_id", "")
        target_question = signal.get("market_a_question", "")
        implied_prob = signal.get("p_a", 0.0)
        model_prob = signal.get("p_b", 0.0)

    if not target_id:
        return None

    edge = model_prob - implied_prob
    if edge <= 0:
        return None

    return {
        "final_decision": {"outcome": "TRADE"},
        "market_input": {
            "market_id": target_id,
            "market_title": target_question or f"Arbitrage: {target_id}",
            "market_implied_probability": implied_prob,
        },
        "probability_estimate": {
            "probability_midpoint": model_prob,
            "probability_low": max(0.0, model_prob - 0.03),
            "probability_high": min(1.0, model_prob + 0.03),
            "confidence_level": "MEDIUM",
            "model_type": "CROSS_MARKET_ARBITRAGE",
            "assumption": signal.get("reasoning", "Cross-market consistency"),
            "data_sources": ["cross_market_engine"],
        },
        "market_sanity": {
            "direction": "BUY_YES",
        },
        "edge_calculation": {
            "valid": True,
            "edge": edge,
            "direction": "BUY_YES",
        },
    }


# =============================================================================
# SIGNAL LOADERS
# =============================================================================


def load_recent_weather_signals(max_signals: int = 10) -> List[Dict[str, Any]]:
    """Load recent weather signals from log file."""
    path = BASE_DIR / "logs" / "weather_signals.jsonl"
    return _load_recent_jsonl(path, max_signals)


def load_recent_arbitrage_signals(max_signals: int = 10) -> List[Dict[str, Any]]:
    """Load recent arbitrage signals from log file."""
    path = BASE_DIR / "logs" / "arbitrage_signals.jsonl"
    return _load_recent_jsonl(path, max_signals)


def _load_recent_jsonl(path: Path, max_lines: int) -> List[Dict[str, Any]]:
    """Load last N lines from a JSONL file."""
    if not path.exists():
        return []

    lines = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    lines.append(line)
    except Exception as e:
        logger.warning(f"Failed to read {path}: {e}")
        return []

    # Take last N
    recent = lines[-max_lines:]
    results = []
    for line in recent:
        try:
            results.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return results
