# =============================================================================
# POLYMARKET BEOBACHTER - PAPER TRADING SIMULATOR
# =============================================================================
#
# GOVERNANCE INTENT:
# This module simulates trade entry and exit for paper trading.
# NO real orders are placed. NO funds are at risk.
#
# SIMULATION PRINCIPLES:
# - Never use hindsight
# - Never pick best price
# - Always apply conservative slippage
# - If market snapshot is unavailable, SKIP with reason
#
# PAPER TRADING ONLY:
# All execution is simulated. This module has NO access to:
# - Trading endpoints
# - Wallet functions
# - Order placement APIs
#
# =============================================================================

import re
import sys
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple, Final

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from proposals.models import Proposal

from paper_trader.models import (
    PaperPosition,
    PaperTradeRecord,
    MarketSnapshot,
    TradeAction,
    generate_position_id,
    generate_record_id,
)
from paper_trader.slippage import calculate_entry_price, calculate_exit_price
from paper_trader.snapshot_client import get_market_snapshot
from paper_trader.logger import get_paper_logger, log_trade, log_position
from paper_trader.capital_manager import (
    get_capital_manager,
    allocate_capital,
    release_capital,
    has_sufficient_capital,
)
from paper_trader.kelly import kelly_size, FALLBACK_POSITION_EUR
from paper_trader.drawdown_protector import check_can_open_position


logger = logging.getLogger(__name__)


# =============================================================================
# CONSTANTS
# =============================================================================

# Fixed paper trading amount in EUR
FIXED_AMOUNT_EUR: Final[float] = 100.0

# Simulated spread for fallback snapshots (%)
SIMULATED_SPREAD_PCT: Final[float] = 4.0

# Diversification limits
MAX_POSITIONS_PER_CITY_DATE: Final[int] = 1  # Exclusive markets: only 1 per city+date
MAX_POSITIONS_PER_CITY: Final[int] = 3        # Max positions per city overall


def _extract_city_date(market_question: str) -> tuple:
    """
    Extract city and date from a weather market question.

    Returns:
        Tuple of (city, date_str) or (None, None) if not parseable.
    """
    # Pattern: "...temperature in {City} be ... on {Date}?"
    m = re.search(
        r"temperature in ([A-Za-z\s]+?)\s+be\s+.+?\s+on\s+(.+?)\?",
        market_question,
        re.IGNORECASE,
    )
    if m:
        city = m.group(1).strip()
        date_str = m.group(2).strip().rstrip(".")
        return city, date_str
    # Fallback: "...temperature in {City} ... {Month} {Day}"
    m2 = re.search(
        r"temperature in ([A-Za-z\s]+?)(?:\s+be|\s+exceed|\s+reach)",
        market_question,
        re.IGNORECASE,
    )
    city = m2.group(1).strip() if m2 else None
    return city, None


# =============================================================================
# EXECUTION SIMULATOR
# =============================================================================


class ExecutionSimulator:
    """
    Simulates trade entry and exit for paper trading.

    GOVERNANCE:
    - NO real orders are placed
    - NO real funds are at risk
    - All execution is simulated with conservative slippage
    - If data is unavailable, SKIP with documented reason
    """

    def __init__(self, fixed_amount_eur: float = FIXED_AMOUNT_EUR):
        """
        Initialize the simulator.

        Args:
            fixed_amount_eur: Fixed paper trading amount per trade
        """
        self._capital_manager = get_capital_manager()
        # Use provided amount if explicitly set, otherwise use capital manager
        if fixed_amount_eur != FIXED_AMOUNT_EUR:
            self.fixed_amount_eur = fixed_amount_eur
        else:
            self.fixed_amount_eur = self._capital_manager.get_position_size()
        self._paper_logger = get_paper_logger()

    def simulate_entry(
        self,
        proposal: Proposal
    ) -> Tuple[Optional[PaperPosition], PaperTradeRecord]:
        """
        Simulate entering a paper position.

        GOVERNANCE:
        - Uses current market snapshot (no hindsight)
        - Applies conservative slippage
        - If snapshot unavailable, returns SKIP record

        Args:
            proposal: The proposal to simulate entry for

        Returns:
            Tuple of (PaperPosition or None, PaperTradeRecord)
            Position is None if entry was skipped.
        """
        now = datetime.now().isoformat()

        # Check position limit BEFORE attempting entry
        open_positions = self._paper_logger.get_open_positions()
        can_open, limit_reason = self._capital_manager.can_open_position(len(open_positions))
        if not can_open:
            record = PaperTradeRecord(
                record_id=generate_record_id(),
                timestamp=now,
                proposal_id=proposal.proposal_id,
                market_id=proposal.market_id,
                action=TradeAction.SKIP.value,
                reason=limit_reason,
                position_id=None,
                snapshot_time=None,
                entry_price=None,
                exit_price=None,
                slippage_applied=None,
                pnl_eur=None,
            )
            log_trade(record)
            logger.warning(f"SKIP: {limit_reason} for {proposal.market_id}")
            return (None, record)

        # DrawdownProtector: Keine neuen Positionen im Recovery-Modus
        dd_ok, dd_reason = check_can_open_position()
        if not dd_ok:
            record = PaperTradeRecord(
                record_id=generate_record_id(),
                timestamp=now,
                proposal_id=proposal.proposal_id,
                market_id=proposal.market_id,
                action=TradeAction.SKIP.value,
                reason=dd_reason,
                position_id=None,
                snapshot_time=None,
                entry_price=None,
                exit_price=None,
                slippage_applied=None,
                pnl_eur=None,
            )
            log_trade(record)
            logger.warning(f"SKIP (DrawdownProtector): {dd_reason} for {proposal.market_id}")
            return (None, record)

        # Check diversification: max positions per city+date (exclusive markets)
        new_city, new_date = _extract_city_date(proposal.market_question)
        if new_city:
            city_date_count = 0
            city_count = 0
            for pos in open_positions:
                pos_city, pos_date = _extract_city_date(pos.market_question)
                if pos_city and pos_city.lower() == new_city.lower():
                    city_count += 1
                    if pos_date and new_date and pos_date == new_date:
                        city_date_count += 1

            if new_date and city_date_count >= MAX_POSITIONS_PER_CITY_DATE:
                skip_reason = (
                    f"Exclusive market limit: already {city_date_count} position(s) "
                    f"for {new_city} on {new_date} (max {MAX_POSITIONS_PER_CITY_DATE})"
                )
                record = PaperTradeRecord(
                    record_id=generate_record_id(),
                    timestamp=now,
                    proposal_id=proposal.proposal_id,
                    market_id=proposal.market_id,
                    action=TradeAction.SKIP.value,
                    reason=skip_reason,
                    position_id=None,
                    snapshot_time=None,
                    entry_price=None,
                    exit_price=None,
                    slippage_applied=None,
                    pnl_eur=None,
                )
                log_trade(record)
                logger.warning(f"SKIP: {skip_reason} for {proposal.market_id}")
                return (None, record)

            if city_count >= MAX_POSITIONS_PER_CITY:
                skip_reason = (
                    f"City diversification limit: already {city_count} position(s) "
                    f"for {new_city} (max {MAX_POSITIONS_PER_CITY})"
                )
                record = PaperTradeRecord(
                    record_id=generate_record_id(),
                    timestamp=now,
                    proposal_id=proposal.proposal_id,
                    market_id=proposal.market_id,
                    action=TradeAction.SKIP.value,
                    reason=skip_reason,
                    position_id=None,
                    snapshot_time=None,
                    entry_price=None,
                    exit_price=None,
                    slippage_applied=None,
                    pnl_eur=None,
                )
                log_trade(record)
                logger.warning(f"SKIP: {skip_reason} for {proposal.market_id}")
                return (None, record)

        # Get market snapshot - or create simulated one from proposal
        snapshot = get_market_snapshot(proposal.market_id)

        if snapshot is None:
            # Create simulated snapshot from proposal price data
            implied_prob = proposal.implied_probability
            if implied_prob and 0.01 <= implied_prob <= 0.99:
                # Use proposal's implied probability as mid price
                snapshot = MarketSnapshot(
                    market_id=proposal.market_id,
                    snapshot_time=now,
                    best_bid=max(0.01, implied_prob - 0.02),
                    best_ask=min(0.99, implied_prob + 0.02),
                    mid_price=implied_prob,
                    spread_pct=SIMULATED_SPREAD_PCT,
                    liquidity_bucket="MEDIUM",
                    is_resolved=False,
                    resolved_outcome=None,
                )
                logger.info(f"Using simulated snapshot for {proposal.market_id} @ {implied_prob:.2f}")
            else:
                # SKIP: No snapshot and no valid implied probability
                record = PaperTradeRecord(
                    record_id=generate_record_id(),
                    timestamp=now,
                    proposal_id=proposal.proposal_id,
                    market_id=proposal.market_id,
                    action=TradeAction.SKIP.value,
                    reason="No snapshot and no valid implied probability",
                    position_id=None,
                    snapshot_time=None,
                    entry_price=None,
                    exit_price=None,
                    slippage_applied=None,
                    pnl_eur=None,
                )
                log_trade(record)
                logger.warning(f"SKIP: No snapshot for {proposal.market_id}")
                return (None, record)

        if not snapshot.has_valid_prices():
            # SKIP: No valid prices
            record = PaperTradeRecord(
                record_id=generate_record_id(),
                timestamp=now,
                proposal_id=proposal.proposal_id,
                market_id=proposal.market_id,
                action=TradeAction.SKIP.value,
                reason="Market snapshot has no valid prices - cannot simulate entry",
                position_id=None,
                snapshot_time=snapshot.snapshot_time,
                entry_price=None,
                exit_price=None,
                slippage_applied=None,
                pnl_eur=None,
            )
            log_trade(record)
            logger.warning(f"SKIP: No valid prices for {proposal.market_id}")
            return (None, record)

        if snapshot.is_resolved:
            # SKIP: Market already resolved
            record = PaperTradeRecord(
                record_id=generate_record_id(),
                timestamp=now,
                proposal_id=proposal.proposal_id,
                market_id=proposal.market_id,
                action=TradeAction.SKIP.value,
                reason=f"Market already resolved ({snapshot.resolved_outcome}) - cannot enter",
                position_id=None,
                snapshot_time=snapshot.snapshot_time,
                entry_price=None,
                exit_price=None,
                slippage_applied=None,
                pnl_eur=None,
            )
            log_trade(record)
            logger.warning(f"SKIP: Market {proposal.market_id} already resolved")
            return (None, record)

        # Determine side based on edge direction
        # Positive edge (model > implied) = buy YES
        # Negative edge (model < implied) = buy NO
        side = "YES" if proposal.edge > 0 else "NO"

        # Kelly position sizing: use model probability and market price
        win_prob = proposal.model_probability if hasattr(proposal, 'model_probability') else None
        try:
            available = self._capital_manager.get_state().available_capital_eur
        except Exception:
            available = 10000.0
        position_eur = kelly_size(
            win_probability=win_prob,
            entry_price=snapshot.mid_price,
            bankroll=available,
        )

        # Calculate entry price with slippage
        price_result = calculate_entry_price(snapshot, side)

        if price_result is None:
            # SKIP: Cannot calculate entry price
            record = PaperTradeRecord(
                record_id=generate_record_id(),
                timestamp=now,
                proposal_id=proposal.proposal_id,
                market_id=proposal.market_id,
                action=TradeAction.SKIP.value,
                reason="Cannot calculate entry price with slippage",
                position_id=None,
                snapshot_time=snapshot.snapshot_time,
                entry_price=None,
                exit_price=None,
                slippage_applied=None,
                pnl_eur=None,
            )
            log_trade(record)
            logger.warning(f"SKIP: Cannot calculate entry price for {proposal.market_id}")
            return (None, record)

        entry_price, slippage_applied = price_result

        # Calculate position size
        # In prediction markets: price is probability, contracts pay $1 if correct
        # Size = amount / price
        if entry_price <= 0:
            logger.warning(f"Entry price <= 0 ({entry_price}), skipping trade for {proposal.market_id}")
            record = PaperTradeRecord(
                record_id=generate_record_id(),
                timestamp=now,
                proposal_id=proposal.proposal_id,
                market_id=proposal.market_id,
                action=TradeAction.SKIP.value,
                reason=f"Entry price <= 0 ({entry_price})",
                position_id=None,
                snapshot_time=snapshot.snapshot_time,
                entry_price=None,
                exit_price=None,
                slippage_applied=None,
                pnl_eur=None,
            )
            log_trade(record)
            return (None, record)
        size_contracts = position_eur / entry_price

        # Create paper position
        position_id = generate_position_id()
        position = PaperPosition(
            position_id=position_id,
            proposal_id=proposal.proposal_id,
            market_id=proposal.market_id,
            market_question=proposal.market_question,
            side=side,
            status="OPEN",
            entry_time=now,
            entry_price=entry_price,
            entry_slippage=slippage_applied,
            size_contracts=size_contracts,
            cost_basis_eur=position_eur,
            exit_time=None,
            exit_price=None,
            exit_slippage=None,
            exit_reason=None,
            realized_pnl_eur=None,
            pnl_pct=None,
        )

        # Create trade record
        record = PaperTradeRecord(
            record_id=generate_record_id(),
            timestamp=now,
            proposal_id=proposal.proposal_id,
            market_id=proposal.market_id,
            action=TradeAction.PAPER_ENTER.value,
            reason=f"Paper entry: {side} at {entry_price:.4f} ({size_contracts:.2f} contracts)",
            position_id=position_id,
            snapshot_time=snapshot.snapshot_time,
            entry_price=entry_price,
            exit_price=None,
            slippage_applied=slippage_applied,
            pnl_eur=None,
        )

        # Allocate capital for this position
        if not allocate_capital(position_eur, f"Entry: {proposal.market_id}"):
            # Capital allocation failed (race condition) - skip
            record = PaperTradeRecord(
                record_id=generate_record_id(),
                timestamp=now,
                proposal_id=proposal.proposal_id,
                market_id=proposal.market_id,
                action=TradeAction.SKIP.value,
                reason="Capital allocation failed - insufficient funds",
                position_id=None,
                snapshot_time=snapshot.snapshot_time,
                entry_price=None,
                exit_price=None,
                slippage_applied=None,
                pnl_eur=None,
            )
            log_trade(record)
            logger.warning(f"SKIP: Capital allocation failed for {proposal.market_id}")
            return (None, record)

        # Log both
        log_position(position)
        log_trade(record)

        logger.info(
            f"PAPER_ENTER: {proposal.market_id} | {side} @ {entry_price:.4f} | "
            f"{size_contracts:.2f} contracts | slippage: {slippage_applied:.4f}"
        )

        return (position, record)

    def simulate_exit_market(
        self,
        position: PaperPosition,
        snapshot: MarketSnapshot,
        reason: str
    ) -> Tuple[PaperPosition, PaperTradeRecord]:
        """
        Simulate exit at current market price (take-profit, stop-loss, etc.).

        Args:
            position: The open position to close
            snapshot: Current market snapshot
            reason: Exit reason (e.g. "Take-Profit", "Stop-Loss")

        Returns:
            Tuple of (closed PaperPosition, PaperTradeRecord)
        """
        now = datetime.now().isoformat()

        exit_result = calculate_exit_price(snapshot, position.side, is_resolution=False)

        if exit_result is None:
            exit_price = snapshot.mid_price or position.entry_price
            exit_slippage = 0.0
        else:
            exit_price, exit_slippage = exit_result

        revenue_eur = position.size_contracts * exit_price
        realized_pnl = revenue_eur - position.cost_basis_eur
        pnl_pct = (realized_pnl / position.cost_basis_eur) * 100 if position.cost_basis_eur > 0 else 0.0

        closed_position = PaperPosition(
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
            realized_pnl_eur=realized_pnl,
            pnl_pct=pnl_pct,
        )

        record = PaperTradeRecord(
            record_id=generate_record_id(),
            timestamp=now,
            proposal_id=position.proposal_id,
            market_id=position.market_id,
            action=TradeAction.PAPER_EXIT.value,
            reason=f"{reason}: exit @ {exit_price:.4f} | P&L: {realized_pnl:+.2f} EUR ({pnl_pct:+.1f}%)",
            position_id=position.position_id,
            snapshot_time=snapshot.snapshot_time,
            entry_price=position.entry_price,
            exit_price=exit_price,
            slippage_applied=exit_slippage,
            pnl_eur=realized_pnl,
        )

        release_capital(
            position.cost_basis_eur,
            realized_pnl,
            f"{reason}: {position.market_id}"
        )

        log_position(closed_position)
        log_trade(record)

        logger.info(
            f"PAPER_EXIT ({reason}): {position.market_id} | {position.side} | "
            f"entry @ {position.entry_price:.4f} → exit @ {exit_price:.4f} | "
            f"P&L: {realized_pnl:+.2f} EUR ({pnl_pct:+.1f}%)"
        )

        return (closed_position, record)

    def simulate_exit_resolution(
        self,
        position: PaperPosition,
        snapshot: MarketSnapshot
    ) -> Tuple[PaperPosition, PaperTradeRecord]:
        """
        Simulate exit due to market resolution.

        GOVERNANCE:
        - Uses resolution outcome (no hindsight on timing)
        - Pays 1.0 for winning side, 0.0 for losing side
        - No slippage on resolution

        Args:
            position: The open position to close
            snapshot: Market snapshot showing resolution

        Returns:
            Tuple of (closed PaperPosition, PaperTradeRecord)
        """
        now = datetime.now().isoformat()

        # Calculate exit price based on resolution
        exit_result = calculate_exit_price(snapshot, position.side, is_resolution=True)

        if exit_result is None:
            # Should not happen for resolved markets, but handle gracefully
            exit_price = 0.5  # Assume 50/50 as fallback
            exit_slippage = 0.0
        else:
            exit_price, exit_slippage = exit_result

        # Calculate P&L
        # Revenue = size * exit_price
        revenue_eur = position.size_contracts * exit_price
        realized_pnl = revenue_eur - position.cost_basis_eur
        pnl_pct = (realized_pnl / position.cost_basis_eur) * 100 if position.cost_basis_eur > 0 else 0.0

        # Create closed position
        closed_position = PaperPosition(
            position_id=position.position_id,
            proposal_id=position.proposal_id,
            market_id=position.market_id,
            market_question=position.market_question,
            side=position.side,
            status="RESOLVED",
            entry_time=position.entry_time,
            entry_price=position.entry_price,
            entry_slippage=position.entry_slippage,
            size_contracts=position.size_contracts,
            cost_basis_eur=position.cost_basis_eur,
            exit_time=now,
            exit_price=exit_price,
            exit_slippage=exit_slippage,
            exit_reason=f"Market resolved: {snapshot.resolved_outcome}",
            realized_pnl_eur=realized_pnl,
            pnl_pct=pnl_pct,
        )

        # Create trade record
        record = PaperTradeRecord(
            record_id=generate_record_id(),
            timestamp=now,
            proposal_id=position.proposal_id,
            market_id=position.market_id,
            action=TradeAction.PAPER_EXIT.value,
            reason=f"Resolution exit: {snapshot.resolved_outcome} | P&L: {realized_pnl:+.2f} EUR",
            position_id=position.position_id,
            snapshot_time=snapshot.snapshot_time,
            entry_price=position.entry_price,
            exit_price=exit_price,
            slippage_applied=exit_slippage,
            pnl_eur=realized_pnl,
        )

        # Release capital back to available pool
        release_capital(
            position.cost_basis_eur,
            realized_pnl,
            f"Resolution exit: {position.market_id} ({snapshot.resolved_outcome})"
        )

        # Log both
        log_position(closed_position)
        log_trade(record)

        logger.info(
            f"PAPER_EXIT (RESOLVED): {position.market_id} | {position.side} | "
            f"exit @ {exit_price:.4f} | P&L: {realized_pnl:+.2f} EUR ({pnl_pct:+.1f}%)"
        )

        return (closed_position, record)


# =============================================================================
# MODULE-LEVEL FUNCTIONS
# =============================================================================

_simulator: Optional[ExecutionSimulator] = None


def get_simulator() -> ExecutionSimulator:
    """Get the global simulator instance."""
    global _simulator
    if _simulator is None:
        _simulator = ExecutionSimulator()
    return _simulator


def simulate_entry(proposal: Proposal) -> Tuple[Optional[PaperPosition], PaperTradeRecord]:
    """Convenience function to simulate entry."""
    return get_simulator().simulate_entry(proposal)


def simulate_exit_market(
    position: PaperPosition,
    snapshot: MarketSnapshot,
    reason: str
) -> Tuple[PaperPosition, PaperTradeRecord]:
    """Convenience function to simulate market-price exit."""
    return get_simulator().simulate_exit_market(position, snapshot, reason)


def simulate_exit_resolution(
    position: PaperPosition,
    snapshot: MarketSnapshot
) -> Tuple[PaperPosition, PaperTradeRecord]:
    """Convenience function to simulate resolution exit."""
    return get_simulator().simulate_exit_resolution(position, snapshot)
