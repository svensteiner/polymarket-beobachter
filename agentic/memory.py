from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from .state import AgentDecision, RunContext


class AgentMemoryStore:
    def __init__(self, base_dir: Path):
        self.base_dir = base_dir
        self.memory_dir = self.base_dir / "data" / "agent_memory"
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        self.short_term_path = self.memory_dir / "short_term.json"
        self.long_term_path = self.memory_dir / "long_term.json"
        self.decision_log_path = self.base_dir / "output" / "agent_decisions.jsonl"

    def load_short_term(self) -> Dict[str, Any]:
        return self._load_json(
            self.short_term_path,
            {"recent_runs": [], "active_hypotheses": [], "blocked_actions": []},
        )

    def load_long_term(self) -> Dict[str, Any]:
        return self._load_json(
            self.long_term_path,
            {
                "agent_version": "sprint1",
                "last_updated": None,
                "regime_counts": {},
                "action_stats": {},
                "learned_patterns": [],
            },
        )

    def persist(self, context: RunContext, decision: AgentDecision) -> None:
        short_term = self.load_short_term()
        long_term = self.load_long_term()

        run_entry = {
            "timestamp": context.timestamp,
            "run_id": context.run_id,
            "mode": decision.mode,
            "summary": decision.summary,
            "hypothesis": decision.hypothesis,
            "state": context.summary.get("state", "UNKNOWN"),
            "drawdown_pct": context.summary.get("drawdown_pct", 0.0),
            "market_condition": context.summary.get("market_condition", "WATCH"),
            "bot_health_status": context.summary.get("bot_health_status", "UNKNOWN"),
            "paper_pnl_eur": context.summary.get("paper_pnl_eur", 0.0),
            "open_positions": len(context.open_positions),
            "proposed_actions": [item.to_dict() for item in decision.proposed_actions],
        }

        recent_runs: List[Dict[str, Any]] = list(short_term.get("recent_runs", []))
        recent_runs.append(run_entry)
        short_term["recent_runs"] = recent_runs[-50:]
        short_term["active_hypotheses"] = [decision.hypothesis]
        short_term["blocked_actions"] = decision.blocked_actions[-20:]
        short_term["last_updated"] = context.timestamp

        regime = decision.mode
        regime_counts = dict(long_term.get("regime_counts", {}))
        regime_counts[regime] = int(regime_counts.get(regime, 0)) + 1
        long_term["regime_counts"] = regime_counts

        action_stats = dict(long_term.get("action_stats", {}))
        for proposal in decision.proposed_actions:
            stats = dict(action_stats.get(proposal.action_type, {}))
            stats["count"] = int(stats.get("count", 0)) + 1
            stats["last_seen"] = context.timestamp
            stats["last_priority"] = proposal.priority
            action_stats[proposal.action_type] = stats
        long_term["action_stats"] = action_stats

        patterns = list(long_term.get("learned_patterns", []))
        pattern = self._derive_pattern(context, decision)
        if pattern and pattern not in patterns:
            patterns.append(pattern)
        long_term["learned_patterns"] = patterns[-20:]
        long_term["last_updated"] = context.timestamp

        self._write_json(self.short_term_path, short_term)
        self._write_json(self.long_term_path, long_term)
        self._append_jsonl(self.decision_log_path, decision.to_dict())

    @staticmethod
    def _derive_pattern(context: RunContext, decision: AgentDecision) -> str:
        if context.summary.get("drawdown_recovery_mode"):
            return "Recovery mode repeats when drawdown remains elevated."
        if context.summary.get("high_price_open_positions", 0) > 0:
            return "High-price entries require explicit audit before active agent execution."
        if decision.mode == "DEFENSIVE" and len(context.open_positions) >= 5:
            return "DEFENSIVE mode correlates with elevated open-position inventory."
        return ""

    @staticmethod
    def _load_json(path: Path, default: Dict[str, Any]) -> Dict[str, Any]:
        if not path.exists():
            return default
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return default

    @staticmethod
    def _write_json(path: Path, payload: Dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    @staticmethod
    def _append_jsonl(path: Path, payload: Dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")

