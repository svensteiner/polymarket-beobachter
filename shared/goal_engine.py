"""
Goal Engine — Polymarket Beobachter.

Verfolgt Prediction-Market-Ziele und eskaliert bei Misserfolg:
  consecutive_fails=1 → Log-Warning
  consecutive_fails=2 → Improvement-Cycle forcieren
  consecutive_fails=3 → Proposal-Datei schreiben (human review)
  consecutive_fails>=4 → Ziel lockern (verhindert unmoeglich-Spirale)

Progressive Ziele:
  consecutive_wins>=3 → Ziel wird 10% anspruchsvoller

Persistenz: logs/bot_goals.json
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger("goal_engine")

PROJECT_ROOT = Path(__file__).parent.parent
GOALS_FILE = PROJECT_ROOT / "logs" / "bot_goals.json"
PROPOSALS_DIR = PROJECT_ROOT / "proposals"
PERFORMANCE_REPORT = PROJECT_ROOT / "analytics" / "performance_report.json"

COOLDOWN_HOURS = float(os.getenv("GOAL_ENGINE_COOLDOWN_HOURS", "6"))
MIN_CLOSED_POSITIONS = 3


@dataclass
class Goal:
    name: str
    metric: str       # "win_rate_pct" | "profit_factor" | "brier_score"
    target: float
    direction: str    # "above" | "below"
    consecutive_fails: int = 0
    consecutive_wins: int = 0
    last_checked: float = 0.0
    last_value: float = 0.0

    def check(self, value: float) -> bool:
        """True = Ziel erfuellt."""
        self.last_value = value
        if self.direction == "above":
            return value >= self.target
        return value <= self.target

    def tighten(self) -> None:
        """Ziel 10% schwieriger nach 3 aufeinanderfolgenden Wins."""
        if self.direction == "above":
            self.target = round(self.target * 1.10, 3)
        else:
            self.target = round(self.target * 0.90, 3)
        logger.info("[GOALS] Ziel '%s' verschaerft → %.3f", self.name, self.target)

    def relax(self) -> None:
        """Ziel 5% lockerer nach 4+ Fails."""
        if self.direction == "above":
            self.target = round(self.target * 0.95, 3)
        else:
            self.target = round(self.target * 1.05, 3)
        logger.info("[GOALS] Ziel '%s' gelockert → %.3f", self.name, self.target)


class GoalEngine:
    """Prueft Prediction-Market-Ziele und eskaliert bei Misserfolg."""

    DEFAULT_GOALS = [
        Goal("Win-Rate",      "win_rate_pct",  45.0, "above"),
        Goal("Profit-Factor", "profit_factor",  1.10, "above"),
        Goal("Brier-Score",   "brier_score",    0.25, "below"),
    ]

    def __init__(self) -> None:
        self._goals: list[Goal] = []
        self._last_run: float = 0.0
        self._load()

    def _load(self) -> None:
        try:
            data = json.loads(GOALS_FILE.read_text(encoding="utf-8"))
            self._goals = [Goal(**g) for g in data]
            logger.debug("[GOALS] %d Ziele geladen", len(self._goals))
        except (FileNotFoundError, json.JSONDecodeError, TypeError):
            self._goals = [Goal(**asdict(g)) for g in self.DEFAULT_GOALS]
            logger.info("[GOALS] Standard-Ziele initialisiert")

    def _save(self) -> None:
        try:
            GOALS_FILE.parent.mkdir(parents=True, exist_ok=True)
            GOALS_FILE.write_text(
                json.dumps([asdict(g) for g in self._goals], indent=2),
                encoding="utf-8",
            )
        except OSError as e:
            logger.warning("[GOALS] Speichern fehlgeschlagen: %s", e)

    def _get_metrics(self) -> dict:
        """Liest Performance-Metriken aus performance_report.json."""
        try:
            report = json.loads(PERFORMANCE_REPORT.read_text(encoding="utf-8"))
            metrics = report.get("metrics", {})
            calibration = report.get("calibration", {})
            return {
                "win_rate_pct": float(metrics.get("win_rate_pct", 0)),
                "profit_factor": float(metrics.get("profit_factor", 0)),
                "brier_score": calibration.get("brier_score") or 0.0,
                "total_pnl_eur": float(metrics.get("total_pnl_eur", 0)),
                "total_trades": int(metrics.get("total_trades", 0)),
            }
        except Exception as e:
            logger.debug("[GOALS] Metriken-Fehler: %s", e)
            return {}

    def _count_closed_positions(self) -> int:
        """Zaehlt geschlossene/aufgeloeste Positionen aus dem positions-Log."""
        try:
            from paper_trader.logger import get_paper_logger
            stats = get_paper_logger().get_statistics()
            return int(stats.get("closed_positions", 0))
        except Exception:
            return 0

    def run(self) -> None:
        """Hauptaufruf — prueft alle Ziele und eskaliert."""
        now = time.time()
        if (now - self._last_run) < COOLDOWN_HOURS * 3600:
            return
        self._last_run = now

        metrics = self._get_metrics()
        if not metrics:
            logger.debug("[GOALS] Keine Metriken verfuegbar")
            return

        closed = self._count_closed_positions()
        if closed < MIN_CLOSED_POSITIONS:
            logger.debug("[GOALS] Zu wenige geschlossene Positionen (%d) fuer Goal-Check", closed)
            return

        for goal in self._goals:
            raw = metrics.get(goal.metric)
            if raw is None:
                continue
            metric_val = float(raw)
            # Brier-Score 0.0 means no data — skip
            if goal.metric == "brier_score" and metric_val == 0.0:
                continue

            met = goal.check(metric_val)
            goal.last_checked = now

            if met:
                goal.consecutive_fails = 0
                goal.consecutive_wins += 1
                logger.info(
                    "[GOALS] ✅ '%s': %.2f %s %.2f",
                    goal.name,
                    metric_val,
                    ">" if goal.direction == "above" else "<",
                    goal.target,
                )
                if goal.consecutive_wins >= 3:
                    goal.tighten()
                    goal.consecutive_wins = 0
            else:
                goal.consecutive_fails += 1
                goal.consecutive_wins = 0
                logger.warning(
                    "[GOALS] ❌ '%s': %.2f (Ziel: %.2f) — Fail #%d",
                    goal.name,
                    metric_val,
                    goal.target,
                    goal.consecutive_fails,
                )
                self._escalate(goal, metric_val)

        self._save()

    def _escalate(self, goal: Goal, current_value: float) -> None:
        """Eskaliert je nach consecutive_fails-Stufe."""
        fails = goal.consecutive_fails

        if fails == 1:
            logger.warning(
                "[GOALS] Stufe 1 — Alert: '%s' = %.2f vs Ziel %.2f",
                goal.name, current_value, goal.target,
            )

        elif fails == 2:
            logger.warning("[GOALS] Stufe 2 — forciere Improvement-Cycle fuer '%s'", goal.name)
            try:
                from analytics.improvement_agent import run_improvement_cycle
                result = run_improvement_cycle()
                logger.info("[GOALS] Improvement-Cycle: action=%s", result.get("action"))
            except Exception as e:
                logger.error("[GOALS] Improvement-Cycle fehlgeschlagen: %s", e)

        elif fails >= 3:
            logger.error("[GOALS] Stufe 3 — schreibe Proposal fuer '%s'", goal.name)
            self._write_proposal(goal, current_value)
            if fails >= 4:
                goal.relax()

    def _write_proposal(self, goal: Goal, current_value: float) -> None:
        """Schreibt eine Proposal-Datei fuer menschliche Pruefung."""
        try:
            PROPOSALS_DIR.mkdir(parents=True, exist_ok=True)
            filename = f"goal_fail_{goal.name.replace(' ', '_')}_{int(time.time())}.json"
            p = PROPOSALS_DIR / filename
            p.write_text(json.dumps({
                "type": "goal_failure",
                "bot": "polymarket",
                "goal": goal.name,
                "metric": goal.metric,
                "target": goal.target,
                "current_value": current_value,
                "consecutive_fails": goal.consecutive_fails,
                "advisory_only": True,
                "created_at": datetime.now().isoformat(),
            }, indent=2), encoding="utf-8")
            logger.warning("[GOALS] Proposal geschrieben: %s", p.name)
        except OSError as e:
            logger.error("[GOALS] Proposal-Fehler: %s", e)


_engine: Optional[GoalEngine] = None


def get_goal_engine() -> GoalEngine:
    global _engine
    if _engine is None:
        _engine = GoalEngine()
    return _engine
