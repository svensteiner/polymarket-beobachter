from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from .governor import AgentGovernor
from .memory import AgentMemoryStore
from .state import ActionProposal, AgentDecision, GoalState, RunContext

logger = logging.getLogger(__name__)


class AgentLoop:
    def __init__(self, base_dir: Path):
        self.base_dir = base_dir
        self.memory = AgentMemoryStore(base_dir)
        self.governor = AgentGovernor()

    def run(self, summary: Dict[str, Any]) -> Dict[str, Any]:
        context = self._build_context(summary)
        goals = self._build_goals(context)
        mode = self._detect_mode(context)
        hypothesis = self._build_hypothesis(context, mode)
        proposals = self._propose_actions(context, mode)
        validation = self.governor.validate(proposals, context)

        decision = AgentDecision(
            timestamp=context.timestamp,
            run_id=context.run_id,
            mode=mode,
            summary=self._build_summary_line(context, mode, validation["approved"]),
            hypothesis=hypothesis,
            goals=goals,
            context_snapshot=context.snapshot(),
            proposed_actions=validation["approved"],
            blocked_actions=validation["blocked"],
            notes=self._build_notes(context),
        )
        self.memory.persist(context, decision)

        return {
            "mode": decision.mode,
            "summary": decision.summary,
            "hypothesis": decision.hypothesis,
            "proposed_actions": [item.to_dict() for item in decision.proposed_actions],
            "blocked_actions": decision.blocked_actions,
            "decision_log": str(self.memory.decision_log_path),
        }

    def _build_context(self, summary: Dict[str, Any]) -> RunContext:
        short_term = self.memory.load_short_term()
        long_term = self.memory.load_long_term()
        timestamp = str(summary.get("run_time") or datetime.now().isoformat())
        run_id = str(summary.get("run_id", "UNKNOWN"))

        return RunContext(
            timestamp=timestamp,
            run_id=run_id,
            summary=summary,
            capital=self._load_json(self.base_dir / "data" / "capital_config.json", {}),
            strategy_advice=self._load_json(self.base_dir / "output" / "strategy_advice.json", {}),
            open_positions=self._load_positions(status="OPEN"),
            recent_closed_positions=self._load_positions(statuses={"CLOSED", "RESOLVED"}, limit=10),
            short_term_memory=short_term,
            long_term_memory=long_term,
        )

    def _build_goals(self, context: RunContext) -> GoalState:
        recovery = bool(context.summary.get("drawdown_recovery_mode"))
        bot_health = str(context.summary.get("bot_health_status", "UNKNOWN")).upper()
        advice_mode = str(context.strategy_advice.get("mode", "observe")).lower()

        capital_protection = "HIGH" if recovery or bot_health in {"DEGRADED", "CRITICAL"} else "MEDIUM"
        trade_quality = "HIGH" if advice_mode in {"protect", "tighten", "attack"} else "MEDIUM"
        calibration = "MEDIUM"
        activity_level = "HIGH" if advice_mode == "attack" else ("LOW" if recovery or advice_mode == "protect" else "MEDIUM")

        return GoalState(
            capital_protection=capital_protection,
            trade_quality=trade_quality,
            calibration=calibration,
            activity_level=activity_level,
        )

    def _detect_mode(self, context: RunContext) -> str:
        if context.summary.get("drawdown_recovery_mode"):
            return "DEFENSIVE"
        advice_mode = str(context.strategy_advice.get("mode", "")).lower()
        if advice_mode == "protect":
            return "DEFENSIVE"
        if advice_mode == "attack":
            return "ATTACK"
        if context.summary.get("bot_health_guardrails_active"):
            return "DEFENSIVE"
        if context.summary.get("edge_observations", 0) == 0 and len(context.open_positions) == 0:
            return "OBSERVE_ONLY"
        return "NORMAL"

    def _build_hypothesis(self, context: RunContext, mode: str) -> str:
        issues = context.strategy_advice.get("issues", [])
        if mode == "DEFENSIVE" and issues:
            return f"Kapitalschutz priorisieren; Hauptproblem aktuell: {issues[0]}."
        if mode == "ATTACK":
            attack_score = float(context.strategy_advice.get("metrics_snapshot", {}).get("attack_score", 0.0) or 0.0)
            return (
                f"Attack-Mode ist vertretbar; Score {attack_score:.2f} spricht fuer selektiv groessere Bets "
                "auf die besten Setups und Arbitrage-Fenster."
            )
        if context.summary.get("high_price_open_positions", 0) > 0:
            return "Ein Teil der Underperformance koennte aus zu teuren Entries statt aus Forecast-Qualitaet kommen."
        if context.summary.get("edge_observations", 0) == 0:
            return "Der Markt liefert aktuell zu wenige robuste Edges; Beobachtung ist sinnvoller als aggressives Handeln."
        return "Die aktuelle Policy ist nutzbar, braucht aber strukturierte Diagnostik pro Marktregime."

    def _propose_actions(self, context: RunContext, mode: str) -> List[ActionProposal]:
        proposals: List[ActionProposal] = []
        issues = context.strategy_advice.get("issues", [])
        weak_cities = context.strategy_advice.get("weak_cities", [])
        attack_score = float(context.strategy_advice.get("metrics_snapshot", {}).get("attack_score", 0.0) or 0.0)
        attack_components = context.strategy_advice.get("metrics_snapshot", {}).get("attack_components", {})
        attack_buckets = context.strategy_advice.get("metrics_snapshot", {}).get("attack_signals", {})

        if mode == "DEFENSIVE":
            proposals.append(ActionProposal(
                action_type="tighten_risk",
                title="Risk-Regeln enger simulieren",
                rationale="Drawdown/Protect-Modus spricht fuer strengere Entries und kleineres Risiko.",
                evidence=[
                    f"drawdown={context.summary.get('drawdown_pct', 0.0):.1f}%",
                    f"bot_health={context.summary.get('bot_health_status', 'UNKNOWN')}",
                    f"strategy_mode={context.strategy_advice.get('mode', 'observe')}",
                ],
                priority="HIGH",
                params={
                    "target": "entry_filters_and_kelly",
                    "reason": "defensive_mode",
                },
            ))

        if weak_cities:
            proposals.append(ActionProposal(
                action_type="pause_city",
                title="Schwache Staedte auf Cooldown pruefen",
                rationale="Wiederholt schwache Staedte sollten zuerst im Agent-Layer markiert werden.",
                evidence=[city.get("city", "") for city in weak_cities[:3] if city.get("city")],
                priority="HIGH" if mode == "DEFENSIVE" else "MEDIUM",
                params={"cities": [city.get("city") for city in weak_cities[:3] if city.get("city")]},
            ))

        if context.summary.get("high_price_open_positions", 0) > 0:
            proposals.append(ActionProposal(
                action_type="audit_entry_guardrails",
                title="Auffaellige High-Price-Entries auditieren",
                rationale="Offene Positionen mit hohem Entry-Preis sind fuer konservative Agentik kritisch.",
                evidence=[f"high_price_open_positions={context.summary.get('high_price_open_positions', 0)}"],
                priority="HIGH",
            ))

        if "selection_execution_gap" in issues or "entry_quality_too_weak" in issues:
            proposals.append(ActionProposal(
                action_type="start_shadow_experiment",
                title="Shadow-Test fuer strengere Entry-Selektion vorbereiten",
                rationale="Die Strategie scheint eher an Selektion/Execution als an Forecast-Kalibrierung zu leiden.",
                evidence=issues[:2],
                priority="MEDIUM",
                params={"experiment": "stricter_entry_filters"},
            ))

        if mode == "ATTACK":
            proposals.append(ActionProposal(
                action_type="scale_attack",
                title="Attack-Mode auf Top-Signale beschraenken",
                rationale="Gute Scores rechtfertigen mehr Druck, aber nur auf die saubersten Kanten.",
                evidence=[
                    f"attack_score={attack_score:.2f}",
                    f"performance={attack_components.get('performance', 0.0):.2f}",
                    f"arbitrage={attack_components.get('arbitrage', 0.0):.2f}",
                    f"smart_money={attack_components.get('smart_money', 0.0):.2f}",
                    f"arbitrage_opportunities={attack_buckets.get('arbitrage_opportunities', 0)}",
                ],
                priority="HIGH",
                params={
                    "target": "attack_policy",
                    "reason": "high_attack_score",
                },
            ))

        recent_runs = context.short_term_memory.get("recent_runs", [])
        if recent_runs:
            last_mode = recent_runs[-1].get("mode")
            if last_mode == mode and mode == "DEFENSIVE":
                proposals.append(ActionProposal(
                    action_type="revert_last_change",
                    title="Juengste Aenderungen auf Rollback-Bedarf pruefen",
                    rationale="Anhaltender Defensive-Modus rechtfertigt einen strukturierten Blick auf juengste Eingriffe.",
                    evidence=[f"last_mode={last_mode}", f"recent_runs={len(recent_runs)}"],
                    priority="MEDIUM",
                ))

        return proposals

    @staticmethod
    def _build_summary_line(
        context: RunContext,
        mode: str,
        approved_actions: List[ActionProposal],
    ) -> str:
        return (
            f"{mode}: {len(approved_actions)} read-only action(s) | "
            f"Open={len(context.open_positions)} | "
            f"DD={context.summary.get('drawdown_pct', 0.0):.1f}% | "
            f"BotHealth={context.summary.get('bot_health_status', 'UNKNOWN')}"
        )

    @staticmethod
    def _build_notes(context: RunContext) -> List[str]:
        notes: List[str] = []
        if context.summary.get("paper_pnl_eur", 0.0) < 0:
            notes.append("Paper-PnL des aktuellen Runs ist negativ oder flach.")
        if context.summary.get("edge_observations", 0) == 0:
            notes.append("Keine neuen Edge-Beobachtungen in diesem Run.")
        if not context.recent_closed_positions:
            notes.append("Keine juengst geschlossenen Positionen fuer schnelle Wirkungsmessung.")
        blocked_ratio = float(context.summary.get("guardrail_blocked_ratio", 0.0) or 0.0)
        if blocked_ratio >= 0.8:
            notes.append("Guardrails blocken derzeit einen sehr hohen Anteil der Eintritte; Policy-Feintuning pruefen.")
        return notes

    def _load_positions(self, status: str | None = None, statuses: set[str] | None = None, limit: int | None = None) -> List[Dict[str, Any]]:
        path = self.base_dir / "paper_trader" / "logs" / "paper_positions.jsonl"
        if not path.exists():
            return []

        # Deduplicate by position_id: keep the latest record per position.
        # The JSONL is append-only: OPEN first, then CLOSED/EXPIRED on resolution.
        # Without dedup, status="OPEN" returns all historical OPEN entries,
        # making the agent think all past positions are still open.
        latest_by_id: Dict[str, Any] = {}
        orphans: List[Dict[str, Any]] = []  # records without a position_id
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if payload.get("_type") == "LOG_HEADER":
                continue
            pid = payload.get("position_id")
            if pid:
                latest_by_id[pid] = payload  # last write wins
            else:
                orphans.append(payload)

        all_latest = list(latest_by_id.values()) + orphans

        # Filter by requested status(es)
        items: List[Dict[str, Any]] = []
        for payload in all_latest:
            item_status = str(payload.get("status", "")).upper()
            if status and item_status != status.upper():
                continue
            if statuses and item_status not in {value.upper() for value in statuses}:
                continue
            items.append(payload)

        if statuses:
            items.sort(key=lambda item: item.get("exit_time") or item.get("entry_time") or "", reverse=True)
        else:
            items.sort(key=lambda item: item.get("entry_time") or "", reverse=True)

        return items[:limit] if limit else items

    @staticmethod
    def _load_json(path: Path, default: Dict[str, Any]) -> Dict[str, Any]:
        if not path.exists():
            return default
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            logger.debug("AgentLoop konnte %s nicht lesen", path)
            return default
