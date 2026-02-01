# =============================================================================
# POLYMARKET BEOBACHTER - HONEST PROBABILITY MODEL INTERFACE
# =============================================================================
#
# FORENSIC REFACTOR: This module replaces all placeholder/fake probability logic.
#
# FUNDAMENTAL PRINCIPLE:
# A probability is a CLAIM about reality.
# If you cannot explain it in one sentence, you are not allowed to return a number.
#
# RULES:
# 1. NO hardcoded probabilities (0.5, 0.6, etc.)
# 2. NO fallback "edges"
# 3. Every probability MUST have an explicit assumption
# 4. If no defensible model exists -> NO_SIGNAL
# 5. Better silence than false confidence
#
# =============================================================================

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import List, Optional, Dict, Any

logger = logging.getLogger(__name__)


# =============================================================================
# CONFIDENCE LEVELS
# =============================================================================


class ModelConfidence(Enum):
    """
    Confidence level of a probability estimate.

    NONE = Model cannot produce a valid estimate
    LOW = High uncertainty, wide bands
    MEDIUM = Moderate uncertainty
    HIGH = Narrow uncertainty bands, strong model
    """
    NONE = "NONE"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


# =============================================================================
# MODEL TYPES
# =============================================================================


class ModelType(Enum):
    """
    Supported probability model types.

    ONLY these models are allowed to produce valid probabilities:
    - WEATHER: Physical forecast data + statistical model
    - EU_REGULATION: Procedural step analysis + historical base rates
    - CORPORATE_EVENT: SEC filings + announcement pattern analysis
    - COURT_RULING: Judicial process analysis + historical patterns

    Everything else is UNSUPPORTED.
    """
    WEATHER = "WEATHER"
    EU_REGULATION = "EU_REGULATION"
    CORPORATE_EVENT = "CORPORATE_EVENT"
    COURT_RULING = "COURT_RULING"
    FED_RATE = "FED_RATE"
    CRYPTO_MARKET = "CRYPTO_MARKET"
    NUMERIC_THRESHOLD = "NUMERIC_THRESHOLD"
    POLLING = "POLLING"
    SPORTS = "SPORTS"
    UNSUPPORTED = "UNSUPPORTED"


# =============================================================================
# PROBABILITY ESTIMATE (HONEST INTERFACE)
# =============================================================================


@dataclass
class HonestProbabilityEstimate:
    """
    An HONEST probability estimate.

    INVARIANTS:
    - probability is ONLY set if valid == True
    - confidence is NONE if valid == False
    - Every valid estimate MUST have an assumption
    - Every valid estimate MUST list data sources

    This interface enforces that we cannot pretend to have edge.
    """

    # Core fields
    probability: Optional[float] = None  # Only set if valid
    probability_low: Optional[float] = None
    probability_high: Optional[float] = None

    # Validity
    valid: bool = False
    confidence: ModelConfidence = ModelConfidence.NONE

    # Model provenance
    model_type: Optional[ModelType] = None
    assumption: Optional[str] = None
    data_sources: List[str] = field(default_factory=list)

    # Warnings and metadata
    warnings: List[str] = field(default_factory=list)
    reasoning: Optional[str] = None
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    def __post_init__(self):
        """Enforce invariants."""
        self._validate()

    def _validate(self):
        """
        Validate invariants.

        RULES:
        1. valid == True requires probability in [0, 1]
        2. valid == True requires assumption
        3. valid == True requires at least one data source
        4. valid == False requires probability == None
        5. valid == False requires confidence == NONE
        """
        if self.valid:
            # Valid estimate must have probability
            if self.probability is None:
                raise ValueError("valid=True but probability is None")
            if not (0.0 <= self.probability <= 1.0):
                raise ValueError(f"probability {self.probability} not in [0, 1]")

            # Valid estimate must have assumption
            if not self.assumption:
                raise ValueError("valid=True but no assumption provided")

            # Valid estimate must have data sources
            if not self.data_sources:
                raise ValueError("valid=True but no data_sources provided")

            # Valid estimate must have confidence != NONE
            if self.confidence == ModelConfidence.NONE:
                raise ValueError("valid=True but confidence is NONE")
        else:
            # Invalid estimate must NOT pretend to have probability
            if self.probability is not None:
                self.warnings.append(
                    f"Clearing invalid probability={self.probability}"
                )
                self.probability = None
                self.probability_low = None
                self.probability_high = None

            # Invalid estimate must have NONE confidence
            if self.confidence != ModelConfidence.NONE:
                self.warnings.append(
                    f"Resetting confidence from {self.confidence.value} to NONE"
                )
                self.confidence = ModelConfidence.NONE

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "probability": self.probability,
            "probability_low": self.probability_low,
            "probability_high": self.probability_high,
            "valid": self.valid,
            "confidence": self.confidence.value,
            "model_type": self.model_type.value if self.model_type else None,
            "assumption": self.assumption,
            "data_sources": self.data_sources,
            "warnings": self.warnings,
            "reasoning": self.reasoning,
            "timestamp": self.timestamp,
        }

    @classmethod
    def invalid(
        cls,
        reason: str,
        model_type: ModelType = ModelType.UNSUPPORTED,
        warnings: Optional[List[str]] = None,
    ) -> "HonestProbabilityEstimate":
        """
        Factory for creating INVALID estimates.

        Use this when no defensible probability can be computed.

        Args:
            reason: Why the estimate is invalid
            model_type: The model type (usually UNSUPPORTED)
            warnings: Additional warnings

        Returns:
            An invalid HonestProbabilityEstimate
        """
        return cls(
            probability=None,
            valid=False,
            confidence=ModelConfidence.NONE,
            model_type=model_type,
            assumption=None,
            data_sources=[],
            warnings=warnings or [],
            reasoning=reason,
        )


# =============================================================================
# BASE MODEL INTERFACE
# =============================================================================


class BaseProbabilityModel(ABC):
    """
    Abstract base class for probability models.

    Every concrete model must implement:
    - can_estimate(): Check if this model applies to a market
    - estimate(): Produce an HonestProbabilityEstimate
    """

    @property
    @abstractmethod
    def model_type(self) -> ModelType:
        """Return the model type."""
        pass

    @abstractmethod
    def can_estimate(self, market_data: Dict[str, Any]) -> bool:
        """
        Check if this model can produce a valid estimate for the market.

        Args:
            market_data: Market metadata

        Returns:
            True if this model applies, False otherwise
        """
        pass

    @abstractmethod
    def estimate(self, market_data: Dict[str, Any]) -> HonestProbabilityEstimate:
        """
        Produce a probability estimate.

        MUST return an honest estimate:
        - If model applies and has data: valid=True with probability
        - If model cannot compute: valid=False with reason

        Args:
            market_data: Market metadata and any required inputs

        Returns:
            HonestProbabilityEstimate
        """
        pass


# =============================================================================
# UNSUPPORTED MODEL (DEFAULT)
# =============================================================================


class UnsupportedModel(BaseProbabilityModel):
    """
    Model for markets where no defensible probability estimate is possible.

    Categories that are ALWAYS unsupported:
    - Politics (elections, policy changes)
    - Entertainment (game releases, album releases, celebrity events)
    - Speculative timelines (GTA VI, product launches, etc.)
    - Sports (game outcomes, player performance)
    - Crypto prices (without explicit market-making model)

    This model ALWAYS returns valid=False.
    It is HONEST about our ignorance.
    """

    # Categories that are NEVER supported — only pure speculation with no data
    UNSUPPORTED_KEYWORDS = [
        # Entertainment / Celebrity — no measurable data
        "gta", "game release", "album release", "rihanna",
        "tv show", "netflix series", "spotify", "taylor swift album",
        "celebrity", "grammy", "oscar", "emmy",
        "divorce", "scandal", "dating", "married",
        # Politics — no measurable model
        "election", "trump", "biden", "resign", "senate", "republican",
        "democrat", "midterm", "impeach", "vote",
        # Sports — no measurable model
        "nba", "super bowl", "world cup", "soccer", "nfl",
        "champions league", "olympics", "finals winner",
        # Crypto price speculation — no structural model
        "bitcoin", "btc", "ethereum", "eth", "crypto price",
        "above $", "below $",
    ]

    @property
    def model_type(self) -> ModelType:
        return ModelType.UNSUPPORTED

    def can_estimate(self, market_data: Dict[str, Any]) -> bool:
        """
        Check if this market is unsupported.

        Returns True if market contains unsupported keywords,
        meaning we CANNOT provide a valid probability.
        """
        title = market_data.get("title", "").lower()
        description = market_data.get("description", "").lower()
        category = market_data.get("category", "").lower()

        combined = f"{title} {description} {category}"

        for keyword in self.UNSUPPORTED_KEYWORDS:
            if keyword in combined:
                return True

        return False

    def estimate(self, market_data: Dict[str, Any]) -> HonestProbabilityEstimate:
        """
        Return an INVALID estimate for unsupported markets.

        This is HONEST: we do not pretend to have edge.
        """
        title = market_data.get("title", "Unknown market")
        category = market_data.get("category", "Unknown")

        return HonestProbabilityEstimate.invalid(
            reason=(
                f"No defensible probabilistic model for market type: {category}. "
                f"Market '{title[:50]}...' involves speculation beyond our modeling capability. "
                "Returning NO_SIGNAL to avoid false confidence."
            ),
            model_type=ModelType.UNSUPPORTED,
            warnings=[
                "Market direction: UNKNOWN",
                "No edge calculation possible",
                "Requires human judgment or specialized model",
            ],
        )


# =============================================================================
# MODEL ROUTER
# =============================================================================


class ProbabilityModelRouter:
    """
    Routes markets to appropriate probability models.

    ROUTING LOGIC:
    1. Try specialized models (Weather, EU Regulation, Corporate, Court)
    2. If no model applies -> return UNSUPPORTED (invalid estimate)

    This router ensures we NEVER return a fake probability.
    """

    def __init__(self):
        """Initialize with registered models."""
        self._models: List[BaseProbabilityModel] = []
        self._unsupported_model = UnsupportedModel()

        # Register default models
        self._register_default_models()

    def _register_default_models(self):
        """Register the default probability models."""
        # Order matters: more specific models first, broad catchers last
        model_imports = [
            ("FedRateModel", ".fed_rate_model"),
            ("CryptoMarketModel", ".crypto_market_model"),
            ("PollingModel", ".polling_model"),
            ("SportsBettingModel", ".sports_model"),
            ("NumericThresholdModel", ".numeric_threshold_model"),
        ]
        for class_name, module_path in model_imports:
            try:
                import importlib
                mod = importlib.import_module(module_path, package=__package__)
                model_cls = getattr(mod, class_name)
                self._models.append(model_cls())
                logger.info(f"Registered {class_name}")
            except (ImportError, AttributeError) as e:
                logger.warning(f"Could not register {class_name}: {e}")

    def register_model(self, model: BaseProbabilityModel):
        """
        Register a new probability model.

        Args:
            model: A model implementing BaseProbabilityModel
        """
        self._models.append(model)
        logger.info(f"Registered probability model: {model.model_type.value}")

    def estimate(self, market_data: Dict[str, Any]) -> HonestProbabilityEstimate:
        """
        Route to appropriate model and get estimate.

        Args:
            market_data: Market metadata

        Returns:
            HonestProbabilityEstimate (valid or invalid)
        """
        # Try each specialized model
        for model in self._models:
            if model.can_estimate(market_data):
                estimate = model.estimate(market_data)
                logger.info(
                    f"Model {model.model_type.value} handled market "
                    f"'{market_data.get('title', 'Unknown')[:30]}...' | "
                    f"valid={estimate.valid}"
                )
                return estimate

        # No specialized model applies -> check if it's unsupported
        if self._unsupported_model.can_estimate(market_data):
            return self._unsupported_model.estimate(market_data)

        # Default: return invalid with generic reason
        return HonestProbabilityEstimate.invalid(
            reason="No probability model available for this market category",
            model_type=ModelType.UNSUPPORTED,
            warnings=["Market type not recognized by any registered model"],
        )


# =============================================================================
# EDGE CALCULATOR (HONEST)
# =============================================================================


@dataclass
class EdgeCalculation:
    """
    Result of edge calculation.

    Edge is ONLY valid if:
    - probability_estimate.valid == True
    - market_probability is known and valid
    """
    edge: Optional[float] = None
    edge_percent: Optional[float] = None
    direction: str = "UNKNOWN"
    valid: bool = False
    reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "edge": self.edge,
            "edge_percent": self.edge_percent,
            "direction": self.direction,
            "valid": self.valid,
            "reason": self.reason,
        }


def calculate_edge(
    estimate: HonestProbabilityEstimate,
    market_probability: Optional[float],
) -> EdgeCalculation:
    """
    Calculate edge between model estimate and market price.

    RULES:
    1. estimate.valid MUST be True
    2. market_probability MUST be in (0, 1)
    3. estimate.confidence MUST NOT be NONE

    If ANY rule fails -> return invalid EdgeCalculation.

    Args:
        estimate: The model's probability estimate
        market_probability: The market-implied probability

    Returns:
        EdgeCalculation (valid or invalid)
    """
    # Rule 1: Estimate must be valid
    if not estimate.valid:
        return EdgeCalculation(
            valid=False,
            reason="Cannot calculate edge: probability estimate is invalid",
        )

    # Rule 2: Market probability must be valid
    if market_probability is None:
        return EdgeCalculation(
            valid=False,
            reason="Cannot calculate edge: market probability is unknown",
        )

    if not (0.0 < market_probability < 1.0):
        return EdgeCalculation(
            valid=False,
            reason=f"Cannot calculate edge: market probability {market_probability} out of range",
        )

    # Rule 3: Confidence must not be NONE
    if estimate.confidence == ModelConfidence.NONE:
        return EdgeCalculation(
            valid=False,
            reason="Cannot calculate edge: model confidence is NONE",
        )

    # Calculate edge
    model_prob = estimate.probability
    edge = model_prob - market_probability
    edge_percent = (edge / market_probability) * 100

    # Determine direction
    if edge > 0.01:
        direction = "MARKET_TOO_LOW"
    elif edge < -0.01:
        direction = "MARKET_TOO_HIGH"
    else:
        direction = "FAIR"

    return EdgeCalculation(
        edge=round(edge, 4),
        edge_percent=round(edge_percent, 2),
        direction=direction,
        valid=True,
        reason=f"Model: {model_prob:.3f} vs Market: {market_probability:.3f}",
    )


# =============================================================================
# MODULE SINGLETON
# =============================================================================

_router: Optional[ProbabilityModelRouter] = None


def get_probability_router() -> ProbabilityModelRouter:
    """Get the global probability model router."""
    global _router
    if _router is None:
        _router = ProbabilityModelRouter()
    return _router


def get_honest_estimate(market_data: Dict[str, Any]) -> HonestProbabilityEstimate:
    """
    Convenience function to get an honest probability estimate.

    Args:
        market_data: Market metadata

    Returns:
        HonestProbabilityEstimate
    """
    return get_probability_router().estimate(market_data)
