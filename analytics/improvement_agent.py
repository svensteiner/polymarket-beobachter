"""
analytics/improvement_agent.py – Self-Improvement-Agent für Polymarket Beobachter.

Beobachtet Paper-Trading-Performance und optimiert kontinuierlich:
  - MIN_EDGE       (config/weather.yaml)
  - MIN_ODDS       (config/weather.yaml)
  - MIN_TIME_TO_RESOLUTION_HOURS (config/weather.yaml)
  - KELLY_FRACTION (paper_trader/kelly.py)

Läuft am Ende jedes Orchestrator-Runs.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from typing import Any

# Self-Improvement-Basis aus tools/
import sys
_TOOLS = Path(__file__).parent.parent.parent.parent / "tools"
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

from self_improvement_agent import SelfImprovementAgent, Metrics

logger = logging.getLogger("improvement.polymarket")

PROJECT_DIR = Path(__file__).parent.parent


class PolymarketImprovementAgent(SelfImprovementAgent):
    bot_name = "polymarket"

    def __init__(self):
        super().__init__(project_dir=PROJECT_DIR)

    # -----------------------------------------------------------------------
    # observe() – lese aktuelle Paper-Trading-Performance
    # -----------------------------------------------------------------------

    def observe(self) -> Metrics:
        """
        Lese Performance aus analytics/performance_report.json falls vorhanden,
        sonst aus paper_trader/positions direkt.
        """
        report_file = PROJECT_DIR / "analytics" / "performance_report.json"

        if report_file.exists():
            try:
                return self._observe_from_report(report_file)
            except Exception as e:
                logger.debug(f"performance_report.json Fehler: {e}")

        return self._observe_from_positions()

    def _observe_from_report(self, report_file: Path) -> Metrics:
        data = json.loads(report_file.read_text(encoding="utf-8"))
        total = data.get("total_trades", data.get("total_closed", 0))
        wins = data.get("wins", data.get("winning_trades", 0))
        win_rate = data.get("win_rate", wins / total if total > 0 else 0.0)
        pf = data.get("profit_factor", 0.0)
        avg_loss = abs(data.get("avg_loss_pct", data.get("avg_loss", 0.0)))
        avg_win = abs(data.get("avg_win_pct", data.get("avg_win", 0.0)))

        return Metrics(
            win_rate=float(win_rate),
            profit_factor=float(pf),
            total_trades=int(total),
            avg_loss_pct=float(avg_loss),
            avg_win_pct=float(avg_win),
            extra={
                "stop_loss_count": data.get("stop_loss_count", 0),
                "source": "performance_report.json",
            },
        )

    def _observe_from_positions(self) -> Metrics:
        """Direkte Auswertung aus Paper-Trader-Positions-Dateien."""
        try:
            positions_dir = PROJECT_DIR / "paper_trader" / "positions"
            if not positions_dir.exists():
                return Metrics()

            closed = []
            for f in positions_dir.glob("*.json"):
                try:
                    d = json.loads(f.read_text(encoding="utf-8"))
                    if d.get("status") in ("closed", "stop_loss", "take_profit", "expired"):
                        closed.append(d)
                except Exception:
                    pass

            if not closed:
                return Metrics()

            wins = [p for p in closed if p.get("pnl_eur", 0) > 0]
            losses = [p for p in closed if p.get("pnl_eur", 0) <= 0]
            win_rate = len(wins) / len(closed)

            gross_win = sum(p.get("pnl_eur", 0) for p in wins)
            gross_loss = abs(sum(p.get("pnl_eur", 0) for p in losses)) or 1e-9
            pf = gross_win / gross_loss

            def _loss_pct(p: dict) -> float:
                cost = p.get("cost_eur", p.get("size_eur", 1))
                return abs(p.get("pnl_eur", 0)) / max(cost, 1) * 100

            avg_loss = (sum(_loss_pct(p) for p in losses) / len(losses)) if losses else 0.0
            avg_win = (sum(_loss_pct(p) for p in wins) / len(wins)) if wins else 0.0
            sl_count = sum(1 for p in closed if p.get("status") == "stop_loss")

            return Metrics(
                win_rate=win_rate,
                profit_factor=pf,
                total_trades=len(closed),
                avg_loss_pct=avg_loss,
                avg_win_pct=avg_win,
                extra={"stop_loss_count": sl_count, "source": "positions_dir"},
            )
        except Exception as e:
            logger.debug(f"observe_from_positions Fehler: {e}")
            return Metrics()

    # -----------------------------------------------------------------------
    # get_governance_bounds()
    # -----------------------------------------------------------------------

    def get_governance_bounds(self) -> dict[str, dict]:
        return {
            "MIN_EDGE": {
                "file": "config/weather.yaml",
                "patch_type": "yaml",
                "min": 0.08,
                "max": 0.20,
                "step": 0.02,
                "min_trades_to_evaluate": 5,
                "description": "Minimum relativer Edge für BUY-Signal",
            },
            "MIN_ODDS": {
                "file": "config/weather.yaml",
                "patch_type": "yaml",
                "min": 0.05,
                "max": 0.25,
                "step": 0.02,
                "min_trades_to_evaluate": 5,
                "description": "Minimum Markt-Odds für Kandidaten",
            },
            "MIN_TIME_TO_RESOLUTION_HOURS": {
                "file": "config/weather.yaml",
                "patch_type": "yaml",
                "min": 12,
                "max": 72,
                "step": 12,
                "min_trades_to_evaluate": 5,
                "description": "Mindest-Restlaufzeit bis Market-Resolution",
            },
            "KELLY_FRACTION": {
                "file": "paper_trader/kelly.py",
                "patch_type": "py_const",
                "min": 0.10,
                "max": 0.35,
                "step": 0.05,
                "min_trades_to_evaluate": 8,
                "description": "Kelly-Fraction für Position-Sizing",
            },
        }


# ---------------------------------------------------------------------------
# Convenience-Funktion für Orchestrator
# ---------------------------------------------------------------------------

_agent: PolymarketImprovementAgent | None = None


def run_improvement_cycle() -> dict:
    """Starte einen Improvement-Cycle. Non-blocking – Exceptions werden gefangen."""
    global _agent
    try:
        if _agent is None:
            _agent = PolymarketImprovementAgent()
        return _agent.run_improvement_cycle()
    except Exception as e:
        logger.debug(f"Polymarket Improvement Cycle fehlgeschlagen (unkritisch): {e}")
        return {"action": "error", "error": str(e)}
