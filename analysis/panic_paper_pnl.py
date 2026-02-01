# =============================================================================
# POLYMARKET BEOBACHTER - PAPER PNL EVALUATION
# =============================================================================
#
# GOVERNANCE:
# This module is PURELY ANALYTICAL.
# It does NOT affect trading logic or parameters.
# It does NOT execute trades.
# It does NOT modify engine behavior.
# It does NOT optimize anything.
#
# PURPOSE:
# Stress test shadow mode results with CONSERVATIVE assumptions.
# This is NOT a backtest for optimism - it is a reality check.
#
# NON-NEGOTIABLE RULES:
# 1. No changes to panic_contrarian_engine logic
# 2. No parameter tuning
# 3. No optimization
# 4. No execution logic
# 5. Conservative assumptions ONLY
#
# MENTAL MODEL:
# If results are inconclusive or marginal: classify as NOT VIABLE.
#
# =============================================================================

import json
import logging
import statistics
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple

logger = logging.getLogger(__name__)


# =============================================================================
# CONFIGURATION CONSTANTS
# =============================================================================
#
# CONSERVATIVE by design.
# These assumptions penalize the strategy, not favor it.
#
# =============================================================================

DEFAULT_POSITION_SIZE_USD: float = 100.0
"""
Fixed position size for paper PnL calculations.
Small to ensure individual trade losses are contained.
"""

DEFAULT_TRADING_FEE_PCT: float = 0.02
"""
Total trading fees as a fraction (2% = 0.02).
This is CONSERVATIVE - includes:
- Exchange fees (typically 0.5-1%)
- Spread cost (1-2% for prediction markets)
- Slippage allowance

Real fees may be lower, but we assume worse case.
"""

DEFAULT_EXTREME_ADVERSE_THRESHOLD: float = 0.10
"""
Flag trades where adverse move exceeded 10%.
This indicates potential for larger-than-expected losses.
"""

DEFAULT_LOSS_FLAG_THRESHOLD: float = 0.05
"""
Flag trades where continued panic caused > 5% loss.
These are the trades we should have avoided.
"""

MAX_ACCEPTABLE_DRAWDOWN_PCT: float = 0.30
"""
Maximum acceptable overall drawdown (30%).
If cumulative PnL drops more than this, classify as NOT VIABLE.
"""

MIN_AVERAGE_PNL_FOR_VIABILITY: float = 0.0
"""
Minimum average net PnL for economic viability.
Must be positive (after fees) to be considered viable.
"""

# Paths
DEFAULT_SHADOW_LOG_PATH: Path = Path(__file__).parent.parent / "logs" / "panic_shadow"
DEFAULT_OUTPUT_PATH: Path = Path(__file__).parent / "panic_paper_pnl_summary.json"


# =============================================================================
# DATA MODELS
# =============================================================================


@dataclass
class TradePnLResult:
    """
    PnL analysis result for a single simulated trade.

    All values are in USD unless otherwise noted.
    """
    # Identification
    trade_id: str
    market_id: str
    market_title: str

    # Trade details
    direction: str  # "UNDERPRICED" (long) or "OVERPRICED" (short)
    entry_price: float
    exit_price: float
    entry_timestamp: str
    exit_timestamp: Optional[str]
    outcome: str

    # Position sizing
    position_size_usd: float
    shares_acquired: float  # position_size / entry_price

    # PnL calculations
    gross_pnl_usd: float
    fee_cost_usd: float
    net_pnl_usd: float
    net_pnl_pct: float  # As percentage of position size

    # Risk metrics
    max_adverse_move_pct: float
    max_favorable_move_pct: float
    max_drawdown_during_trade_usd: float
    max_drawdown_during_trade_pct: float

    # Timing
    trade_duration_hours: Optional[float]
    time_to_max_profit_hours: Optional[float]

    # Flags
    is_extreme_adverse: bool
    is_continued_panic_loss: bool
    is_aborted: bool

    def to_dict(self) -> Dict[str, Any]:
        """Convert to JSON-serializable dict."""
        return {
            "trade_id": self.trade_id,
            "market_id": self.market_id,
            "market_title": self.market_title,
            "direction": self.direction,
            "entry_price": self.entry_price,
            "exit_price": self.exit_price,
            "entry_timestamp": self.entry_timestamp,
            "exit_timestamp": self.exit_timestamp,
            "outcome": self.outcome,
            "position_size_usd": self.position_size_usd,
            "shares_acquired": round(self.shares_acquired, 4),
            "gross_pnl_usd": round(self.gross_pnl_usd, 4),
            "fee_cost_usd": round(self.fee_cost_usd, 4),
            "net_pnl_usd": round(self.net_pnl_usd, 4),
            "net_pnl_pct": round(self.net_pnl_pct, 4),
            "max_adverse_move_pct": round(self.max_adverse_move_pct, 4),
            "max_favorable_move_pct": round(self.max_favorable_move_pct, 4),
            "max_drawdown_during_trade_usd": round(self.max_drawdown_during_trade_usd, 4),
            "max_drawdown_during_trade_pct": round(self.max_drawdown_during_trade_pct, 4),
            "trade_duration_hours": (
                round(self.trade_duration_hours, 2)
                if self.trade_duration_hours else None
            ),
            "time_to_max_profit_hours": (
                round(self.time_to_max_profit_hours, 2)
                if self.time_to_max_profit_hours else None
            ),
            "is_extreme_adverse": self.is_extreme_adverse,
            "is_continued_panic_loss": self.is_continued_panic_loss,
            "is_aborted": self.is_aborted,
        }


@dataclass
class AggregatePnLMetrics:
    """
    Aggregate PnL metrics across all analyzed trades.
    """
    # Counts
    total_trades: int
    completed_trades: int
    pending_trades: int
    aborted_trades: int

    # Win/Loss breakdown
    winning_trades: int
    losing_trades: int
    breakeven_trades: int

    # Rates
    win_rate: float
    loss_rate: float
    breakeven_rate: float

    # PnL statistics (USD)
    total_gross_pnl: float
    total_fees: float
    total_net_pnl: float

    average_net_pnl: float
    median_net_pnl: float
    std_dev_net_pnl: float

    # Extremes
    best_trade_pnl: float
    best_trade_id: str
    worst_trade_pnl: float
    worst_trade_id: str

    # Cumulative metrics
    max_cumulative_pnl: float
    min_cumulative_pnl: float
    max_drawdown_overall: float
    max_drawdown_pct: float

    # Risk flags
    extreme_adverse_count: int
    continued_panic_loss_count: int

    # Viability assessment
    is_economically_viable: bool
    viability_reason: str

    # Timestamp
    analysis_timestamp: str

    def to_dict(self) -> Dict[str, Any]:
        """Convert to JSON-serializable dict."""
        return {
            "counts": {
                "total_trades": self.total_trades,
                "completed_trades": self.completed_trades,
                "pending_trades": self.pending_trades,
                "aborted_trades": self.aborted_trades,
            },
            "win_loss": {
                "winning_trades": self.winning_trades,
                "losing_trades": self.losing_trades,
                "breakeven_trades": self.breakeven_trades,
                "win_rate": round(self.win_rate, 4),
                "loss_rate": round(self.loss_rate, 4),
                "breakeven_rate": round(self.breakeven_rate, 4),
            },
            "pnl_statistics": {
                "total_gross_pnl_usd": round(self.total_gross_pnl, 2),
                "total_fees_usd": round(self.total_fees, 2),
                "total_net_pnl_usd": round(self.total_net_pnl, 2),
                "average_net_pnl_usd": round(self.average_net_pnl, 2),
                "median_net_pnl_usd": round(self.median_net_pnl, 2),
                "std_dev_net_pnl_usd": round(self.std_dev_net_pnl, 2),
            },
            "extremes": {
                "best_trade_pnl_usd": round(self.best_trade_pnl, 2),
                "best_trade_id": self.best_trade_id,
                "worst_trade_pnl_usd": round(self.worst_trade_pnl, 2),
                "worst_trade_id": self.worst_trade_id,
            },
            "cumulative": {
                "max_cumulative_pnl_usd": round(self.max_cumulative_pnl, 2),
                "min_cumulative_pnl_usd": round(self.min_cumulative_pnl, 2),
                "max_drawdown_overall_usd": round(self.max_drawdown_overall, 2),
                "max_drawdown_pct": round(self.max_drawdown_pct, 4),
            },
            "risk_flags": {
                "extreme_adverse_count": self.extreme_adverse_count,
                "continued_panic_loss_count": self.continued_panic_loss_count,
            },
            "viability": {
                "is_economically_viable": self.is_economically_viable,
                "viability_reason": self.viability_reason,
            },
            "analysis_timestamp": self.analysis_timestamp,
        }


@dataclass
class PaperPnLReport:
    """
    Complete Paper PnL analysis report.
    """
    # Configuration used
    position_size_usd: float
    trading_fee_pct: float
    extreme_adverse_threshold: float
    loss_flag_threshold: float

    # Results
    aggregate_metrics: AggregatePnLMetrics
    trade_results: List[TradePnLResult]
    cumulative_pnl_curve: List[Tuple[str, float]]  # (timestamp, cumulative_pnl)

    # Flagged trades
    flagged_extreme_adverse: List[str]  # trade_ids
    flagged_continued_panic: List[str]  # trade_ids

    def to_dict(self) -> Dict[str, Any]:
        """Convert to JSON-serializable dict."""
        return {
            "configuration": {
                "position_size_usd": self.position_size_usd,
                "trading_fee_pct": self.trading_fee_pct,
                "extreme_adverse_threshold": self.extreme_adverse_threshold,
                "loss_flag_threshold": self.loss_flag_threshold,
            },
            "aggregate_metrics": self.aggregate_metrics.to_dict(),
            "trade_results": [t.to_dict() for t in self.trade_results],
            "cumulative_pnl_curve": [
                {"timestamp": ts, "cumulative_pnl_usd": round(pnl, 2)}
                for ts, pnl in self.cumulative_pnl_curve
            ],
            "flagged_trades": {
                "extreme_adverse": self.flagged_extreme_adverse,
                "continued_panic_loss": self.flagged_continued_panic,
            },
        }


# =============================================================================
# PAPER PNL ANALYZER
# =============================================================================


class PaperPnLAnalyzer:
    """
    Analyzes shadow mode simulated trades for paper PnL.

    GOVERNANCE:
    - READ ONLY - does not modify any source data
    - CONSERVATIVE - assumptions penalize the strategy
    - ANALYTICAL - no execution or trading logic
    """

    def __init__(
        self,
        position_size_usd: float = DEFAULT_POSITION_SIZE_USD,
        trading_fee_pct: float = DEFAULT_TRADING_FEE_PCT,
        extreme_adverse_threshold: float = DEFAULT_EXTREME_ADVERSE_THRESHOLD,
        loss_flag_threshold: float = DEFAULT_LOSS_FLAG_THRESHOLD,
        shadow_log_path: Optional[Path] = None,
    ):
        """
        Initialize the Paper PnL Analyzer.

        Args:
            position_size_usd: Fixed position size for all trades.
            trading_fee_pct: Total trading fees as fraction.
            extreme_adverse_threshold: Threshold for extreme adverse flag.
            loss_flag_threshold: Threshold for continued panic loss flag.
            shadow_log_path: Path to shadow mode logs.
        """
        self.position_size_usd = position_size_usd
        self.trading_fee_pct = trading_fee_pct
        self.extreme_adverse_threshold = extreme_adverse_threshold
        self.loss_flag_threshold = loss_flag_threshold
        self.shadow_log_path = shadow_log_path or DEFAULT_SHADOW_LOG_PATH

        logger.info(
            f"PaperPnLAnalyzer initialized | "
            f"position_size=${position_size_usd} | "
            f"fee={trading_fee_pct:.1%} | "
            f"log_path={self.shadow_log_path}"
        )

    def load_trades(self) -> List[Dict[str, Any]]:
        """
        Load simulated trades from shadow log.

        Returns list of trade dictionaries.
        """
        trades_file = self.shadow_log_path / "simulated_trades.jsonl"

        if not trades_file.exists():
            logger.warning(f"No trades file found at {trades_file}")
            return []

        trades = []
        try:
            with open(trades_file, "r") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        trades.append(json.loads(line))
        except Exception as e:
            logger.error(f"Failed to load trades: {e}")
            return []

        logger.info(f"Loaded {len(trades)} trades from {trades_file}")
        return trades

    def analyze_trade(self, trade: Dict[str, Any]) -> TradePnLResult:
        """
        Analyze a single trade for paper PnL.

        CONSERVATIVE ASSUMPTIONS:
        - Exit strictly at logged exit price (no optimistic timing)
        - Fees applied to both entry and exit
        - Adverse moves use worst case from logged data
        """
        trade_id = trade.get("trade_id", "unknown")
        market_id = trade.get("market_id", "unknown")
        market_title = trade.get("market_title", "unknown")

        direction = trade.get("direction", "UNDERPRICED")
        entry_price = trade.get("entry_price", 0.0)
        exit_price = trade.get("price_at_exit_time")
        outcome = trade.get("outcome", "PENDING")
        is_aborted = trade.get("aborted", False)

        entry_timestamp = trade.get("entry_timestamp", "")
        exit_timestamp = trade.get("exit_timestamp")

        max_adverse = trade.get("max_adverse_move", 0.0)
        max_favorable = trade.get("max_favorable_move", 0.0)

        # Handle missing exit price
        if exit_price is None:
            # Use entry price (no change) for pending/incomplete trades
            exit_price = entry_price

        # Calculate shares acquired
        # In prediction markets, you buy shares that pay $1 if outcome is YES
        # Entry price is cost per share, position_size / entry_price = shares
        if entry_price > 0:
            shares_acquired = self.position_size_usd / entry_price
        else:
            shares_acquired = 0.0

        # Calculate gross PnL
        # UNDERPRICED (long): profit = (exit_price - entry_price) * shares
        # OVERPRICED (short): profit = (entry_price - exit_price) * shares
        if direction == "UNDERPRICED":
            # Long position - bought expecting price to rise
            price_change = exit_price - entry_price
            gross_pnl = price_change * shares_acquired
        else:
            # Short position - sold expecting price to fall
            price_change = entry_price - exit_price
            gross_pnl = price_change * shares_acquired

        # Calculate fees (apply to both entry and exit)
        # Fee is percentage of position size for each leg
        fee_cost = self.position_size_usd * self.trading_fee_pct * 2

        # Net PnL
        net_pnl = gross_pnl - fee_cost
        net_pnl_pct = net_pnl / self.position_size_usd if self.position_size_usd > 0 else 0.0

        # Calculate drawdown during trade
        # Adverse move is price movement against our position
        max_drawdown_during_trade = max_adverse * shares_acquired
        max_drawdown_pct = max_adverse

        # Calculate duration
        trade_duration_hours = None
        time_to_max_profit_hours = None
        if entry_timestamp and exit_timestamp:
            try:
                entry_dt = datetime.fromisoformat(entry_timestamp)
                exit_dt = datetime.fromisoformat(exit_timestamp)
                duration = exit_dt - entry_dt
                trade_duration_hours = duration.total_seconds() / 3600
            except Exception:
                pass

        # Estimate time to max profit from available price observations
        # This is a rough estimate based on logged price checkpoints
        time_to_max_profit_hours = self._estimate_time_to_max_profit(
            trade, direction, entry_price
        )

        # Set flags
        is_extreme_adverse = max_adverse >= self.extreme_adverse_threshold
        is_continued_panic_loss = (
            outcome == "CONTINUED_PANIC" and
            net_pnl_pct <= -self.loss_flag_threshold
        )

        return TradePnLResult(
            trade_id=trade_id,
            market_id=market_id,
            market_title=market_title,
            direction=direction,
            entry_price=entry_price,
            exit_price=exit_price,
            entry_timestamp=entry_timestamp,
            exit_timestamp=exit_timestamp,
            outcome=outcome,
            position_size_usd=self.position_size_usd,
            shares_acquired=shares_acquired,
            gross_pnl_usd=gross_pnl,
            fee_cost_usd=fee_cost,
            net_pnl_usd=net_pnl,
            net_pnl_pct=net_pnl_pct,
            max_adverse_move_pct=max_adverse,
            max_favorable_move_pct=max_favorable,
            max_drawdown_during_trade_usd=max_drawdown_during_trade,
            max_drawdown_during_trade_pct=max_drawdown_pct,
            trade_duration_hours=trade_duration_hours,
            time_to_max_profit_hours=time_to_max_profit_hours,
            is_extreme_adverse=is_extreme_adverse,
            is_continued_panic_loss=is_continued_panic_loss,
            is_aborted=is_aborted,
        )

    def _estimate_time_to_max_profit(
        self,
        trade: Dict[str, Any],
        direction: str,
        entry_price: float,
    ) -> Optional[float]:
        """
        Estimate time to maximum profit from price checkpoints.

        Returns hours to max profit, or None if cannot determine.
        """
        checkpoints = [
            (1.0, trade.get("price_after_1h")),
            (6.0, trade.get("price_after_6h")),
            (12.0, trade.get("price_after_12h")),
            (24.0, trade.get("price_at_exit_time")),  # Assume 24h default exit
        ]

        best_profit = 0.0
        best_time = None

        for hours, price in checkpoints:
            if price is None:
                continue

            if direction == "UNDERPRICED":
                profit = price - entry_price
            else:
                profit = entry_price - price

            if profit > best_profit:
                best_profit = profit
                best_time = hours

        return best_time

    def compute_aggregate_metrics(
        self,
        trade_results: List[TradePnLResult],
    ) -> AggregatePnLMetrics:
        """
        Compute aggregate metrics across all trades.
        """
        total_trades = len(trade_results)

        if total_trades == 0:
            return self._empty_aggregate_metrics()

        # Filter by completion status
        completed = [t for t in trade_results if t.outcome != "PENDING"]
        pending = [t for t in trade_results if t.outcome == "PENDING"]
        aborted = [t for t in trade_results if t.is_aborted]

        completed_trades = len(completed)
        pending_trades = len(pending)
        aborted_trades = len(aborted)

        # Win/Loss breakdown (use small threshold for breakeven)
        BREAKEVEN_THRESHOLD = 0.01  # $0.01 is effectively breakeven
        winning = [t for t in completed if t.net_pnl_usd > BREAKEVEN_THRESHOLD]
        losing = [t for t in completed if t.net_pnl_usd < -BREAKEVEN_THRESHOLD]
        breakeven = [
            t for t in completed
            if -BREAKEVEN_THRESHOLD <= t.net_pnl_usd <= BREAKEVEN_THRESHOLD
        ]

        winning_trades = len(winning)
        losing_trades = len(losing)
        breakeven_trades = len(breakeven)

        # Rates
        if completed_trades > 0:
            win_rate = winning_trades / completed_trades
            loss_rate = losing_trades / completed_trades
            breakeven_rate = breakeven_trades / completed_trades
        else:
            win_rate = loss_rate = breakeven_rate = 0.0

        # PnL statistics
        net_pnls = [t.net_pnl_usd for t in completed]
        gross_pnls = [t.gross_pnl_usd for t in completed]
        fees = [t.fee_cost_usd for t in completed]

        total_gross_pnl = sum(gross_pnls)
        total_fees = sum(fees)
        total_net_pnl = sum(net_pnls)

        if net_pnls:
            average_net_pnl = statistics.mean(net_pnls)
            median_net_pnl = statistics.median(net_pnls)
            std_dev_net_pnl = statistics.stdev(net_pnls) if len(net_pnls) > 1 else 0.0
        else:
            average_net_pnl = median_net_pnl = std_dev_net_pnl = 0.0

        # Extremes
        if completed:
            best_trade = max(completed, key=lambda t: t.net_pnl_usd)
            worst_trade = min(completed, key=lambda t: t.net_pnl_usd)
            best_trade_pnl = best_trade.net_pnl_usd
            best_trade_id = best_trade.trade_id
            worst_trade_pnl = worst_trade.net_pnl_usd
            worst_trade_id = worst_trade.trade_id
        else:
            best_trade_pnl = worst_trade_pnl = 0.0
            best_trade_id = worst_trade_id = "N/A"

        # Cumulative metrics
        cumulative_curve = self._compute_cumulative_curve(completed)
        if cumulative_curve:
            cumulative_values = [v for _, v in cumulative_curve]
            max_cumulative_pnl = max(cumulative_values)
            min_cumulative_pnl = min(cumulative_values)

            # Calculate max drawdown
            max_drawdown_overall, max_drawdown_pct = self._compute_max_drawdown(
                cumulative_values
            )
        else:
            max_cumulative_pnl = min_cumulative_pnl = 0.0
            max_drawdown_overall = max_drawdown_pct = 0.0

        # Risk flags
        extreme_adverse_count = sum(1 for t in trade_results if t.is_extreme_adverse)
        continued_panic_loss_count = sum(
            1 for t in trade_results if t.is_continued_panic_loss
        )

        # Viability assessment
        is_viable, viability_reason = self._assess_viability(
            average_net_pnl=average_net_pnl,
            max_drawdown_pct=max_drawdown_pct,
            completed_trades=completed_trades,
            win_rate=win_rate,
        )

        return AggregatePnLMetrics(
            total_trades=total_trades,
            completed_trades=completed_trades,
            pending_trades=pending_trades,
            aborted_trades=aborted_trades,
            winning_trades=winning_trades,
            losing_trades=losing_trades,
            breakeven_trades=breakeven_trades,
            win_rate=win_rate,
            loss_rate=loss_rate,
            breakeven_rate=breakeven_rate,
            total_gross_pnl=total_gross_pnl,
            total_fees=total_fees,
            total_net_pnl=total_net_pnl,
            average_net_pnl=average_net_pnl,
            median_net_pnl=median_net_pnl,
            std_dev_net_pnl=std_dev_net_pnl,
            best_trade_pnl=best_trade_pnl,
            best_trade_id=best_trade_id,
            worst_trade_pnl=worst_trade_pnl,
            worst_trade_id=worst_trade_id,
            max_cumulative_pnl=max_cumulative_pnl,
            min_cumulative_pnl=min_cumulative_pnl,
            max_drawdown_overall=max_drawdown_overall,
            max_drawdown_pct=max_drawdown_pct,
            extreme_adverse_count=extreme_adverse_count,
            continued_panic_loss_count=continued_panic_loss_count,
            is_economically_viable=is_viable,
            viability_reason=viability_reason,
            analysis_timestamp=datetime.utcnow().isoformat(),
        )

    def _empty_aggregate_metrics(self) -> AggregatePnLMetrics:
        """Return empty aggregate metrics when no trades exist."""
        return AggregatePnLMetrics(
            total_trades=0,
            completed_trades=0,
            pending_trades=0,
            aborted_trades=0,
            winning_trades=0,
            losing_trades=0,
            breakeven_trades=0,
            win_rate=0.0,
            loss_rate=0.0,
            breakeven_rate=0.0,
            total_gross_pnl=0.0,
            total_fees=0.0,
            total_net_pnl=0.0,
            average_net_pnl=0.0,
            median_net_pnl=0.0,
            std_dev_net_pnl=0.0,
            best_trade_pnl=0.0,
            best_trade_id="N/A",
            worst_trade_pnl=0.0,
            worst_trade_id="N/A",
            max_cumulative_pnl=0.0,
            min_cumulative_pnl=0.0,
            max_drawdown_overall=0.0,
            max_drawdown_pct=0.0,
            extreme_adverse_count=0,
            continued_panic_loss_count=0,
            is_economically_viable=False,
            viability_reason="INSUFFICIENT DATA: No trades to analyze.",
            analysis_timestamp=datetime.utcnow().isoformat(),
        )

    def _compute_cumulative_curve(
        self,
        completed_trades: List[TradePnLResult],
    ) -> List[Tuple[str, float]]:
        """
        Compute cumulative PnL curve over time.

        Returns list of (timestamp, cumulative_pnl) tuples.
        """
        if not completed_trades:
            return []

        # Sort by exit timestamp
        sorted_trades = sorted(
            completed_trades,
            key=lambda t: t.exit_timestamp or t.entry_timestamp or ""
        )

        curve = []
        cumulative = 0.0

        for trade in sorted_trades:
            cumulative += trade.net_pnl_usd
            timestamp = trade.exit_timestamp or trade.entry_timestamp or ""
            curve.append((timestamp, cumulative))

        return curve

    def _compute_max_drawdown(
        self,
        cumulative_values: List[float],
    ) -> Tuple[float, float]:
        """
        Compute maximum drawdown from cumulative PnL curve.

        Returns (max_drawdown_usd, max_drawdown_pct).
        """
        if not cumulative_values:
            return 0.0, 0.0

        peak = cumulative_values[0]
        max_drawdown = 0.0

        for value in cumulative_values:
            if value > peak:
                peak = value
            drawdown = peak - value
            if drawdown > max_drawdown:
                max_drawdown = drawdown

        # Calculate percentage relative to position size
        max_drawdown_pct = max_drawdown / self.position_size_usd

        return max_drawdown, max_drawdown_pct

    def _assess_viability(
        self,
        average_net_pnl: float,
        max_drawdown_pct: float,
        completed_trades: int,
        win_rate: float,
    ) -> Tuple[bool, str]:
        """
        Assess economic viability.

        CONSERVATIVE ASSESSMENT:
        - If marginal or inconclusive, classify as NOT VIABLE
        - Require positive average PnL
        - Require acceptable drawdown
        - Require minimum sample size
        """
        reasons = []

        # Check minimum sample size
        MIN_TRADES_FOR_ASSESSMENT = 5
        if completed_trades < MIN_TRADES_FOR_ASSESSMENT:
            reasons.append(
                f"INSUFFICIENT DATA: Only {completed_trades} trades "
                f"(need >= {MIN_TRADES_FOR_ASSESSMENT})"
            )

        # Check average PnL
        if average_net_pnl <= MIN_AVERAGE_PNL_FOR_VIABILITY:
            reasons.append(
                f"NEGATIVE/ZERO PNL: Average net PnL is ${average_net_pnl:.2f} "
                f"(must be > ${MIN_AVERAGE_PNL_FOR_VIABILITY:.2f})"
            )

        # Check max drawdown
        if max_drawdown_pct > MAX_ACCEPTABLE_DRAWDOWN_PCT:
            reasons.append(
                f"EXCESSIVE DRAWDOWN: Max drawdown is {max_drawdown_pct:.1%} "
                f"(must be <= {MAX_ACCEPTABLE_DRAWDOWN_PCT:.1%})"
            )

        # Check win rate (must be > 50% to be viable with fees)
        MIN_WIN_RATE = 0.50
        if completed_trades >= MIN_TRADES_FOR_ASSESSMENT and win_rate < MIN_WIN_RATE:
            reasons.append(
                f"LOW WIN RATE: {win_rate:.1%} (should be >= {MIN_WIN_RATE:.1%})"
            )

        if reasons:
            return False, "NOT VIABLE: " + "; ".join(reasons)
        else:
            return True, (
                f"ECONOMICALLY VIABLE: Average net PnL ${average_net_pnl:.2f}, "
                f"win rate {win_rate:.1%}, max drawdown {max_drawdown_pct:.1%}"
            )

    def analyze(self) -> PaperPnLReport:
        """
        Run complete paper PnL analysis.

        Returns PaperPnLReport with all results.
        """
        logger.info("Starting paper PnL analysis...")

        # Load trades
        trades = self.load_trades()

        # Analyze each trade
        trade_results = [self.analyze_trade(t) for t in trades]

        # Compute aggregates
        aggregate_metrics = self.compute_aggregate_metrics(trade_results)

        # Build cumulative curve
        completed = [t for t in trade_results if t.outcome != "PENDING"]
        cumulative_curve = self._compute_cumulative_curve(completed)

        # Collect flagged trades
        flagged_extreme_adverse = [
            t.trade_id for t in trade_results if t.is_extreme_adverse
        ]
        flagged_continued_panic = [
            t.trade_id for t in trade_results if t.is_continued_panic_loss
        ]

        report = PaperPnLReport(
            position_size_usd=self.position_size_usd,
            trading_fee_pct=self.trading_fee_pct,
            extreme_adverse_threshold=self.extreme_adverse_threshold,
            loss_flag_threshold=self.loss_flag_threshold,
            aggregate_metrics=aggregate_metrics,
            trade_results=trade_results,
            cumulative_pnl_curve=cumulative_curve,
            flagged_extreme_adverse=flagged_extreme_adverse,
            flagged_continued_panic=flagged_continued_panic,
        )

        logger.info(
            f"Analysis complete | "
            f"total_trades={aggregate_metrics.total_trades} | "
            f"net_pnl=${aggregate_metrics.total_net_pnl:.2f} | "
            f"viable={aggregate_metrics.is_economically_viable}"
        )

        return report

    def save_report(
        self,
        report: PaperPnLReport,
        output_path: Optional[Path] = None,
    ):
        """
        Save report to JSON file.
        """
        output_path = output_path or DEFAULT_OUTPUT_PATH

        # Ensure parent directory exists
        output_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            with open(output_path, "w") as f:
                json.dump(report.to_dict(), f, indent=2)
            logger.info(f"Report saved to {output_path}")
        except Exception as e:
            logger.error(f"Failed to save report: {e}")

    def print_console_report(self, report: PaperPnLReport):
        """
        Print concise console report.
        """
        metrics = report.aggregate_metrics

        print("\n" + "=" * 70)
        print("PANIC CONTRARIAN ENGINE - PAPER PNL EVALUATION")
        print("=" * 70)

        # Configuration
        print(f"\nConfiguration:")
        print(f"  Position Size:     ${report.position_size_usd:.2f}")
        print(f"  Trading Fee:       {report.trading_fee_pct:.1%}")
        print(f"  Adverse Threshold: {report.extreme_adverse_threshold:.1%}")

        # Trade counts
        print(f"\nTrade Counts:")
        print(f"  Total Trades:      {metrics.total_trades}")
        print(f"  Completed:         {metrics.completed_trades}")
        print(f"  Pending:           {metrics.pending_trades}")
        print(f"  Aborted:           {metrics.aborted_trades}")

        # Win/Loss
        print(f"\nWin/Loss Breakdown:")
        print(f"  Winning:           {metrics.winning_trades} ({metrics.win_rate:.1%})")
        print(f"  Losing:            {metrics.losing_trades} ({metrics.loss_rate:.1%})")
        print(f"  Breakeven:         {metrics.breakeven_trades} ({metrics.breakeven_rate:.1%})")

        # PnL
        print(f"\nPnL Summary:")
        print(f"  Total Gross PnL:   ${metrics.total_gross_pnl:+.2f}")
        print(f"  Total Fees:        ${metrics.total_fees:.2f}")
        print(f"  Total Net PnL:     ${metrics.total_net_pnl:+.2f}")
        print(f"  Average Net PnL:   ${metrics.average_net_pnl:+.2f}")
        print(f"  Median Net PnL:    ${metrics.median_net_pnl:+.2f}")
        print(f"  Std Dev:           ${metrics.std_dev_net_pnl:.2f}")

        # Extremes
        print(f"\nExtremes:")
        print(f"  Best Trade:        ${metrics.best_trade_pnl:+.2f} ({metrics.best_trade_id})")
        print(f"  Worst Trade:       ${metrics.worst_trade_pnl:+.2f} ({metrics.worst_trade_id})")

        # Drawdown
        print(f"\nRisk Metrics:")
        print(f"  Max Drawdown:      ${metrics.max_drawdown_overall:.2f} ({metrics.max_drawdown_pct:.1%})")
        print(f"  Extreme Adverse:   {metrics.extreme_adverse_count} trades flagged")
        print(f"  Continued Panic:   {metrics.continued_panic_loss_count} trades flagged")

        # Viability verdict
        print("\n" + "-" * 70)
        if metrics.is_economically_viable:
            print("VERDICT: ECONOMICALLY VIABLE")
        else:
            print("VERDICT: NOT VIABLE")
        print(f"\nReason: {metrics.viability_reason}")
        print("-" * 70)

        # Flagged trades detail
        if report.flagged_extreme_adverse:
            print(f"\nFlagged - Extreme Adverse Move ({len(report.flagged_extreme_adverse)}):")
            for tid in report.flagged_extreme_adverse[:5]:  # Show first 5
                print(f"  - {tid}")
            if len(report.flagged_extreme_adverse) > 5:
                print(f"  ... and {len(report.flagged_extreme_adverse) - 5} more")

        if report.flagged_continued_panic:
            print(f"\nFlagged - Continued Panic Loss ({len(report.flagged_continued_panic)}):")
            for tid in report.flagged_continued_panic[:5]:
                print(f"  - {tid}")
            if len(report.flagged_continued_panic) > 5:
                print(f"  ... and {len(report.flagged_continued_panic) - 5} more")

        print("\n" + "=" * 70)


# =============================================================================
# MAIN ENTRY POINT
# =============================================================================


def run_paper_pnl_analysis(
    position_size_usd: float = DEFAULT_POSITION_SIZE_USD,
    trading_fee_pct: float = DEFAULT_TRADING_FEE_PCT,
    shadow_log_path: Optional[Path] = None,
    output_path: Optional[Path] = None,
    print_report: bool = True,
) -> PaperPnLReport:
    """
    Run paper PnL analysis and generate report.

    Args:
        position_size_usd: Fixed position size for all trades.
        trading_fee_pct: Total trading fees as fraction.
        shadow_log_path: Path to shadow mode logs.
        output_path: Path for output JSON file.
        print_report: Whether to print console report.

    Returns:
        PaperPnLReport with all results.
    """
    analyzer = PaperPnLAnalyzer(
        position_size_usd=position_size_usd,
        trading_fee_pct=trading_fee_pct,
        shadow_log_path=shadow_log_path,
    )

    report = analyzer.analyze()

    # Save to file
    analyzer.save_report(report, output_path)

    # Print console report
    if print_report:
        analyzer.print_console_report(report)

    return report


# =============================================================================
# CLI ENTRY POINT
# =============================================================================


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Paper PnL Evaluation for Panic Contrarian Engine"
    )
    parser.add_argument(
        "--position-size",
        type=float,
        default=DEFAULT_POSITION_SIZE_USD,
        help=f"Position size in USD (default: {DEFAULT_POSITION_SIZE_USD})",
    )
    parser.add_argument(
        "--fee",
        type=float,
        default=DEFAULT_TRADING_FEE_PCT,
        help=f"Trading fee as decimal (default: {DEFAULT_TRADING_FEE_PCT})",
    )
    parser.add_argument(
        "--shadow-log-path",
        type=str,
        default=None,
        help="Path to shadow mode logs",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Output path for JSON report",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress console output",
    )

    args = parser.parse_args()

    # Setup basic logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
    )

    # Run analysis
    report = run_paper_pnl_analysis(
        position_size_usd=args.position_size,
        trading_fee_pct=args.fee,
        shadow_log_path=Path(args.shadow_log_path) if args.shadow_log_path else None,
        output_path=Path(args.output) if args.output else None,
        print_report=not args.quiet,
    )

    # Exit with appropriate code
    if report.aggregate_metrics.is_economically_viable:
        exit(0)
    else:
        exit(1)
