# =============================================================================
# POLYMARKET EU AI REGULATION ANALYZER
# Module: models/data_models.py
# Purpose: Define all data structures for analysis pipeline
# =============================================================================
#
# AUDIT NOTE:
# All data models are:
# - Immutable after creation (use dataclasses with frozen=True where applicable)
# - Fully serializable to JSON for audit trails
# - Documented with explicit field semantics
#
# REGULATORY CONTEXT:
# These models encode the structure of EU legislative processes.
# The EU AI Act (Regulation 2024/1689) serves as the primary reference.
# Stages follow the standard EU legislative procedure (OLP).
#
# =============================================================================

from dataclasses import dataclass, field, asdict
from datetime import date
from enum import Enum
from typing import Optional, List, Dict, Any


class DecisionOutcome(Enum):
    """
    Final trading decision outcome.

    TRADE: All criteria met, market is structurally tradeable.
    NO_TRADE: One or more criteria failed, do not trade.

    AUDIT NOTE: There is no "MAYBE" - fail closed by design.
    """
    TRADE = "TRADE"
    NO_TRADE = "NO_TRADE"


class ConfidenceLevel(Enum):
    """
    Confidence level for probability estimates and decisions.

    Used instead of string literals to ensure type safety.
    """
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class MarketDirection(Enum):
    """
    Direction of market mispricing relative to rule-based estimate.

    MARKET_TOO_HIGH: Market overestimates probability (consider NO position)
    MARKET_TOO_LOW: Market underestimates probability (consider YES position)
    ALIGNED: Market pricing is within acceptable range of estimate
    """
    MARKET_TOO_HIGH = "MARKET_TOO_HIGH"
    MARKET_TOO_LOW = "MARKET_TOO_LOW"
    ALIGNED = "ALIGNED"


class EURegulationStage(Enum):
    """
    Stages of the EU regulatory lifecycle.

    Based on the Ordinary Legislative Procedure (OLP) and post-adoption phases.
    Reference: Article 294 TFEU

    STAGES EXPLAINED:
    - PROPOSAL: Commission has proposed the regulation
    - FIRST_READING_EP: European Parliament first reading
    - FIRST_READING_COUNCIL: Council first reading
    - SECOND_READING_EP: EP second reading (if needed)
    - SECOND_READING_COUNCIL: Council second reading (if needed)
    - CONCILIATION: Conciliation Committee (if needed)
    - ADOPTED: Regulation adopted by co-legislators
    - PUBLISHED_OJ: Published in Official Journal of the EU
    - ENTERED_INTO_FORCE: Usually 20 days after OJ publication
    - APPLICATION_DATE: When the regulation starts applying
    - TRANSITIONAL_PERIOD: Specific provisions with delayed application
    - DELEGATED_ACTS_PENDING: Commission delegated acts required
    - IMPLEMENTING_ACTS_PENDING: Commission implementing acts required
    - FULLY_APPLICABLE: All provisions in force
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


@dataclass
class MarketInput:
    """
    Input data structure for market analysis.

    All fields are manually provided - no API calls, no scraping.
    This ensures full auditability of input data.

    FIELDS:
    - market_title: The exact title of the Polymarket market
    - resolution_text: Full, verbatim resolution criteria from Polymarket
    - target_date: The date by which the market resolves (YYYY-MM-DD)
    - referenced_regulation: EU regulation name (e.g., "EU AI Act")
    - authority_involved: Which EU institution(s) are relevant
    - market_implied_probability: Current market probability (0.0 to 1.0)
    - analysis_date: Date when this analysis is performed
    - notes: Optional additional context
    """
    market_title: str
    resolution_text: str
    target_date: date
    referenced_regulation: str
    authority_involved: str
    market_implied_probability: float  # 0.0 to 1.0
    analysis_date: date
    notes: Optional[str] = None

    def __post_init__(self):
        """Validate fields after initialization."""
        # Validate market_implied_probability range
        if not isinstance(self.market_implied_probability, (int, float)):
            raise TypeError(
                f"market_implied_probability must be a number, "
                f"got {type(self.market_implied_probability).__name__}"
            )
        if not 0.0 <= self.market_implied_probability <= 1.0:
            hint = ""
            if 1.0 < self.market_implied_probability <= 100.0:
                hint = f" Did you mean {self.market_implied_probability / 100}?"
            raise ValueError(
                f"market_implied_probability must be between 0.0 and 1.0, "
                f"got {self.market_implied_probability}.{hint}"
            )

        # Validate required string fields are not empty
        if not self.market_title.strip():
            raise ValueError("market_title cannot be empty")
        if not self.resolution_text.strip():
            raise ValueError("resolution_text cannot be empty")
        if not self.referenced_regulation.strip():
            raise ValueError("referenced_regulation cannot be empty")

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        result = asdict(self)
        result["target_date"] = self.target_date.isoformat()
        result["analysis_date"] = self.analysis_date.isoformat()
        return result


@dataclass
class ResolutionAnalysis:
    """
    Analysis of the market's resolution criteria.

    AUDIT PRINCIPLE:
    A tradeable market MUST have binary, objectively verifiable resolution.
    Any ambiguity results in automatic NO_TRADE.

    FIELDS:
    - is_binary: True if resolution is clearly YES/NO
    - is_objectively_verifiable: True if resolution can be checked against public record
    - ambiguity_flags: List of identified ambiguities
    - resolution_source_identified: True if official source for resolution is clear
    - hard_fail: True if resolution is too ambiguous to trade
    - reasoning: Detailed explanation of analysis
    """
    is_binary: bool
    is_objectively_verifiable: bool
    ambiguity_flags: List[str]
    resolution_source_identified: bool
    hard_fail: bool
    reasoning: str

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)


@dataclass
class ProcessStageAnalysis:
    """
    Analysis of where the regulation stands in the EU legislative process.

    REGULATORY CONTEXT:
    Understanding the current stage is critical for timeline assessment.
    Each stage has minimum durations and procedural requirements.

    FIELDS:
    - current_stage: The identified current stage of the regulation
    - stages_completed: List of stages already completed
    - stages_remaining: List of stages still required
    - key_dates: Dictionary of known dates (adoption, publication, etc.)
    - blocking_factors: Any identified factors that could delay progress
    - reasoning: Detailed explanation
    """
    current_stage: EURegulationStage
    stages_completed: List[EURegulationStage]
    stages_remaining: List[EURegulationStage]
    key_dates: Dict[str, Optional[date]]
    blocking_factors: List[str]
    reasoning: str

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        result = {
            "current_stage": self.current_stage.value,
            "stages_completed": [s.value for s in self.stages_completed],
            "stages_remaining": [s.value for s in self.stages_remaining],
            "key_dates": {k: v.isoformat() if v else None for k, v in self.key_dates.items()},
            "blocking_factors": self.blocking_factors,
            "reasoning": self.reasoning,
        }
        return result


@dataclass
class TimeFeasibilityAnalysis:
    """
    Analysis of whether the market's timeline is realistic.

    AUDIT PRINCIPLE:
    EU regulatory processes have minimum durations that cannot be bypassed.
    If the market requires something faster than physically possible, NO_TRADE.

    FIELDS:
    - days_until_target: Calendar days from analysis to target date
    - minimum_days_required: Conservative estimate of minimum days needed
    - is_timeline_feasible: True if timeline is realistically achievable
    - mandatory_waiting_periods: List of non-negotiable waiting periods
    - institutional_constraints: Identified capacity/calendar constraints
    - hard_fail: True if timeline is physically impossible
    - reasoning: Detailed explanation
    """
    days_until_target: int
    minimum_days_required: int
    is_timeline_feasible: bool
    mandatory_waiting_periods: List[str]
    institutional_constraints: List[str]
    hard_fail: bool
    reasoning: str

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)


@dataclass
class ProbabilityEstimate:
    """
    Rule-based probability estimate.

    AUDIT PRINCIPLE:
    Probabilities are NOT predictions. They are conservative ranges based on:
    - Number of remaining formal steps
    - Historical EU implementation patterns
    - Status quo bias (default: things don't change)

    NO sentiment analysis. NO analyst opinions. NO ML.

    FIELDS:
    - probability_low: Lower bound of probability range (conservative)
    - probability_high: Upper bound of probability range
    - probability_midpoint: Central estimate
    - assumptions: List of explicit assumptions made
    - historical_precedents: Relevant historical data points
    - status_quo_bias_applied: True if status quo bias was factored in
    - confidence_level: "LOW", "MEDIUM", "HIGH" based on data availability
    - reasoning: Detailed explanation
    """
    probability_low: float
    probability_high: float
    probability_midpoint: float
    assumptions: List[str]
    historical_precedents: List[str]
    status_quo_bias_applied: bool
    confidence_level: str  # "LOW", "MEDIUM", "HIGH"
    reasoning: str

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)


@dataclass
class MarketSanityAnalysis:
    """
    Comparison between rule-based estimate and market-implied probability.

    AUDIT PRINCIPLE:
    Trading is only justified if there is significant divergence between
    our conservative estimate and market pricing. The threshold is 15pp.

    FIELDS:
    - market_implied_prob: The probability implied by market prices
    - rule_based_prob: Our midpoint probability estimate
    - delta: Absolute difference (market - rule_based)
    - delta_percentage_points: Delta expressed in percentage points
    - direction: "MARKET_TOO_HIGH" or "MARKET_TOO_LOW" or "ALIGNED"
    - meets_threshold: True if delta >= 15 percentage points
    - reasoning: Detailed explanation
    """
    market_implied_prob: float
    rule_based_prob: float
    delta: float
    delta_percentage_points: float
    direction: str  # "MARKET_TOO_HIGH", "MARKET_TOO_LOW", "ALIGNED"
    meets_threshold: bool
    reasoning: str

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)


@dataclass
class FinalDecision:
    """
    The final trading decision with full audit trail.

    AUDIT PRINCIPLE:
    Decision must be:
    - TRADE only if ALL criteria are met
    - NO_TRADE if ANY criterion fails
    - Fully explainable with explicit reasoning

    FIELDS:
    - outcome: TRADE or NO_TRADE
    - criteria_met: Dictionary of each criterion and whether it passed
    - blocking_criteria: List of criteria that caused NO_TRADE (if any)
    - confidence: "LOW", "MEDIUM", "HIGH"
    - recommended_action: Human-readable action recommendation
    - risk_warnings: Any identified risks even if decision is TRADE
    - reasoning: Full explanation of decision
    """
    outcome: DecisionOutcome
    criteria_met: Dict[str, bool]
    blocking_criteria: List[str]
    confidence: str
    recommended_action: str
    risk_warnings: List[str]
    reasoning: str

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        result = asdict(self)
        result["outcome"] = self.outcome.value
        return result


@dataclass
class FullAnalysisReport:
    """
    Complete analysis report combining all modules.

    This is the top-level output structure.
    Designed for full auditability and traceability.

    FIELDS:
    - market_input: Original input data
    - resolution_analysis: Resolution parsing results
    - process_analysis: EU process stage analysis
    - time_feasibility: Timeline feasibility check
    - probability_estimate: Rule-based probability
    - market_sanity: Market comparison
    - final_decision: Trading decision
    - analysis_version: Version of the analyzer used
    - generated_at: Timestamp of report generation
    """
    market_input: MarketInput
    resolution_analysis: ResolutionAnalysis
    process_analysis: ProcessStageAnalysis
    time_feasibility: TimeFeasibilityAnalysis
    probability_estimate: ProbabilityEstimate
    market_sanity: MarketSanityAnalysis
    final_decision: FinalDecision
    analysis_version: str = "1.0.0"
    generated_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert entire report to dictionary for JSON serialization."""
        return {
            "analysis_version": self.analysis_version,
            "generated_at": self.generated_at,
            "market_input": self.market_input.to_dict(),
            "resolution_analysis": self.resolution_analysis.to_dict(),
            "process_analysis": self.process_analysis.to_dict(),
            "time_feasibility": self.time_feasibility.to_dict(),
            "probability_estimate": self.probability_estimate.to_dict(),
            "market_sanity": self.market_sanity.to_dict(),
            "final_decision": self.final_decision.to_dict(),
        }
