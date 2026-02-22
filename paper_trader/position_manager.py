# =============================================================================
# POLYMARKET BEOBACHTER - PAPER POSITION MANAGER
# =============================================================================
#
# GOVERNANCE INTENT:
# This module manages the lifecycle of paper positions.
# It tracks open positions and handles exit conditions.
#
# PAPER TRADING ONLY:
# All positions are simulated. No real funds are allocated.
#
# EXIT CONDITIONS:
# A) Resolution-based exit: Market resolves to YES/NO
# B) Time stop (optional): Exit after N days using current price
#
# =============================================================================

import json
import sys
import logging
import os
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Any

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from paper_trader.models import (
    PaperPosition, PaperTradeRecord, MarketSnapshot, TradeAction,
    generate_record_id,
)
from paper_trader.logger import get_paper_logger, log_trade
from paper_trader.snapshot_client import get_market_snapshots
from paper_trader.simulator import simulate_exit_resolution, simulate_exit_market
from paper_trader.capital_manager import release_capital
from paper_trader.slippage import calculate_exit_price


logger = logging.getLogger(__name__)

# Pfad zur TP-State-Datei (pro Position welche TPs wurden erreicht)
TP_STATE_PATH = Path(__file__).parent.parent / "data" / "tp_state.json"


def _load_tp_state() -> Dict[str, Any]:
    """Lade TP-State aus JSON-Datei (position_id -> TP-Infos)."""
    if not TP_STATE_PATH.exists():
        return {}
    try:
        with open(TP_STATE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"TP-State nicht lesbar: {e}")
        return {}


def _save_tp_state(state: Dict[str, Any]) -> None:
    """Speichere TP-State atomar."""
    TP_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    dirpath = str(TP_STATE_PATH.parent)
    fd, tmp = tempfile.mkstemp(dir=dirpath, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
        os.replace(tmp, str(TP_STATE_PATH))
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _default_tp_entry() -> Dict[str, Any]:
    """Leerer TP-State fuer eine neue Position."""
    return {
        "tp1_hit": False,
        "tp2_hit": False,
        "tp3_hit": False,
        "trailing_stop_price": None,   # Preis unter dem exit getriggert wird
        "exited_fraction": 0.0,         # Anteil der bereits exits-gemacht wurden
        "accumulated_partial_pnl": 0.0, # Bereits realisierter Partial-P&L
    }


# =============================================================================
# POSITION MANAGER
# =============================================================================


class PositionManager:
    """
    Manages paper trading positions.

    GOVERNANCE:
    - Tracks open positions
    - Checks for resolution/exit conditions
    - No real positions are managed
    """

    def __init__(self):
        """Initialize the position manager."""
        self._paper_logger = get_paper_logger()

    def get_open_positions(self) -> List[PaperPosition]:
        """
        Get all currently open paper positions.

        Returns:
            List of open PaperPosition objects
        """
        return self._paper_logger.get_open_positions()

    def check_and_close_resolved(self) -> Dict[str, Any]:
        """
        Check open positions and close any that have resolved.

        GOVERNANCE:
        - Fetches current market snapshots
        - If market is resolved, exits position
        - No hindsight used - uses current resolution state

        Returns:
            Summary dictionary with counts and P&L
        """
        open_positions = self.get_open_positions()
        logger.info(f"Checking {len(open_positions)} open positions for resolution")

        if not open_positions:
            return {
                "checked": 0,
                "closed": 0,
                "still_open": 0,
                "total_pnl_eur": 0.0,
            }

        # Get snapshots for all open position markets
        market_ids = [p.market_id for p in open_positions]
        snapshots = get_market_snapshots(market_ids)

        closed_count = 0
        total_pnl = 0.0
        still_open = 0

        for position in open_positions:
            snapshot = snapshots.get(position.market_id)

            if snapshot is None:
                logger.debug(f"No snapshot for {position.market_id} - keeping open")
                still_open += 1
                continue

            if snapshot.is_resolved:
                # Close the position
                logger.info(
                    f"Market {position.market_id} resolved to {snapshot.resolved_outcome}"
                )
                closed_position, record = simulate_exit_resolution(position, snapshot)
                closed_count += 1

                if closed_position.realized_pnl_eur is not None:
                    total_pnl += closed_position.realized_pnl_eur
            else:
                still_open += 1

        summary = {
            "checked": len(open_positions),
            "closed": closed_count,
            "still_open": still_open,
            "total_pnl_eur": total_pnl,
        }

        logger.info(
            f"Position check complete: {closed_count} closed, "
            f"{still_open} still open, P&L: {total_pnl:+.2f} EUR"
        )

        return summary

    # ==========================================================================
    # GESTAFFELTE TAKE-PROFIT SCHWELLEN (adaptiert aus tradingbot/risk_engine.py)
    # ==========================================================================
    # TP1: +10% -> 40% der Position verkaufen, Trailing Stop auf Entry setzen
    # TP2: +18% -> weitere 40% verkaufen, Trailing Stop anpassen
    # TP3: +25% -> Restliche 20% vollstaendig schliessen
    # Stop-Loss: -25% (unveraendert)
    TP1_PCT = 0.10
    TP1_FRACTION = 0.40   # 40% bei TP1 verkaufen
    TP2_PCT = 0.18
    TP2_FRACTION = 0.40   # 40% bei TP2 verkaufen (kumuliert: 80%)
    TP3_PCT = 0.25        # Restliche 20% bei TP3 schliessen
    STOP_LOSS_PCT = -0.25

    def _calc_unrealized_pct(self, position: PaperPosition, current_price: float) -> float:
        """Berechne unrealisierten P&L in Prozent (relativ zu Entry)."""
        entry = position.entry_price
        if entry <= 0:
            return 0.0
        if position.side == "NO":
            return (entry - current_price) / entry
        return (current_price - entry) / entry

    def _partial_exit(
        self,
        position: PaperPosition,
        snapshot: MarketSnapshot,
        fraction: float,
        reason: str,
    ) -> float:
        """
        Fuehre partiellen Exit aus (ohne Position zu schliessen).

        Berechnet anteiligen P&L, gibt Kapital frei und loggt Trade-Record.

        Args:
            position: Offene Position (bleibt OPEN nach partial exit)
            snapshot: Aktueller Markt-Snapshot
            fraction: Anteil der Position der verkauft wird (0.0-1.0)
            reason: Exit-Grund fuer Logging

        Returns:
            Realisierter P&L fuer diesen Anteil in EUR
        """
        now = datetime.now().isoformat()
        partial_contracts = position.size_contracts * fraction
        partial_cost = position.cost_basis_eur * fraction

        # Exit-Preis mit Slippage
        exit_result = calculate_exit_price(snapshot, position.side, is_resolution=False)
        if exit_result:
            exit_price, exit_slippage = exit_result
        else:
            exit_price = snapshot.mid_price or position.entry_price
            exit_slippage = 0.0

        revenue = partial_contracts * exit_price
        partial_pnl = revenue - partial_cost
        pnl_pct = (partial_pnl / partial_cost * 100) if partial_cost > 0 else 0.0

        # Kapital anteilig freigeben
        release_capital(partial_cost, partial_pnl, f"Partial exit: {reason}")

        # Trade-Record loggen
        record = PaperTradeRecord(
            record_id=generate_record_id(),
            timestamp=now,
            proposal_id=position.proposal_id,
            market_id=position.market_id,
            action="PARTIAL_EXIT",
            reason=(
                f"Partial exit {fraction:.0%}: {reason} | "
                f"exit @ {exit_price:.4f} | P&L: {partial_pnl:+.2f} EUR ({pnl_pct:+.1f}%)"
            ),
            position_id=position.position_id,
            snapshot_time=snapshot.snapshot_time,
            entry_price=position.entry_price,
            exit_price=exit_price,
            slippage_applied=exit_slippage,
            pnl_eur=partial_pnl,
        )
        log_trade(record)

        logger.info(
            f"PARTIAL_EXIT ({fraction:.0%}): {position.market_id} | "
            f"{reason} | P&L: {partial_pnl:+.2f} EUR"
        )

        return partial_pnl

    def _full_exit_remaining(
        self,
        position: PaperPosition,
        snapshot: MarketSnapshot,
        tp_entry: Dict[str, Any],
        reason: str,
    ) -> float:
        """
        Schliesse restliche Position vollstaendig (nach partiellen Exits).

        Berechnet P&L nur fuer den verbliebenen Anteil und korrigiert
        die simulate_exit_market Berechnung entsprechend.
        """
        remaining_fraction = 1.0 - tp_entry.get("exited_fraction", 0.0)

        if remaining_fraction <= 0.01:
            logger.info(f"Position {position.position_id} bereits vollstaendig exits, Skip.")
            return 0.0

        if remaining_fraction >= 0.99:
            # Kein partieller Exit vorher - normal schliessen
            closed, record = simulate_exit_market(position, snapshot, reason)
            return closed.realized_pnl_eur or 0.0

        # Partiell: erstelle "virtuelle" Rest-Position fuer korrekte P&L-Berechnung
        # Direkte Berechnung fuer den Restanteil
        exit_result = calculate_exit_price(snapshot, position.side, is_resolution=False)
        if exit_result:
            exit_price, exit_slippage = exit_result
        else:
            exit_price = snapshot.mid_price or position.entry_price
            exit_slippage = 0.0

        remaining_contracts = position.size_contracts * remaining_fraction
        remaining_cost = position.cost_basis_eur * remaining_fraction
        revenue = remaining_contracts * exit_price
        remaining_pnl = revenue - remaining_cost
        pnl_pct = (remaining_pnl / remaining_cost * 100) if remaining_cost > 0 else 0.0

        now = datetime.now().isoformat()

        # Schliesse Position korrekt (CLOSED Status)
        from paper_trader.models import PaperPosition as PP
        from paper_trader.logger import log_position

        closed_position = PP(
            position_id=position.position_id,
            proposal_id=position.proposal_id,
            market_id=position.market_id,
            market_question=position.market_question,
            side=position.side,
            status="CLOSED",
            entry_time=position.entry_time,
            entry_price=position.entry_price,
            entry_slippage=position.entry_slippage,
            size_contracts=position.size_contracts,
            cost_basis_eur=position.cost_basis_eur,
            exit_time=now,
            exit_price=exit_price,
            exit_slippage=exit_slippage,
            exit_reason=reason,
            realized_pnl_eur=remaining_pnl,
            pnl_pct=pnl_pct,
        )

        record = PaperTradeRecord(
            record_id=generate_record_id(),
            timestamp=now,
            proposal_id=position.proposal_id,
            market_id=position.market_id,
            action=TradeAction.PAPER_EXIT.value,
            reason=(
                f"{reason} (rest {remaining_fraction:.0%}): "
                f"exit @ {exit_price:.4f} | P&L: {remaining_pnl:+.2f} EUR"
            ),
            position_id=position.position_id,
            snapshot_time=snapshot.snapshot_time,
            entry_price=position.entry_price,
            exit_price=exit_price,
            slippage_applied=exit_slippage,
            pnl_eur=remaining_pnl,
        )

        release_capital(remaining_cost, remaining_pnl, f"Final exit: {reason}")
        log_position(closed_position)
        log_trade(record)

        logger.info(
            f"FINAL_EXIT (rest {remaining_fraction:.0%}): {position.market_id} | "
            f"{reason} | P&L: {remaining_pnl:+.2f} EUR"
        )

        return remaining_pnl

    def check_mid_trade_exits(self) -> Dict[str, Any]:
        """
        Check open positions for staged take-profit or stop-loss conditions.

        Gestaffelte Logik (adaptiert aus tradingbot/risk_engine.py):
        - TP1 @+10%: 40% Partial Exit, Trailing Stop auf Entry-Preis setzen
        - TP2 @+18%: 40% Partial Exit, Trailing Stop erhoehen
        - TP3 @+25%: Restliche 20% vollstaendig schliessen
        - Trailing Stop: Exit wenn Preis unter Stop faellt
        - Stop-Loss: -25% sofortiger Vollausgang

        Returns:
            Summary with counts and P&L
        """
        open_positions = self.get_open_positions()
        if not open_positions:
            return {"checked": 0, "take_profit": 0, "stop_loss": 0, "pnl_eur": 0.0}

        market_ids = [p.market_id for p in open_positions]
        snapshots = get_market_snapshots(market_ids)

        tp_state = _load_tp_state()
        tp_count = 0
        sl_count = 0
        total_pnl = 0.0
        state_changed = False

        for position in open_positions:
            snapshot = snapshots.get(position.market_id)
            if snapshot is None or snapshot.mid_price is None:
                continue
            if snapshot.is_resolved:
                continue  # wird von check_and_close_resolved behandelt

            current_price = snapshot.mid_price
            entry_price = position.entry_price
            if entry_price <= 0:
                continue

            unrealized_pct = self._calc_unrealized_pct(position, current_price)
            pos_id = position.position_id
            tp_entry = tp_state.get(pos_id, _default_tp_entry())

            exited_fraction = tp_entry.get("exited_fraction", 0.0)
            remaining_fraction = 1.0 - exited_fraction

            # ---------------------------------------------------------------
            # STOP-LOSS: Immer zuerst pruefen (Prioritaet: Verlust begrenzen)
            # ---------------------------------------------------------------
            if unrealized_pct <= self.STOP_LOSS_PCT:
                pnl = self._full_exit_remaining(position, snapshot, tp_entry, f"Stop-Loss ({unrealized_pct:+.1%})")
                total_pnl += pnl
                sl_count += 1
                # TP-State loeschen (Position geschlossen)
                tp_state.pop(pos_id, None)
                state_changed = True
                logger.info(f"SL: {position.market_id} | {unrealized_pct:+.1%} | P&L: {pnl:+.2f} EUR")
                continue

            # ---------------------------------------------------------------
            # TRAILING STOP: Wenn aktiv und Preis unterschritten
            # ---------------------------------------------------------------
            trailing_stop = tp_entry.get("trailing_stop_price")
            if trailing_stop is not None:
                # Bei YES: stop wenn aktueller YES-Preis < trailing_stop
                # Bei NO: stop wenn aktueller YES-Preis > trailing_stop
                stop_triggered = False
                if position.side == "YES" and current_price < trailing_stop:
                    stop_triggered = True
                elif position.side == "NO" and current_price > trailing_stop:
                    stop_triggered = True

                if stop_triggered:
                    pnl = self._full_exit_remaining(
                        position, snapshot, tp_entry,
                        f"Trailing-Stop ({unrealized_pct:+.1%}, stop@{trailing_stop:.4f})"
                    )
                    total_pnl += pnl
                    tp_count += 1
                    tp_state.pop(pos_id, None)
                    state_changed = True
                    logger.info(
                        f"TRAILING_STOP: {position.market_id} | "
                        f"{unrealized_pct:+.1%} | P&L: {pnl:+.2f} EUR"
                    )
                    continue

            # ---------------------------------------------------------------
            # TP3: +25% -> restliche 20% schliessen
            # ---------------------------------------------------------------
            if tp_entry.get("tp2_hit") and not tp_entry.get("tp3_hit") and unrealized_pct >= self.TP3_PCT:
                pnl = self._full_exit_remaining(
                    position, snapshot, tp_entry,
                    f"TP3 ({unrealized_pct:+.1%})"
                )
                total_pnl += pnl
                tp_count += 1
                tp_state.pop(pos_id, None)
                state_changed = True
                logger.info(f"TP3: {position.market_id} | {unrealized_pct:+.1%} | P&L: {pnl:+.2f} EUR")
                continue

            # ---------------------------------------------------------------
            # TP2: +18% -> weitere 40% verkaufen
            # ---------------------------------------------------------------
            if tp_entry.get("tp1_hit") and not tp_entry.get("tp2_hit") and unrealized_pct >= self.TP2_PCT:
                pnl = self._partial_exit(position, snapshot, self.TP2_FRACTION, f"TP2 ({unrealized_pct:+.1%})")
                total_pnl += pnl
                tp_count += 1

                # Trailing Stop erhoehen auf halbe aktuelle Gewinne
                new_trailing = self._calc_trailing_stop_price(position, unrealized_pct * 0.5)
                tp_state[pos_id] = {
                    **tp_entry,
                    "tp2_hit": True,
                    "trailing_stop_price": new_trailing,
                    "exited_fraction": exited_fraction + self.TP2_FRACTION,
                    "accumulated_partial_pnl": tp_entry.get("accumulated_partial_pnl", 0.0) + pnl,
                }
                state_changed = True
                logger.info(
                    f"TP2: {position.market_id} | {unrealized_pct:+.1%} | "
                    f"P&L: {pnl:+.2f} EUR | Trailing@{new_trailing:.4f}"
                )
                continue

            # ---------------------------------------------------------------
            # TP1: +10% -> 40% verkaufen, Trailing Stop auf Entry setzen
            # ---------------------------------------------------------------
            if not tp_entry.get("tp1_hit") and unrealized_pct >= self.TP1_PCT:
                pnl = self._partial_exit(position, snapshot, self.TP1_FRACTION, f"TP1 ({unrealized_pct:+.1%})")
                total_pnl += pnl
                tp_count += 1

                # Trailing Stop = Entry-Preis (Break-Even)
                trailing_stop_price = self._calc_trailing_stop_price(position, 0.0)
                tp_state[pos_id] = {
                    **_default_tp_entry(),
                    "tp1_hit": True,
                    "trailing_stop_price": trailing_stop_price,
                    "exited_fraction": self.TP1_FRACTION,
                    "accumulated_partial_pnl": pnl,
                }
                state_changed = True
                logger.info(
                    f"TP1: {position.market_id} | {unrealized_pct:+.1%} | "
                    f"P&L: {pnl:+.2f} EUR | Trailing@{trailing_stop_price:.4f}"
                )

        if state_changed:
            _save_tp_state(tp_state)

        # Alte TP-States fuer geschlossene Positionen bereinigen
        self._cleanup_tp_state(tp_state)

        summary = {
            "checked": len(open_positions),
            "take_profit": tp_count,
            "stop_loss": sl_count,
            "pnl_eur": total_pnl,
        }

        if tp_count or sl_count:
            logger.info(f"Mid-trade exits: {tp_count} TP/Trail, {sl_count} SL, P&L: {total_pnl:+.2f} EUR")

        return summary

    def _calc_trailing_stop_price(self, position: PaperPosition, lock_in_pct: float) -> float:
        """
        Berechne Trailing Stop Preis der mindestens lock_in_pct Gewinn sichert.

        Args:
            position: Offene Position
            lock_in_pct: Mindestgewinn der gesichert werden soll (z.B. 0.0 = Break-Even)

        Returns:
            Stop-Preis (fuer YES: Minimum-Kurs, fuer NO: Maximum-Kurs)
        """
        entry = position.entry_price
        if position.side == "YES":
            return entry * (1.0 + lock_in_pct)  # bei YES: stop UNTER entry*(1+pct)
        else:
            return entry * (1.0 - lock_in_pct)  # bei NO: stop UEBER entry*(1-pct)

    def _cleanup_tp_state(self, tp_state: Dict[str, Any]) -> None:
        """Entferne TP-States fuer nicht mehr offene Positionen."""
        try:
            open_positions = self.get_open_positions()
            open_ids = {p.position_id for p in open_positions}
            stale = [pid for pid in list(tp_state.keys()) if pid not in open_ids]
            if stale:
                for pid in stale:
                    tp_state.pop(pid, None)
                _save_tp_state(tp_state)
                logger.debug(f"TP-State: {len(stale)} veraltete Eintraege bereinigt")
        except Exception as e:
            logger.debug(f"TP-State cleanup: {e}")

    def get_position_summary(self) -> Dict[str, Any]:
        """
        Get summary of all positions.

        Returns:
            Summary dictionary
        """
        all_positions = self._paper_logger.read_all_positions()

        # Build latest state for each position
        position_states: Dict[str, PaperPosition] = {}
        for pos in all_positions:
            position_states[pos.position_id] = pos

        # Count by status
        open_count = 0
        closed_count = 0
        resolved_count = 0
        total_pnl = 0.0
        total_cost = 0.0

        for pos in position_states.values():
            if pos.status == "OPEN":
                open_count += 1
                total_cost += pos.cost_basis_eur
            elif pos.status == "CLOSED":
                closed_count += 1
                if pos.realized_pnl_eur is not None:
                    total_pnl += pos.realized_pnl_eur
            elif pos.status == "RESOLVED":
                resolved_count += 1
                if pos.realized_pnl_eur is not None:
                    total_pnl += pos.realized_pnl_eur

        return {
            "total_positions": len(position_states),
            "open": open_count,
            "closed": closed_count,
            "resolved": resolved_count,
            "total_realized_pnl_eur": total_pnl,
            "open_cost_basis_eur": total_cost,
        }


# =============================================================================
# MODULE-LEVEL FUNCTIONS
# =============================================================================

_manager: Optional[PositionManager] = None


def get_position_manager() -> PositionManager:
    """Get the global position manager instance."""
    global _manager
    if _manager is None:
        _manager = PositionManager()
    return _manager


def get_open_positions() -> List[PaperPosition]:
    """Convenience function to get open positions."""
    return get_position_manager().get_open_positions()


def check_and_close_resolved() -> Dict[str, Any]:
    """Convenience function to check and close resolved positions."""
    return get_position_manager().check_and_close_resolved()


def check_mid_trade_exits() -> Dict[str, Any]:
    """Convenience function to check take-profit/stop-loss exits."""
    return get_position_manager().check_mid_trade_exits()


def get_position_summary() -> Dict[str, Any]:
    """Convenience function to get position summary."""
    return get_position_manager().get_position_summary()
