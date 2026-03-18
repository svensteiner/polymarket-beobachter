from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List


@dataclass
class GoalState:
    capital_protection: str
    trade_quality: str
    calibration: str
    activity_level: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ActionProposal:
    action_type: str
    title: str
    rationale: str
    evidence: List[str] = field(default_factory=list)
    priority: str = "MEDIUM"
    risk_level: str = "LOW"
    status: str = "PROPOSED"
    params: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class AgentDecision:
    timestamp: str
    run_id: str
    mode: str
    summary: str
    hypothesis: str
    goals: GoalState
    context_snapshot: Dict[str, Any]
    proposed_actions: List[ActionProposal] = field(default_factory=list)
    blocked_actions: List[Dict[str, Any]] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["goals"] = self.goals.to_dict()
        data["proposed_actions"] = [action.to_dict() for action in self.proposed_actions]
        return data


@dataclass
class RunContext:
    timestamp: str
    run_id: str
    summary: Dict[str, Any]
    capital: Dict[str, Any]
    strategy_advice: Dict[str, Any]
    open_positions: List[Dict[str, Any]]
    recent_closed_positions: List[Dict[str, Any]]
    short_term_memory: Dict[str, Any]
    long_term_memory: Dict[str, Any]

    def snapshot(self) -> Dict[str, Any]:
        return {
            "state": self.summary.get("state", "UNKNOWN"),
            "market_condition": self.summary.get("market_condition", "WATCH"),
            "drawdown_pct": self.summary.get("drawdown_pct", 0.0),
            "bot_health_status": self.summary.get("bot_health_status", "UNKNOWN"),
            "open_positions": len(self.open_positions),
            "recent_closed_positions": len(self.recent_closed_positions),
            "available_capital_eur": self.capital.get("available_capital_eur", 0.0),
            "allocated_capital_eur": self.capital.get("allocated_capital_eur", 0.0),
            "paper_pnl_eur": self.summary.get("paper_pnl_eur", 0.0),
            "strategy_mode": self.strategy_advice.get("mode", "observe"),
        }

