# =============================================================================
# POLYMARKET BEOBACHTER - CAPITAL MANAGER
# =============================================================================
#
# GOVERNANCE INTENT:
# This module manages paper trading capital allocation.
# All capital tracking is simulated - no real funds are managed.
#
# CAPITAL RULES:
# - Initial capital: 5000 EUR (configurable)
# - Position size: 100 EUR per trade (configurable)
# - Cannot enter new positions if insufficient capital
# - Capital is updated on entry and exit
#
# =============================================================================

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional
from dataclasses import dataclass
from threading import Lock

logger = logging.getLogger(__name__)


# Path to capital config
CAPITAL_CONFIG_PATH = Path(__file__).parent.parent / "data" / "capital_config.json"


@dataclass
class CapitalState:
    """Current state of paper trading capital."""
    initial_capital_eur: float
    available_capital_eur: float
    allocated_capital_eur: float
    realized_pnl_eur: float
    position_size_eur: float
    max_position_pct: float
    max_open_positions: int
    max_daily_trades: int


class CapitalManager:
    """
    Manages paper trading capital allocation.

    GOVERNANCE:
    - All capital is SIMULATED (paper trading)
    - No real funds are at risk
    - Capital state is persisted to JSON for audit trail
    """

    def __init__(self, config_path: Optional[Path] = None):
        """
        Initialize the capital manager.

        Args:
            config_path: Path to capital config JSON. Defaults to data/capital_config.json
        """
        self._config_path = config_path or CAPITAL_CONFIG_PATH
        self._lock = Lock()
        self._state: Optional[CapitalState] = None
        self._load_config()

    def _load_config(self) -> None:
        """Load capital configuration from JSON file."""
        if not self._config_path.exists():
            logger.warning(f"Capital config not found at {self._config_path}")
            # Create default config
            self._create_default_config()

        with open(self._config_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        self._state = CapitalState(
            initial_capital_eur=data.get("initial_capital_eur", 5000.0),
            available_capital_eur=data.get("available_capital_eur", 5000.0),
            allocated_capital_eur=data.get("allocated_capital_eur", 0.0),
            realized_pnl_eur=data.get("realized_pnl_eur", 0.0),
            position_size_eur=data.get("position_size_eur", 100.0),
            max_position_pct=data.get("max_position_pct", 2.0),
            max_open_positions=data.get("max_open_positions", 50),
            max_daily_trades=data.get("max_daily_trades", 10),
        )

        logger.info(
            f"Capital loaded: {self._state.available_capital_eur:.2f} EUR available, "
            f"{self._state.allocated_capital_eur:.2f} EUR allocated"
        )

    def _create_default_config(self) -> None:
        """Create default capital configuration."""
        default_config = {
            "governance_notice": "PAPER TRADING CAPITAL - No real funds are allocated",
            "initial_capital_eur": 5000.00,
            "available_capital_eur": 5000.00,
            "allocated_capital_eur": 0.00,
            "realized_pnl_eur": 0.00,
            "position_size_eur": 100.00,
            "max_position_pct": 2.0,
            "max_open_positions": 50,
            "max_daily_trades": 10,
            "created_at": datetime.now().isoformat(),
            "last_updated": datetime.now().isoformat(),
            "last_updated_reason": "Auto-created default config"
        }

        self._config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._config_path, "w", encoding="utf-8") as f:
            json.dump(default_config, f, indent=2, ensure_ascii=False)

        logger.info(f"Created default capital config at {self._config_path}")

    def _save_config(self, reason: str) -> None:
        """Save current state to config file."""
        if self._state is None:
            return

        data = {
            "governance_notice": "PAPER TRADING CAPITAL - No real funds are allocated",
            "initial_capital_eur": self._state.initial_capital_eur,
            "available_capital_eur": self._state.available_capital_eur,
            "allocated_capital_eur": self._state.allocated_capital_eur,
            "realized_pnl_eur": self._state.realized_pnl_eur,
            "position_size_eur": self._state.position_size_eur,
            "max_position_pct": self._state.max_position_pct,
            "max_open_positions": self._state.max_open_positions,
            "max_daily_trades": self._state.max_daily_trades,
            "created_at": datetime.now().isoformat(),
            "last_updated": datetime.now().isoformat(),
            "last_updated_reason": reason
        }

        with open(self._config_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def get_state(self) -> CapitalState:
        """Get current capital state."""
        if self._state is None:
            self._load_config()
        return self._state  # type: ignore

    def get_position_size(self) -> float:
        """Get the configured position size in EUR."""
        return self.get_state().position_size_eur

    def has_sufficient_capital(self, amount_eur: Optional[float] = None) -> bool:
        """
        Check if there is sufficient capital for a new position.

        Args:
            amount_eur: Amount to check. Defaults to configured position_size_eur.

        Returns:
            True if sufficient capital is available.
        """
        state = self.get_state()
        check_amount = amount_eur or state.position_size_eur
        return state.available_capital_eur >= check_amount

    def can_open_position(self, current_open_positions: int) -> tuple[bool, str]:
        """
        Check if a new position can be opened.

        Args:
            current_open_positions: Number of currently open positions

        Returns:
            Tuple of (can_open, reason)
        """
        state = self.get_state()

        # Check capital
        if not self.has_sufficient_capital():
            return (
                False,
                f"Insufficient capital: {state.available_capital_eur:.2f} EUR available, "
                f"{state.position_size_eur:.2f} EUR required"
            )

        # Check position limit
        if current_open_positions >= state.max_open_positions:
            return (
                False,
                f"Max positions reached: {current_open_positions}/{state.max_open_positions}"
            )

        return (True, "OK")

    def allocate_capital(self, amount_eur: float, reason: str) -> bool:
        """
        Allocate capital for a new position.

        Args:
            amount_eur: Amount to allocate
            reason: Reason for allocation (for audit)

        Returns:
            True if allocation successful, False if insufficient capital
        """
        with self._lock:
            state = self.get_state()

            if state.available_capital_eur < amount_eur:
                logger.warning(
                    f"Cannot allocate {amount_eur:.2f} EUR - "
                    f"only {state.available_capital_eur:.2f} EUR available"
                )
                return False

            # Update state
            self._state = CapitalState(
                initial_capital_eur=state.initial_capital_eur,
                available_capital_eur=state.available_capital_eur - amount_eur,
                allocated_capital_eur=state.allocated_capital_eur + amount_eur,
                realized_pnl_eur=state.realized_pnl_eur,
                position_size_eur=state.position_size_eur,
                max_position_pct=state.max_position_pct,
                max_open_positions=state.max_open_positions,
                max_daily_trades=state.max_daily_trades,
            )

            self._save_config(f"Allocated {amount_eur:.2f} EUR: {reason}")

            logger.info(
                f"Capital allocated: {amount_eur:.2f} EUR | "
                f"Available: {self._state.available_capital_eur:.2f} EUR | "
                f"Allocated: {self._state.allocated_capital_eur:.2f} EUR"
            )
            return True

    def release_capital(self, cost_basis_eur: float, pnl_eur: float, reason: str) -> None:
        """
        Release capital from a closed position.

        Args:
            cost_basis_eur: Original cost basis of the position
            pnl_eur: Realized P&L from the position
            reason: Reason for release (for audit)
        """
        with self._lock:
            state = self.get_state()

            # Calculate return: cost basis + P&L
            return_amount = cost_basis_eur + pnl_eur

            # Update state
            self._state = CapitalState(
                initial_capital_eur=state.initial_capital_eur,
                available_capital_eur=state.available_capital_eur + return_amount,
                allocated_capital_eur=max(0.0, state.allocated_capital_eur - cost_basis_eur),
                realized_pnl_eur=state.realized_pnl_eur + pnl_eur,
                position_size_eur=state.position_size_eur,
                max_position_pct=state.max_position_pct,
                max_open_positions=state.max_open_positions,
                max_daily_trades=state.max_daily_trades,
            )

            self._save_config(f"Released {return_amount:.2f} EUR (P&L: {pnl_eur:+.2f}): {reason}")

            logger.info(
                f"Capital released: {return_amount:.2f} EUR (P&L: {pnl_eur:+.2f}) | "
                f"Available: {self._state.available_capital_eur:.2f} EUR | "
                f"Total P&L: {self._state.realized_pnl_eur:+.2f} EUR"
            )

    def get_summary(self) -> Dict[str, Any]:
        """
        Get capital summary for reporting.

        Returns:
            Summary dictionary
        """
        state = self.get_state()
        total_equity = state.available_capital_eur + state.allocated_capital_eur
        roi_pct = (state.realized_pnl_eur / state.initial_capital_eur) * 100 if state.initial_capital_eur > 0 else 0.0

        return {
            "initial_capital_eur": state.initial_capital_eur,
            "available_capital_eur": state.available_capital_eur,
            "allocated_capital_eur": state.allocated_capital_eur,
            "total_equity_eur": total_equity,
            "realized_pnl_eur": state.realized_pnl_eur,
            "roi_pct": roi_pct,
            "position_size_eur": state.position_size_eur,
            "max_open_positions": state.max_open_positions,
            "governance_notice": "PAPER TRADING - No real funds"
        }

    def reset_capital(self, initial_amount_eur: float = 5000.0) -> None:
        """
        Reset capital to initial state.

        WARNING: This clears all P&L and resets to starting capital.

        Args:
            initial_amount_eur: New initial capital amount
        """
        with self._lock:
            self._state = CapitalState(
                initial_capital_eur=initial_amount_eur,
                available_capital_eur=initial_amount_eur,
                allocated_capital_eur=0.0,
                realized_pnl_eur=0.0,
                position_size_eur=100.0,
                max_position_pct=2.0,
                max_open_positions=30,
                max_daily_trades=5,
            )
            self._save_config(f"Capital reset to {initial_amount_eur:.2f} EUR")
            logger.warning(f"Capital RESET to {initial_amount_eur:.2f} EUR")


# =============================================================================
# MODULE-LEVEL FUNCTIONS
# =============================================================================

_capital_manager: Optional[CapitalManager] = None


def get_capital_manager() -> CapitalManager:
    """Get the global capital manager instance."""
    global _capital_manager
    if _capital_manager is None:
        _capital_manager = CapitalManager()
    return _capital_manager


def has_sufficient_capital() -> bool:
    """Check if there is sufficient capital for a new position."""
    return get_capital_manager().has_sufficient_capital()


def allocate_capital(amount_eur: float, reason: str) -> bool:
    """Allocate capital for a new position."""
    return get_capital_manager().allocate_capital(amount_eur, reason)


def release_capital(cost_basis_eur: float, pnl_eur: float, reason: str) -> None:
    """Release capital from a closed position."""
    get_capital_manager().release_capital(cost_basis_eur, pnl_eur, reason)


def get_capital_summary() -> Dict[str, Any]:
    """Get capital summary for reporting."""
    return get_capital_manager().get_summary()
