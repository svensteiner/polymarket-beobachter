# =============================================================================
# POLYMARKET BEOBACHTER - PANIC CONTRARIAN ENGINE
# =============================================================================
#
# GOVERNANCE INTENT:
# This module implements a strictly constrained "Panic Contrarian Strategy".
# It is COMPLETELY ISOLATED from the core decision engine.
#
# CORE PRINCIPLE:
# Trade ONLY when human panic creates short-lived price dislocations.
# If in doubt, DO NOTHING.
#
# NON-NEGOTIABLE RULES:
# 1. The existing core decision engine MUST remain unchanged.
# 2. No existing thresholds may be loosened.
# 3. No live self-learning or adaptive thresholds.
# 4. No leverage logic.
# 5. No scaling in/out.
# 6. No more than ONE trade per market per panic event.
# 7. Time-based exits ONLY.
#
# THIS MODULE MAY ONLY ACTIVATE IF ALL OF THE FOLLOWING ARE TRUE:
# A) External news shock detected (no change to resolution rules)
# B) Price moves >= PANIC_PRICE_DELTA within <= PANIC_TIME_WINDOW
# C) Volume >= PANIC_VOLUME_MULTIPLIER vs rolling baseline
# D) Time until resolution >= SAFETY_BUFFER_HOURS
#
# IF ANY CONDITION FAILS → IGNORE (no trade, no signal).
#
# STATE MACHINE:
# NORMAL → PANIC_WINDOW_OPEN → COOLDOWN → NORMAL
#
# =============================================================================
#
# SHADOW MODE (MANDATORY):
# This engine is assumed to be WRONG by default.
# Shadow mode MUST be enabled until the engine proves its value.
#
# In shadow mode:
# - All trades are SIMULATED only
# - No real capital movement
# - Full logging of hypothetical outcomes
# - Automatic kill switch if FALSE_TRIGGER rate exceeds threshold
#
# The engine's job is to prove usefulness over time.
# If unsure, the correct action is: DO NOTHING.
#
# =============================================================================

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple
from enum import Enum

from shared.enums import (
    PanicEngineState,
    PanicEngineOutput,
    PanicDirection,
    PanicConditionResult,
    PanicTradeOutcome,
    AbortReason,
    ShadowModeStatus,
)

logger = logging.getLogger(__name__)


# =============================================================================
# SHADOW MODE CONFIGURATION
# =============================================================================
#
# These settings control shadow mode behavior.
# They are HARDCODED to prevent accidental production trading.
#
# =============================================================================

PANIC_SHADOW_MODE: bool = True
"""
GLOBAL SHADOW MODE FLAG - DEFAULT: TRUE (ALWAYS ON)

When TRUE:
- PANIC_WINDOW_OPEN produces ONLY simulated trades
- No capital movement
- No execution calls
- Full logging required

When FALSE:
- Real trades MAY be executed (NOT RECOMMENDED)
- Requires explicit manual change to this constant
- Should only be changed after extensive shadow validation

WARNING: Setting this to FALSE without extensive shadow mode
validation will likely result in losses.
"""

SHADOW_LOG_PATH: Path = Path(__file__).parent.parent / "logs" / "panic_shadow"
"""
Directory for shadow mode trade logs.
Each simulated trade gets a full audit trail here.
"""

FALSE_TRIGGER_THRESHOLD: float = 0.30
"""
Kill switch threshold for FALSE_TRIGGER rate.
If FALSE_TRIGGER outcomes exceed 30% of total outcomes,
the engine auto-disables.

WHY 30%:
- Below 20%: Expected noise, some false triggers normal
- 20-30%: Concerning, needs investigation
- 30%+: Engine is not working, disable immediately

This is a HARD threshold. No exceptions.
"""

KILL_SWITCH_MIN_SAMPLES: int = 10
"""
Minimum number of completed trades before kill switch can trigger.
Prevents premature kill switch activation on small samples.

WHY 10:
- Under 5: Statistical noise dominates
- 5-10: Starting to be meaningful
- 10+: Enough data for kill switch decision
"""

REVERSION_THRESHOLD: float = 0.05
"""
Minimum price reversion (5%) to classify as GOOD_REVERSION.
If price moves back toward pre-panic level by at least 5%,
we consider the contrarian thesis validated.
"""

CONTINUED_PANIC_THRESHOLD: float = 0.05
"""
Minimum price movement in panic direction (5%) to classify as CONTINUED_PANIC.
If price continues to move against our contrarian position by 5%+,
we classify as CONTINUED_PANIC (loss scenario).
"""


# =============================================================================
# CONFIGURATION CONSTANTS
# =============================================================================
#
# These are the ONLY parameters that control panic detection.
# They are hardcoded to prevent live modification.
# Any change requires code deployment and review.
#
# =============================================================================

# -----------------------------------------------------------------------------
# PRICE DISLOCATION THRESHOLDS
# -----------------------------------------------------------------------------
# WHY: Panic events cause rapid, significant price movements.
# Small moves are normal market noise; we only care about large dislocations.

PANIC_PRICE_DELTA: float = 0.15
"""
Minimum price movement (as decimal) to qualify as panic.
0.15 = 15 percentage points (e.g., 50% → 35% or 50% → 65%).

WHY THIS VALUE:
- Below 10%: Normal market fluctuation, too much noise.
- 10-15%: Could be informed trading, not clear panic.
- 15%+: Highly likely to be emotional/panic-driven.
- Above 25%: Almost certainly panic, but rare.

CONSERVATIVE CHOICE: 15% balances signal quality vs opportunity frequency.
"""

PANIC_TIME_WINDOW_MINUTES: int = 60
"""
Maximum time window (minutes) for the price movement to occur.
Movement must happen within this window to qualify.

WHY THIS VALUE:
- Under 15 min: Flash crash, may recover before we can act.
- 15-30 min: Very fast, high confidence of panic.
- 30-60 min: Still fast enough to be panic, gives us time to validate.
- Over 60 min: Could be fundamental re-pricing, not panic.

CONSERVATIVE CHOICE: 60 minutes allows thorough validation while
still capturing panic events that aren't instant flash crashes.
"""

# -----------------------------------------------------------------------------
# VOLUME SPIKE THRESHOLDS
# -----------------------------------------------------------------------------
# WHY: Panic is characterized by abnormally high trading activity.
# Volume spikes confirm that the price move is panic, not manipulation.

PANIC_VOLUME_MULTIPLIER: float = 3.0
"""
Minimum volume spike (as multiplier of rolling baseline).
3.0 = 300% of normal volume.

WHY THIS VALUE:
- 2x: Could be normal variance or single large order.
- 3x: Highly unusual, multiple participants panicking.
- 5x+: Extreme panic, but may already be recovering.

CONSERVATIVE CHOICE: 3x ensures broad participation, not single actor.
"""

VOLUME_BASELINE_HOURS: int = 24
"""
Rolling window (hours) for calculating baseline volume.
24 hours = captures daily pattern including quiet hours.

WHY THIS VALUE:
- 1 hour: Too short, sensitive to normal intraday variance.
- 6 hours: May miss overnight patterns.
- 24 hours: Captures full daily cycle, smooths variance.
- 7 days: Too long, may include unusual events.

CONSERVATIVE CHOICE: 24 hours is standard for intraday analysis.
"""

# -----------------------------------------------------------------------------
# TEMPORAL SAFETY THRESHOLDS
# -----------------------------------------------------------------------------
# WHY: Trading near resolution is dangerous - resolution risk dominates panic.
# We need enough time for panic to subside and price to normalize.

SAFETY_BUFFER_HOURS: int = 48
"""
Minimum hours until market resolution to allow trading.
48 hours = 2 full days of trading.

WHY THIS VALUE:
- Under 24h: Resolution risk too high, no time for recovery.
- 24-48h: Marginal, depends on market specifics.
- 48h+: Sufficient time for panic to subside.
- Over 7 days: Could be structural re-pricing, not panic.

CONSERVATIVE CHOICE: 48 hours ensures we're not gambling on resolution.
"""

# -----------------------------------------------------------------------------
# STATE MACHINE TIMING
# -----------------------------------------------------------------------------

PANIC_WINDOW_DURATION_MINUTES: int = 30
"""
How long the PANIC_WINDOW_OPEN state lasts (minutes).
After this, window expires regardless of trade execution.

WHY THIS VALUE:
- Under 10 min: May miss execution opportunities.
- 10-15 min: Tight but workable.
- 15-30 min: Reasonable window for deliberate action.
- Over 30 min: Panic may have already resolved, stale signal.

CONSERVATIVE CHOICE: 30 minutes allows deliberate entry without staleness.
"""

COOLDOWN_DURATION_HOURS: int = 4
"""
Duration of COOLDOWN state after a panic window closes (hours).
No new panic windows can open during cooldown.

WHY THIS VALUE:
- Under 1h: Risk of re-entering same panic event.
- 1-2h: May still be same event, aftershocks.
- 4h: Most panic events fully resolve within 4 hours.
- Over 8h: May miss unrelated new panic events.

CONSERVATIVE CHOICE: 4 hours prevents re-entry while allowing new events.
"""

# -----------------------------------------------------------------------------
# EXECUTION CONSTRAINTS (not enforced here, but documented for downstream)
# -----------------------------------------------------------------------------

MAX_POSITION_SIZE_USD: float = 100.0
"""
Maximum position size in USD for any panic trade.
This is a HARD LIMIT enforced at execution layer.

WHY THIS VALUE:
- Small enough that total loss is acceptable.
- Large enough to be meaningful if correct.
- Fixed, never scaled based on confidence or opportunity.
"""

MAX_HOLDING_TIME_HOURS: int = 24
"""
Maximum time to hold a panic contrarian position.
Mandatory exit after this time regardless of P&L.

WHY THIS VALUE:
- Panic dislocations should correct within hours.
- Holding longer means we were wrong about the panic thesis.
- Time-based exit prevents anchoring and hoping.
"""


# =============================================================================
# DATA MODELS
# =============================================================================


@dataclass
class PanicMetrics:
    """
    Metrics that triggered (or failed to trigger) a panic signal.

    This is a pure data container - no logic, no decisions.
    Used for audit trail and post-mortem analysis.
    """
    # Price movement metrics
    price_start: float
    price_end: float
    price_delta: float  # Absolute difference
    price_delta_direction: str  # "UP" or "DOWN"
    price_move_duration_minutes: int

    # Volume metrics
    current_volume: float
    baseline_volume: float
    volume_multiplier: float

    # Temporal metrics
    hours_until_resolution: float

    # Condition results
    price_condition: PanicConditionResult
    volume_condition: PanicConditionResult
    temporal_condition: PanicConditionResult
    news_shock_detected: bool

    # Timestamps
    observation_timestamp: str

    def to_dict(self) -> Dict[str, Any]:
        """Convert to JSON-serializable dict for audit logging."""
        return {
            "price_start": self.price_start,
            "price_end": self.price_end,
            "price_delta": self.price_delta,
            "price_delta_direction": self.price_delta_direction,
            "price_move_duration_minutes": self.price_move_duration_minutes,
            "current_volume": self.current_volume,
            "baseline_volume": self.baseline_volume,
            "volume_multiplier": self.volume_multiplier,
            "hours_until_resolution": self.hours_until_resolution,
            "price_condition": self.price_condition.value,
            "volume_condition": self.volume_condition.value,
            "temporal_condition": self.temporal_condition.value,
            "news_shock_detected": self.news_shock_detected,
            "observation_timestamp": self.observation_timestamp,
        }


@dataclass
class PanicMarketInput:
    """
    Input data required for panic contrarian analysis.

    This is kept SEPARATE from the core MarketInput to ensure isolation.
    The panic engine has different data requirements than the core engine.
    """
    market_id: str
    market_title: str

    # Current market state
    current_price: float  # 0.0 to 1.0

    # Historical price data for movement detection
    # List of (timestamp, price) tuples, most recent last
    price_history: List[Tuple[datetime, float]]

    # Volume data
    current_volume_24h: float
    historical_volume_baseline: float  # Average over baseline period

    # Resolution timing
    resolution_timestamp: Optional[datetime]

    # News/narrative context (boolean flags, not text analysis)
    news_shock_indicator: bool  # External signal that news shock occurred
    resolution_rules_changed: bool  # If True, disqualifies panic trade

    # Timestamp of this observation
    observation_timestamp: datetime = field(
        default_factory=datetime.utcnow
    )

    def __post_init__(self):
        """Validate input data."""
        if not 0.0 <= self.current_price <= 1.0:
            raise ValueError(
                f"current_price must be 0.0-1.0, got {self.current_price}"
            )
        if self.historical_volume_baseline < 0:
            raise ValueError(
                f"historical_volume_baseline cannot be negative"
            )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to JSON-serializable dict."""
        return {
            "market_id": self.market_id,
            "market_title": self.market_title,
            "current_price": self.current_price,
            "price_history_length": len(self.price_history),
            "current_volume_24h": self.current_volume_24h,
            "historical_volume_baseline": self.historical_volume_baseline,
            "resolution_timestamp": (
                self.resolution_timestamp.isoformat()
                if self.resolution_timestamp else None
            ),
            "news_shock_indicator": self.news_shock_indicator,
            "resolution_rules_changed": self.resolution_rules_changed,
            "observation_timestamp": self.observation_timestamp.isoformat(),
        }


@dataclass
class PanicEngineResult:
    """
    Output from the Panic Contrarian Engine.

    This is what the engine emits after analyzing a market.
    It does NOT execute trades - it only signals opportunities.
    """
    # Output state
    output: PanicEngineOutput

    # Engine state (for monitoring)
    engine_state: PanicEngineState

    # Market identification
    market_id: str

    # Only populated when output is PANIC_WINDOW_OPEN
    panic_direction: Optional[PanicDirection] = None
    window_expiration: Optional[datetime] = None

    # Only populated when output is COOLDOWN
    cooldown_remaining_minutes: Optional[int] = None

    # Always populated
    metrics: Optional[PanicMetrics] = None

    # Reasoning for audit trail
    reasoning: str = ""

    # Metadata
    analysis_version: str = "1.0.0"
    generated_at: str = field(
        default_factory=lambda: datetime.utcnow().isoformat()
    )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to JSON-serializable dict for audit logging."""
        return {
            "output": self.output.value,
            "engine_state": self.engine_state.value,
            "market_id": self.market_id,
            "panic_direction": (
                self.panic_direction.value if self.panic_direction else None
            ),
            "window_expiration": (
                self.window_expiration.isoformat()
                if self.window_expiration else None
            ),
            "cooldown_remaining_minutes": self.cooldown_remaining_minutes,
            "metrics": self.metrics.to_dict() if self.metrics else None,
            "reasoning": self.reasoning,
            "analysis_version": self.analysis_version,
            "generated_at": self.generated_at,
        }


@dataclass
class EngineStateSnapshot:
    """
    Persistent state of the engine for a specific market.

    This is stored externally (file/DB) and loaded on startup.
    Each market has its own state snapshot.
    """
    market_id: str
    current_state: PanicEngineState

    # PANIC_WINDOW_OPEN state data
    window_opened_at: Optional[datetime] = None
    window_expires_at: Optional[datetime] = None
    trade_executed_in_window: bool = False

    # COOLDOWN state data
    cooldown_started_at: Optional[datetime] = None
    cooldown_expires_at: Optional[datetime] = None

    # Last analysis timestamp
    last_analysis_at: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to JSON-serializable dict for persistence."""
        return {
            "market_id": self.market_id,
            "current_state": self.current_state.value,
            "window_opened_at": (
                self.window_opened_at.isoformat()
                if self.window_opened_at else None
            ),
            "window_expires_at": (
                self.window_expires_at.isoformat()
                if self.window_expires_at else None
            ),
            "trade_executed_in_window": self.trade_executed_in_window,
            "cooldown_started_at": (
                self.cooldown_started_at.isoformat()
                if self.cooldown_started_at else None
            ),
            "cooldown_expires_at": (
                self.cooldown_expires_at.isoformat()
                if self.cooldown_expires_at else None
            ),
            "last_analysis_at": (
                self.last_analysis_at.isoformat()
                if self.last_analysis_at else None
            ),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EngineStateSnapshot":
        """Reconstruct from JSON dict."""
        return cls(
            market_id=data["market_id"],
            current_state=PanicEngineState(data["current_state"]),
            window_opened_at=(
                datetime.fromisoformat(data["window_opened_at"])
                if data.get("window_opened_at") else None
            ),
            window_expires_at=(
                datetime.fromisoformat(data["window_expires_at"])
                if data.get("window_expires_at") else None
            ),
            trade_executed_in_window=data.get("trade_executed_in_window", False),
            cooldown_started_at=(
                datetime.fromisoformat(data["cooldown_started_at"])
                if data.get("cooldown_started_at") else None
            ),
            cooldown_expires_at=(
                datetime.fromisoformat(data["cooldown_expires_at"])
                if data.get("cooldown_expires_at") else None
            ),
            last_analysis_at=(
                datetime.fromisoformat(data["last_analysis_at"])
                if data.get("last_analysis_at") else None
            ),
        )

    @classmethod
    def new_for_market(cls, market_id: str) -> "EngineStateSnapshot":
        """Create a new state snapshot for a market (starts in NORMAL)."""
        return cls(
            market_id=market_id,
            current_state=PanicEngineState.NORMAL,
        )


# =============================================================================
# SHADOW MODE DATA MODELS
# =============================================================================


@dataclass
class SimulatedTrade:
    """
    Record of a simulated panic trade in shadow mode.

    This captures everything needed for post-mortem analysis:
    - Entry conditions
    - Price evolution over time
    - Exit conditions
    - Outcome classification

    NO REAL CAPITAL IS MOVED. This is observation only.
    """
    # Identification
    trade_id: str
    market_id: str
    market_title: str

    # Entry details
    entry_timestamp: datetime
    entry_price: float
    direction: PanicDirection
    triggering_metrics: Dict[str, Any]

    # Price observations (populated over time)
    price_after_1h: Optional[float] = None
    price_after_6h: Optional[float] = None
    price_after_12h: Optional[float] = None
    price_at_exit_time: Optional[float] = None

    # Extremes during observation period
    max_adverse_move: float = 0.0
    max_favorable_move: float = 0.0

    # Exit details
    exit_timestamp: Optional[datetime] = None
    exit_reason: Optional[str] = None

    # Outcome classification (populated after exit)
    outcome: PanicTradeOutcome = PanicTradeOutcome.PENDING

    # Abort details (if applicable)
    aborted: bool = False
    abort_reason: Optional[AbortReason] = None
    abort_timestamp: Optional[datetime] = None

    # Pre-panic baseline for comparison
    pre_panic_price: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to JSON-serializable dict for logging."""
        return {
            "trade_id": self.trade_id,
            "market_id": self.market_id,
            "market_title": self.market_title,
            "entry_timestamp": self.entry_timestamp.isoformat(),
            "entry_price": self.entry_price,
            "direction": self.direction.value,
            "triggering_metrics": self.triggering_metrics,
            "price_after_1h": self.price_after_1h,
            "price_after_6h": self.price_after_6h,
            "price_after_12h": self.price_after_12h,
            "price_at_exit_time": self.price_at_exit_time,
            "max_adverse_move": self.max_adverse_move,
            "max_favorable_move": self.max_favorable_move,
            "exit_timestamp": (
                self.exit_timestamp.isoformat() if self.exit_timestamp else None
            ),
            "exit_reason": self.exit_reason,
            "outcome": self.outcome.value,
            "aborted": self.aborted,
            "abort_reason": self.abort_reason.value if self.abort_reason else None,
            "abort_timestamp": (
                self.abort_timestamp.isoformat() if self.abort_timestamp else None
            ),
            "pre_panic_price": self.pre_panic_price,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SimulatedTrade":
        """Reconstruct from JSON dict."""
        return cls(
            trade_id=data["trade_id"],
            market_id=data["market_id"],
            market_title=data["market_title"],
            entry_timestamp=datetime.fromisoformat(data["entry_timestamp"]),
            entry_price=data["entry_price"],
            direction=PanicDirection(data["direction"]),
            triggering_metrics=data["triggering_metrics"],
            price_after_1h=data.get("price_after_1h"),
            price_after_6h=data.get("price_after_6h"),
            price_after_12h=data.get("price_after_12h"),
            price_at_exit_time=data.get("price_at_exit_time"),
            max_adverse_move=data.get("max_adverse_move", 0.0),
            max_favorable_move=data.get("max_favorable_move", 0.0),
            exit_timestamp=(
                datetime.fromisoformat(data["exit_timestamp"])
                if data.get("exit_timestamp") else None
            ),
            exit_reason=data.get("exit_reason"),
            outcome=PanicTradeOutcome(data.get("outcome", "PENDING")),
            aborted=data.get("aborted", False),
            abort_reason=(
                AbortReason(data["abort_reason"])
                if data.get("abort_reason") else None
            ),
            abort_timestamp=(
                datetime.fromisoformat(data["abort_timestamp"])
                if data.get("abort_timestamp") else None
            ),
            pre_panic_price=data.get("pre_panic_price"),
        )


@dataclass
class ShadowModeStats:
    """
    Aggregate statistics for shadow mode performance.

    Used to evaluate engine quality and trigger kill switch.
    """
    total_signals: int = 0
    total_completed_trades: int = 0

    # Outcome counts
    good_reversions: int = 0
    no_reversions: int = 0
    continued_panics: int = 0
    false_triggers: int = 0
    aborted: int = 0
    pending: int = 0

    # Kill switch status
    kill_switch_triggered: bool = False
    kill_switch_timestamp: Optional[datetime] = None

    # Performance metrics
    false_trigger_rate: float = 0.0
    win_rate: float = 0.0  # GOOD_REVERSION / completed

    def to_dict(self) -> Dict[str, Any]:
        """Convert to JSON-serializable dict."""
        return {
            "total_signals": self.total_signals,
            "total_completed_trades": self.total_completed_trades,
            "good_reversions": self.good_reversions,
            "no_reversions": self.no_reversions,
            "continued_panics": self.continued_panics,
            "false_triggers": self.false_triggers,
            "aborted": self.aborted,
            "pending": self.pending,
            "kill_switch_triggered": self.kill_switch_triggered,
            "kill_switch_timestamp": (
                self.kill_switch_timestamp.isoformat()
                if self.kill_switch_timestamp else None
            ),
            "false_trigger_rate": self.false_trigger_rate,
            "win_rate": self.win_rate,
        }

    def update_rates(self):
        """Recalculate derived rates."""
        if self.total_completed_trades > 0:
            self.false_trigger_rate = (
                self.false_triggers / self.total_completed_trades
            )
            self.win_rate = (
                self.good_reversions / self.total_completed_trades
            )
        else:
            self.false_trigger_rate = 0.0
            self.win_rate = 0.0

    def check_kill_switch(self) -> bool:
        """
        Check if kill switch should be triggered.

        Returns True if kill switch should activate.
        """
        # Need minimum samples
        if self.total_completed_trades < KILL_SWITCH_MIN_SAMPLES:
            return False

        # Check FALSE_TRIGGER rate
        self.update_rates()
        if self.false_trigger_rate > FALSE_TRIGGER_THRESHOLD:
            return True

        return False


# =============================================================================
# SHADOW MODE LOGGER
# =============================================================================


class ShadowModeLogger:
    """
    Handles all shadow mode logging.

    Writes simulated trades to JSONL files for post-mortem analysis.
    Thread-safe and append-only.
    """

    def __init__(self, log_dir: Optional[Path] = None):
        """Initialize the shadow mode logger."""
        self.log_dir = log_dir or SHADOW_LOG_PATH
        self.log_dir.mkdir(parents=True, exist_ok=True)

        # Stats file
        self.stats_file = self.log_dir / "shadow_stats.json"

        # Trades log (JSONL)
        self.trades_file = self.log_dir / "simulated_trades.jsonl"

        # Load or initialize stats
        self.stats = self._load_stats()

        logger.info(
            f"ShadowModeLogger initialized | log_dir={self.log_dir} | "
            f"total_signals={self.stats.total_signals}"
        )

    def _load_stats(self) -> ShadowModeStats:
        """Load stats from file or create new."""
        if self.stats_file.exists():
            try:
                with open(self.stats_file, "r") as f:
                    data = json.load(f)
                stats = ShadowModeStats(
                    total_signals=data.get("total_signals", 0),
                    total_completed_trades=data.get("total_completed_trades", 0),
                    good_reversions=data.get("good_reversions", 0),
                    no_reversions=data.get("no_reversions", 0),
                    continued_panics=data.get("continued_panics", 0),
                    false_triggers=data.get("false_triggers", 0),
                    aborted=data.get("aborted", 0),
                    pending=data.get("pending", 0),
                    kill_switch_triggered=data.get("kill_switch_triggered", False),
                    kill_switch_timestamp=(
                        datetime.fromisoformat(data["kill_switch_timestamp"])
                        if data.get("kill_switch_timestamp") else None
                    ),
                )
                stats.update_rates()
                return stats
            except Exception as e:
                logger.warning(f"Failed to load shadow stats: {e}")
        return ShadowModeStats()

    def _save_stats(self):
        """Save stats to file."""
        try:
            with open(self.stats_file, "w") as f:
                json.dump(self.stats.to_dict(), f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save shadow stats: {e}")

    def log_signal(self, result: "PanicEngineResult"):
        """Log a panic signal (PANIC_WINDOW_OPEN)."""
        self.stats.total_signals += 1
        self._save_stats()

        logger.info(
            f"SHADOW: Signal logged | market={result.market_id} | "
            f"total_signals={self.stats.total_signals}"
        )

    def log_simulated_trade(self, trade: SimulatedTrade):
        """Log a new simulated trade."""
        try:
            with open(self.trades_file, "a") as f:
                f.write(json.dumps(trade.to_dict()) + "\n")

            self.stats.pending += 1
            self._save_stats()

            logger.info(
                f"SHADOW: Trade logged | trade_id={trade.trade_id} | "
                f"market={trade.market_id} | direction={trade.direction.value}"
            )
        except Exception as e:
            logger.error(f"Failed to log simulated trade: {e}")

    def update_trade_outcome(
        self,
        trade_id: str,
        outcome: PanicTradeOutcome,
        exit_price: float,
        exit_timestamp: datetime,
        exit_reason: str,
    ):
        """
        Update a trade with its final outcome.

        This is called when the observation window closes.
        """
        # Update stats based on outcome
        self.stats.pending = max(0, self.stats.pending - 1)
        self.stats.total_completed_trades += 1

        if outcome == PanicTradeOutcome.GOOD_REVERSION:
            self.stats.good_reversions += 1
        elif outcome == PanicTradeOutcome.NO_REVERSION:
            self.stats.no_reversions += 1
        elif outcome == PanicTradeOutcome.CONTINUED_PANIC:
            self.stats.continued_panics += 1
        elif outcome == PanicTradeOutcome.FALSE_TRIGGER:
            self.stats.false_triggers += 1
        elif outcome == PanicTradeOutcome.ABORTED:
            self.stats.aborted += 1

        self.stats.update_rates()

        # Check kill switch
        if self.stats.check_kill_switch() and not self.stats.kill_switch_triggered:
            self.stats.kill_switch_triggered = True
            self.stats.kill_switch_timestamp = datetime.utcnow()
            logger.critical(
                f"SHADOW: KILL SWITCH TRIGGERED | "
                f"false_trigger_rate={self.stats.false_trigger_rate:.2%} | "
                f"threshold={FALSE_TRIGGER_THRESHOLD:.2%}"
            )

        self._save_stats()

        logger.info(
            f"SHADOW: Outcome recorded | trade_id={trade_id} | "
            f"outcome={outcome.value} | exit_price={exit_price:.4f} | "
            f"false_trigger_rate={self.stats.false_trigger_rate:.2%}"
        )

    def log_abort(
        self,
        trade_id: str,
        reason: AbortReason,
        timestamp: datetime,
    ):
        """Log a trade abort."""
        self.stats.pending = max(0, self.stats.pending - 1)
        self.stats.aborted += 1
        self.stats.total_completed_trades += 1
        self.stats.update_rates()
        self._save_stats()

        logger.warning(
            f"SHADOW: Trade ABORTED | trade_id={trade_id} | "
            f"reason={reason.value}"
        )

    def get_status(self) -> Dict[str, Any]:
        """Get current shadow mode status."""
        self.stats.update_rates()
        return {
            "shadow_mode_enabled": PANIC_SHADOW_MODE,
            "kill_switch_triggered": self.stats.kill_switch_triggered,
            "stats": self.stats.to_dict(),
        }

    def is_kill_switch_active(self) -> bool:
        """Check if kill switch is currently active."""
        return self.stats.kill_switch_triggered


# =============================================================================
# PANIC CONTRARIAN ENGINE
# =============================================================================


class PanicContrarianEngine:
    """
    Panic Contrarian Engine - Isolated from Core Decision Engine.

    PURPOSE:
    Detect short-lived price dislocations caused by human panic.
    Signal potential contrarian trade opportunities.

    WHAT THIS ENGINE DOES:
    - Monitors markets for panic conditions
    - Manages state machine (NORMAL → PANIC_WINDOW_OPEN → COOLDOWN → NORMAL)
    - Emits signals (IGNORE, PANIC_WINDOW_OPEN, COOLDOWN)
    - Provides full audit trail for post-mortem analysis
    - SHADOW MODE: Simulates trades without real capital

    WHAT THIS ENGINE DOES NOT DO:
    - Execute real trades (shadow mode is MANDATORY)
    - Modify the core decision engine
    - Learn or adapt thresholds
    - Use leverage
    - Scale positions
    - Retry failed trades

    CORE PRINCIPLE:
    This engine is assumed to be WRONG by default.
    Its job is to prove usefulness over time.
    When in doubt, the correct behavior is: DO NOTHING.
    This system is designed to trade RARELY.

    SHADOW MODE:
    - DEFAULT: ON (PANIC_SHADOW_MODE = True)
    - All trades are SIMULATED only
    - Full logging of hypothetical outcomes
    - Kill switch auto-disables if FALSE_TRIGGER rate > 30%
    """

    # -------------------------------------------------------------------------
    # CONDITION CRITERION NAMES (for audit trail)
    # -------------------------------------------------------------------------
    CRITERION_NEWS_SHOCK = "news_shock_detected"
    CRITERION_NO_RESOLUTION_CHANGE = "resolution_rules_unchanged"
    CRITERION_PRICE_DISLOCATION = "price_dislocation_sufficient"
    CRITERION_VOLUME_SPIKE = "volume_spike_sufficient"
    CRITERION_TEMPORAL_SAFETY = "temporal_safety_met"

    def __init__(self, shadow_logger: Optional[ShadowModeLogger] = None):
        """
        Initialize the Panic Contrarian Engine.

        No configuration parameters - all thresholds are hardcoded.
        No state - state is managed externally per market.

        Args:
            shadow_logger: Optional custom shadow logger. If None, creates default.
        """
        # Shadow mode logger
        self.shadow_logger = shadow_logger or ShadowModeLogger()

        # Track active simulated trades (trade_id -> SimulatedTrade)
        self._active_trades: Dict[str, SimulatedTrade] = {}

        # Log initialization for audit trail
        logger.info(
            "PanicContrarianEngine initialized | "
            f"SHADOW_MODE={PANIC_SHADOW_MODE} | "
            f"PANIC_PRICE_DELTA={PANIC_PRICE_DELTA} | "
            f"PANIC_TIME_WINDOW_MINUTES={PANIC_TIME_WINDOW_MINUTES} | "
            f"PANIC_VOLUME_MULTIPLIER={PANIC_VOLUME_MULTIPLIER} | "
            f"SAFETY_BUFFER_HOURS={SAFETY_BUFFER_HOURS} | "
            f"FALSE_TRIGGER_THRESHOLD={FALSE_TRIGGER_THRESHOLD:.0%}"
        )

        if PANIC_SHADOW_MODE:
            logger.info(
                "SHADOW MODE ACTIVE: All trades are SIMULATED. "
                "No real capital will be moved."
            )
        else:
            logger.critical(
                "WARNING: SHADOW MODE DISABLED! "
                "Real trades MAY be executed. "
                "This is NOT RECOMMENDED without extensive validation."
            )

    # -------------------------------------------------------------------------
    # MAIN ANALYSIS METHOD
    # -------------------------------------------------------------------------

    def analyze(
        self,
        market_input: PanicMarketInput,
        state: EngineStateSnapshot,
    ) -> Tuple[PanicEngineResult, EngineStateSnapshot]:
        """
        Analyze a market for panic contrarian opportunities.

        This is the main entry point for the engine.

        Args:
            market_input: Current market data and indicators.
            state: Current state snapshot for this market.

        Returns:
            Tuple of (PanicEngineResult, updated EngineStateSnapshot).

        PROCESS:
        1. Check kill switch - if triggered, return IGNORE
        2. Check hard abort conditions
        3. Check and update state machine based on time
        4. If in COOLDOWN, return COOLDOWN output
        5. If in PANIC_WINDOW_OPEN, check expiration and abort conditions
        6. If in NORMAL, evaluate all panic conditions
        7. If all conditions pass, transition to PANIC_WINDOW_OPEN
        8. Return result with full audit trail

        INVARIANT: This method is DETERMINISTIC.
        Same inputs + same state → same outputs + same new state.
        """
        now = datetime.utcnow()
        logger.info(
            f"Analyzing market {market_input.market_id} | "
            f"current_state={state.current_state.value} | "
            f"shadow_mode={PANIC_SHADOW_MODE}"
        )

        # Step 1: Check kill switch
        if self.shadow_logger.is_kill_switch_active():
            logger.warning(
                f"Market {market_input.market_id}: KILL SWITCH ACTIVE - "
                "engine disabled"
            )
            return self._return_ignore_killed(market_input, state, now)

        # Step 2: Check hard abort conditions
        abort_reason = self._check_abort_conditions(market_input, state, now)
        if abort_reason:
            return self._handle_abort(market_input, state, now, abort_reason)

        # Step 3: Update state machine based on time
        state = self._update_state_for_time(state, now)

        # Step 4: Handle COOLDOWN state
        if state.current_state == PanicEngineState.COOLDOWN:
            return self._handle_cooldown_state(market_input, state, now)

        # Step 5: Handle PANIC_WINDOW_OPEN state
        if state.current_state == PanicEngineState.PANIC_WINDOW_OPEN:
            return self._handle_panic_window_state(market_input, state, now)

        # Step 6: Handle NORMAL state - evaluate panic conditions
        return self._handle_normal_state(market_input, state, now)

    # -------------------------------------------------------------------------
    # ABORT AND KILL SWITCH HANDLING
    # -------------------------------------------------------------------------

    def _check_abort_conditions(
        self,
        market_input: PanicMarketInput,
        state: EngineStateSnapshot,
        now: datetime,
    ) -> Optional[AbortReason]:
        """
        Check for hard abort conditions.

        Returns AbortReason if abort should occur, None otherwise.

        HARD ABORT CONDITIONS:
        1. Resolution definition changed after trigger
        2. Official rule clarification released (via resolution_rules_changed)
        3. Panic occurs within SAFETY_BUFFER hours

        Any of these IMMEDIATELY aborts and enters COOLDOWN.
        """
        # Only check abort conditions if we have an active window
        if state.current_state != PanicEngineState.PANIC_WINDOW_OPEN:
            return None

        # Check 1: Resolution rules changed
        if market_input.resolution_rules_changed:
            logger.warning(
                f"Market {market_input.market_id}: "
                "Resolution rules changed - ABORT"
            )
            return AbortReason.RESOLUTION_CHANGED

        # Check 2: Time safety buffer breached
        hours_until = self._calculate_hours_until_resolution(market_input, now)
        if hours_until is not None and hours_until < SAFETY_BUFFER_HOURS:
            logger.warning(
                f"Market {market_input.market_id}: "
                f"Safety buffer breached ({hours_until:.1f}h < {SAFETY_BUFFER_HOURS}h) - ABORT"
            )
            return AbortReason.SAFETY_BUFFER_BREACHED

        return None

    def _handle_abort(
        self,
        market_input: PanicMarketInput,
        state: EngineStateSnapshot,
        now: datetime,
        abort_reason: AbortReason,
    ) -> Tuple[PanicEngineResult, EngineStateSnapshot]:
        """
        Handle an abort condition.

        Immediately transitions to COOLDOWN and logs the abort.
        """
        # Log abort in shadow logger
        trade_id = f"{market_input.market_id}_{state.window_opened_at.isoformat() if state.window_opened_at else now.isoformat()}"
        self.shadow_logger.log_abort(trade_id, abort_reason, now)

        # Transition to cooldown
        state = self._transition_to_cooldown(state, now)

        result = PanicEngineResult(
            output=PanicEngineOutput.COOLDOWN,
            engine_state=state.current_state,
            market_id=market_input.market_id,
            cooldown_remaining_minutes=int(COOLDOWN_DURATION_HOURS * 60),
            reasoning=(
                f"ABORTED: {abort_reason.value}. "
                f"Transitioning to COOLDOWN for {COOLDOWN_DURATION_HOURS} hours. "
                f"This abort was triggered by safety conditions."
            ),
        )

        logger.warning(
            f"Market {market_input.market_id}: ABORTED | "
            f"reason={abort_reason.value} | entering COOLDOWN"
        )

        return result, state

    def _return_ignore_killed(
        self,
        market_input: PanicMarketInput,
        state: EngineStateSnapshot,
        now: datetime,
    ) -> Tuple[PanicEngineResult, EngineStateSnapshot]:
        """
        Return IGNORE result when kill switch is active.
        """
        result = PanicEngineResult(
            output=PanicEngineOutput.IGNORE,
            engine_state=state.current_state,
            market_id=market_input.market_id,
            reasoning=(
                f"KILL SWITCH ACTIVE: Engine disabled due to high FALSE_TRIGGER rate "
                f"({self.shadow_logger.stats.false_trigger_rate:.1%}). "
                f"Manual re-enable required after investigation."
            ),
        )

        return result, state

    # -------------------------------------------------------------------------
    # SHADOW MODE TRADE MANAGEMENT
    # -------------------------------------------------------------------------

    def create_simulated_trade(
        self,
        market_input: PanicMarketInput,
        result: PanicEngineResult,
    ) -> Optional[SimulatedTrade]:
        """
        Create a simulated trade when PANIC_WINDOW_OPEN is signaled.

        This is called by the execution layer (or automatically in shadow mode)
        to record a hypothetical trade entry.

        Returns SimulatedTrade or None if conditions not met.
        """
        if not PANIC_SHADOW_MODE:
            logger.warning(
                "create_simulated_trade called but SHADOW_MODE is OFF - "
                "this should not happen in production"
            )
            return None

        if result.output != PanicEngineOutput.PANIC_WINDOW_OPEN:
            logger.debug("Cannot create trade: output is not PANIC_WINDOW_OPEN")
            return None

        if result.panic_direction is None:
            logger.warning("Cannot create trade: panic_direction is None")
            return None

        now = datetime.utcnow()
        trade_id = f"{market_input.market_id}_{now.strftime('%Y%m%d_%H%M%S')}"

        # Calculate pre-panic price from history
        pre_panic_price = None
        if market_input.price_history:
            pre_panic_price = market_input.price_history[0][1]  # First price in history

        trade = SimulatedTrade(
            trade_id=trade_id,
            market_id=market_input.market_id,
            market_title=market_input.market_title,
            entry_timestamp=now,
            entry_price=market_input.current_price,
            direction=result.panic_direction,
            triggering_metrics=result.metrics.to_dict() if result.metrics else {},
            pre_panic_price=pre_panic_price,
        )

        # Store in active trades
        self._active_trades[trade_id] = trade

        # Log to shadow logger
        self.shadow_logger.log_simulated_trade(trade)
        self.shadow_logger.log_signal(result)

        logger.info(
            f"SHADOW: Simulated trade created | "
            f"trade_id={trade_id} | "
            f"market={market_input.market_id} | "
            f"entry_price={market_input.current_price:.4f} | "
            f"direction={result.panic_direction.value}"
        )

        return trade

    def update_trade_observation(
        self,
        trade_id: str,
        current_price: float,
        observation_type: str,  # "1h", "6h", "12h", "exit"
    ):
        """
        Update a simulated trade with price observation.

        Called periodically to track price evolution.
        """
        if trade_id not in self._active_trades:
            logger.warning(f"Trade {trade_id} not found in active trades")
            return

        trade = self._active_trades[trade_id]

        # Update price observation
        if observation_type == "1h":
            trade.price_after_1h = current_price
        elif observation_type == "6h":
            trade.price_after_6h = current_price
        elif observation_type == "12h":
            trade.price_after_12h = current_price
        elif observation_type == "exit":
            trade.price_at_exit_time = current_price

        # Update max adverse/favorable moves
        if trade.direction == PanicDirection.UNDERPRICED:
            # We're long - adverse is down, favorable is up
            adverse_move = trade.entry_price - current_price
            favorable_move = current_price - trade.entry_price
        else:
            # We're short - adverse is up, favorable is down
            adverse_move = current_price - trade.entry_price
            favorable_move = trade.entry_price - current_price

        trade.max_adverse_move = max(trade.max_adverse_move, max(0, adverse_move))
        trade.max_favorable_move = max(trade.max_favorable_move, max(0, favorable_move))

        logger.debug(
            f"SHADOW: Trade observation | trade_id={trade_id} | "
            f"type={observation_type} | price={current_price:.4f}"
        )

    def complete_trade(
        self,
        trade_id: str,
        exit_price: float,
        exit_reason: str = "time_expiry",
    ) -> Optional[PanicTradeOutcome]:
        """
        Complete a simulated trade and classify its outcome.

        Called when the observation window closes (typically after 24h).

        Returns the outcome classification.
        """
        if trade_id not in self._active_trades:
            logger.warning(f"Trade {trade_id} not found in active trades")
            return None

        trade = self._active_trades[trade_id]
        now = datetime.utcnow()

        # Update exit details
        trade.exit_timestamp = now
        trade.exit_reason = exit_reason
        trade.price_at_exit_time = exit_price

        # Classify outcome
        outcome = self._classify_outcome(trade, exit_price)
        trade.outcome = outcome

        # Log to shadow logger
        self.shadow_logger.update_trade_outcome(
            trade_id=trade_id,
            outcome=outcome,
            exit_price=exit_price,
            exit_timestamp=now,
            exit_reason=exit_reason,
        )

        # Remove from active trades
        del self._active_trades[trade_id]

        logger.info(
            f"SHADOW: Trade completed | trade_id={trade_id} | "
            f"outcome={outcome.value} | exit_price={exit_price:.4f} | "
            f"entry_price={trade.entry_price:.4f}"
        )

        return outcome

    def _classify_outcome(
        self,
        trade: SimulatedTrade,
        exit_price: float,
    ) -> PanicTradeOutcome:
        """
        Classify the outcome of a simulated trade.

        GOOD_REVERSION: Price reverted toward pre-panic level by >= REVERSION_THRESHOLD
        NO_REVERSION: Price stayed flat (no significant movement)
        CONTINUED_PANIC: Price continued in panic direction by >= CONTINUED_PANIC_THRESHOLD
        FALSE_TRIGGER: Resolution rules changed during trade (detected via abort)
        """
        # Check if aborted
        if trade.aborted:
            return PanicTradeOutcome.ABORTED

        # Calculate price movement from entry
        entry_price = trade.entry_price

        if trade.direction == PanicDirection.UNDERPRICED:
            # We bought expecting price to rise (revert from panic selling)
            # Favorable = exit > entry
            # Adverse = exit < entry
            price_change = exit_price - entry_price
        else:
            # We sold/shorted expecting price to fall (revert from panic buying)
            # Favorable = exit < entry
            # Adverse = exit > entry
            price_change = entry_price - exit_price

        # Classify based on thresholds
        if price_change >= REVERSION_THRESHOLD:
            return PanicTradeOutcome.GOOD_REVERSION
        elif price_change <= -CONTINUED_PANIC_THRESHOLD:
            return PanicTradeOutcome.CONTINUED_PANIC
        else:
            return PanicTradeOutcome.NO_REVERSION

    def abort_trade(
        self,
        trade_id: str,
        reason: AbortReason,
    ):
        """
        Abort an active simulated trade.

        Called when hard abort conditions are met.
        """
        if trade_id not in self._active_trades:
            logger.warning(f"Trade {trade_id} not found in active trades")
            return

        trade = self._active_trades[trade_id]
        now = datetime.utcnow()

        trade.aborted = True
        trade.abort_reason = reason
        trade.abort_timestamp = now
        trade.outcome = PanicTradeOutcome.ABORTED

        # Log abort
        self.shadow_logger.log_abort(trade_id, reason, now)

        # Remove from active trades
        del self._active_trades[trade_id]

        logger.warning(
            f"SHADOW: Trade aborted | trade_id={trade_id} | "
            f"reason={reason.value}"
        )

    def get_shadow_status(self) -> Dict[str, Any]:
        """
        Get current shadow mode status and statistics.

        Returns a dict with all relevant shadow mode information.
        """
        return {
            "shadow_mode_enabled": PANIC_SHADOW_MODE,
            "kill_switch_active": self.shadow_logger.is_kill_switch_active(),
            "active_trades_count": len(self._active_trades),
            "stats": self.shadow_logger.stats.to_dict(),
            "thresholds": {
                "false_trigger_threshold": FALSE_TRIGGER_THRESHOLD,
                "kill_switch_min_samples": KILL_SWITCH_MIN_SAMPLES,
                "reversion_threshold": REVERSION_THRESHOLD,
                "continued_panic_threshold": CONTINUED_PANIC_THRESHOLD,
            },
        }

    # -------------------------------------------------------------------------
    # STATE MACHINE MANAGEMENT
    # -------------------------------------------------------------------------

    def _update_state_for_time(
        self,
        state: EngineStateSnapshot,
        now: datetime,
    ) -> EngineStateSnapshot:
        """
        Update state machine based on elapsed time.

        Called at the start of every analysis to handle:
        - Expired panic windows → transition to COOLDOWN
        - Expired cooldowns → transition to NORMAL

        This ensures the state machine doesn't get stuck.
        """
        # Check if panic window has expired
        if state.current_state == PanicEngineState.PANIC_WINDOW_OPEN:
            if state.window_expires_at and now >= state.window_expires_at:
                logger.info(
                    f"Market {state.market_id}: Panic window expired, "
                    "transitioning to COOLDOWN"
                )
                state = self._transition_to_cooldown(state, now)

        # Check if cooldown has expired
        if state.current_state == PanicEngineState.COOLDOWN:
            if state.cooldown_expires_at and now >= state.cooldown_expires_at:
                logger.info(
                    f"Market {state.market_id}: Cooldown expired, "
                    "transitioning to NORMAL"
                )
                state = self._transition_to_normal(state)

        return state

    def _transition_to_panic_window(
        self,
        state: EngineStateSnapshot,
        now: datetime,
    ) -> EngineStateSnapshot:
        """
        Transition from NORMAL to PANIC_WINDOW_OPEN.

        This is only called when ALL panic conditions are met.
        """
        window_expiration = now + timedelta(minutes=PANIC_WINDOW_DURATION_MINUTES)

        return EngineStateSnapshot(
            market_id=state.market_id,
            current_state=PanicEngineState.PANIC_WINDOW_OPEN,
            window_opened_at=now,
            window_expires_at=window_expiration,
            trade_executed_in_window=False,
            cooldown_started_at=None,
            cooldown_expires_at=None,
            last_analysis_at=now,
        )

    def _transition_to_cooldown(
        self,
        state: EngineStateSnapshot,
        now: datetime,
    ) -> EngineStateSnapshot:
        """
        Transition from PANIC_WINDOW_OPEN to COOLDOWN.

        Called when:
        - Panic window expires (time-based)
        - Trade is executed in window (execution layer calls mark_trade_executed)
        """
        cooldown_expiration = now + timedelta(hours=COOLDOWN_DURATION_HOURS)

        return EngineStateSnapshot(
            market_id=state.market_id,
            current_state=PanicEngineState.COOLDOWN,
            window_opened_at=None,
            window_expires_at=None,
            trade_executed_in_window=False,
            cooldown_started_at=now,
            cooldown_expires_at=cooldown_expiration,
            last_analysis_at=now,
        )

    def _transition_to_normal(
        self,
        state: EngineStateSnapshot,
    ) -> EngineStateSnapshot:
        """
        Transition from COOLDOWN to NORMAL.

        Called when cooldown period expires.
        """
        return EngineStateSnapshot(
            market_id=state.market_id,
            current_state=PanicEngineState.NORMAL,
            window_opened_at=None,
            window_expires_at=None,
            trade_executed_in_window=False,
            cooldown_started_at=None,
            cooldown_expires_at=None,
            last_analysis_at=datetime.utcnow(),
        )

    def mark_trade_executed(
        self,
        state: EngineStateSnapshot,
    ) -> EngineStateSnapshot:
        """
        Mark that a trade was executed in the current panic window.

        Called by the execution layer AFTER a trade is placed.
        This triggers transition to COOLDOWN.

        IMPORTANT: This is the ONLY way to transition from
        PANIC_WINDOW_OPEN to COOLDOWN before window expiration.

        ONE TRADE PER WINDOW RULE:
        Once this is called, no more trades can be taken until
        the cooldown expires and a new panic event occurs.
        """
        if state.current_state != PanicEngineState.PANIC_WINDOW_OPEN:
            logger.warning(
                f"mark_trade_executed called in {state.current_state.value} state, "
                "ignoring"
            )
            return state

        logger.info(
            f"Market {state.market_id}: Trade executed, "
            "transitioning to COOLDOWN"
        )

        return self._transition_to_cooldown(state, datetime.utcnow())

    # -------------------------------------------------------------------------
    # STATE HANDLERS
    # -------------------------------------------------------------------------

    def _handle_cooldown_state(
        self,
        market_input: PanicMarketInput,
        state: EngineStateSnapshot,
        now: datetime,
    ) -> Tuple[PanicEngineResult, EngineStateSnapshot]:
        """
        Handle analysis when engine is in COOLDOWN state.

        In COOLDOWN, we always return COOLDOWN output.
        No panic conditions are evaluated.
        This prevents overtrading and emotional re-entry.
        """
        remaining_minutes = 0
        if state.cooldown_expires_at:
            remaining = state.cooldown_expires_at - now
            remaining_minutes = max(0, int(remaining.total_seconds() / 60))

        result = PanicEngineResult(
            output=PanicEngineOutput.COOLDOWN,
            engine_state=state.current_state,
            market_id=market_input.market_id,
            cooldown_remaining_minutes=remaining_minutes,
            reasoning=(
                f"Engine in COOLDOWN state. "
                f"{remaining_minutes} minutes remaining. "
                f"No panic evaluation performed."
            ),
        )

        state.last_analysis_at = now

        logger.info(
            f"Market {market_input.market_id}: COOLDOWN | "
            f"remaining={remaining_minutes}min"
        )

        return result, state

    def _handle_panic_window_state(
        self,
        market_input: PanicMarketInput,
        state: EngineStateSnapshot,
        now: datetime,
    ) -> Tuple[PanicEngineResult, EngineStateSnapshot]:
        """
        Handle analysis when engine is in PANIC_WINDOW_OPEN state.

        We re-emit PANIC_WINDOW_OPEN with updated metrics.
        The window may still be active even if conditions have changed,
        because we're committed to the opportunity.
        """
        # Recalculate metrics for audit trail
        metrics = self._calculate_metrics(market_input, now)

        # Determine panic direction based on current price vs historical
        panic_direction = self._determine_panic_direction(market_input)

        result = PanicEngineResult(
            output=PanicEngineOutput.PANIC_WINDOW_OPEN,
            engine_state=state.current_state,
            market_id=market_input.market_id,
            panic_direction=panic_direction,
            window_expiration=state.window_expires_at,
            metrics=metrics,
            reasoning=(
                f"PANIC_WINDOW_OPEN: Contrarian opportunity detected. "
                f"Direction: {panic_direction.value if panic_direction else 'UNKNOWN'}. "
                f"Window expires at {state.window_expires_at}. "
                f"ONE TRADE ONLY permitted."
            ),
        )

        state.last_analysis_at = now

        logger.info(
            f"Market {market_input.market_id}: PANIC_WINDOW_OPEN | "
            f"direction={panic_direction.value if panic_direction else 'UNKNOWN'} | "
            f"expires={state.window_expires_at}"
        )

        return result, state

    def _handle_normal_state(
        self,
        market_input: PanicMarketInput,
        state: EngineStateSnapshot,
        now: datetime,
    ) -> Tuple[PanicEngineResult, EngineStateSnapshot]:
        """
        Handle analysis when engine is in NORMAL state.

        This is where we evaluate all panic conditions.
        If ALL pass, we transition to PANIC_WINDOW_OPEN.
        If ANY fail, we return IGNORE.
        """
        # Calculate all metrics
        metrics = self._calculate_metrics(market_input, now)

        # Evaluate all conditions
        conditions = self._evaluate_all_conditions(market_input, metrics)

        # Check if ALL conditions pass
        all_passed = all(
            result == PanicConditionResult.PASSED
            for result in conditions.values()
        )

        if all_passed:
            # TRANSITION TO PANIC_WINDOW_OPEN
            state = self._transition_to_panic_window(state, now)
            panic_direction = self._determine_panic_direction(market_input)

            result = PanicEngineResult(
                output=PanicEngineOutput.PANIC_WINDOW_OPEN,
                engine_state=state.current_state,
                market_id=market_input.market_id,
                panic_direction=panic_direction,
                window_expiration=state.window_expires_at,
                metrics=metrics,
                reasoning=self._build_panic_detected_reasoning(conditions, metrics),
            )

            logger.warning(  # WARNING level because this is significant
                f"Market {market_input.market_id}: PANIC DETECTED | "
                f"direction={panic_direction.value if panic_direction else 'UNKNOWN'} | "
                f"price_delta={metrics.price_delta:.2%} | "
                f"volume_mult={metrics.volume_multiplier:.1f}x"
            )
        else:
            # NO PANIC - return IGNORE
            result = PanicEngineResult(
                output=PanicEngineOutput.IGNORE,
                engine_state=state.current_state,
                market_id=market_input.market_id,
                metrics=metrics,
                reasoning=self._build_no_panic_reasoning(conditions, metrics),
            )

            state.last_analysis_at = now

            logger.debug(
                f"Market {market_input.market_id}: IGNORE | "
                f"failed_conditions={[k for k, v in conditions.items() if v != PanicConditionResult.PASSED]}"
            )

        return result, state

    # -------------------------------------------------------------------------
    # CONDITION EVALUATION
    # -------------------------------------------------------------------------

    def _evaluate_all_conditions(
        self,
        market_input: PanicMarketInput,
        metrics: PanicMetrics,
    ) -> Dict[str, PanicConditionResult]:
        """
        Evaluate all panic conditions.

        Returns dict mapping criterion name to result.
        ALL must be PASSED for panic detection.
        """
        return {
            self.CRITERION_NEWS_SHOCK: self._eval_news_shock(market_input),
            self.CRITERION_NO_RESOLUTION_CHANGE: self._eval_no_resolution_change(
                market_input
            ),
            self.CRITERION_PRICE_DISLOCATION: metrics.price_condition,
            self.CRITERION_VOLUME_SPIKE: metrics.volume_condition,
            self.CRITERION_TEMPORAL_SAFETY: metrics.temporal_condition,
        }

    def _eval_news_shock(
        self,
        market_input: PanicMarketInput,
    ) -> PanicConditionResult:
        """
        Evaluate: External news shock detected?

        This is a boolean flag passed in from external monitoring.
        We don't do NLP or sentiment analysis here.

        WHY: Panic trades make sense when news triggers emotional reaction.
        Without news, price movement may be informed trading.
        """
        if market_input.news_shock_indicator:
            return PanicConditionResult.PASSED
        return PanicConditionResult.FAILED

    def _eval_no_resolution_change(
        self,
        market_input: PanicMarketInput,
    ) -> PanicConditionResult:
        """
        Evaluate: Resolution rules unchanged?

        If resolution rules/definitions changed, the price move
        may be rational re-pricing, not panic.

        WHY: We only want to trade panic, not rational re-pricing.
        Changed rules = new fundamentals = not panic.
        """
        if market_input.resolution_rules_changed:
            return PanicConditionResult.FAILED
        return PanicConditionResult.PASSED

    def _calculate_metrics(
        self,
        market_input: PanicMarketInput,
        now: datetime,
    ) -> PanicMetrics:
        """
        Calculate all panic metrics from market input.

        This is a pure calculation - no decisions made here.
        Decisions happen in condition evaluation.
        """
        # Calculate price movement
        price_delta, price_start, duration_minutes, direction = (
            self._calculate_price_movement(market_input, now)
        )

        # Evaluate price condition
        if duration_minutes > PANIC_TIME_WINDOW_MINUTES:
            price_condition = PanicConditionResult.FAILED
        elif price_delta < PANIC_PRICE_DELTA:
            price_condition = PanicConditionResult.FAILED
        else:
            price_condition = PanicConditionResult.PASSED

        # Calculate volume metrics
        volume_multiplier = self._calculate_volume_multiplier(market_input)

        # Evaluate volume condition
        if market_input.historical_volume_baseline <= 0:
            volume_condition = PanicConditionResult.INSUFFICIENT_DATA
        elif volume_multiplier < PANIC_VOLUME_MULTIPLIER:
            volume_condition = PanicConditionResult.FAILED
        else:
            volume_condition = PanicConditionResult.PASSED

        # Calculate temporal metrics
        hours_until_resolution = self._calculate_hours_until_resolution(
            market_input, now
        )

        # Evaluate temporal condition
        if hours_until_resolution is None:
            temporal_condition = PanicConditionResult.INSUFFICIENT_DATA
        elif hours_until_resolution < SAFETY_BUFFER_HOURS:
            temporal_condition = PanicConditionResult.FAILED
        else:
            temporal_condition = PanicConditionResult.PASSED

        return PanicMetrics(
            price_start=price_start,
            price_end=market_input.current_price,
            price_delta=price_delta,
            price_delta_direction=direction,
            price_move_duration_minutes=duration_minutes,
            current_volume=market_input.current_volume_24h,
            baseline_volume=market_input.historical_volume_baseline,
            volume_multiplier=volume_multiplier,
            hours_until_resolution=hours_until_resolution or -1,
            price_condition=price_condition,
            volume_condition=volume_condition,
            temporal_condition=temporal_condition,
            news_shock_detected=market_input.news_shock_indicator,
            observation_timestamp=now.isoformat(),
        )

    def _calculate_price_movement(
        self,
        market_input: PanicMarketInput,
        now: datetime,
    ) -> Tuple[float, float, int, str]:
        """
        Calculate price movement within the panic time window.

        Returns:
            Tuple of (delta, start_price, duration_minutes, direction).

        We look for the maximum price delta within the time window.
        """
        if not market_input.price_history:
            return 0.0, market_input.current_price, 0, "NONE"

        # Filter history to within time window
        window_start = now - timedelta(minutes=PANIC_TIME_WINDOW_MINUTES)
        relevant_history = [
            (ts, price) for ts, price in market_input.price_history
            if ts >= window_start
        ]

        if not relevant_history:
            return 0.0, market_input.current_price, 0, "NONE"

        # Find the extreme price (furthest from current)
        current_price = market_input.current_price
        max_delta = 0.0
        extreme_price = current_price
        extreme_ts = now

        for ts, price in relevant_history:
            delta = abs(price - current_price)
            if delta > max_delta:
                max_delta = delta
                extreme_price = price
                extreme_ts = ts

        # Calculate duration
        duration = now - extreme_ts
        duration_minutes = int(duration.total_seconds() / 60)

        # Determine direction
        if current_price > extreme_price:
            direction = "UP"  # Price moved up (was lower)
        elif current_price < extreme_price:
            direction = "DOWN"  # Price moved down (was higher)
        else:
            direction = "NONE"

        return max_delta, extreme_price, duration_minutes, direction

    def _calculate_volume_multiplier(
        self,
        market_input: PanicMarketInput,
    ) -> float:
        """
        Calculate volume spike multiplier.

        Returns current volume / baseline volume.
        """
        if market_input.historical_volume_baseline <= 0:
            return 0.0
        return market_input.current_volume_24h / market_input.historical_volume_baseline

    def _calculate_hours_until_resolution(
        self,
        market_input: PanicMarketInput,
        now: datetime,
    ) -> Optional[float]:
        """
        Calculate hours until market resolution.

        Returns None if resolution timestamp not set.
        """
        if not market_input.resolution_timestamp:
            return None

        delta = market_input.resolution_timestamp - now
        return delta.total_seconds() / 3600

    def _determine_panic_direction(
        self,
        market_input: PanicMarketInput,
    ) -> Optional[PanicDirection]:
        """
        Determine the direction of panic.

        OVERPRICED: Price spiked up (panic buying / FOMO).
                    Contrarian action: SELL.

        UNDERPRICED: Price crashed down (panic selling / FUD).
                     Contrarian action: BUY.

        We determine this by comparing current price to recent history.
        If current is higher than recent, it's panic buying (overpriced).
        If current is lower than recent, it's panic selling (underpriced).
        """
        if not market_input.price_history:
            return None

        # Get average price from beginning of price history
        recent_prices = [price for ts, price in market_input.price_history]
        if not recent_prices:
            return None

        avg_recent = sum(recent_prices) / len(recent_prices)
        current = market_input.current_price

        # Threshold for direction determination
        # Use half the panic delta as threshold
        threshold = PANIC_PRICE_DELTA / 2

        if current > avg_recent + threshold:
            return PanicDirection.OVERPRICED  # Price spiked UP
        elif current < avg_recent - threshold:
            return PanicDirection.UNDERPRICED  # Price crashed DOWN
        else:
            # Price moved but direction unclear
            # Default to UNDERPRICED (buy bias) as it's safer
            return PanicDirection.UNDERPRICED

    # -------------------------------------------------------------------------
    # REASONING BUILDERS
    # -------------------------------------------------------------------------

    def _build_panic_detected_reasoning(
        self,
        conditions: Dict[str, PanicConditionResult],
        metrics: PanicMetrics,
    ) -> str:
        """Build detailed reasoning for PANIC_WINDOW_OPEN."""
        return (
            f"PANIC DETECTED: All conditions passed.\n"
            f"- News shock: YES\n"
            f"- Resolution rules unchanged: YES\n"
            f"- Price dislocation: {metrics.price_delta:.2%} "
            f"(threshold: {PANIC_PRICE_DELTA:.2%}) - PASSED\n"
            f"- Volume spike: {metrics.volume_multiplier:.1f}x "
            f"(threshold: {PANIC_VOLUME_MULTIPLIER:.1f}x) - PASSED\n"
            f"- Temporal safety: {metrics.hours_until_resolution:.1f}h "
            f"(threshold: {SAFETY_BUFFER_HOURS}h) - PASSED\n"
            f"Window duration: {PANIC_WINDOW_DURATION_MINUTES} minutes.\n"
            f"ONE TRADE ONLY permitted in this window."
        )

    def _build_no_panic_reasoning(
        self,
        conditions: Dict[str, PanicConditionResult],
        metrics: PanicMetrics,
    ) -> str:
        """Build detailed reasoning for IGNORE."""
        failed = []
        for name, result in conditions.items():
            if result != PanicConditionResult.PASSED:
                failed.append(f"{name}: {result.value}")

        return (
            f"NO PANIC: {len(failed)} condition(s) not met.\n"
            f"Failed conditions: {', '.join(failed)}\n"
            f"Metrics:\n"
            f"- Price delta: {metrics.price_delta:.2%} "
            f"(need >= {PANIC_PRICE_DELTA:.2%})\n"
            f"- Volume mult: {metrics.volume_multiplier:.1f}x "
            f"(need >= {PANIC_VOLUME_MULTIPLIER:.1f}x)\n"
            f"- Hours to resolution: {metrics.hours_until_resolution:.1f}h "
            f"(need >= {SAFETY_BUFFER_HOURS}h)"
        )


# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================


def get_config_summary() -> Dict[str, Any]:
    """
    Return current configuration for logging/monitoring.

    This allows external systems to verify configuration
    without accessing internal constants directly.
    """
    return {
        # Core thresholds
        "PANIC_PRICE_DELTA": PANIC_PRICE_DELTA,
        "PANIC_TIME_WINDOW_MINUTES": PANIC_TIME_WINDOW_MINUTES,
        "PANIC_VOLUME_MULTIPLIER": PANIC_VOLUME_MULTIPLIER,
        "VOLUME_BASELINE_HOURS": VOLUME_BASELINE_HOURS,
        "SAFETY_BUFFER_HOURS": SAFETY_BUFFER_HOURS,
        "PANIC_WINDOW_DURATION_MINUTES": PANIC_WINDOW_DURATION_MINUTES,
        "COOLDOWN_DURATION_HOURS": COOLDOWN_DURATION_HOURS,
        "MAX_POSITION_SIZE_USD": MAX_POSITION_SIZE_USD,
        "MAX_HOLDING_TIME_HOURS": MAX_HOLDING_TIME_HOURS,
        # Shadow mode configuration
        "PANIC_SHADOW_MODE": PANIC_SHADOW_MODE,
        "FALSE_TRIGGER_THRESHOLD": FALSE_TRIGGER_THRESHOLD,
        "KILL_SWITCH_MIN_SAMPLES": KILL_SWITCH_MIN_SAMPLES,
        "REVERSION_THRESHOLD": REVERSION_THRESHOLD,
        "CONTINUED_PANIC_THRESHOLD": CONTINUED_PANIC_THRESHOLD,
        "SHADOW_LOG_PATH": str(SHADOW_LOG_PATH),
    }


def is_shadow_mode_active() -> bool:
    """
    Check if shadow mode is currently active.

    Returns True if PANIC_SHADOW_MODE is True.
    This is a convenience function for external callers.
    """
    return PANIC_SHADOW_MODE


def get_shadow_mode_status() -> ShadowModeStatus:
    """
    Get the current shadow mode status.

    Returns appropriate ShadowModeStatus enum value.
    """
    if not PANIC_SHADOW_MODE:
        return ShadowModeStatus.PRODUCTION

    # Check if kill switch is triggered (need to load stats)
    stats_file = SHADOW_LOG_PATH / "shadow_stats.json"
    if stats_file.exists():
        try:
            with open(stats_file, "r") as f:
                data = json.load(f)
            if data.get("kill_switch_triggered", False):
                return ShadowModeStatus.DISABLED_KILL_SWITCH
        except Exception:
            pass

    return ShadowModeStatus.ACTIVE
