# =============================================================================
# POLYMARKET BEOBACHTER - AVERAGING DOWN (NACHKAUF)
# =============================================================================
#
# GOVERNANCE INTENT:
# When a position's market price drops but our forecast stays the same
# (or improves), the edge INCREASES. In this case, buying more contracts
# at the lower price is mathematically justified (averaging down).
#
# CONSTRAINTS:
# - Max 1 add-on per position (no pyramiding)
# - Must re-validate forecast freshness
# - Edge must have INCREASED since entry
# - Minimum edge threshold still applies
# - Capital limits still enforced
#
# PAPER TRADING ONLY:
# All trades are simulated. No real funds involved.
#
# =============================================================================

import re
import sys
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from paper_trader.models import PaperPosition, PaperTradeRecord, MarketSnapshot, TradeAction, generate_position_id, generate_record_id
from paper_trader.logger import get_paper_logger, log_trade, log_position
from paper_trader.snapshot_client import get_market_snapshots
from paper_trader.capital_manager import get_capital_manager, allocate_capital
from paper_trader.slippage import calculate_entry_price
from paper_trader.kelly import kelly_size

logger = logging.getLogger(__name__)


# =============================================================================
# CONSTANTS
# =============================================================================

# Minimum price drop (%) to consider averaging down
MIN_PRICE_DROP_PCT = 0.10  # 10% drop from entry

# Minimum edge improvement (absolute) to trigger add-on
MIN_EDGE_IMPROVEMENT = 0.05  # Edge must improve by at least 5 percentage points

# Max add-ons per position (prevent pyramiding)
MAX_ADDONS_PER_POSITION = 1

# Default forecast target: days from now for resolution approximation
MIN_FORECAST_AGE_DAYS = 2


# =============================================================================
# CITY / THRESHOLD EXTRACTION FROM MARKET QUESTION
# =============================================================================

CITY_PATTERNS = {
    "london": "London",
    "new york city": "New York",
    "new york": "New York",
    "nyc": "New York",
    "manhattan": "New York",
    "seoul": "Seoul",
    "los angeles": "Los Angeles",
    "la ": "Los Angeles",
    "chicago": "Chicago",
    "miami": "Miami",
    "denver": "Denver",
    "phoenix": "Phoenix",
    "seattle": "Seattle",
    "boston": "Boston",
    "tokyo": "Tokyo",
    "paris": "Paris",
    "berlin": "Berlin",
    "sydney": "Sydney",
    "toronto": "Toronto",
    "houston": "Houston",
    "atlanta": "Atlanta",
    "dallas": "Dallas",
    "san francisco": "San Francisco",
    "washington": "Washington",
    "philadelphia": "Philadelphia",
    "buenos aires": "Buenos Aires",
    "ankara": "Ankara",
}

TEMPERATURE_PATTERNS = [
    re.compile(r'between\s*(\d+)\s*-\s*(\d+)\s*°?\s*([FC])', re.I),
    re.compile(r'be\s+(\d+)\s*°?\s*([FC])\s*(or\s+)?(higher|below|lower)?', re.I),
    re.compile(r'(?:above|exceed|over|>=|≥)\s*(\d+)\s*°?\s*([FC])', re.I),
    re.compile(r'(?:below|under|<=|≤|less than)\s*(\d+)\s*°?\s*([FC])', re.I),
    re.compile(r'(\d+)\s*°\s*([FC])', re.I),
]


def extract_city(market_question: str) -> Optional[str]:
    """Extract city name from market question text."""
    text = market_question.lower()
    for pattern, city_name in CITY_PATTERNS.items():
        if pattern in text:
            return city_name
    return None


def extract_threshold_f(market_question: str) -> Optional[float]:
    """Extract temperature threshold in Fahrenheit from market question."""
    for pattern in TEMPERATURE_PATTERNS:
        match = pattern.search(market_question)
        if match:
            groups = match.groups()
            threshold = None
            unit = None
            for group in groups:
                if group is None:
                    continue
                try:
                    threshold = float(group)
                except ValueError:
                    pass
                if group.upper() in ('F', 'C'):
                    unit = group.upper()
            if threshold is not None and unit is not None:
                if unit == 'C':
                    return threshold * 9 / 5 + 32
                return threshold
    return None


# =============================================================================
# AVERAGING DOWN CHECKER
# =============================================================================


def _get_addon_count(position_id: str) -> int:
    """Count how many add-on entries exist for a base position."""
    paper_logger = get_paper_logger()
    all_positions = paper_logger.read_all_positions()
    count = 0
    for pos in all_positions:
        if pos.position_id != position_id and pos.proposal_id.startswith(f"ADDON-{position_id}"):
            count += 1
    return count


def check_averaging_down() -> Dict[str, Any]:
    """
    Check open positions for averaging-down opportunities.

    For each open position:
    1. Get current market price (snapshot)
    2. Check if price dropped significantly from entry
    3. Get fresh weather forecast
    4. Compute new edge
    5. If edge improved → execute add-on entry

    Returns:
        Summary dict with counts
    """
    paper_logger = get_paper_logger()
    open_positions = paper_logger.get_open_positions()

    if not open_positions:
        return {"checked": 0, "addons": 0, "skipped": 0, "cost_eur": 0.0}

    # Get snapshots for all open positions
    market_ids = [p.market_id for p in open_positions]
    snapshots = get_market_snapshots(market_ids)

    # Load weather config and model
    try:
        import yaml
        config_path = Path(__file__).parent.parent / "config" / "weather.yaml"
        with open(config_path, 'r') as f:
            try:
                config = yaml.safe_load(f)
            except yaml.YAMLError as e:
                logger.error("Kann weather.yaml nicht parsen: %s", e)
                return {"checked": 0, "addons": 0, "skipped": 0, "cost_eur": 0.0, "error": str(e)}

        from core.weather_probability_model import WeatherProbabilityModel, compute_edge, meets_edge_threshold
        from core.multi_forecast import fetch_forecast_multi

        model = WeatherProbabilityModel(config)
        min_edge = config.get("MIN_EDGE", 0.12)
        med_multiplier = config.get("MEDIUM_CONFIDENCE_EDGE_MULTIPLIER", 1.25)
    except Exception as e:
        logger.error(f"Cannot load weather model for averaging down: {e}")
        return {"checked": 0, "addons": 0, "skipped": 0, "cost_eur": 0.0, "error": str(e)}

    capital_mgr = get_capital_manager()
    addon_count = 0
    skipped_count = 0
    total_cost = 0.0

    for position in open_positions:
        snapshot = snapshots.get(position.market_id)
        if snapshot is None or snapshot.mid_price is None:
            continue
        if snapshot.is_resolved:
            continue

        current_price = snapshot.mid_price
        entry_price = position.entry_price

        if entry_price <= 0:
            continue

        # Check 1: Price must have dropped significantly
        price_change_pct = (current_price - entry_price) / entry_price
        if price_change_pct > -MIN_PRICE_DROP_PCT:
            continue  # Price hasn't dropped enough

        # Check 2: Max add-ons not exceeded
        existing_addons = _get_addon_count(position.position_id)
        if existing_addons >= MAX_ADDONS_PER_POSITION:
            logger.debug(f"Averaging down: max addons reached for {position.position_id}")
            skipped_count += 1
            continue

        # Check 3: Capital available
        state = capital_mgr.get_state()
        can_open, reason = capital_mgr.can_open_position(len(open_positions) + addon_count)
        if not can_open:
            logger.debug(f"Averaging down: {reason}")
            skipped_count += 1
            continue

        # Check 4: Extract city and threshold from market question
        city = extract_city(position.market_question)
        threshold_f = extract_threshold_f(position.market_question)

        if city is None or threshold_f is None:
            logger.debug(f"Cannot parse city/threshold from: {position.market_question[:60]}")
            skipped_count += 1
            continue

        # Check 5: Get fresh forecast
        # Estimate resolution time from the market
        # For weather markets, resolution is typically within a few days
        try:
            # Use a reasonable target time (2 days from now as approximation)
            from datetime import timedelta
            target_time = datetime.now(timezone.utc) + timedelta(days=MIN_FORECAST_AGE_DAYS)
            forecast = fetch_forecast_multi(city, target_time)
        except Exception as e:
            logger.debug(f"Forecast fetch failed for {city}: {e}")
            skipped_count += 1
            continue

        if forecast is None:
            logger.debug(f"No forecast available for {city}")
            skipped_count += 1
            continue

        # Check 6: Compute new fair probability and edge
        try:
            prob_result = model.compute_probability(
                forecast=forecast,
                threshold_f=threshold_f,
                event_type="exceeds",
            )
        except Exception as e:
            logger.debug(f"Probability computation failed: {e}")
            skipped_count += 1
            continue

        # Compute edges
        new_edge = compute_edge(prob_result.fair_probability, current_price)
        original_edge = compute_edge(prob_result.fair_probability, entry_price)

        # Check 7: Edge must have improved
        edge_improvement = new_edge - original_edge
        if edge_improvement < MIN_EDGE_IMPROVEMENT:
            logger.debug(
                f"Edge improvement insufficient: {edge_improvement:.2%} "
                f"(need {MIN_EDGE_IMPROVEMENT:.2%})"
            )
            skipped_count += 1
            continue

        # Check 8: New edge must still meet minimum threshold
        if not meets_edge_threshold(new_edge, min_edge, prob_result.confidence, med_multiplier):
            logger.debug(f"New edge {new_edge:.2%} doesn't meet threshold")
            skipped_count += 1
            continue

        # All checks passed - execute add-on entry
        logger.info(
            f"AVERAGING DOWN: {position.market_id} | {city} | "
            f"entry @ {entry_price:.4f} → current @ {current_price:.4f} | "
            f"edge: {original_edge:.2%} → {new_edge:.2%} (+{edge_improvement:.2%})"
        )

        addon_result = _execute_addon(
            position, snapshot, prob_result.fair_probability, new_edge, city
        )

        if addon_result is not None:
            addon_count += 1
            total_cost += addon_result.cost_basis_eur
        else:
            skipped_count += 1

    summary = {
        "checked": len(open_positions),
        "addons": addon_count,
        "skipped": skipped_count,
        "cost_eur": total_cost,
    }

    if addon_count:
        logger.info(f"Averaging down: {addon_count} add-ons, cost: {total_cost:.2f} EUR")

    return summary


def _execute_addon(
    base_position: PaperPosition,
    snapshot: MarketSnapshot,
    model_probability: float,
    new_edge: float,
    city: str,
) -> Optional[PaperPosition]:
    """
    Execute an add-on entry for an existing position.

    Creates a new position linked to the base position via proposal_id prefix.

    Returns:
        New PaperPosition if successful, None if failed
    """
    now = datetime.now().isoformat()
    capital_mgr = get_capital_manager()

    # Calculate entry price with slippage
    price_result = calculate_entry_price(snapshot, base_position.side)
    if price_result is None:
        logger.warning(f"Cannot calculate entry price for addon")
        return None

    entry_price, slippage = price_result

    # Position sizing via Kelly
    try:
        available = capital_mgr.get_state().available_capital_eur
    except Exception:
        available = 10000.0

    position_size = kelly_size(
        win_probability=model_probability,
        entry_price=entry_price,
        bankroll=available,
    )

    # Allocate capital
    if not allocate_capital(position_size, f"Addon: {base_position.market_id}"):
        logger.warning(f"Capital allocation failed for addon")
        return None

    # Calculate contracts
    if entry_price <= 0:
        logger.warning(f"Entry price <= 0 ({entry_price}), skipping addon for {base_position.market_id}")
        return None
    size_contracts = position_size / entry_price

    # Create new position (linked via proposal_id)
    addon_position_id = generate_position_id()
    addon_proposal_id = f"ADDON-{base_position.position_id}"

    addon_position = PaperPosition(
        position_id=addon_position_id,
        proposal_id=addon_proposal_id,
        market_id=base_position.market_id,
        market_question=base_position.market_question,
        side=base_position.side,
        status="OPEN",
        entry_time=now,
        entry_price=entry_price,
        entry_slippage=slippage,
        size_contracts=size_contracts,
        cost_basis_eur=position_size,
        exit_time=None,
        exit_price=None,
        exit_slippage=None,
        exit_reason=None,
        realized_pnl_eur=None,
        pnl_pct=None,
    )

    record = PaperTradeRecord(
        record_id=generate_record_id(),
        timestamp=now,
        proposal_id=addon_proposal_id,
        market_id=base_position.market_id,
        action=TradeAction.PAPER_ENTER.value,
        reason=(
            f"Averaging down: {base_position.side} @ {entry_price:.4f} | "
            f"base entry @ {base_position.entry_price:.4f} | "
            f"edge: {new_edge:.2%} | {city}"
        ),
        position_id=addon_position_id,
        snapshot_time=snapshot.snapshot_time,
        entry_price=entry_price,
        exit_price=None,
        slippage_applied=slippage,
        pnl_eur=None,
    )

    log_position(addon_position)
    log_trade(record)

    logger.info(
        f"ADDON ENTRY: {base_position.market_id} | {base_position.side} @ {entry_price:.4f} | "
        f"{size_contracts:.2f} contracts | {position_size:.2f} EUR | linked to {base_position.position_id}"
    )

    return addon_position
