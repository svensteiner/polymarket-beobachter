# =============================================================================
# POLYMARKET BEOBACHTER - TIME URGENCY CALCULATOR
# =============================================================================
#
# GOVERNANCE INTENT:
# Intensifies trading as markets approach resolution. Markets often show
# inefficiencies in the final hours that can be exploited.
#
# Key Principle: As time-to-resolution decreases, we:
# 1. Accept lower edge thresholds (more signals)
# 2. Increase position sizes (more conviction)
# 3. Raise confidence requirements (only high-quality signals)
#
# =============================================================================

import logging
from dataclasses import dataclass
from typing import Dict, Optional, Tuple, List
from enum import Enum

logger = logging.getLogger(__name__)


class UrgencyPhase(Enum):
    """Trading phases based on time to resolution."""
    CRITICAL = "critical"      # 0-2 hours: Maximum intensity
    URGENT = "urgent"          # 2-8 hours: High intensity
    APPROACHING = "approaching"  # 8-24 hours: Elevated intensity
    NORMAL = "normal"          # 24-72 hours: Standard trading
    DISTANT = "distant"        # 72+ hours: Conservative trading


@dataclass
class UrgencyConfig:
    """Configuration for an urgency phase."""
    phase: UrgencyPhase
    hours_min: float
    hours_max: float
    edge_multiplier: float      # Multiplier for min_edge (< 1 = lower threshold)
    position_multiplier: float  # Multiplier for position size (> 1 = larger)
    confidence_floor: float     # Minimum confidence required in this phase


@dataclass
class UrgencyAdjustment:
    """Result of urgency calculation."""
    phase: UrgencyPhase
    hours_remaining: float
    edge_multiplier: float
    position_multiplier: float
    confidence_floor: float
    adjusted_min_edge: float
    adjusted_max_position: float
    reason: str


# Default urgency configurations
DEFAULT_URGENCY_CONFIGS = [
    UrgencyConfig(
        phase=UrgencyPhase.CRITICAL,
        hours_min=0,
        hours_max=2,
        edge_multiplier=0.5,      # Accept 50% of normal edge
        position_multiplier=1.5,   # 50% larger positions
        confidence_floor=0.70      # Require higher confidence
    ),
    UrgencyConfig(
        phase=UrgencyPhase.URGENT,
        hours_min=2,
        hours_max=8,
        edge_multiplier=0.7,       # Accept 70% of normal edge
        position_multiplier=1.3,   # 30% larger positions
        confidence_floor=0.65      # Elevated confidence requirement
    ),
    UrgencyConfig(
        phase=UrgencyPhase.APPROACHING,
        hours_min=8,
        hours_max=24,
        edge_multiplier=0.85,      # Accept 85% of normal edge
        position_multiplier=1.1,   # 10% larger positions
        confidence_floor=0.60      # Standard confidence
    ),
    UrgencyConfig(
        phase=UrgencyPhase.NORMAL,
        hours_min=24,
        hours_max=72,
        edge_multiplier=1.0,       # Normal edge
        position_multiplier=1.0,   # Normal positions
        confidence_floor=0.60      # Standard confidence
    ),
    UrgencyConfig(
        phase=UrgencyPhase.DISTANT,
        hours_min=72,
        hours_max=float("inf"),
        edge_multiplier=1.2,       # Require MORE edge (distant = uncertain)
        position_multiplier=0.8,   # Smaller positions
        confidence_floor=0.70      # Higher confidence needed
    ),
]


class TimeUrgencyCalculator:
    """
    Calculates trading parameter adjustments based on time to resolution.

    The closer we get to resolution, the more aggressive we become because:
    1. Weather forecasts become more accurate
    2. Market participants may not have updated their positions
    3. Time value decay creates opportunities
    """

    def __init__(self, configs: Optional[List[UrgencyConfig]] = None):
        """
        Initialize time urgency calculator.

        Args:
            configs: Custom urgency configurations. Defaults to standard configs.
        """
        self.configs = configs or DEFAULT_URGENCY_CONFIGS
        self._config_by_phase = {c.phase: c for c in self.configs}

        # Sort by hours_min for efficient lookup
        self.configs.sort(key=lambda c: c.hours_min)
        logger.info("TimeUrgencyCalculator initialized with %d phases", len(self.configs))

    def get_phase(self, hours_remaining: float) -> UrgencyPhase:
        """
        Determine urgency phase from hours remaining.

        Args:
            hours_remaining: Hours until market resolution

        Returns:
            Current urgency phase
        """
        for config in self.configs:
            if config.hours_min <= hours_remaining < config.hours_max:
                return config.phase
        return UrgencyPhase.NORMAL

    def get_config(self, hours_remaining: float) -> UrgencyConfig:
        """Get configuration for given time remaining."""
        phase = self.get_phase(hours_remaining)
        return self._config_by_phase[phase]

    def calculate_adjustment(
        self,
        hours_remaining: float,
        base_min_edge: float = 0.05,
        base_max_position: float = 100.0
    ) -> UrgencyAdjustment:
        """
        Calculate full adjustment for time remaining.

        Args:
            hours_remaining: Hours until market resolution
            base_min_edge: Normal minimum edge threshold
            base_max_position: Normal maximum position size

        Returns:
            UrgencyAdjustment with all modified parameters
        """
        config = self.get_config(hours_remaining)

        adjusted_min_edge = base_min_edge * config.edge_multiplier
        adjusted_max_position = base_max_position * config.position_multiplier

        # Build reason string
        if config.phase == UrgencyPhase.CRITICAL:
            reason = f"CRITICAL: Only {hours_remaining:.1f}h remaining - maximum intensity"
        elif config.phase == UrgencyPhase.URGENT:
            reason = f"URGENT: {hours_remaining:.1f}h remaining - elevated trading"
        elif config.phase == UrgencyPhase.APPROACHING:
            reason = f"APPROACHING: {hours_remaining:.1f}h remaining - slightly elevated"
        elif config.phase == UrgencyPhase.DISTANT:
            reason = f"DISTANT: {hours_remaining:.1f}h remaining - conservative mode"
        else:
            reason = f"NORMAL: {hours_remaining:.1f}h remaining - standard parameters"

        return UrgencyAdjustment(
            phase=config.phase,
            hours_remaining=hours_remaining,
            edge_multiplier=config.edge_multiplier,
            position_multiplier=config.position_multiplier,
            confidence_floor=config.confidence_floor,
            adjusted_min_edge=adjusted_min_edge,
            adjusted_max_position=adjusted_max_position,
            reason=reason
        )

    def adjust_min_edge(self, base_min_edge: float, hours_remaining: float) -> float:
        """
        Adjust minimum edge threshold based on time remaining.

        Args:
            base_min_edge: Normal minimum edge (e.g., 0.05)
            hours_remaining: Hours until resolution

        Returns:
            Adjusted minimum edge
        """
        config = self.get_config(hours_remaining)
        return base_min_edge * config.edge_multiplier

    def adjust_position_size(self, base_size: float, hours_remaining: float) -> float:
        """
        Adjust position size based on time remaining.

        Args:
            base_size: Calculated position size
            hours_remaining: Hours until resolution

        Returns:
            Adjusted position size
        """
        config = self.get_config(hours_remaining)
        return base_size * config.position_multiplier

    def should_trade(
        self,
        edge: float,
        confidence: float,
        hours_remaining: float,
        base_min_edge: float = 0.05
    ) -> Tuple[bool, str]:
        """
        Determine if a trade should be made given time urgency.

        Args:
            edge: Calculated edge
            confidence: Confidence level
            hours_remaining: Hours until resolution
            base_min_edge: Normal minimum edge

        Returns:
            Tuple of (should_trade, reason)
        """
        adjustment = self.calculate_adjustment(hours_remaining, base_min_edge)

        # Check confidence floor
        if confidence < adjustment.confidence_floor:
            return False, f"Confidence {confidence:.1%} below floor {adjustment.confidence_floor:.1%} for {adjustment.phase.value} phase"

        # Check edge threshold
        if edge < adjustment.adjusted_min_edge:
            return False, f"Edge {edge:.1%} below threshold {adjustment.adjusted_min_edge:.1%} for {adjustment.phase.value} phase"

        return True, adjustment.reason

    def get_phase_summary(self) -> List[Dict]:
        """Get summary of all phases for display."""
        return [{
            "phase": c.phase.value,
            "hours_range": f"{c.hours_min}-{c.hours_max}h",
            "edge_multiplier": c.edge_multiplier,
            "position_multiplier": c.position_multiplier,
            "confidence_floor": c.confidence_floor
        } for c in self.configs]


def create_custom_urgency_calculator(
    critical_hours: float = 2,
    urgent_hours: float = 8,
    approaching_hours: float = 24,
    normal_hours: float = 72,
    critical_edge_mult: float = 0.5,
    urgent_edge_mult: float = 0.7,
    critical_pos_mult: float = 1.5,
    urgent_pos_mult: float = 1.3
) -> TimeUrgencyCalculator:
    """
    Create a custom urgency calculator with specified thresholds.

    Args:
        critical_hours: Hours threshold for critical phase
        urgent_hours: Hours threshold for urgent phase
        approaching_hours: Hours threshold for approaching phase
        normal_hours: Hours threshold for normal phase
        critical_edge_mult: Edge multiplier in critical phase
        urgent_edge_mult: Edge multiplier in urgent phase
        critical_pos_mult: Position multiplier in critical phase
        urgent_pos_mult: Position multiplier in urgent phase

    Returns:
        Configured TimeUrgencyCalculator
    """
    configs = [
        UrgencyConfig(
            phase=UrgencyPhase.CRITICAL,
            hours_min=0,
            hours_max=critical_hours,
            edge_multiplier=critical_edge_mult,
            position_multiplier=critical_pos_mult,
            confidence_floor=0.70
        ),
        UrgencyConfig(
            phase=UrgencyPhase.URGENT,
            hours_min=critical_hours,
            hours_max=urgent_hours,
            edge_multiplier=urgent_edge_mult,
            position_multiplier=urgent_pos_mult,
            confidence_floor=0.65
        ),
        UrgencyConfig(
            phase=UrgencyPhase.APPROACHING,
            hours_min=urgent_hours,
            hours_max=approaching_hours,
            edge_multiplier=0.85,
            position_multiplier=1.1,
            confidence_floor=0.60
        ),
        UrgencyConfig(
            phase=UrgencyPhase.NORMAL,
            hours_min=approaching_hours,
            hours_max=normal_hours,
            edge_multiplier=1.0,
            position_multiplier=1.0,
            confidence_floor=0.60
        ),
        UrgencyConfig(
            phase=UrgencyPhase.DISTANT,
            hours_min=normal_hours,
            hours_max=float("inf"),
            edge_multiplier=1.2,
            position_multiplier=0.8,
            confidence_floor=0.70
        ),
    ]

    return TimeUrgencyCalculator(configs)
