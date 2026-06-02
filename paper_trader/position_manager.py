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
import tempfile
from datetime import datetime, timezone
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
from paper_trader.simulator import simulate_exit_resolution, simulate_exit_market, record_sl_cooloff
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

            # Zombie check: fire when snapshot is unavailable (None) OR has no price
            # data (mid_price is None). Daily weather markets resolve within 1-2 days.
            # Root cause of 28 accumulated zombies: Gamma API returned non-None snapshot
            # objects with mid_price=None for old markets → the `snapshot is None` check
            # did not fire → positions stayed OPEN indefinitely.
            if snapshot is None or snapshot.mid_price is None:
                try:
                    entry_dt = datetime.fromisoformat(position.entry_time)
                    if entry_dt.tzinfo is None:
                        entry_dt = entry_dt.replace(tzinfo=timezone.utc)
                    age_days = (datetime.now(timezone.utc) - entry_dt).days
                    if age_days >= 2:
                        no_data_reason = "no snapshot" if snapshot is None else "no price data"
                        logger.info(
                            f"Zombie expiry: {position.market_id} | age={age_days}d | "
                            f"{no_data_reason}"
                        )
                        self._paper_logger.expire_position(position)
                        closed_count += 1
                        continue
                except Exception:
                    pass
                logger.debug(f"No snapshot/price for {position.market_id} - keeping open")
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
    # GESTAFFELTE TAKE-PROFIT SCHWELLEN - Strategie: Kleine konstante Gewinne
    # ==========================================================================
    # TP1: +15% -> 50% der Position verkaufen
    # TP2: +20% -> weitere 35% verkaufen (kumuliert: 85%)
    # TP3: +25% -> Restliche 15% schliessen
    # Stop-Loss: -0.70 (70%) — Prediction markets resolve binary (0 or 1).
    # Resolution WR=89% when held; a tight -25% SL was exiting winners early.
    # Historisch: 120/237 Trades wurden bei -25% gestoppt → -2562 EUR Verlust.
    # Mit -70% halten HIGH-confidence-Positionen bis zur Auflösung.
    TP1_PCT = 0.15
    TP1_FRACTION = 0.50   # 50% bei TP1 verkaufen
    TP2_PCT = 0.20
    TP2_FRACTION = 0.35   # 35% bei TP2 verkaufen (kumuliert: 85%)
    TP3_PCT = 0.25        # Restliche 15% bei TP3 schliessen
    STOP_LOSS_PCT = -0.40  # Tightened from -0.70: avg SL loss was -4.11 EUR, reduces to ~-2.35 EUR
    MIN_EXIT_LIQUIDITY_BUCKETS = {"HIGH", "MEDIUM"}
    INVALID_PRICE_LOW = 0.02
    INVALID_PRICE_HIGH = 0.98

    # ==========================================================================
    # RESOLUTION-HOLD STRATEGIE
    # ==========================================================================
    # YES-Positionen auf at_or_above/at_or_below Märkten dürfen bei Annäherung
    # an die Auflösung NICHT durch Stop-Loss oder Trailing-Stop geschlossen werden.
    #
    # Begründung: Wettermärkte auf Temperaturschwellen haben auf Auflösungstag
    # extreme Preisausschläge (z.B. -70% intraday), weil Market-Maker ihre
    # Positionen vor Auflösung hedgen. Diese Ausschläge treffen den Stop-Loss,
    # obwohl die Vorhersage KORREKT ist (und YES zu 1.0 aufgelöst wird).
    #
    # Lösung: 48h vor geschätzter Auflösung -> alle SL/Trailing-Stop-Checks
    # für YES-Positionen deaktivieren. Erweitert von 24h auf 48h:
    # Evidenz: Atlanta YES at_or_above (45h entry) wäre mit 24h-Fenster in TP-Gefahr.
    # YES hat 100% WR (4/4) → lohnt sich, volle binäre Auflösung abzuwarten.
    RESOLUTION_HOLD_HOURS: float = 48.0       # Stunden vor Auflösung -> SL deaktivieren (erhöht von 24h)
    # YES-Positionen auf allen binären Wetter-Typen haben 100% WR wenn zur Auflösung gehalten.
    # Resolution-Day Intraday-Spikes triggern sonst -40% SL auf korrekten Positionen.
    RESOLUTION_HOLD_MARKET_TYPES = frozenset({"at_or_above", "at_or_below", "exact", "between"})

    @staticmethod
    def _estimate_hours_to_resolution(position: "PaperPosition") -> Optional[float]:
        """
        Schätze verbleibende Stunden bis zur Auflösung.

        Berechnung: hours_to_resolution (bei Entry) - vergangene Zeit seit Entry.

        Returns:
            Geschätzte Stunden bis Auflösung, oder None wenn nicht berechenbar.
        """
        hours_at_entry = getattr(position, "hours_to_resolution", None)
        if hours_at_entry is None:
            return None
        entry_time_str = getattr(position, "entry_time", None)
        if not entry_time_str:
            return None
        try:
            entry_dt = datetime.fromisoformat(str(entry_time_str))
            if entry_dt.tzinfo is None:
                entry_dt = entry_dt.replace(tzinfo=timezone.utc)
            now = datetime.now(timezone.utc)
            hours_elapsed = (now - entry_dt).total_seconds() / 3600.0
            return float(hours_at_entry) - hours_elapsed
        except Exception:
            return None

    def _is_in_resolution_hold(self, position: "PaperPosition") -> bool:
        """
        Prüfe ob eine Position im Resolution-Hold-Fenster ist.

        Gilt für alle YES-Positionen (alle Markttypen),
        wenn die geschätzte Restzeit bis Auflösung < RESOLUTION_HOLD_HOURS (48h).

        Returns:
            True wenn Stop-Loss/Trailing-Stop deaktiviert werden sollen.
        """
        if position.side != "YES":
            return False
        market_type = str(getattr(position, "market_type", "") or "").lower()
        if market_type not in self.RESOLUTION_HOLD_MARKET_TYPES:
            return False
        hours_remaining = self._estimate_hours_to_resolution(position)
        if hours_remaining is None:
            return False
        return hours_remaining <= self.RESOLUTION_HOLD_HOURS

    def _calc_unrealized_pct(self, position: PaperPosition, current_price: float) -> float:
        """Berechne unrealisierten P&L in Prozent (relativ zu Entry).

        current_price ist immer der YES-Preis (snapshot.mid_price).
        Fuer NO-Positionen wird er in den aktuellen NO-Preis umgerechnet.
        """
        entry = position.entry_price
        if entry <= 0:
            return 0.0
        # BUGFIX: Clamp current_price to valid [0, 1] range.
        # Gamma API can return prices > 1.0, causing impossible NO P&L.
        current_price = max(0.0, min(1.0, current_price))
        if position.side == "NO":
            # NO-Wert = 1 - YES-Preis; Vergleich mit dem NO-Entry-Preis
            current_no_price = 1.0 - current_price
            return (current_no_price - entry) / entry
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

        # BUGFIX: Include accumulated partial P&L from earlier TP exits (TP1, TP2)
        # Without this, positions that went through staged TP show only the
        # final portion's P&L, hiding profits from partial exits.
        accumulated_pnl = tp_entry.get("accumulated_partial_pnl", 0.0)
        total_pnl = remaining_pnl + accumulated_pnl
        # P&L percentage based on FULL cost basis (not just remaining fraction)
        pnl_pct = (total_pnl / position.cost_basis_eur * 100) if position.cost_basis_eur > 0 else 0.0

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
            realized_pnl_eur=total_pnl,
            pnl_pct=pnl_pct,
            confidence_level=position.confidence_level,
            market_type=position.market_type,
            proposal_edge=getattr(position, "proposal_edge", None),
            hours_to_resolution=getattr(position, "hours_to_resolution", None),
            edge_bucket=getattr(position, "edge_bucket", None),
            city=getattr(position, "city", None),
        )

        record = PaperTradeRecord(
            record_id=generate_record_id(),
            timestamp=now,
            proposal_id=position.proposal_id,
            market_id=position.market_id,
            action=TradeAction.PAPER_EXIT.value,
            reason=(
                f"{reason} (rest {remaining_fraction:.0%}): "
                f"exit @ {exit_price:.4f} | P&L: {total_pnl:+.2f} EUR "
                f"(partial: {accumulated_pnl:+.2f} + final: {remaining_pnl:+.2f})"
            ),
            position_id=position.position_id,
            snapshot_time=snapshot.snapshot_time,
            entry_price=position.entry_price,
            exit_price=exit_price,
            slippage_applied=exit_slippage,
            pnl_eur=total_pnl,
        )

        release_capital(remaining_cost, remaining_pnl, f"Final exit: {reason}")
        log_position(closed_position)
        log_trade(record)

        # Darwin-Feedback: Signal-Typ lernt aus Trade-Ergebnis
        try:
            from analytics.signal_darwin import get_darwin
            darwin = get_darwin()
            darwin.record_result(
                confidence_level=getattr(position, "confidence_level", None),
                market_type=getattr(position, "market_type", None),
                win=total_pnl > 0,
            )
            darwin.maybe_rebalance()
        except Exception:
            pass  # Fail-open

        logger.info(
            f"FINAL_EXIT (rest {remaining_fraction:.0%}): {position.market_id} | "
            f"{reason} | total P&L: {total_pnl:+.2f} EUR "
            f"(partial: {accumulated_pnl:+.2f} + final: {remaining_pnl:+.2f})"
        )

        return total_pnl

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

            liquidity_bucket = str(getattr(snapshot, "liquidity_bucket", "UNKNOWN") or "UNKNOWN").upper()
            if liquidity_bucket not in self.MIN_EXIT_LIQUIDITY_BUCKETS:
                hours_rem_liq = self._estimate_hours_to_resolution(position)

                # EMERGENCY-SL: Force exit even in LOW-liquidity markets when:
                # loss is severe (>55%) AND position is within 36h of resolution.
                # Normal SL at -40% cannot execute in LOW-liq markets.
                # Evidence: all 10 historical SL exits lost -70% to -93% because
                # the LOW-liq skip prevented any protective action (Emergency-SL
                # only triggered at <=-70% AND <12h — too late).
                # 2026-04-19: Threshold tightened -0.70→-0.55, window 12h→36h
                # to catch positions earlier in their drawdown.
                _emg_price = snapshot.mid_price
                if (
                    _emg_price is not None
                    and position.entry_price > 0
                    and hours_rem_liq is not None
                    and hours_rem_liq < 36.0
                ):
                    _unrealized_emg = self._calc_unrealized_pct(position, _emg_price)
                    if _unrealized_emg <= -0.55:
                        _tp_entry_emg = tp_state.get(position.position_id, _default_tp_entry())
                        pnl = self._full_exit_remaining(
                            position, snapshot, _tp_entry_emg,
                            f"Emergency-SL: LOW-liq near-resolution ({_unrealized_emg:+.1%})",
                        )
                        total_pnl += pnl
                        sl_count += 1
                        tp_state.pop(position.position_id, None)
                        state_changed = True
                        try:
                            record_sl_cooloff(position.market_id)
                        except Exception as _emg_err:
                            logger.debug("Emergency-SL cooloff failed: %s", _emg_err)
                        logger.warning(
                            "EMERGENCY-SL: %s (%s) | %.1fh to resolution | %+.1f%% loss | "
                            "Force-closing LOW-liq position at -55%% threshold (36h window)",
                            position.market_id, position.side, hours_rem_liq, _unrealized_emg * 100,
                        )
                        continue

                    # EMERGENCY-TP (Profit Lock-In): Force-close LOW-liq YES positions
                    # near resolution when already in profit.
                    # LOW-liq markets have unreliable resolution: spreads widen to 50%+
                    # in the final hours, and intraday reversals can erase gains before
                    # resolution settles.  At <12h AND +15%+ gain, locking in is better
                    # than risking an illiquid adverse resolution.
                    # Evidence: Atlanta 74°F (LOW-liq, 13.1h to res) — if YES price
                    # reverses from +30% to 0% in the last hours, Emergency-SL only
                    # triggers at -70% from entry, leaving all profit at risk.
                    if (
                        position.side == "YES"
                        and hours_rem_liq is not None
                        and hours_rem_liq < 12.0
                        and _unrealized_emg >= 0.15
                    ):
                        _tp_entry_emg = tp_state.get(position.position_id, _default_tp_entry())
                        pnl = self._full_exit_remaining(
                            position, snapshot, _tp_entry_emg,
                            f"Emergency-TP: LOW-liq profit lock-in ({_unrealized_emg:+.1%})",
                        )
                        total_pnl += pnl
                        tp_count += 1
                        tp_state.pop(position.position_id, None)
                        state_changed = True
                        logger.info(
                            "EMERGENCY-TP: %s (%s) | %.1fh to resolution | %+.1f%% gain | "
                            "Locking in profit on LOW-liquidity position",
                            position.market_id, position.side, hours_rem_liq, _unrealized_emg * 100,
                        )
                        continue

                if hours_rem_liq is not None and hours_rem_liq < 24.0:
                    logger.warning(
                        "RISK: LOW liquidity position %s (%s) hat nur %.1fh bis Aufloesung "
                        "— SL/TP nicht moeglich, Position koennte voll verlieren!",
                        position.market_id,
                        position.side,
                        hours_rem_liq,
                    )
                else:
                    logger.warning(
                        "Skipping SL/TP for %s: liquidity bucket %s too thin",
                        position.market_id,
                        liquidity_bucket,
                    )
                continue

            current_price = snapshot.mid_price
            entry_price = position.entry_price
            if entry_price <= 0:
                continue

            # Guard: skip SL/TP when API returns a boundary price (0.0 or 1.0).
            # Gamma API occasionally returns mid_price > 1.0 for NO-dominant markets.
            # _calc_unrealized_pct clamps to [0,1], but clamping to 1.0 gives
            # current_no=0.0 → unrealized=-100% for NO positions, triggering
            # a spurious SL exit. Prices at exact boundaries are invalid data.
            if current_price <= self.INVALID_PRICE_LOW or current_price >= self.INVALID_PRICE_HIGH:
                logger.warning(
                    "Skipping SL/TP for %s: mid_price %.4f is at boundary "
                    "(likely invalid API data)", position.market_id, current_price
                )
                continue

            unrealized_pct = self._calc_unrealized_pct(position, current_price)
            pos_id = position.position_id
            tp_entry = tp_state.get(pos_id, _default_tp_entry())
            exited_fraction = tp_entry.get("exited_fraction", 0.0)

            # ---------------------------------------------------------------
            # RESOLUTION-HOLD: SL/Trailing für YES-Positionen nahe Auflösung
            # deaktivieren. Wettermärkte zeigen auf Auflösungstag extreme
            # Intraday-Ausschläge die SL triggern, obwohl die Vorhersage stimmt.
            # ---------------------------------------------------------------
            in_resolution_hold = self._is_in_resolution_hold(position)
            hours_remaining = self._estimate_hours_to_resolution(position)
            if in_resolution_hold:
                logger.info(
                    "RESOLUTION-HOLD aktiv für %s | %.1fh bis Auflösung | "
                    "SL/Trailing deaktiviert (YES %s Markt)",
                    position.market_id[:40],
                    hours_remaining or 0,
                    getattr(position, "market_type", "?"),
                )

            # ---------------------------------------------------------------
            # STOP-LOSS: Immer zuerst pruefen (Prioritaet: Verlust begrenzen)
            # Im Resolution-Hold-Fenster übersprungen (halten bis Auflösung).
            # ---------------------------------------------------------------
            if not in_resolution_hold and unrealized_pct <= self.STOP_LOSS_PCT:
                pnl = self._full_exit_remaining(position, snapshot, tp_entry, f"Stop-Loss ({unrealized_pct:+.1%})")
                total_pnl += pnl
                sl_count += 1
                # TP-State loeschen (Position geschlossen)
                tp_state.pop(pos_id, None)
                state_changed = True
                # Register cooling-off so re-entry on this market is blocked
                try:
                    record_sl_cooloff(position.market_id)
                except Exception as _sl_err:
                    logger.debug("SL cooloff register failed: %s", _sl_err)
                logger.info(f"SL: {position.market_id} | {unrealized_pct:+.1%} | P&L: {pnl:+.2f} EUR")
                continue

            # ---------------------------------------------------------------
            # TRAILING STOP: Wenn aktiv und Preis unterschritten
            # Im Resolution-Hold-Fenster übersprungen.
            # ---------------------------------------------------------------
            trailing_stop = tp_entry.get("trailing_stop_price")
            if not in_resolution_hold and trailing_stop is not None:
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
            # RESOLUTION-HOLD: TP-Exits fuer YES-Positionen nahe Aufloesung
            # deaktivieren. Binaere Maerkte zahlen 100-300% bei Resolution
            # vs. 15-25% TP. YES hat 100% historische WR → halten lohnt sich.
            # Evidenz: YES-TP-Exits brachten avg +1.68 EUR, Resolution wuerde
            # avg +5-15 EUR bringen (Entry 0.30-0.45 → Resolution 1.0).
            # ---------------------------------------------------------------
            if in_resolution_hold and position.side == "YES":
                logger.info(
                    "RESOLUTION-HOLD: TP-Exit uebersprungen fuer YES %s | "
                    "%.1fh bis Aufloesung | Unrealized: %+.1f%% | "
                    "Halten bis binaere Aufloesung (100%% hist. WR)",
                    position.market_id[:40],
                    hours_remaining or 0,
                    unrealized_pct * 100,
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

                # Trailing Stop = +5% above entry after TP1 (lock in meaningful profit).
                # Raised from +3%: at 5% floor, even if the trailing fires right after
                # TP1, the blended exit on the remaining 50% gives net +10% on the trade.
                # With the new stricter entry filters, every trade that gets in is higher
                # quality — we should protect the gains more aggressively.
                trailing_stop_price = self._calc_trailing_stop_price(position, 0.05)
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

        Der Stop-Preis wird als YES-Marktpreis ausgedrueckt (snapshot.mid_price).
        Bei YES: Stop = YES-Preis faellt unter Schwelle.
        Bei NO: Stop = YES-Preis steigt ueber Schwelle
                (da NO-Wert = 1 - YES-Preis, steigt YES -> faellt NO).

        Args:
            position: Offene Position
            lock_in_pct: Mindestgewinn der gesichert werden soll (z.B. 0.0 = Break-Even)

        Returns:
            Stop-Preis als YES-Marktpreis-Schwelle
        """
        entry = position.entry_price
        if position.side == "YES":
            # YES-Stop: Exit wenn YES-Preis unter entry*(1+lock_in_pct) faellt
            return entry * (1.0 + lock_in_pct)
        else:
            # NO-Entry-Preis entsp. 1 - YES_entry_price
            # Break-Even-NO-Preis: entry*(1+lock_in_pct)
            # Als YES-Schwelle: YES > 1 - entry*(1+lock_in_pct)
            return 1.0 - entry * (1.0 + lock_in_pct)

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

    # Guardrail constants (mirrors simulator.py)
    _BLOCKED_MARKET_TYPES_NO = frozenset({"between", "exact"})
    _MIN_YES_ENTRY_PRICE = 0.05
    # 2026-06-02: Aligned with simulator.WEAK_PERFORMANCE_CITIES (empty per
    # 2026-04-18 autopsy). The stale hardcoded list here was force-closing
    # legitimately-opened London/LA/NYC/Seattle/SF positions, eating slippage
    # without giving the strategy a chance. Dynamic blocking is now handled
    # entry-side via auto_city_blacklist; post-entry city blocks were causing
    # pure friction loss (e.g. 2026-06-02 London trio = -1.39 EUR slippage).
    _WEAK_PERFORMANCE_CITIES = frozenset()

    @staticmethod
    def _extract_city(market_question: str) -> Optional[str]:
        """Extract city name from market question (lower-cased)."""
        import re
        m = re.search(r"temperature in ([A-Za-z\s]+?)\s+(?:be|exceed|reach)", market_question, re.IGNORECASE)
        return m.group(1).strip().lower() if m else None

    @staticmethod
    def _violates_guardrail(position: "PaperPosition") -> Optional[str]:
        """
        Return a reason string if the position violates any current entry guardrail,
        or None if the position is compliant.

        Guardrails checked (mirror simulator._entry_quality_gate):
        1. NO bets on "between" / "exact" market types (0% historical WR)
        2. YES bets entered at near-zero price (<5%) — model miscalibration signal
        3. Positions in weak-performance cities (≤33% historical WR)
        """
        import re as _re
        market_type = str(getattr(position, "market_type", "") or "").lower()
        is_no_bet = position.side == "NO"
        entry_price = float(getattr(position, "entry_price", 0.5) or 0.5)

        # Rule 1: NO bet on narrow-band market
        if is_no_bet and market_type in PositionManager._BLOCKED_MARKET_TYPES_NO:
            return (
                f"NO-{market_type} position: 0% historical WR on narrow-band NO bets "
                "(resolution-day price spikes trigger -70% SL even on correct forecasts)"
            )

        # Rule 2: YES bet at near-zero entry price (model miscalibration)
        if not is_no_bet and entry_price < PositionManager._MIN_YES_ENTRY_PRICE:
            return (
                f"YES position at {entry_price:.1%} entry price — below {PositionManager._MIN_YES_ENTRY_PRICE:.0%} minimum: "
                "extreme model-vs-market divergence (lottery-ticket bet)"
            )

        # Rule 3: Blocked city
        city = PositionManager._extract_city(getattr(position, "market_question", "") or "")
        if city and city in PositionManager._WEAK_PERFORMANCE_CITIES:
            return (
                f"City '{city}' is on the blocked list (≤33% historical WR). "
                "Re-evaluate after ≥10 trades show ≥50% WR."
            )

        return None

    def check_guardrail_violations(self) -> Dict[str, Any]:
        """
        Force-close open positions that would now be blocked by the entry guardrail.

        Catches legacy positions entered before a guardrail rule was active.
        Closes:
          - NO bets on "between" / "exact" markets (0% historical WR)
          - YES bets entered at near-zero price (<5%) — model miscalibration
          - Positions in weak-performance cities (London, NYC, LA, SF, Seattle)

        Returns:
            Summary with count of positions force-closed and P&L.
        """
        open_positions = self.get_open_positions()
        if not open_positions:
            return {"checked": 0, "force_closed": 0, "pnl_eur": 0.0}

        market_ids = [p.market_id for p in open_positions]
        snapshots = get_market_snapshots(market_ids)

        tp_state = _load_tp_state()
        force_closed = 0
        total_pnl = 0.0
        state_changed = False

        for position in open_positions:
            violation_reason = self._violates_guardrail(position)
            if violation_reason is None:
                continue  # Position is fine under current rules

            snapshot = snapshots.get(position.market_id)
            pos_id = position.position_id
            tp_entry = tp_state.get(pos_id, _default_tp_entry())

            snapshot = snapshots.get(position.market_id)
            pos_id = position.position_id
            tp_entry = tp_state.get(pos_id, _default_tp_entry())

            close_reason = f"Guardrail-Exit: {violation_reason}"
            if snapshot is not None and snapshot.mid_price is not None and not snapshot.is_resolved:
                pnl = self._full_exit_remaining(position, snapshot, tp_entry, close_reason)
            else:
                # No snapshot: expire the position to clear it from the book
                logger.info(
                    "Guardrail-Exit (no snapshot): expiring position %s — %s",
                    pos_id, violation_reason,
                )
                self._paper_logger.expire_position(position)
                pnl = 0.0

            total_pnl += pnl
            force_closed += 1
            tp_state.pop(pos_id, None)
            state_changed = True
            logger.info(
                "GUARDRAIL-EXIT: %s | %s | P&L: %+.2f EUR | %s",
                position.market_id, position.side, pnl, violation_reason,
            )

        if state_changed:
            _save_tp_state(tp_state)

        if force_closed:
            logger.info(
                "Guardrail violations: %d positions force-closed, P&L: %+.2f EUR",
                force_closed, total_pnl,
            )

        return {"checked": len(open_positions), "force_closed": force_closed, "pnl_eur": total_pnl}

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


def check_guardrail_violations() -> Dict[str, Any]:
    """Convenience function to force-close guardrail-violating positions."""
    return get_position_manager().check_guardrail_violations()
