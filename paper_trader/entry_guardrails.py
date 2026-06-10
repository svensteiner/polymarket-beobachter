# =============================================================================
# POLYMARKET BEOBACHTER - ENTRY GUARDRAILS
# =============================================================================
#
# GOVERNANCE INTENT:
# Evaluiert ob ein neuer Trade-Entry erlaubt ist basierend auf:
# - Aktuelle Anzahl offener Positionen
# - Max Positionen pro Stadt
# - Entry-Preis Limits
# - Agent Policy Einschränkungen
#
# =============================================================================

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT / "data"
AGENTIC_DIR = PROJECT_ROOT / "agentic"

# Default limits — tightened to match new intelligent strategy
DEFAULT_MAX_OPEN_POSITIONS = 10
DEFAULT_MAX_ENTRY_PRICE = 0.80       # Matches weather.yaml MAX_ODDS
DEFAULT_MIN_ENTRY_PRICE = 0.30       # Allow spring weather YES bets at 30-39%; near-zero lottery trap handled by simulator MIN_YES_ENTRY_PRICE=0.05
DEFAULT_MIN_EDGE = 0.40              # Raised from 0.12: only enter high-confidence divergences
DEFAULT_MIN_EDGE_ABSOLUTE = 0.10     # Raised from 0.05: meaningful absolute gap required
# YES-only relaxed thresholds (2026-04-19 update):
# Lowered from 0.30 → 0.24 after consecutive_zero_edge_runs=2 confirmed zero throughput.
# Evidence: 5/6 YES trades at 30-50% edge WON (80% WR). Extrapolating conservatively
# to 24%+. At 10 EUR position + -40% SL, max downside is ~4 EUR per trade.
YES_MIN_EDGE = 0.24
# YES_MIN_ENTRY_PRICE: 2026-06-04 REVERTED to 0.15 — revert trigger fired.
# Recent (since 2026-05-21): 4 closed YES trades with ep < 0.15 → 0% WR, -7.36 EUR.
# 0.15-0.22 bucket: 60% WR (5 trades, only -1.58 EUR). Floor 0.15 cleanly separates
# the working zone from the lottery zone while preserving the productive band.
# Trigger doc: "REVERT TRIGGER: if WR <40% on next 10 YES trades with ep 0.10-0.15"
# was satisfied for the <0.15 region with overwhelming negative evidence.
# Boundary markets retain 0.15 floor (unchanged); non-boundary now matches.
YES_MIN_ENTRY_PRICE = 0.15
# YES_MIN_EDGE_ABSOLUTE: 2026-05-29 lowered from 0.065 → 0.04 — cheap-market YES
# bets have inherently small absolute gaps (4-5 pp), and EV is the absolute_edge.
# At ep=0.115 with abs_edge=0.046, EV per $1 = +4.6¢. 6.5% floor blocked all such
# real opportunities. 4% floor still rejects noise (Brier-score-style indistinct).
# Standard NO bets retain MIN_EDGE_ABSOLUTE (config, currently 0.03).
YES_MIN_EDGE_ABSOLUTE = 0.04


def describe_proposal(proposal) -> Dict[str, Any]:
    """Extract metadata from a proposal for logging/auditing."""
    return {
        "market_id": getattr(proposal, "market_id", None),
        "market_question": getattr(proposal, "market_question", "")[:100],
        "edge": getattr(proposal, "edge", 0),
        "implied_probability": getattr(proposal, "implied_probability", 0),
        "model_probability": getattr(proposal, "model_probability", 0),
        "confidence_level": getattr(proposal, "confidence_level", "UNKNOWN"),
        "city": _extract_city(getattr(proposal, "market_question", "")),
        "entry_price": getattr(proposal, "implied_probability", 0),
    }


def _load_capital_config() -> Dict[str, Any]:
    """Load capital configuration."""
    config_file = DATA_DIR / "capital_config.json"
    if config_file.exists():
        try:
            return json.loads(config_file.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _load_weather_config() -> Dict[str, Any]:
    """Load weather strategy configuration."""
    config_file = PROJECT_ROOT / "config" / "weather.yaml"
    if config_file.exists():
        try:
            import yaml
            data = yaml.safe_load(config_file.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except Exception:
            pass
    return {}


def _load_agent_policy() -> Dict[str, Any]:
    """Load current agent policy."""
    policy_file = AGENTIC_DIR / "active_policy.json"
    if policy_file.exists():
        try:
            return json.loads(policy_file.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _extract_city(question: str) -> Optional[str]:
    """Extract city name from market question."""
    # Common cities in weather markets
    cities = [
        "New York", "Los Angeles", "Chicago", "Houston", "Phoenix",
        "Philadelphia", "San Antonio", "San Diego", "Dallas", "San Jose",
        "Austin", "Jacksonville", "Fort Worth", "Columbus", "Charlotte",
        "San Francisco", "Indianapolis", "Seattle", "Denver", "Washington",
        "Boston", "Detroit", "Nashville", "Portland", "Memphis",
        "Oklahoma City", "Las Vegas", "Louisville", "Baltimore", "Milwaukee",
        "Albuquerque", "Tucson", "Fresno", "Sacramento", "Atlanta",
        "Miami", "Tampa", "Orlando", "Minneapolis", "Cleveland",
        "London", "Paris", "Berlin", "Tokyo", "Sydney",
    ]

    question_upper = question.upper()
    for city in cities:
        if city.upper() in question_upper:
            return city

    return None


# 2026-06-10 no-forward-edge decision: market types with no proven edge and the
# bulk of historical losses. exact = -36.66 EUR, at_or_above = -29.94 EUR (~-66 of
# the -87 EUR book). A Gaussian-CDF over continuous temperature is the wrong model
# for near-binary exact-bucket resolution. Override via weather.yaml
# BLOCKED_MARKET_TYPES (set to [] to disable once forward edge is proven).
DEFAULT_BLOCKED_MARKET_TYPES = ("exact", "at_or_above")

_MT_BELOW_RE = re.compile(r"or\s+below|or\s+less|or\s+under|or\s+lower|\bbelow\b", re.I)
_MT_ABOVE_RE = re.compile(r"above|or\s+above|exceed|or\s+higher|or\s+more|or\s+over", re.I)
_MT_BETWEEN_RE = re.compile(r"\bbetween\b", re.I)


def _detect_market_type(proposal) -> str:
    """Resolve a proposal's market type, falling back to question-text parsing.

    proposal.market_type is frequently None in this pipeline, so the question
    text is the reliable signal. Returns one of:
    exact | between | at_or_above | at_or_below.
    """
    mt = str(getattr(proposal, "market_type", "") or "").lower()
    if mt in ("exact", "between", "at_or_above", "at_or_below"):
        return mt
    question = (getattr(proposal, "market_question", "") or "").lower()
    if _MT_BELOW_RE.search(question):
        return "at_or_below"
    if _MT_ABOVE_RE.search(question):
        return "at_or_above"
    if _MT_BETWEEN_RE.search(question):
        return "between"
    return "exact"


def evaluate_entry_guardrails(
    proposal,
    open_positions_count: int = 0,
    ignore_inventory_limit: bool = False,
) -> Tuple[bool, str]:
    """
    Evaluate if a new entry is allowed based on guardrails.

    Args:
        proposal: Proposal object to evaluate
        open_positions_count: Current number of open positions
        ignore_inventory_limit: If True, ignore position count limits

    Returns:
        Tuple of (allowed: bool, reason: str)
    """
    capital_config = _load_capital_config()
    agent_policy = _load_agent_policy()
    weather_config = _load_weather_config()

    # Get limits
    max_positions = capital_config.get("max_open_positions", DEFAULT_MAX_OPEN_POSITIONS)
    max_entry_price = min(
        float(weather_config.get("MAX_ODDS", DEFAULT_MAX_ENTRY_PRICE)),
        float(agent_policy.get("max_entry_price", DEFAULT_MAX_ENTRY_PRICE)),
    )
    # Minimum entry price: block low-probability traps (entry < 40% = systematically losing)
    min_entry_price = float(weather_config.get("MIN_ENTRY_PRICE", DEFAULT_MIN_ENTRY_PRICE))
    min_edge = float(weather_config.get("MIN_EDGE", DEFAULT_MIN_EDGE))
    min_edge_absolute = float(weather_config.get("MIN_EDGE_ABSOLUTE", DEFAULT_MIN_EDGE_ABSOLUTE))
    # Auto-tuned soft overrides (clamped to safe BOUNDS by the tuner itself).
    # Applied only when present in `data/agent_memory/auto_param_overrides.json`.
    try:
        from analytics.auto_parameter_tuner import get_overrides
        _auto = get_overrides()
        if "MIN_EDGE" in _auto:
            min_edge = float(_auto["MIN_EDGE"])
        if "MIN_EDGE_ABSOLUTE" in _auto:
            min_edge_absolute = float(_auto["MIN_EDGE_ABSOLUTE"])
    except Exception:
        pass  # fail-open: keep static config values
    cooldown_cities = agent_policy.get("cooldown_cities", [])
    policy_mode = agent_policy.get("mode", "NORMAL")

    # Extract proposal data
    entry_price = getattr(proposal, "implied_probability", 0)
    city = _extract_city(getattr(proposal, "market_question", ""))

    # Check 0: Blocked market types (2026-06-10 no-forward-edge decision).
    # exact + at_or_above carry ~-66 of the -87 EUR loss and have no proven
    # forward edge over the market. Configurable via weather.yaml.
    blocked_types = weather_config.get(
        "BLOCKED_MARKET_TYPES", list(DEFAULT_BLOCKED_MARKET_TYPES)
    )
    if blocked_types:
        mtype = _detect_market_type(proposal)
        if mtype in {str(t).lower() for t in blocked_types}:
            return (
                False,
                f"market_type_blocked|Market type '{mtype}' blocked — no proven "
                "forward edge (exact/at_or_above = -66 EUR historical)",
            )

    # Check 1: Position count limit
    if not ignore_inventory_limit:
        if open_positions_count >= max_positions:
            return (False, f"inventory_limit|Max {max_positions} positions reached ({open_positions_count})")

    # Check 2: Entry price limits (max + min)
    # For YES bets: implied_probability is the contract cost. Block if too low (long-shot trap).
    # For NO bets: the NO contract cost = 1 - implied_probability. Block if NO price < min
    #   (high YES market price → tiny NO payout → bad risk/reward).
    #   Example: YES=92% → NO contract costs 8 cents → max profit only 8.7%, loss -100%.
    edge_val = getattr(proposal, "edge", 0) or 0
    is_no_bet = float(edge_val) < 0
    if is_no_bet:
        no_contract_price = 1.0 - entry_price
        if no_contract_price < min_entry_price:
            return (
                False,
                f"no_price_too_low|NO contract price {no_contract_price:.2f} < min "
                f"{min_entry_price:.2f} (YES={entry_price:.2f} too high — bad R:R for NO bet)",
            )
    else:
        if entry_price > max_entry_price:
            return (False, f"price_limit|Entry price {entry_price:.2f} > max {max_entry_price:.2f}")
        # Boundary markets (at_or_above / at_or_below) allow lower entry prices:
        # YES=0.15–0.29 with model≥0.40 is genuine edge on directional markets —
        # ensemble member-counting is accurate for threshold events (count members
        # above/below a single value). Contrast with exact/between narrow-band
        # markets where model miscalibration inflates probabilities.
        # Evidence: at_or_above YES=0.366 won +42%; today Dallas at_or_below
        # YES=0.23 with P_ensemble=0.46 had 96.71% edge but was blocked.
        market_type_str = str(getattr(proposal, "market_type", "") or "").lower()
        if not market_type_str:
            # Fallback: detect from question text (proposal.market_type is often None
            # because the pipeline doesn't populate it — but the question always reveals type)
            _q = (getattr(proposal, "market_question", "") or "").lower()
            if re.search(r"or\s+below|or\s+less|or\s+under|or\s+lower|\bbelow\b", _q):
                market_type_str = "at_or_below"
            elif re.search(r"above|or\s+above|exceed|or\s+higher|or\s+more|or\s+over", _q):
                market_type_str = "at_or_above"
        is_boundary_market = market_type_str in ("at_or_above", "at_or_below")
        # YES bets: use YES_MIN_ENTRY_PRICE (0.22) instead of min_entry_price (0.30).
        # Boundary markets (at_or_above / at_or_below): use 0.15 as before.
        # Near-zero lotteries (<0.22) still blocked here; further protection comes
        # from the LOW-liq check and SQS ep_score in simulator.py.
        effective_min_entry = 0.15 if is_boundary_market else YES_MIN_ENTRY_PRICE
        if effective_min_entry > 0 and entry_price < effective_min_entry:
            boundary_note = " — boundary market relaxed to 0.15" if is_boundary_market else ""
            return (False, f"price_too_low|Entry price {entry_price:.2f} < min {effective_min_entry:.2f} (low-prob trap{boundary_note})")

    # Check 3: City cooldown — policy-managed list
    if city and city in cooldown_cities:
        return (False, f"city_cooldown|City {city} is on cooldown")

    # Check 3b: City cooldown — autonomously managed (auto_city_blacklist).
    # Per-city WR threshold maintained automatically from paper_positions.jsonl.
    if city:
        try:
            from analytics.auto_city_blacklist import get_blocked_cities
            auto_blocked = {c.lower() for c in get_blocked_cities()}
            if city.lower() in auto_blocked:
                return (
                    False,
                    f"auto_city_cooldown|City {city} auto-blocked "
                    "(see data/agent_memory/auto_city_cooldowns.json)",
                )
        except Exception:
            pass  # fail-open: never block a trade because of tracker plumbing

    # Check 4: Policy mode restrictions
    if policy_mode == "HALT":
        return (False, "policy_halt|Trading halted by agent policy")

    if policy_mode == "DEFENSIVE":
        # In defensive mode, only allow high-confidence trades
        confidence = getattr(proposal, "confidence_level", "UNKNOWN")
        if confidence not in ("HIGH", "VERY_HIGH"):
            return (False, f"defensive_mode|Only HIGH confidence allowed in defensive mode (got {confidence})")

    # Check 5: Minimum edge (relative + absolute safety checks)
    relative_edge = abs(getattr(proposal, "edge", 0) or 0)
    market_probability = getattr(proposal, "implied_probability", None)
    model_probability = getattr(proposal, "model_probability", None)
    absolute_edge = abs((model_probability or 0) - (market_probability or 0)) if (
        market_probability is not None and model_probability is not None
    ) else relative_edge

    # YES bets use relaxed edge threshold (YES_MIN_EDGE=0.30 vs general min_edge=0.40).
    # Evidence: 80% WR on YES trades at 30-50% edge (5/6 wins, +8.82 EUR). The only
    # YES loss was in a LOW-liq market that is now blocked at entry.
    is_yes_bet = not is_no_bet  # is_no_bet defined above from edge sign
    # Honor auto-tuned YES_MIN_EDGE override if present.
    _yes_min_edge_effective = YES_MIN_EDGE
    try:
        from analytics.auto_parameter_tuner import get_overrides as _gp
        _ov = _gp()
        if "YES_MIN_EDGE" in _ov:
            _yes_min_edge_effective = float(_ov["YES_MIN_EDGE"])
    except Exception:
        pass
    effective_min_edge = _yes_min_edge_effective if is_yes_bet else min_edge
    if relative_edge < effective_min_edge:
        return (False, f"min_edge|Edge {relative_edge:.2%} below minimum {effective_min_edge:.0%} ({'YES' if is_yes_bet else 'NO'} threshold)")

    # YES bets use the relaxed YES_MIN_EDGE_ABSOLUTE floor (6.5% vs 10% standard).
    _abs_min = YES_MIN_EDGE_ABSOLUTE if is_yes_bet else min_edge_absolute
    if absolute_edge < _abs_min:
        return (
            False,
            f"absolute_edge|Absolute edge {absolute_edge:.2%} below minimum {_abs_min:.1%} ({'YES' if is_yes_bet else 'NO'} threshold)",
        )

    return (True, "passed|All guardrails passed")


def get_guardrail_status() -> Dict[str, Any]:
    """
    Get current guardrail status for monitoring.

    Returns:
        Dict with current guardrail settings
    """
    capital_config = _load_capital_config()
    agent_policy = _load_agent_policy()
    weather_config = _load_weather_config()

    return {
        "max_open_positions": capital_config.get("max_open_positions", DEFAULT_MAX_OPEN_POSITIONS),
        "max_entry_price": min(
            float(weather_config.get("MAX_ODDS", DEFAULT_MAX_ENTRY_PRICE)),
            float(agent_policy.get("max_entry_price", DEFAULT_MAX_ENTRY_PRICE)),
        ),
        "min_edge": float(weather_config.get("MIN_EDGE", DEFAULT_MIN_EDGE)),
        "min_edge_absolute": float(weather_config.get("MIN_EDGE_ABSOLUTE", DEFAULT_MIN_EDGE_ABSOLUTE)),
        "cooldown_cities": agent_policy.get("cooldown_cities", []),
        "policy_mode": agent_policy.get("mode", "NORMAL"),
        "timestamp": datetime.now().isoformat(),
    }
