from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Tuple


class UrgencyPhase(str, Enum):
    CRITICAL = "critical"
    URGENT = "urgent"
    APPROACHING = "approaching"
    NORMAL = "normal"
    DISTANT = "distant"


@dataclass
class UrgencyAdjustment:
    phase: UrgencyPhase
    adjusted_min_edge: float
    adjusted_max_position: float


class TimeUrgencyCalculator:
    def __init__(
        self,
        critical_hours: float = 2.0,
        urgent_hours: float = 8.0,
        approaching_hours: float = 24.0,
        distant_hours: float = 72.0,
        critical_edge_mult: float = 0.5,
    ) -> None:
        self.critical_hours = critical_hours
        self.urgent_hours = urgent_hours
        self.approaching_hours = approaching_hours
        self.distant_hours = distant_hours
        self.critical_edge_mult = critical_edge_mult

    def get_phase(self, hours_remaining: float) -> UrgencyPhase:
        if hours_remaining <= self.critical_hours:
            return UrgencyPhase.CRITICAL
        if hours_remaining <= self.urgent_hours:
            return UrgencyPhase.URGENT
        if hours_remaining <= self.approaching_hours:
            return UrgencyPhase.APPROACHING
        if hours_remaining <= self.distant_hours:
            return UrgencyPhase.NORMAL
        return UrgencyPhase.DISTANT

    def calculate_adjustment(
        self,
        hours_remaining: float,
        base_min_edge: float = 0.05,
        base_max_position: float = 100.0,
    ) -> UrgencyAdjustment:
        phase = self.get_phase(hours_remaining)
        edge_mult = {
            UrgencyPhase.CRITICAL: self.critical_edge_mult,
            UrgencyPhase.URGENT: 0.65,
            UrgencyPhase.APPROACHING: 0.8,
            UrgencyPhase.NORMAL: 1.0,
            UrgencyPhase.DISTANT: 1.15,
        }[phase]
        pos_mult = {
            UrgencyPhase.CRITICAL: 1.5,
            UrgencyPhase.URGENT: 1.25,
            UrgencyPhase.APPROACHING: 1.1,
            UrgencyPhase.NORMAL: 1.0,
            UrgencyPhase.DISTANT: 0.85,
        }[phase]
        return UrgencyAdjustment(
            phase=phase,
            adjusted_min_edge=base_min_edge * edge_mult,
            adjusted_max_position=base_max_position * pos_mult,
        )

    def should_trade(
        self,
        edge: float,
        confidence: float,
        hours_remaining: float,
        base_min_edge: float = 0.05,
    ) -> tuple[bool, str]:
        adjustment = self.calculate_adjustment(hours_remaining, base_min_edge=base_min_edge)
        if confidence < 0.6:
            return False, "Confidence below floor"
        if edge < adjustment.adjusted_min_edge:
            return False, "Edge below floor"
        return True, "Trade allowed"


def create_custom_urgency_calculator(
    critical_hours: float = 2.0,
    urgent_hours: float = 8.0,
    critical_edge_mult: float = 0.5,
) -> TimeUrgencyCalculator:
    return TimeUrgencyCalculator(
        critical_hours=critical_hours,
        urgent_hours=urgent_hours,
        critical_edge_mult=critical_edge_mult,
    )
