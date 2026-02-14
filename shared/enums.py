# =============================================================================
# POLYMARKET BEOBACHTER - SHARED ENUMS
# =============================================================================
#
# WEATHER OBSERVATION + PAPER TRADING SYSTEM
#
# Enums for the observation and paper trading pipeline.
# Paper trading only - no live execution.
#
# =============================================================================

from enum import Enum


class Layer(Enum):
    """
    System layer classification for isolation enforcement.

    LAYER1_INSTITUTIONAL: Institutional/Process Edge analysis
    LAYER2_MICROSTRUCTURE: Microstructure research (experimental)
    """
    LAYER1_INSTITUTIONAL = "LAYER1_INSTITUTIONAL"
    LAYER2_MICROSTRUCTURE = "LAYER2_MICROSTRUCTURE"


class ConfidenceLevel(Enum):
    """Confidence level for probability estimates."""
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class WeatherValidationResult(Enum):
    """
    Result of weather market validation checklist.

    VALID: All checklist items passed
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


class ObservationOutcome(Enum):
    """
    Observation outcome classification for calibration.

    CORRECT_EDGE: Model detected edge, resolution confirmed
    FALSE_EDGE: Model detected edge, but resolution contradicted
    NO_SIGNAL_CORRECT: No signal, market resolved as expected
    NO_SIGNAL_MISSED: No signal, but edge existed
    PENDING: Awaiting resolution
    """
    CORRECT_EDGE = "CORRECT_EDGE"
    FALSE_EDGE = "FALSE_EDGE"
    NO_SIGNAL_CORRECT = "NO_SIGNAL_CORRECT"
    NO_SIGNAL_MISSED = "NO_SIGNAL_MISSED"
    PENDING = "PENDING"


# =============================================================================
# PAPER TRADING ENUMS
# =============================================================================


class TradeSide(Enum):
    """
    Trading side for paper positions.

    BUY_YES: Buy YES tokens (bullish on outcome)
    BUY_NO: Buy NO tokens (bearish on outcome)
    """
    BUY_YES = "BUY_YES"
    BUY_NO = "BUY_NO"


class PositionStatus(Enum):
    """
    Status of a paper trading position.

    OPEN: Position is active, awaiting resolution
    CLOSED: Position was closed (market resolved or manually closed)
    CANCELLED: Position was cancelled before entry
    """
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class ProposalDecision(Enum):
    """
    Decision outcome from proposal generator.

    TRADE: Sufficient edge detected, proposal recommends trading
    NO_TRADE: Insufficient edge or criteria not met
    """
    TRADE = "TRADE"
    NO_TRADE = "NO_TRADE"
