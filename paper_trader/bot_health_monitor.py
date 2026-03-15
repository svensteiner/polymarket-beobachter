# =============================================================================
# POLYMARKET BEOBACHTER - BOT HEALTH MONITOR
# =============================================================================
#
# GOVERNANCE INTENT:
# This module provides temporary guardrails based on bot health metrics.
# It can temporarily restrict new entries without mutating the main config.
#
# =============================================================================

import logging
from dataclasses import dataclass
from typing import Tuple, Optional, Dict, Any

logger = logging.getLogger(__name__)


@dataclass
class BotHealthState:
    """Current health state of the bot."""
    is_healthy: bool = True
    consecutive_losses: int = 0
    daily_drawdown_pct: float = 0.0
    max_entry_price: Optional[float] = None
    reason: str = "OK"


# Global health state (in-memory, not persisted)
_health_state = BotHealthState()


def check_can_open_entry(
    entry_price: Optional[float] = None,
    is_addon: bool = False,
) -> Tuple[bool, str]:
    """
    Check if a new entry (or addon) is allowed based on current bot health.

    This provides temporary guardrails that don't require config changes.

    Args:
        entry_price: The proposed entry price (optional)
        is_addon: Whether this is an addon to existing position

    Returns:
        Tuple of (is_allowed, reason)
    """
    global _health_state

    # If bot is healthy, allow all entries
    if _health_state.is_healthy:
        return (True, "OK")

    # If max_entry_price is set and entry_price exceeds it
    if (
        entry_price is not None
        and _health_state.max_entry_price is not None
        and entry_price > _health_state.max_entry_price
    ):
        return (
            False,
            f"Entry price {entry_price:.2f} exceeds health limit {_health_state.max_entry_price:.2f}"
        )

    # Check consecutive losses
    if _health_state.consecutive_losses >= 5:
        return (
            False,
            f"Too many consecutive losses ({_health_state.consecutive_losses})"
        )

    # Check daily drawdown
    if _health_state.daily_drawdown_pct >= 10.0:
        return (
            False,
            f"Daily drawdown too high ({_health_state.daily_drawdown_pct:.1f}%)"
        )

    return (True, "OK")


def update_bot_health(summary: Dict[str, Any]) -> BotHealthState:
    """
    Update bot health state based on recent performance summary.

    Args:
        summary: Performance summary dict from orchestrator

    Returns:
        Updated BotHealthState
    """
    global _health_state

    # Extract metrics from summary
    consecutive_losses = summary.get("consecutive_losses", 0)
    daily_drawdown_pct = summary.get("daily_drawdown_pct", 0.0)
    win_rate = summary.get("win_rate", 1.0)

    # Determine health status
    is_healthy = True
    reason = "OK"

    if consecutive_losses >= 3:
        is_healthy = False
        reason = f"Consecutive losses: {consecutive_losses}"

    if daily_drawdown_pct >= 5.0:
        is_healthy = False
        reason = f"Daily drawdown: {daily_drawdown_pct:.1f}%"

    if win_rate < 0.3 and summary.get("total_trades", 0) >= 10:
        is_healthy = False
        reason = f"Low win rate: {win_rate:.1%}"

    # Set max entry price if unhealthy
    max_entry_price = None
    if not is_healthy:
        max_entry_price = 0.35  # Cap entries at 35% when unhealthy

    _health_state = BotHealthState(
        is_healthy=is_healthy,
        consecutive_losses=consecutive_losses,
        daily_drawdown_pct=daily_drawdown_pct,
        max_entry_price=max_entry_price,
        reason=reason,
    )

    logger.info(
        "Bot health updated: %s (losses=%d, drawdown=%.1f%%)",
        "HEALTHY" if is_healthy else "DEGRADED",
        consecutive_losses,
        daily_drawdown_pct,
    )

    return _health_state


def get_health_state() -> BotHealthState:
    """Get current bot health state."""
    return _health_state


def reset_health_state() -> None:
    """Reset health state to default (healthy)."""
    global _health_state
    _health_state = BotHealthState()
    logger.info("Bot health state reset to healthy")
