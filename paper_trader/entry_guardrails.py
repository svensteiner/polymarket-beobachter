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
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT / "data"
AGENTIC_DIR = PROJECT_ROOT / "agentic"

# Default limits
DEFAULT_MAX_OPEN_POSITIONS = 10
DEFAULT_MAX_POSITIONS_PER_CITY = 3
DEFAULT_MAX_ENTRY_PRICE = 0.85


def _load_capital_config() -> Dict[str, Any]:
    """Load capital configuration."""
    config_file = DATA_DIR / "capital_config.json"
    if config_file.exists():
        try:
            return json.loads(config_file.read_text(encoding="utf-8"))
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


def describe_proposal(proposal) -> Dict[str, Any]:
    """
    Extract metadata from a proposal for logging/auditing.

    Args:
        proposal: Proposal object

    Returns:
        Dict with proposal metadata
    """
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

    # Get limits
    max_positions = capital_config.get("max_open_positions", DEFAULT_MAX_OPEN_POSITIONS)
    max_entry_price = agent_policy.get("max_entry_price", DEFAULT_MAX_ENTRY_PRICE)
    cooldown_cities = agent_policy.get("cooldown_cities", [])
    policy_mode = agent_policy.get("mode", "NORMAL")

    # Extract proposal data
    entry_price = getattr(proposal, "implied_probability", 0)
    city = _extract_city(getattr(proposal, "market_question", ""))

    # Check 1: Position count limit
    if not ignore_inventory_limit:
        if open_positions_count >= max_positions:
            return (False, f"inventory_limit|Max {max_positions} positions reached ({open_positions_count})")

    # Check 2: Entry price limit
    if entry_price > max_entry_price:
        return (False, f"price_limit|Entry price {entry_price:.2f} > max {max_entry_price:.2f}")

    # Check 3: City cooldown
    if city and city in cooldown_cities:
        return (False, f"city_cooldown|City {city} is on cooldown")

    # Check 4: Policy mode restrictions
    if policy_mode == "HALT":
        return (False, f"policy_halt|Trading halted by agent policy")

    if policy_mode == "DEFENSIVE":
        # In defensive mode, only allow high-confidence trades
        confidence = getattr(proposal, "confidence_level", "UNKNOWN")
        if confidence not in ("HIGH", "VERY_HIGH"):
            return (False, f"defensive_mode|Only HIGH confidence allowed in defensive mode (got {confidence})")

    # Check 5: Minimum edge (safety check)
    edge = abs(getattr(proposal, "edge", 0))
    if edge < 0.05:
        return (False, f"min_edge|Edge {edge:.2%} below minimum 5%")

    return (True, "passed|All guardrails passed")


def get_guardrail_status() -> Dict[str, Any]:
    """
    Get current guardrail status for monitoring.

    Returns:
        Dict with current guardrail settings
    """
    capital_config = _load_capital_config()
    agent_policy = _load_agent_policy()

    return {
        "max_open_positions": capital_config.get("max_open_positions", DEFAULT_MAX_OPEN_POSITIONS),
        "max_entry_price": agent_policy.get("max_entry_price", DEFAULT_MAX_ENTRY_PRICE),
        "cooldown_cities": agent_policy.get("cooldown_cities", []),
        "policy_mode": agent_policy.get("mode", "NORMAL"),
        "timestamp": datetime.now().isoformat(),
    }
