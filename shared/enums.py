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
