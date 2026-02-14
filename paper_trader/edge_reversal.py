# =============================================================================
# POLYMARKET BEOBACHTER - EDGE REVERSAL EXIT
# =============================================================================
#
# GOVERNANCE INTENT:
# When a position's forecast reverses and our edge disappears, holding the
# position until TP/SL/Resolution wastes capital. This module detects edge
# reversal by fetching fresh forecasts and exits positions where the edge
# has vanished.
#
# CONDITIONS FOR EXIT:
# - Edge reversed (was positive, now negative) OR
# - Edge fallen below MIN_EDGE AND confidence is HIGH
#
# PAPER TRADING ONLY:
# All trades are simulated. No real funds involved.
#
# =============================================================================

import sys
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Any, Optional

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from paper_trader.logger import get_paper_logger
from paper_trader.snapshot_client import get_market_snapshots
from paper_trader.simulator import simulate_exit_market
from paper_trader.averaging_down import extract_city, extract_threshold_f

logger = logging.getLogger(__name__)


# =============================================================================
# CONSTANTS
# =============================================================================

# Default forecast target: days from now for resolution approximation
MIN_FORECAST_AGE_DAYS = 2


# =============================================================================
# EDGE REVERSAL CHECKER
# =============================================================================


def check_edge_reversal_exits() -> Dict[str, Any]:
    """
    Check open positions for edge reversal and exit if edge has vanished.

    For each open position:
    1. Extract city + threshold from market_question
    2. Fetch fresh forecast via multi_forecast
    3. Compute new fair probability
    4. Compute edge against current market price
    5. If edge reversed or below minimum: exit position

    Returns:
        Summary dict with checked, skipped, exited, pnl_eur
    """
    paper_logger = get_paper_logger()
    open_positions = paper_logger.get_open_positions()

    if not open_positions:
        return {"checked": 0, "skipped": 0, "exited": 0, "pnl_eur": 0.0}

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
                return {"checked": 0, "skipped": 0, "exited": 0, "pnl_eur": 0.0, "error": str(e)}

        from core.weather_probability_model import WeatherProbabilityModel, compute_edge
        from core.multi_forecast import fetch_forecast_multi
        from core.weather_signal import WeatherConfidence

        model = WeatherProbabilityModel(config)
        min_edge = config.get("MIN_EDGE", 0.12)
    except Exception as e:
        logger.error(f"Cannot load weather model for edge reversal: {e}")
        return {"checked": 0, "skipped": 0, "exited": 0, "pnl_eur": 0.0, "error": str(e)}

    exited_count = 0
    skipped_count = 0
    total_pnl = 0.0

    for position in open_positions:
        snapshot = snapshots.get(position.market_id)
        if snapshot is None or snapshot.mid_price is None:
            skipped_count += 1
            continue
        if snapshot.is_resolved:
            continue  # handled by resolution checker

        current_price = snapshot.mid_price

        # Extract city and threshold from market question
        city = extract_city(position.market_question)
        threshold_f = extract_threshold_f(position.market_question)

        if city is None or threshold_f is None:
            logger.debug(f"Edge reversal: cannot parse city/threshold from: {position.market_question[:60]}")
            skipped_count += 1
            continue

        # Fetch fresh forecast
        try:
            target_time = datetime.now(timezone.utc) + timedelta(days=MIN_FORECAST_AGE_DAYS)
            forecast = fetch_forecast_multi(city, target_time)
        except Exception as e:
            logger.debug(f"Edge reversal: forecast fetch failed for {city}: {e}")
            skipped_count += 1
            continue

        if forecast is None:
            logger.debug(f"Edge reversal: no forecast available for {city}")
            skipped_count += 1
            continue

        # Compute new fair probability
        try:
            prob_result = model.compute_probability(
                forecast=forecast,
                threshold_f=threshold_f,
                event_type="exceeds",
            )
        except Exception as e:
            logger.debug(f"Edge reversal: probability computation failed: {e}")
            skipped_count += 1
            continue

        # Compute edge against current market price
        new_edge = compute_edge(prob_result.fair_probability, current_price)

        # Determine if we should exit
        should_exit = False
        exit_reason = ""

        if new_edge <= 0:
            # Edge reversed: model now says market is fairly priced or overpriced
            should_exit = True
            exit_reason = (
                f"Edge reversal (edge={new_edge:+.2%}, "
                f"fair={prob_result.fair_probability:.2%}, "
                f"market={current_price:.2%})"
            )
        elif new_edge < min_edge and prob_result.confidence == WeatherConfidence.HIGH:
            # Edge below minimum but only act on HIGH confidence forecasts
            should_exit = True
            exit_reason = (
                f"Edge below minimum (edge={new_edge:+.2%} < {min_edge:.0%}, "
                f"confidence=HIGH, "
                f"fair={prob_result.fair_probability:.2%}, "
                f"market={current_price:.2%})"
            )

        if should_exit:
            logger.info(
                f"EDGE REVERSAL: {position.market_id} | {city} | "
                f"entry @ {position.entry_price:.4f} | current @ {current_price:.4f} | "
                f"{exit_reason}"
            )

            closed, record = simulate_exit_market(
                position, snapshot, f"Edge reversal: {exit_reason}"
            )

            exited_count += 1
            if closed.realized_pnl_eur is not None:
                total_pnl += closed.realized_pnl_eur

    summary = {
        "checked": len(open_positions),
        "skipped": skipped_count,
        "exited": exited_count,
        "pnl_eur": total_pnl,
    }

    if exited_count:
        logger.info(f"Edge reversal exits: {exited_count} positions, P&L: {total_pnl:+.2f} EUR")

    return summary
