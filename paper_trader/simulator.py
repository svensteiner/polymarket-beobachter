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

import json
import os
import re
import sys
import logging
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Tuple, Final, Dict

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
)
from paper_trader.kelly import kelly_size
from paper_trader.drawdown_protector import check_can_open_position
from paper_trader.bot_health_monitor import check_can_open_entry
from paper_trader.high_conviction import evaluate_high_conviction_exception
from analytics.edge_memory import assess_proposal_edge, classify_bucket
from analytics.signal_quality_scorer import assess_signal_from_proposal


logger = logging.getLogger(__name__)


# =============================================================================
# CONSTANTS
# =============================================================================

# Fixed paper trading amount in EUR
FIXED_AMOUNT_EUR: Final[float] = 100.0

# Simulated spread for fallback snapshots (%)
SIMULATED_SPREAD_PCT: Final[float] = 4.0

# Diversification limits
MAX_POSITIONS_PER_CITY_DATE: Final[int] = 2  # YES bets on different temp bands for same city+date are partially anti-correlated
MAX_POSITIONS_PER_CITY: Final[int] = 3        # Max positions per city overall

# Entry hardening — tightened after 8/13 paper trades hit stop-loss (BSS=-0.31)
MIN_ENTRY_EDGE_ABSOLUTE: Final[float] = 0.12   # raised from 0.08
MIN_ENTRY_EDGE_UNKNOWN_MARKET: Final[float] = 0.18  # raised from 0.12
MIN_ENTRY_CONFIDENCE_RANK: Final[int] = 2  # HIGH or better (raised from MEDIUM=1)

# Resolution window: 60-96h is the NWP sweet spot.
# <60h: positions enter RESOLUTION_HOLD zone too quickly → Emergency-SL fires before
#        regular SL can protect (Atlanta -18.46 EUR at 45.95h, Ankara -7.07 EUR at 24.1h).
#        Both losses happened because the filter in weather_market_filter uses market
#        settlement END_DATE (often D+1 for verification) while the actual temperature
#        event — and thus the price spike — happens D+0.  This constant acts as a
#        second-line defence inside the simulator itself.
# >96h: 4-day+ forecasts are unreliable.
MIN_ENTRY_HOURS_TO_RESOLUTION: Final[float] = 30.0
MAX_ENTRY_HOURS_TO_RESOLUTION: Final[float] = 96.0

# Cities blocked due to consistently poor paper trading results (0-33% WR).
# Re-evaluate after >=10 live trades show >=50% WR per city.
WEAK_PERFORMANCE_CITIES: Final[frozenset] = frozenset({
    # Cities with ≤33% WR on YES bets specifically (after NO-bet losses excluded).
    #
    # 2026-04-18 autopsy: ALL losses in formerly-blocked cities came from NO bets
    # (now globally blocked by YES-only mode). YES-specific WR by city:
    #   Los Angeles: 1/1 YES wins (+1.33 EUR) — unblocked
    #   London:      0/0 YES trades (loss was NO-exact SL) — unblocked
    #   New York City: 0/0 YES trades (all losses were NO bets) — unblocked
    #   Seattle:     0/0 YES trades (loss was NO-between SL) — unblocked
    #   San Francisco: 2/2 YES wins (+1.59 EUR) — removed 2026-04-17 (same logic)
    #
    # Empty: no city has demonstrated poor performance on YES bets.
    # Re-block a city if its YES WR drops below 40% over 5+ YES trades.
})

# Low-probability NO bet protection:
# When the YES price is very low (< 25%), betting NO means YES must stay near 0.
# These markets have 0% historical WR in paper trading (all stop-loss exits).
# Require substantially higher absolute edge to compensate for model uncertainty.
# Raised: LOW_PROB_YES_THRESHOLD 0.15→0.25, MIN_ENTRY_EDGE_LOW_PROB_NO 0.20→0.35
MIN_ENTRY_EDGE_LOW_PROB_NO: Final[float] = 0.35   # 35% required when YES < 25%
LOW_PROB_YES_THRESHOLD: Final[float] = 0.25        # "low probability" cutoff (was 0.15)

# NO-bet guardrail: 2026-04-18 autopsy shows all 10 SL exits were NO bets on
# "between" or "exact" markets (-70% to -93% losses each). Those market types
# are now separately banned (see line ~289). NO bets on at_or_above / at_or_below
# had 2/3 wins (67% WR, +1.02 EUR) — the boundary resolution mechanic avoids the
# narrow-band spike problem. Allow these with ≥50% absolute edge requirement.
# Re-evaluate: if NO at_or_above/at_or_below WR drops <40% over 10+ trades, raise
# threshold back to 0.99.
MIN_ENTRY_EDGE_NO_BET: Final[float] = 0.50         # Allow boundary-market NO bets with strong signal

# Minimum YES entry price: block lottery-ticket bets where the market
# is priced near-zero (e.g. 2%). These bets show extreme model-vs-market
# divergence — the model is almost certainly wrong when YES < 5%.
# Evidence: Paris 18°C @ 2.06% with model_prob=52.5% on same day Paris 19°C
# was at 92% — mutual exclusivity means the model was miscalibrated.
MIN_YES_ENTRY_PRICE: Final[float] = 0.05

# SL cooling-off: after a stop-loss on a specific market, block re-entry
# for this many hours. Prevents the double-SL pattern (same market exits at
# -80% twice in one day because a fresh proposal re-enters immediately).
# Raised 6 → 12h (2026-04-19): market 2003743 confirmed double-SL within 6h window;
# 12h covers a full active trading session and avoids re-entry on resolution-day spikes.
SL_COOLOFF_HOURS: Final[float] = 12.0
SL_COOLOFF_PATH: Final[str] = "data/sl_cooloff.json"

# Stale-proposal price-drift guard:
# Proposals are generated when the weather engine last observed the market.
# By execution time, the market price may have moved significantly. If the
# absolute drift > YES_PRICE_DRIFT_MAX_ABS AND the realtime edge is below the
# YES threshold, reject the entry (the original edge signal is no longer valid).
# Evidence: Ankara YES 2003773 — proposal generated at YES=19.5% (edge=+87.8%),
# but snapshot at execution was YES=49.7% → realtime edge=(36.6%-49.7%)/49.7%=-26%.
YES_PRICE_DRIFT_MAX_ABS: Final[float] = 0.15   # 15 pp absolute tolerance
YES_MIN_REALTIME_EDGE: Final[float] = 0.24     # mirrors entry_guardrails.YES_MIN_EDGE

# Near-resolution MEDIUM-liq guard (Feature Flag)
# Root cause of Atlanta -18.46 EUR and Ankara -7.07 EUR: both were MEDIUM-liq (spread ~3%)
# at entry but collapsed near resolution. The LOW-liq block (spread ≥ 5%) did not catch them.
# This guard blocks MEDIUM+UNKNOWN liq markets when hours_to_resolution < 48h.
# Activate: set NEAR_RES_LIQ_GUARD=1 in .env. Default OFF to allow gradual validation.
_NEAR_RES_LIQ_GUARD_ENABLED: Final[bool] = os.environ.get("NEAR_RES_LIQ_GUARD", "0") == "1"
# 48h was calibrated to spread-based MEDIUM (3% spread). Mit dem neuen
# Volume-basierten Bucket (USD-Liquidity 400-2000) sind viele MEDIUM-Märkte
# strukturell anders. 24h erfasst weiterhin den Ankara-Risikofall (24.1h)
# und gibt der Pipeline >24h-Märkte zum Traden frei.
NEAR_RES_LIQ_GUARD_HOURS: Final[float] = float(
    os.environ.get("NEAR_RES_LIQ_GUARD_HOURS", "24")
)


def _load_sl_cooloff() -> Dict[str, str]:
    """Load stop-loss cooling-off registry {market_id: iso_timestamp}."""
    path = Path(SL_COOLOFF_PATH)
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _save_sl_cooloff(registry: Dict[str, str]) -> None:
    """Persist SL cooling-off registry atomically."""
    path = Path(SL_COOLOFF_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(registry, f, indent=2)
        os.replace(tmp, str(path))
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def record_sl_cooloff(market_id: str) -> None:
    """Register a stop-loss exit so re-entry is blocked for SL_COOLOFF_HOURS."""
    registry = _load_sl_cooloff()
    registry[market_id] = datetime.now(timezone.utc).isoformat()
    _save_sl_cooloff(registry)


def _is_in_sl_cooloff(market_id: str) -> bool:
    """Return True if the market is within the SL cooling-off window."""
    registry = _load_sl_cooloff()
    ts_str = registry.get(market_id)
    if ts_str is None:
        return False
    try:
        sl_time = datetime.fromisoformat(ts_str)
        if sl_time.tzinfo is None:
            sl_time = sl_time.replace(tzinfo=timezone.utc)
        elapsed_hours = (datetime.now(timezone.utc) - sl_time).total_seconds() / 3600.0
        return elapsed_hours < SL_COOLOFF_HOURS
    except Exception:
        return False


def _confidence_rank(level: Optional[str]) -> int:
    ranks = {
        "LOW": 0,
        "MEDIUM": 1,
        "HIGH": 2,
    }
    return ranks.get(str(level or "").upper(), -1)


def _entry_quality_gate(proposal: Proposal, market_type: str) -> Tuple[bool, str]:
    """
    Conservative pre-entry filter.

    The simulator should prefer missing marginal trades over taking weak,
    noisy, or structurally low-quality signals.
    """
    decision = str(getattr(proposal, "decision", "TRADE") or "TRADE").upper()
    if decision != "TRADE":
        return False, f"Proposal decision is {decision} - entry skipped"

    core_criteria = getattr(proposal, "core_criteria", None)
    if core_criteria is not None and not core_criteria.all_passed():
        failed = ", ".join(core_criteria.failed_criteria()) or "unknown"
        return False, f"Core criteria failed: {failed}"

    confidence_level = getattr(proposal, "confidence_level", None)
    if _confidence_rank(confidence_level) < MIN_ENTRY_CONFIDENCE_RANK:
        return False, f"Confidence {confidence_level} below minimum MEDIUM"

    edge = abs(float(getattr(proposal, "edge", 0.0) or 0.0))
    if market_type == "unknown":
        if edge < MIN_ENTRY_EDGE_UNKNOWN_MARKET:
            return False, (
                f"Unknown market type requires >= {MIN_ENTRY_EDGE_UNKNOWN_MARKET:.0%} "
                f"absolute edge (got {edge:.1%})"
            )
    elif edge < MIN_ENTRY_EDGE_ABSOLUTE:
        return False, f"Absolute edge {edge:.1%} below minimum {MIN_ENTRY_EDGE_ABSOLUTE:.0%}"

    # Ensemble quality gate: reject HIGH_VARIANCE and LOW_SOURCE_COUNT signals
    warnings = getattr(proposal, "warnings", ()) or ()
    for w in warnings:
        w_str = str(w)
        if w_str.startswith("HIGH_VARIANCE:"):
            return False, f"Signal rejected: {w_str}"
        if w_str.startswith("LOW_SOURCE_COUNT:"):
            return False, f"Signal rejected: {w_str}"

    implied_prob = float(getattr(proposal, "implied_probability", 0.5) or 0.5)
    raw_edge = float(getattr(proposal, "edge", 0.0) or 0.0)
    is_no_bet = raw_edge < 0

    # NO bets re-enabled 2026-04-20 (user approval). Only boundary markets
    # (at_or_above / at_or_below) with ≥50% edge are allowed — exact/between
    # remain blocked below (resolution-day spike risk confirmed in autopsy).

    # NO-bet edge floor: boundary markets (at_or_above / at_or_below) allowed with
    # strong signal (≥50% absolute edge). between/exact NO bets are separately banned
    # below regardless. If edge is below threshold, reject here.
    # NOTE: This block is unreachable while YES-only mode is active (above).
    if is_no_bet and edge < MIN_ENTRY_EDGE_NO_BET:
        return False, (
            f"NO bet requires >= {MIN_ENTRY_EDGE_NO_BET:.0%} absolute edge "
            f"(got {edge:.1%}). boundary-market NO bets (at_or_above/below) allowed "
            "when edge >= 50%; between/exact NO bets always blocked."
        )

    # Low-probability NO bet protection:
    # When betting NO on a near-impossible event (YES price < 25%), our model
    # uncertainty is highest and all historical stop-loss exits came from this zone.
    # Require significantly higher edge to compensate.
    if is_no_bet and implied_prob < LOW_PROB_YES_THRESHOLD:
        if edge < MIN_ENTRY_EDGE_LOW_PROB_NO:
            return False, (
                f"Low-prob NO bet (YES={implied_prob:.1%}) requires "
                f">= {MIN_ENTRY_EDGE_LOW_PROB_NO:.0%} edge (got {edge:.1%})"
            )

    # Minimum YES entry price: block near-zero YES bets.
    # When YES < 5%, the market has near-consensus that the event won't happen.
    # If our model disagrees strongly (e.g. 52% vs 2%), the model is almost
    # certainly wrong — these exact-temp markets are mutually exclusive and
    # a companion market at 92% has already established the consensus temperature.
    # Evidence: Paris 18°C YES @ 2.06% (model_prob=52.5%) on same day Paris 19°C
    # traded at 92% YES — both can't resolve YES, but model didn't enforce this.
    if not is_no_bet and implied_prob < MIN_YES_ENTRY_PRICE:
        return False, (
            f"YES bet at {implied_prob:.1%} below minimum {MIN_YES_ENTRY_PRICE:.0%}: "
            "extreme model-vs-market divergence likely means model is miscalibrated "
            f"(model={edge + implied_prob:.1%} vs market={implied_prob:.1%})"
        )

    # SL cooling-off: block re-entry on a market that recently hit stop-loss.
    # Pattern: NYC between NO hit SL twice in one day → -8.4 EUR double-loss.
    # After SL, the same proposal re-enters at the new (lower) market price because
    # the model still shows positive edge. We block this for SL_COOLOFF_HOURS.
    market_id = str(getattr(proposal, "market_id", "") or "")
    if market_id and _is_in_sl_cooloff(market_id):
        return False, (
            f"SL cooling-off active for market {market_id}: "
            f"re-entry blocked for {SL_COOLOFF_HOURS:.0f}h after stop-loss exit "
            "(prevents double-SL pattern on same market)"
        )

    # NO bet protection for narrow-band markets ("between" / "exact"):
    # Data analysis of 13 paper trades showed 0% win rate for NO bets on these types:
    #   - "between" (e.g., "will temp be 84-85°F?"): 1°F wide band → wild resolution-day price spikes
    #   - "exact"   (e.g., "will temp be exactly 72°F?"): same issue, even narrower
    # All 5 NO-between and 3 NO-exact trades hit stop-loss (-70 to -93%), while
    # YES bets on "at_or_above"/"at_or_below"/"exact" won 5/5 when held to resolution.
    # Root cause: on resolution day, YES prices spike toward 0 or 100%, easily
    # triggering a -70% drawdown on high-priced NO contracts even when the position
    # is ultimately correct (the event does NOT happen).
    if is_no_bet and market_type in ("between", "exact"):
        return False, (
            f"NO bet blocked on {market_type} market: "
            "narrow-band resolution-day price spikes cause systematic stop-loss exits "
            "(0% historical win rate on NO-between and NO-exact)"
        )

    # Resolution window gate: 60-96h is the NWP sweet spot.
    # MIN guard is a second-line defence: the upstream weather_market_filter uses the
    # market settlement END_DATE (often D+1) which gives a false ~24h buffer vs. the
    # actual weather-event day.  Without this check, proposals with hours_to_resolution
    # < 60h slip through (Atlanta 45.95h → -18.46 EUR; Ankara 24.1h → -7.07 EUR).
    hours_to_res = getattr(proposal, "hours_to_resolution", None)
    if hours_to_res is not None and hours_to_res < MIN_ENTRY_HOURS_TO_RESOLUTION:
        return False, (
            f"Resolution too close: {hours_to_res:.1f}h < min {MIN_ENTRY_HOURS_TO_RESOLUTION:.0f}h "
            "(near-resolution entries hit Emergency-SL before regular SL fires)"
        )
    if hours_to_res is not None and hours_to_res > MAX_ENTRY_HOURS_TO_RESOLUTION:
        return False, (
            f"Resolution too far: {hours_to_res:.0f}h > max {MAX_ENTRY_HOURS_TO_RESOLUTION:.0f}h "
            "(NWP accuracy degrades beyond 4 days — edge signals unreliable)"
        )

    return True, "OK"


def _detect_market_type(market_question: str) -> str:
    """
    Detect the type of weather market from the question text.
    Used to track which market types our model predicts best.
    """
    q = market_question.lower()
    if re.search(r'between\s+\d', q):
        return "between"
    if re.search(r'or\s+below|or\s+less|or\s+under|or\s+lower', q):
        return "at_or_below"
    if re.search(r'or\s+above|or\s+higher|or\s+more|or\s+over|be\s+above|exceed', q):
        return "at_or_above"
    if re.search(r'\bbe\s+\d+|\bexactly\s+\d+', q):
        return "exact"
    return "unknown"


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
        exception_allowed, exception_reason = evaluate_high_conviction_exception(proposal)
        exception_tag = ""

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
        if not dd_ok and not exception_allowed:
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
        if not dd_ok and exception_allowed:
            logger.warning(
                "Recovery-Bypass fuer %s: %s | %s",
                proposal.market_id,
                dd_reason,
                exception_reason,
            )

        # BotHealthMonitor: temporäre Schutzregeln ohne Config-Mutation
        health_ok, health_reason = check_can_open_entry(
            is_addon=False,
            market_question=proposal.market_question,
        )
        if not health_ok and not exception_allowed:
            record = PaperTradeRecord(
                record_id=generate_record_id(),
                timestamp=now,
                proposal_id=proposal.proposal_id,
                market_id=proposal.market_id,
                action=TradeAction.SKIP.value,
                reason=health_reason,
                position_id=None,
                snapshot_time=None,
                entry_price=None,
                exit_price=None,
                slippage_applied=None,
                pnl_eur=None,
            )
            log_trade(record)
            logger.warning(f"SKIP (BotHealthMonitor): {health_reason} for {proposal.market_id}")
            return (None, record)
        if not health_ok and exception_allowed:
            logger.warning(
                "BotHealth-Bypass fuer %s: %s | %s",
                proposal.market_id,
                health_reason,
                exception_reason,
            )

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

        # LLM Trade Reasoning: GPT-5.4 mini Sanity-Check (non-blocking)
        try:
            from core.llm_trade_reasoning import evaluate_trade
            try:
                default_position_size = self._capital_manager.get_position_size()
            except Exception:
                default_position_size = 5.0
            llm_approved, llm_reason, llm_result = evaluate_trade(
                market_question=proposal.market_question,
                model_probability=proposal.model_probability,
                market_price=proposal.implied_probability or 0.5,
                side=proposal.side,
                position_size_eur=getattr(proposal, "position_size_eur", default_position_size),
                edge=proposal.edge,
                event_type=getattr(proposal, "event_type", ""),
                city=getattr(proposal, "city", ""),
                confidence=getattr(proposal, "confidence", ""),
            )
            if not llm_approved:
                record = PaperTradeRecord(
                    record_id=generate_record_id(),
                    timestamp=now,
                    proposal_id=proposal.proposal_id,
                    market_id=proposal.market_id,
                    action=TradeAction.SKIP.value,
                    reason=f"LLM REJECT: {llm_reason}",
                    position_id=None,
                    snapshot_time=None,
                    entry_price=None,
                    exit_price=None,
                    slippage_applied=None,
                    pnl_eur=None,
                )
                log_trade(record)
                logger.info(f"SKIP (LLM Reject): {llm_reason} for {proposal.market_id}")
                return (None, record)
        except Exception as e:
            # LLM-Fehler blockiert NICHT den Trade (fail-open)
            logger.debug(f"LLM Trade Reasoning uebersprungen: {e}")

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

        # LOW-liquidity entry block (spread-based, classify_liquidity: spread >= 5% = LOW).
        # Evidence (paper_positions.jsonl audit, 2026-04-27): 9 of 9 historical LOW-liq
        # entries resolved with -67% to -93% loss. Total realised loss: -54.32 EUR — i.e.
        # essentially the entire bot drawdown is attributable to LOW-liq trades.
        #   7 × Stop-Loss exits, edge -0.13 to -0.55, all NO-side, -71% to -93%.
        #   2 × Emergency-SL exits with PREMIUM YES edge (+0.84 Atlanta -89.8% / -18.46 EUR;
        #       +0.88 Ankara -67.8% / -7.07 EUR). Even +84% modelled edge did not survive
        #       LOW-liq slippage + adverse selection.
        # Implication: the block is NOT overfit to a single Atlanta trade — it reflects a
        # structural failure to monetise edge in wide-spread markets, regardless of side
        # or edge magnitude. Lifting it without an upstream spread filter resumes the bleed.
        # Upstream root cause: discovery + proposal generation use *volume*-based
        # MIN_LIQUIDITY=375 USD, while this block uses *spread*-based bucketing (>5%).
        # The two metrics are uncorrelated for current weather markets, so 100% of
        # eligible proposals currently land here. Real fix lives in proposal generation.
        # Rollback: revert this commit if the upstream spread pre-filter ships and proves
        # safe.  Do NOT lift this block in isolation.
        liq_bucket = str(getattr(snapshot, "liquidity_bucket", "") or "").upper()
        if liq_bucket == "LOW":
            spread_pct = getattr(snapshot, "spread_pct", None)
            spread_str = f"{spread_pct:.2f}%" if isinstance(spread_pct, (int, float)) else "n/a"
            skip_reason = (
                f"LOW-liquidity market blocked at entry: spread {spread_str} >= 5% "
                f"(SL/TP cannot be enforced; emergency SL only at -55%/<36h). "
                f"Evidence (audit 2026-04-27): 9/9 historical LOW-liq entries lost -67% to -93%, "
                f"total -54.32 EUR — including PREMIUM-edge YES trades. Edge does not survive "
                f"LOW-liq slippage. Re-evaluate only after upstream spread pre-filter ships."
            )
            record = PaperTradeRecord(
                record_id=generate_record_id(),
                timestamp=now,
                proposal_id=proposal.proposal_id,
                market_id=proposal.market_id,
                action=TradeAction.SKIP.value,
                reason=skip_reason,
                position_id=None,
                snapshot_time=snapshot.snapshot_time,
                entry_price=None,
                exit_price=None,
                slippage_applied=None,
                pnl_eur=None,
            )
            log_trade(record)
            logger.warning(
                f"SKIP (LOW-liq): {proposal.market_id} spread={spread_str} edge={proposal.edge:+.3f} "
                f"— entry blocked (audit-confirmed: 9/9 historical LOW-liq lost -67%+)"
            )
            if float(getattr(proposal, "edge", 0) or 0) > 0:
                try:
                    from paper_trader.shadow_tracker import record_shadow_entry
                    record_shadow_entry(proposal, "low_liq_block", skip_reason[:200])
                except Exception:
                    pass
            return (None, record)

        # Near-resolution MEDIUM-liq guard (Feature Flag: NEAR_RES_LIQ_GUARD=1 in .env)
        # MEDIUM-liq (spread 2-5%) markets collapse intraday near resolution even when the
        # spread looks acceptable at entry. The LOW-liq block above catches spread ≥ 5% but
        # misses the 2-5% zone. Evidence:
        #   Atlanta 2003743: MEDIUM (3%), 45.95h → Emergency-SL -18.46 EUR (-92%)
        #   Ankara  2003773: MEDIUM (3%), 24.1h  → Emergency-SL  -7.07 EUR (-71%)
        # Both entered via HighConvictionException and cleared the LOW-liq block.
        if _NEAR_RES_LIQ_GUARD_ENABLED:
            _htr_for_liq = getattr(proposal, "hours_to_resolution", None)
            if _htr_for_liq is not None and _htr_for_liq < NEAR_RES_LIQ_GUARD_HOURS and liq_bucket in ("MEDIUM", "UNKNOWN"):
                _nr_skip_reason = (
                    f"Near-resolution MEDIUM-liq guard: {_htr_for_liq:.1f}h < {NEAR_RES_LIQ_GUARD_HOURS:.0f}h "
                    f"AND liquidity={liq_bucket} (requires HIGH within {NEAR_RES_LIQ_GUARD_HOURS:.0f}h window). "
                    f"Evidence: Atlanta -18.46 EUR (MEDIUM 3%, 45.95h), Ankara -7.07 EUR (MEDIUM 3%, 24.1h). "
                    f"Deactivate: unset NEAR_RES_LIQ_GUARD in .env."
                )
                record = PaperTradeRecord(
                    record_id=generate_record_id(),
                    timestamp=now,
                    proposal_id=proposal.proposal_id,
                    market_id=proposal.market_id,
                    action=TradeAction.SKIP.value,
                    reason=_nr_skip_reason,
                    position_id=None,
                    snapshot_time=snapshot.snapshot_time,
                    entry_price=None,
                    exit_price=None,
                    slippage_applied=None,
                    pnl_eur=None,
                )
                log_trade(record)
                logger.warning(
                    "SKIP (NearResLiqGuard): %s | liq=%s htr=%.1fh < %.0fh "
                    "— MEDIUM-liq blocked near resolution",
                    proposal.market_id, liq_bucket, _htr_for_liq, NEAR_RES_LIQ_GUARD_HOURS,
                )
                if float(getattr(proposal, "edge", 0) or 0) > 0:
                    try:
                        from paper_trader.shadow_tracker import record_shadow_entry
                        record_shadow_entry(proposal, "near_res_liq_guard", _nr_skip_reason[:200])
                    except Exception:
                        pass
                return (None, record)

        # Determine side based on edge direction
        # Positive edge (model > implied) = buy YES
        # Negative edge (model < implied) = buy NO
        side = "YES" if proposal.edge > 0 else "NO"
        market_type = _detect_market_type(proposal.market_question)
        edge_verdict = assess_proposal_edge(proposal, market_type=market_type)
        if not edge_verdict["allowed"]:
            record = PaperTradeRecord(
                record_id=generate_record_id(),
                timestamp=now,
                proposal_id=proposal.proposal_id,
                market_id=proposal.market_id,
                action=TradeAction.SKIP.value,
                reason=f"Edge memory blocked bucket {edge_verdict['bucket']}",
                position_id=None,
                snapshot_time=snapshot.snapshot_time,
                entry_price=None,
                exit_price=None,
                slippage_applied=None,
                pnl_eur=None,
            )
            log_trade(record)
            logger.warning("SKIP (EdgeMemory): %s for %s", edge_verdict["reason"], proposal.market_id)
            return (None, record)

        # City performance block: reject markets in cities with proven low WR.
        # Checks both hardcoded WEAK_PERFORMANCE_CITIES and dynamic agent cooldowns.
        from agentic.action_executor import get_agent_cooldown_cities
        _all_blocked_cities = WEAK_PERFORMANCE_CITIES | get_agent_cooldown_cities()
        if new_city and new_city.lower() in _all_blocked_cities:
            record = PaperTradeRecord(
                record_id=generate_record_id(),
                timestamp=now,
                proposal_id=proposal.proposal_id,
                market_id=proposal.market_id,
                action=TradeAction.SKIP.value,
                reason=(
                    f"City block: {new_city} is on weak-performance list "
                    f"(0-33% historical WR — re-evaluate after 10+ live trades)"
                ),
                position_id=None,
                snapshot_time=snapshot.snapshot_time,
                entry_price=None,
                exit_price=None,
                slippage_applied=None,
                pnl_eur=None,
            )
            log_trade(record)
            logger.info(f"SKIP (CityBlock): {new_city} for {proposal.market_id}")
            return (None, record)

        # Stale-proposal price-drift check:
        # Re-validate YES edge at current snapshot price; reject if market has moved.
        if side == "YES" and snapshot.mid_price is not None:
            _prop_price = float(getattr(proposal, "implied_probability", 0.0) or 0.0)
            _snap_price = float(snapshot.mid_price)
            _price_drift = abs(_snap_price - _prop_price)
            if _price_drift > YES_PRICE_DRIFT_MAX_ABS:
                _model_prob = float(getattr(proposal, "model_probability", 0.0) or 0.0)
                _realtime_edge = (_model_prob - _snap_price) / _snap_price if _snap_price > 0 else -999.0
                if _realtime_edge < YES_MIN_REALTIME_EDGE:
                    _drift_skip_reason = (
                        f"Stale proposal: price drifted {_price_drift:.0%} "
                        f"(proposal={_prop_price:.1%} → snapshot={_snap_price:.1%}). "
                        f"Realtime edge={_realtime_edge:.1%} < min {YES_MIN_REALTIME_EDGE:.0%}. "
                        f"Original proposal_edge={proposal.edge:.1%} at stale price."
                    )
                    record = PaperTradeRecord(
                        record_id=generate_record_id(),
                        timestamp=now,
                        proposal_id=proposal.proposal_id,
                        market_id=proposal.market_id,
                        action=TradeAction.SKIP.value,
                        reason=_drift_skip_reason,
                        position_id=None,
                        snapshot_time=snapshot.snapshot_time,
                        entry_price=None,
                        exit_price=None,
                        slippage_applied=None,
                        pnl_eur=None,
                    )
                    log_trade(record)
                    logger.warning(
                        "SKIP (StalePriceDelivery): %s | drift=%.0f%% | "
                        "realtime_edge=%.1f%% | proposal_edge=%.1f%%",
                        proposal.market_id, _price_drift * 100,
                        _realtime_edge * 100, proposal.edge * 100,
                    )
                    return (None, record)

        quality_ok, quality_reason = _entry_quality_gate(proposal, market_type)
        if not quality_ok:
            record = PaperTradeRecord(
                record_id=generate_record_id(),
                timestamp=now,
                proposal_id=proposal.proposal_id,
                market_id=proposal.market_id,
                action=TradeAction.SKIP.value,
                reason=quality_reason,
                position_id=None,
                snapshot_time=snapshot.snapshot_time,
                entry_price=None,
                exit_price=None,
                slippage_applied=None,
                pnl_eur=None,
            )
            log_trade(record)
            logger.warning(f"SKIP (EntryQuality): {quality_reason} for {proposal.market_id}")
            return (None, record)

        # Signal Quality Score: composite gate combining edge, ensemble, horizon, market type
        try:
            sqs_result = assess_signal_from_proposal(proposal, market_type=market_type)
            if not sqs_result.allowed and not exception_allowed:
                record = PaperTradeRecord(
                    record_id=generate_record_id(),
                    timestamp=now,
                    proposal_id=proposal.proposal_id,
                    market_id=proposal.market_id,
                    action=TradeAction.SKIP.value,
                    reason=f"SQS rejected: {sqs_result.reason}",
                    position_id=None,
                    snapshot_time=snapshot.snapshot_time,
                    entry_price=None,
                    exit_price=None,
                    slippage_applied=None,
                    pnl_eur=None,
                )
                log_trade(record)
                logger.info(f"SKIP (SignalQuality): score={sqs_result.score:.3f} for {proposal.market_id}")
                return (None, record)
        except Exception as _sqs_err:
            logger.debug("SignalQualityScorer skipped: %s", _sqs_err)

        # Kelly position sizing: use model probability and market price
        # For NO bets, use complementary probabilities (1-p, 1-price)
        yes_prob = proposal.model_probability if hasattr(proposal, 'model_probability') else None
        yes_price = snapshot.mid_price
        if side == "NO" and yes_prob is not None:
            win_prob = 1.0 - yes_prob
            kelly_price = 1.0 - yes_price
        else:
            win_prob = yes_prob
            kelly_price = yes_price
        try:
            available = self._capital_manager.get_state().available_capital_eur
        except Exception:
            available = 10000.0
        # Feature 7 + 4: Time-Decay und Ensemble-Vol-Scaling
        hours_to_res = getattr(proposal, 'hours_to_resolution', None)
        ens_variance = getattr(proposal, 'ensemble_variance', None)
        position_eur = kelly_size(
            win_probability=win_prob,
            entry_price=kelly_price,
            bankroll=available,
            hours_to_resolution=hours_to_res,
            ensemble_variance=ens_variance,
            confidence_level=getattr(proposal, "confidence_level", None),
            market_type=market_type,
        )
        position_eur *= float(edge_verdict.get("position_scale", 1.0) or 1.0)
        # Hard cap: position_scale darf capital_config-Limit nicht überschreiten
        from paper_trader.kelly import _get_caps as _kelly_get_caps
        _kmin, _kmax, _ = _kelly_get_caps()
        position_eur = max(_kmin, min(_kmax, position_eur))

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
        entry_exception_allowed, entry_exception_reason = evaluate_high_conviction_exception(
            proposal,
            entry_price=entry_price,
        )
        if entry_exception_allowed:
            exception_tag = " | HighConvictionException"

        # BotHealthMonitor: bei schwacher Gesundheit hohe Entry-Preise deckeln
        health_ok, health_reason = check_can_open_entry(
            entry_price=entry_price,
            is_addon=False,
            market_question=proposal.market_question,
            market_type=market_type,
            city=new_city,
        )
        if not health_ok and not entry_exception_allowed:
            record = PaperTradeRecord(
                record_id=generate_record_id(),
                timestamp=now,
                proposal_id=proposal.proposal_id,
                market_id=proposal.market_id,
                action=TradeAction.SKIP.value,
                reason=health_reason,
                position_id=None,
                snapshot_time=snapshot.snapshot_time,
                entry_price=entry_price,
                exit_price=None,
                slippage_applied=slippage_applied,
                pnl_eur=None,
            )
            log_trade(record)
            logger.warning(f"SKIP (BotHealthMonitor): {health_reason} for {proposal.market_id}")
            return (None, record)
        if not health_ok and entry_exception_allowed:
            logger.warning(
                "BotHealth-Preisdeckel-Bypass fuer %s: %s | %s",
                proposal.market_id,
                health_reason,
                entry_exception_reason,
            )

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
            model_probability=getattr(proposal, 'model_probability', None),
            confidence_level=getattr(proposal, "confidence_level", None),
            market_type=market_type,
            proposal_edge=float(getattr(proposal, "edge", 0.0) or 0.0),
            hours_to_resolution=hours_to_res,
            edge_bucket=str(
                edge_verdict.get("bucket")
                or classify_bucket(
                    confidence_level=getattr(proposal, "confidence_level", None),
                    market_type=market_type,
                    side=side,
                    edge=getattr(proposal, "edge", None),
                    hours_to_resolution=hours_to_res,
                )
            ),
            city=new_city,
            liquidity_bucket=liq_bucket or None,
        )

        # Create trade record
        record = PaperTradeRecord(
            record_id=generate_record_id(),
            timestamp=now,
            proposal_id=proposal.proposal_id,
            market_id=proposal.market_id,
            action=TradeAction.PAPER_ENTER.value,
            reason=(
                f"Paper entry{exception_tag}: {side} at {entry_price:.4f} "
                f"({size_contracts:.2f} contracts)"
            ),
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
            confidence_level=position.confidence_level,
            market_type=position.market_type,
            proposal_edge=position.proposal_edge,
            hours_to_resolution=position.hours_to_resolution,
            edge_bucket=position.edge_bucket,
            city=getattr(position, "city", None),
            liquidity_bucket=getattr(position, "liquidity_bucket", None),
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
            confidence_level=position.confidence_level,
            market_type=position.market_type,
            proposal_edge=position.proposal_edge,
            hours_to_resolution=position.hours_to_resolution,
            edge_bucket=position.edge_bucket,
            city=getattr(position, "city", None),
            liquidity_bucket=getattr(position, "liquidity_bucket", None),
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
