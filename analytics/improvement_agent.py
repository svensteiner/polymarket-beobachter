"""
analytics/improvement_agent.py – Self-Improvement-Agent für Polymarket Beobachter.

Beobachtet Paper-Trading-Performance und optimiert kontinuierlich:
  - MIN_EDGE       (config/weather.yaml)
  - MAX_ODDS       (config/weather.yaml)
  - MIN_TIME_TO_RESOLUTION_HOURS (config/weather.yaml)
  - KELLY_FRACTION (paper_trader/kelly.py)
  - TAKE_PROFIT_PCT (paper_trader/position_manager.py)
  - STOP_LOSS_PCT  (paper_trader/position_manager.py)

Läuft am Ende jedes Orchestrator-Runs.

SELF-HEALING + AUTO-IMPROVEMENT:
- Erkennt Systemprobleme und heilt sie automatisch
- Passt Parameter automatisch an basierend auf Performance
- Alle Änderungen werden git-committed für Nachvollziehbarkeit
- Max 1 Änderung pro Stunde, nur innerhalb sicherer Grenzen
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict

# Import des neuen Self-Healing Systems
from shared.self_healing import (
    AutoCodeImprover,
    SelfHealingMonitor,
    check_and_heal,
    run_auto_improvement,
    record_pipeline_success,
    record_pipeline_failure,
    IssueType,
)

logger = logging.getLogger("improvement.polymarket")

PROJECT_DIR = Path(__file__).parent.parent


# ---------------------------------------------------------------------------
# Convenience-Funktionen für Orchestrator
# ---------------------------------------------------------------------------

def run_improvement_cycle() -> Dict[str, Any]:
    """
    Starte einen vollständigen Improvement-Cycle:
    1. Health Check + Auto-Healing
    2. Auto-Code-Improvement basierend auf Metrics

    Non-blocking – Exceptions werden gefangen.
    """
    try:
        # Step 1: Health Check und Healing
        health_result = check_and_heal()

        # Step 2: Auto-Code-Improvement
        improvement_result = run_auto_improvement()

        # Kombiniertes Ergebnis
        return {
            "action": improvement_result.get("action", "none"),
            "param": improvement_result.get("param"),
            "old": improvement_result.get("old"),
            "new": improvement_result.get("new"),
            "reasoning": improvement_result.get("reasoning", improvement_result.get("reason", "")),
            "commit": improvement_result.get("commit"),
            "health_status": health_result.get("status", "UNKNOWN"),
            "health_issues": health_result.get("issues", []),
            "health_actions": health_result.get("actions", []),
        }

    except Exception as e:
        logger.debug(f"Polymarket Improvement Cycle fehlgeschlagen (unkritisch): {e}")
        return {"action": "error", "error": str(e)}


def run_health_check() -> Dict[str, Any]:
    """Nur Health-Check ohne Improvement."""
    try:
        return check_and_heal()
    except Exception as e:
        logger.debug(f"Health Check fehlgeschlagen: {e}")
        return {"status": "ERROR", "error": str(e)}


def notify_pipeline_success() -> None:
    """Benachrichtige das Self-Healing-System über erfolgreichen Pipeline-Run."""
    try:
        record_pipeline_success()
    except Exception as e:
        logger.debug(f"Pipeline-Success-Notification fehlgeschlagen: {e}")


def notify_pipeline_failure(error_type: str = "UNKNOWN") -> None:
    """Benachrichtige das Self-Healing-System über fehlgeschlagenen Pipeline-Run."""
    try:
        issue_map = {
            "API_TIMEOUT": IssueType.API_TIMEOUT,
            "RATE_LIMIT": IssueType.API_RATE_LIMIT,
            "MEMORY": IssueType.MEMORY_PRESSURE,
            "NETWORK": IssueType.NETWORK_ERROR,
        }
        issue = issue_map.get(error_type.upper())
        record_pipeline_failure(issue)
    except Exception as e:
        logger.debug(f"Pipeline-Failure-Notification fehlgeschlagen: {e}")


# ---------------------------------------------------------------------------
# Legacy-Kompatibilität (falls alter Code noch aufgerufen wird)
# ---------------------------------------------------------------------------

class PolymarketImprovementAgent:
    """Legacy-Wrapper für Rückwärtskompatibilität."""

    bot_name = "polymarket"

    def __init__(self):
        self._improver = AutoCodeImprover(PROJECT_DIR)
        self._healer = SelfHealingMonitor(PROJECT_DIR)

    def observe(self):
        return self._improver.observe_metrics()

    def run_improvement_cycle(self) -> Dict[str, Any]:
        return run_improvement_cycle()

    def get_governance_bounds(self) -> Dict[str, Dict]:
        return self._improver.PARAMETERS
