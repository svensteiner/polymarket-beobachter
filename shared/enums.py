# =============================================================================
# POLYMARKET BEOBACHTER - SHARED ENUMS
# =============================================================================
#
# GOVERNANCE:
# These enums define the shared vocabulary across the system.
# They encode the governance model at the type level.
#
# LAYER ENUM:
# Explicitly encodes the two-layer architecture.
# Used by layer_guard.py to enforce isolation.
#
# =============================================================================

from enum import Enum, auto


class Layer(Enum):
    """
    System architecture layers.

    LAYER1: Institutional/Process Edge (Core Analyzer)
            - Deterministic
            - No prices, volumes, probabilities
            - FINAL decision authority

    LAYER2: Microstructure/Execution Research
            - READ-ONLY research
            - NO decision authority
            - NO capital allocation
    """
    LAYER1_INSTITUTIONAL = "LAYER1_INSTITUTIONAL"
    LAYER2_MICROSTRUCTURE = "LAYER2_MICROSTRUCTURE"


class DecisionOutcome(Enum):
    """
    Final trading decision outcome from Layer 1.

    TRADE: All criteria met, market is structurally tradeable.
    NO_TRADE: One or more criteria failed, do not trade.
    INSUFFICIENT_DATA: Not enough information to make a determination.

    AUDIT NOTE: There is no "MAYBE" - fail closed by design.
    INSUFFICIENT_DATA is used when input data is incomplete or ambiguous,
    distinct from NO_TRADE which indicates a clear rejection.
    """
    TRADE = "TRADE"
    NO_TRADE = "NO_TRADE"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class ConfidenceLevel(Enum):
    """Confidence level for probability estimates and decisions."""
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class MarketDirection(Enum):
    """
    Direction of market mispricing.

    NOTE: This is used ONLY for reporting after a TRADE decision.
    It does NOT influence the tradeability decision.
    """
    MARKET_TOO_HIGH = "MARKET_TOO_HIGH"
    MARKET_TOO_LOW = "MARKET_TOO_LOW"
    ALIGNED = "ALIGNED"


class EURegulationStage(Enum):
    """
    Stages of the EU regulatory lifecycle.

    Based on the Ordinary Legislative Procedure (OLP) and post-adoption phases.
    Reference: Article 294 TFEU
    """
    PROPOSAL = "PROPOSAL"
    FIRST_READING_EP = "FIRST_READING_EP"
    FIRST_READING_COUNCIL = "FIRST_READING_COUNCIL"
    SECOND_READING_EP = "SECOND_READING_EP"
    SECOND_READING_COUNCIL = "SECOND_READING_COUNCIL"
    CONCILIATION = "CONCILIATION"
    ADOPTED = "ADOPTED"
    PUBLISHED_OJ = "PUBLISHED_OJ"
    ENTERED_INTO_FORCE = "ENTERED_INTO_FORCE"
    APPLICATION_DATE = "APPLICATION_DATE"
    TRANSITIONAL_PERIOD = "TRANSITIONAL_PERIOD"
    DELEGATED_ACTS_PENDING = "DELEGATED_ACTS_PENDING"
    IMPLEMENTING_ACTS_PENDING = "IMPLEMENTING_ACTS_PENDING"
    FULLY_APPLICABLE = "FULLY_APPLICABLE"


class OutcomeClassification(Enum):
    """
    Classification of analyzer decisions vs actual outcomes.

    Used in historical/counterfactual testing ONLY.

    CORRECT_REJECTION: Analyzer said NO_TRADE, outcome would have been loss - GOOD
    SAFE_PASS: Analyzer said TRADE, outcome would have been neutral/win - GOOD
    FALSE_ADMISSION: Analyzer said TRADE, outcome would have been loss - CRITICAL FAILURE
    RARE_SUCCESS: Analyzer said NO_TRADE, outcome would have been win - Acceptable miss
    """
    CORRECT_REJECTION = "CORRECT_REJECTION"
    SAFE_PASS = "SAFE_PASS"
    FALSE_ADMISSION = "FALSE_ADMISSION"
    RARE_SUCCESS = "RARE_SUCCESS"


class MarketCategory(Enum):
    """
    Categories of markets supported by the analyzer.

    Each category has specific validation requirements.

    EU_REGULATION: EU regulatory process markets
        - Requires institutional timeline analysis
        - References OJ, TFEU, etc.

    WEATHER_EVENT: Weather/climate measurement markets
        - Requires explicit measurement source
        - Requires objective metric definition
        - NO FORECASTING - structural validation only

    CORPORATE_EVENT: Corporate event markets (earnings, filings, etc.)
        - Requires company/ticker identification
        - Requires official source (SEC, exchange, IR)
        - NO EARNINGS PREDICTIONS - structural validation only

    COURT_RULING: Legal/court ruling markets
        - Requires specific court identification
        - Requires case number/docket reference
        - NO LEGAL PREDICTIONS - structural validation only

    GENERIC: Default category for unclassified markets
        - Basic resolution clarity checks only
    """
    EU_REGULATION = "EU_REGULATION"
    WEATHER_EVENT = "WEATHER_EVENT"
    CORPORATE_EVENT = "CORPORATE_EVENT"
    COURT_RULING = "COURT_RULING"
    GENERIC = "GENERIC"


class WeatherValidationResult(Enum):
    """
    Result of weather market validation checklist.

    VALID: All 6 checklist items passed
    INVALID_SOURCE: Measurement source not explicit/official
    INVALID_METRIC: Metric vague or subjective
    INVALID_LOCATION: Location ambiguous
    INVALID_TIMEZONE: Timezone not defined
    INVALID_CUTOFF: Cutoff time ambiguous
    INVALID_REPORTING: Publication lag makes resolution infeasible
    """
    VALID = "VALID"
    INVALID_SOURCE = "INVALID_SOURCE"
    INVALID_METRIC = "INVALID_METRIC"
    INVALID_LOCATION = "INVALID_LOCATION"
    INVALID_TIMEZONE = "INVALID_TIMEZONE"
    INVALID_CUTOFF = "INVALID_CUTOFF"
    INVALID_REPORTING = "INVALID_REPORTING"


# =============================================================================
# PANIC CONTRARIAN ENGINE ENUMS
# =============================================================================
#
# These enums are used EXCLUSIVELY by the panic_contrarian_engine module.
# They are isolated from the core decision engine by design.
#
# GOVERNANCE:
# - The Panic Contrarian Engine is a SEPARATE trading strategy
# - It does NOT modify or influence the core decision engine
# - It operates on a different risk/reward profile
#
# =============================================================================


class PanicEngineState(Enum):
    """
    State machine states for the Panic Contrarian Engine.

    NORMAL: No panic detected, engine is monitoring.
             No trading signals emitted.

    PANIC_WINDOW_OPEN: Panic conditions detected, window for contrarian entry.
                       A single trade opportunity may be taken.
                       Window has a hard expiration timestamp.

    COOLDOWN: After a panic window closes (trade taken OR expired).
              No new panic windows can open during cooldown.
              Prevents overtrading and emotional decisions.

    STATE TRANSITIONS:
    - NORMAL → PANIC_WINDOW_OPEN: All panic conditions met
    - PANIC_WINDOW_OPEN → COOLDOWN: Window expired OR trade executed
    - COOLDOWN → NORMAL: Cooldown period elapsed

    INVARIANTS:
    - Only ONE state active at any time
    - No direct NORMAL → COOLDOWN transition
    - No direct PANIC_WINDOW_OPEN → NORMAL transition (must cooldown)
    """
    NORMAL = "NORMAL"
    PANIC_WINDOW_OPEN = "PANIC_WINDOW_OPEN"
    COOLDOWN = "COOLDOWN"


class PanicEngineOutput(Enum):
    """
    Output states from the Panic Contrarian Engine.

    IGNORE: No action required. Engine is either:
            - In NORMAL state with no panic detected
            - In COOLDOWN state (blocked from trading)
            - Panic conditions partially met (not all criteria)

    PANIC_WINDOW_OPEN: Panic conditions fully met.
                       A contrarian trade opportunity exists.
                       Output includes:
                       - market_id
                       - direction_of_panic (OVERPRICED / UNDERPRICED)
                       - triggering metrics
                       - expiration timestamp

    COOLDOWN: Engine is in cooldown state.
              Informational only - no trading allowed.
              Output includes remaining cooldown duration.

    NOTE: PANIC_WINDOW_OPEN does NOT mean "trade now".
    It means "a trade MAY be taken if execution rules permit".
    Actual execution is handled by a separate module.
    """
    IGNORE = "IGNORE"
    PANIC_WINDOW_OPEN = "PANIC_WINDOW_OPEN"
    COOLDOWN = "COOLDOWN"


class PanicDirection(Enum):
    """
    Direction of panic-induced price dislocation.

    OVERPRICED: Market panicked into BUYING (price too high).
                Contrarian action: SELL / SHORT.
                Example: FOMO buying on false positive news.

    UNDERPRICED: Market panicked into SELLING (price too low).
                 Contrarian action: BUY.
                 Example: Panic selling on FUD or misinterpreted news.

    NOTE: This is ONLY used for signal generation.
    It does NOT dictate position sizing or execution timing.
    """
    OVERPRICED = "OVERPRICED"
    UNDERPRICED = "UNDERPRICED"


class PanicConditionResult(Enum):
    """
    Result of evaluating a single panic condition.

    PASSED: Condition met (e.g., sufficient price delta detected)
    FAILED: Condition not met (e.g., insufficient volume spike)
    INSUFFICIENT_DATA: Cannot evaluate (e.g., missing baseline data)

    PANIC DETECTION RULE:
    ALL conditions must be PASSED for PANIC_WINDOW_OPEN.
    ANY condition being FAILED or INSUFFICIENT_DATA → IGNORE.
    """
    PASSED = "PASSED"
    FAILED = "FAILED"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


# =============================================================================
# SHADOW MODE ENUMS
# =============================================================================
#
# These enums support the mandatory SHADOW MODE for panic engine validation.
#
# GOVERNANCE:
# - Shadow mode is MANDATORY before any real trading
# - The engine is assumed to be WRONG by default
# - Its job is to prove usefulness over time
# - If unsure, the correct action is: DO NOTHING
#
# =============================================================================


class PanicTradeOutcome(Enum):
    """
    Classification of simulated panic trade outcomes.

    Used ONLY in shadow mode to evaluate engine performance.
    These classifications determine whether the engine's signals are valuable.

    GOOD_REVERSION: Price reverted as expected.
                    Contrarian thesis was CORRECT.
                    This is the desired outcome.

    NO_REVERSION: Price stayed flat, no significant movement.
                  Contrarian thesis was NEUTRAL.
                  Not harmful, but not useful either.

    CONTINUED_PANIC: Price continued in panic direction.
                     Contrarian thesis was WRONG.
                     This is a loss scenario.

    FALSE_TRIGGER: Panic detection was incorrect.
                   Price movement was NOT panic (e.g., fundamental).
                   Resolution rules changed, news was misinterpreted.
                   This is a CRITICAL failure mode.

    ABORTED: Trade was aborted before completion.
             Safety conditions triggered mid-trade.
             No P&L impact but indicates signal quality issue.

    PENDING: Trade outcome not yet determined.
             Still within observation window.
    """
    GOOD_REVERSION = "GOOD_REVERSION"
    NO_REVERSION = "NO_REVERSION"
    CONTINUED_PANIC = "CONTINUED_PANIC"
    FALSE_TRIGGER = "FALSE_TRIGGER"
    ABORTED = "ABORTED"
    PENDING = "PENDING"


class AbortReason(Enum):
    """
    Reasons for aborting a panic trade (simulated or real).

    These are HARD ABORT conditions that override any signal.

    RESOLUTION_CHANGED: Resolution definition changed after trigger.
                        The price movement may now be rational.
                        ABORT immediately.

    RULE_CLARIFICATION: Official rule clarification released.
                        Market may be re-pricing to new information.
                        ABORT immediately.

    SAFETY_BUFFER_BREACHED: Time until resolution fell below buffer.
                            Too close to resolution for safe exit.
                            ABORT immediately.

    KILL_SWITCH_TRIGGERED: FALSE_TRIGGER rate exceeded threshold.
                           Engine is performing poorly.
                           ABORT and disable engine.

    MANUAL_ABORT: Human operator requested abort.
                  Always respected immediately.
    """
    RESOLUTION_CHANGED = "RESOLUTION_CHANGED"
    RULE_CLARIFICATION = "RULE_CLARIFICATION"
    SAFETY_BUFFER_BREACHED = "SAFETY_BUFFER_BREACHED"
    KILL_SWITCH_TRIGGERED = "KILL_SWITCH_TRIGGERED"
    MANUAL_ABORT = "MANUAL_ABORT"


class ShadowModeStatus(Enum):
    """
    Status of shadow mode for the panic engine.

    ACTIVE: Shadow mode is ON (default).
            All trades are simulated.
            No real capital movement.
            Full logging required.

    DISABLED_KILL_SWITCH: Shadow mode forced ON due to kill switch.
                          FALSE_TRIGGER rate exceeded threshold.
                          Manual re-enable required.

    PRODUCTION: Shadow mode is OFF.
                Real trades MAY be executed.
                This requires explicit manual activation.
                NOT RECOMMENDED until extensive shadow validation.
    """
    ACTIVE = "ACTIVE"
    DISABLED_KILL_SWITCH = "DISABLED_KILL_SWITCH"
    PRODUCTION = "PRODUCTION"


# =============================================================================
# EXECUTION ENGINE ENUMS
# =============================================================================
#
# These enums control the execution layer behavior.
#
# SAFETY HIERARCHY (most restrictive to least):
# DISABLED → SHADOW → PAPER → ARMED → LIVE
#
# DEFAULT STATE: DISABLED
# Orders can NEVER be sent unless explicitly ARMED or LIVE.
#
# =============================================================================


class ExecutionMode(Enum):
    """
    Execution engine operating modes.

    SAFETY HIERARCHY (most restrictive to least restrictive):
    DISABLED > SHADOW > PAPER > ARMED > LIVE

    DISABLED: Default state. No orders accepted.
              All order submissions return rejection.
              This is the ONLY safe default.

    SHADOW: Orders are simulated with shadow logging only.
            No API calls. No paper positions.
            Used for signal validation.

    PAPER: Orders create paper positions with simulated fills.
           No API calls. Positions are tracked locally.
           Used for strategy validation.

    ARMED: System is ready for live trading.
           Requires 2-step confirmation to enter.
           Orders are validated but NOT sent.
           One step away from LIVE.

    LIVE: Real orders sent to Polymarket API.
          Requires:
          - ARMED state transition first
          - ENV var POLYMARKET_LIVE=1
          - Valid API credentials

    TRANSITION RULES:
    - Startup → DISABLED (always)
    - DISABLED → SHADOW (allowed)
    - DISABLED → PAPER (allowed)
    - DISABLED → ARMED (requires 2-step)
    - ARMED → LIVE (requires env + keys)
    - Any error → DISABLED (forced)
    - Any mode → DISABLED (always allowed)
    """
    DISABLED = "DISABLED"
    SHADOW = "SHADOW"
    PAPER = "PAPER"
    ARMED = "ARMED"
    LIVE = "LIVE"


class OrderSide(Enum):
    """
    Order side for trade direction.

    BUY: Purchase shares (long position).
    SELL: Sell shares (close long or short position).
    """
    BUY = "BUY"
    SELL = "SELL"


class OrderType(Enum):
    """
    Order type for execution behavior.

    GTC: Good-Til-Cancelled. Remains active until filled or cancelled.
    IOC: Immediate-Or-Cancel. Fill immediately or cancel.
    FOK: Fill-Or-Kill. Fill completely or cancel entirely.
    """
    GTC = "GTC"
    IOC = "IOC"
    FOK = "FOK"


class OrderStatus(Enum):
    """
    Status of an order in the execution system.

    PENDING: Order created but not yet submitted.
    SUBMITTED: Order sent to exchange/API.
    OPEN: Order is active and awaiting fill.
    PARTIALLY_FILLED: Order partially filled.
    FILLED: Order completely filled.
    CANCELLED: Order cancelled (by user or system).
    REJECTED: Order rejected by system or exchange.
    EXPIRED: Order expired (for time-limited orders).
    FAILED: Order submission failed (API error, etc.).
    SIMULATED: Order was simulated (SHADOW/PAPER mode).
    """
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    OPEN = "OPEN"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    FAILED = "FAILED"
    SIMULATED = "SIMULATED"


class OrderRejectionReason(Enum):
    """
    Reasons why an order was rejected.

    Used for audit trail and debugging.
    """
    MODE_DISABLED = "MODE_DISABLED"
    MODE_NOT_LIVE = "MODE_NOT_LIVE"
    GOVERNANCE_REJECTED = "GOVERNANCE_REJECTED"
    KILL_SWITCH_ACTIVE = "KILL_SWITCH_ACTIVE"
    MISSING_API_KEYS = "MISSING_API_KEYS"
    MISSING_ENV_VAR = "MISSING_ENV_VAR"
    INVALID_PARAMETERS = "INVALID_PARAMETERS"
    INSUFFICIENT_BALANCE = "INSUFFICIENT_BALANCE"
    MARKET_CLOSED = "MARKET_CLOSED"
    RATE_LIMITED = "RATE_LIMITED"
    API_ERROR = "API_ERROR"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    MANUAL_ABORT = "MANUAL_ABORT"
