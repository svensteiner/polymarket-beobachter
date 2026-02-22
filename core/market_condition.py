# =============================================================================
# POLYMARKET BEOBACHTER - MARKET CONDITION MONITOR
# =============================================================================
#
# GOVERNANCE INTENT:
# READ-ONLY State Machine fuer Marktbedingungen.
# Beobachtet - kontrolliert NICHTS, aendert NICHTS.
#
# STATE MACHINE (adaptiert aus tradingbot/shared/market_condition_monitor.py):
#   UNFAVORABLE: Schlechte Bedingungen (hohe Forecast-Unsicherheit, wenig Edge)
#   WATCH:       Neutrale Phase - vorsichtig beobachten
#   FAVORABLE:   Gute Bedingungen - normales Trading erlaubt
#
# WETTER-SPEZIFISCHE SIGNALE:
#   - Forecast-Qualitaet: Anzahl verfuegbarer Wetter-APIs
#   - Edge-Dichte: Wieviele Maerkte haben genug Edge
#   - Drawdown-Status: Aus DrawdownProtector
#   - Win-Rate: Aus Outcome-Analyser (wenn genug Daten)
#
# PAPER TRADING ONLY: Keine echten Trades werden kontrolliert.
#
# =============================================================================

from __future__ import annotations

import json
import logging
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# State-Persistenz
CONDITION_STATE_PATH = Path(__file__).parent.parent / "data" / "market_condition.json"


# =============================================================================
# STATE MACHINE
# =============================================================================

class MarketCondition(Enum):
    """Marktbedingung State Machine."""
    UNFAVORABLE = "UNFAVORABLE"   # Keine neuen Positionen empfohlen
    WATCH = "WATCH"               # Vorsichtig, reduziertes Sizing empfohlen
    FAVORABLE = "FAVORABLE"       # Normale Aktivitaet


# Schwellwerte fuer State-Uebergaenge
_THRESHOLDS = {
    # Mindest-Edge-Beobachtungen pro Run fuer FAVORABLE
    "min_edge_obs_favorable": 3,
    "min_edge_obs_watch": 1,
    # Drawdown Schwellen
    "dd_unfavorable_pct": 10.0,   # >= 10% DD -> UNFAVORABLE
    "dd_watch_pct": 5.0,           # >= 5% DD -> WATCH
    # Win-Rate Schwellen (wenn genug Daten)
    "min_win_rate_favorable": 45.0,  # >= 45% fuer FAVORABLE
    "min_trades_for_winrate": 10,     # Mindest-Trades fuer Win-Rate Check
}


# =============================================================================
# SIGNAL-BERECHNUNG
# =============================================================================

def _get_drawdown_signal() -> dict[str, Any]:
    """Hole Drawdown-Status aus DrawdownProtector."""
    try:
        from paper_trader.drawdown_protector import get_drawdown_status
        return get_drawdown_status()
    except Exception as e:
        logger.debug(f"Drawdown-Signal nicht verfuegbar: {e}")
        return {"current_dd_pct": 0.0, "sufficient_data": False}


def _get_performance_signal() -> dict[str, Any]:
    """Hole Performance-Metriken aus Outcome-Analyser (wenn Report vorhanden)."""
    report_path = Path(__file__).parent.parent / "analytics" / "performance_report.json"
    if not report_path.exists():
        return {"win_rate_pct": 0.0, "total_trades": 0, "profit_factor": 0.0}
    try:
        with open(report_path, "r", encoding="utf-8") as f:
            report = json.load(f)
        m = report.get("metrics", {})
        return {
            "win_rate_pct": m.get("win_rate_pct", 0.0),
            "total_trades": m.get("total_trades", 0),
            "profit_factor": m.get("profit_factor", 0.0),
        }
    except (json.JSONDecodeError, OSError) as e:
        logger.debug(f"Performance-Report nicht lesbar: {e}")
        return {"win_rate_pct": 0.0, "total_trades": 0, "profit_factor": 0.0}


# =============================================================================
# STATE-BERECHNUNG
# =============================================================================

def assess_market_condition(
    edge_observations_count: int = 0,
) -> dict[str, Any]:
    """
    Bewerte aktuelle Marktbedingungen und bestimme State.

    READ-ONLY: Diese Funktion beobachtet nur - sie aendert keine Konfiguration,
    startet keine Trades, setzt keine Parameter.

    Args:
        edge_observations_count: Anzahl der Edge-Beobachtungen im letzten Run

    Returns:
        Dict mit:
            condition   - MarketCondition (FAVORABLE/WATCH/UNFAVORABLE)
            signals     - Einzelsignale die zur Entscheidung beitrugen
            reasons     - Liste der Begruendungen
            suggestion  - Handlungsempfehlung (nur informativ)
    """
    dd = _get_drawdown_signal()
    perf = _get_performance_signal()

    reasons = []
    unfavorable_signals = 0
    watch_signals = 0

    # Signal 1: Drawdown
    dd_pct = dd.get("current_dd_pct", 0.0)
    if dd.get("sufficient_data", False):
        if dd_pct >= _THRESHOLDS["dd_unfavorable_pct"]:
            unfavorable_signals += 1
            reasons.append(f"Drawdown {dd_pct:.1f}% >= {_THRESHOLDS['dd_unfavorable_pct']}% [UNFAVORABLE]")
        elif dd_pct >= _THRESHOLDS["dd_watch_pct"]:
            watch_signals += 1
            reasons.append(f"Drawdown {dd_pct:.1f}% >= {_THRESHOLDS['dd_watch_pct']}% [WATCH]")
        else:
            reasons.append(f"Drawdown {dd_pct:.1f}% OK [+]")
    else:
        reasons.append("Drawdown: Zu wenig Daten (kein DD-Schutz)")

    # Signal 2: Edge-Dichte (Markt-Aktivitaet)
    if edge_observations_count >= _THRESHOLDS["min_edge_obs_favorable"]:
        reasons.append(f"Edge-Beobachtungen: {edge_observations_count} >= {_THRESHOLDS['min_edge_obs_favorable']} [+]")
    elif edge_observations_count >= _THRESHOLDS["min_edge_obs_watch"]:
        watch_signals += 1
        reasons.append(f"Edge-Beobachtungen: {edge_observations_count} (wenig) [WATCH]")
    else:
        watch_signals += 1
        reasons.append(f"Edge-Beobachtungen: {edge_observations_count} (keine) [WATCH]")

    # Signal 3: Win-Rate (nur wenn genug Trades vorhanden)
    total_trades = perf.get("total_trades", 0)
    if total_trades >= _THRESHOLDS["min_trades_for_winrate"]:
        win_rate = perf.get("win_rate_pct", 0.0)
        profit_factor = perf.get("profit_factor", 0.0)
        if win_rate < _THRESHOLDS["min_win_rate_favorable"]:
            unfavorable_signals += 1
            reasons.append(
                f"Win-Rate {win_rate:.1f}% < {_THRESHOLDS['min_win_rate_favorable']}% [UNFAVORABLE]"
            )
        elif profit_factor < 1.0:
            watch_signals += 1
            reasons.append(f"Profit-Factor {profit_factor:.2f} < 1.0 [WATCH]")
        else:
            reasons.append(f"Win-Rate {win_rate:.1f}% / PF {profit_factor:.2f} [+]")
    else:
        reasons.append(f"Win-Rate: Nur {total_trades} Trades (min {_THRESHOLDS['min_trades_for_winrate']})")

    # State bestimmen
    if unfavorable_signals >= 1:
        condition = MarketCondition.UNFAVORABLE
        suggestion = "Keine neuen Positionen empfohlen. Bestehende Positionen beobachten."
    elif watch_signals >= 2:
        condition = MarketCondition.WATCH
        suggestion = "Vorsichtig - reduziertes Position-Sizing empfohlen."
    else:
        condition = MarketCondition.FAVORABLE
        suggestion = "Normale Trading-Aktivitaet."

    result = {
        "condition": condition.value,
        "assessed_at": datetime.now().isoformat(),
        "signals": {
            "drawdown_pct": dd_pct,
            "edge_observations": edge_observations_count,
            "win_rate_pct": perf.get("win_rate_pct", 0.0),
            "total_trades": total_trades,
            "profit_factor": perf.get("profit_factor", 0.0),
        },
        "reasons": reasons,
        "suggestion": suggestion,
        "unfavorable_signal_count": unfavorable_signals,
        "watch_signal_count": watch_signals,
    }

    # State persistieren (fuer Status-Reporting)
    _save_condition(result)

    return result


def _save_condition(state: dict[str, Any]) -> None:
    """Speichere aktuellen Condition-State."""
    try:
        CONDITION_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(CONDITION_STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)
    except OSError as e:
        logger.debug(f"Condition-State nicht gespeichert: {e}")


def load_last_condition() -> dict[str, Any]:
    """
    Lade zuletzt berechneten Condition-State.

    Returns:
        Letzter State oder Default (WATCH) wenn kein State vorhanden.
    """
    if not CONDITION_STATE_PATH.exists():
        return {
            "condition": MarketCondition.WATCH.value,
            "assessed_at": None,
            "suggestion": "Noch keine Bewertung vorhanden.",
            "reasons": [],
        }
    try:
        with open(CONDITION_STATE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {
            "condition": MarketCondition.WATCH.value,
            "assessed_at": None,
            "suggestion": "State nicht lesbar.",
            "reasons": [],
        }


# =============================================================================
# STANDALONE / REPORTING
# =============================================================================

def print_condition(state: dict[str, Any] | None = None) -> None:
    """Drucke formatierten Condition-Report."""
    if state is None:
        state = load_last_condition()

    condition = state.get("condition", "UNKNOWN")
    icons = {"FAVORABLE": "[++]", "WATCH": "[~]", "UNFAVORABLE": "[--]"}
    icon = icons.get(condition, "[?]")

    print(f"\n{'='*50}")
    print(f"  MARKET CONDITION  {icon} {condition}")
    print(f"  {state.get('assessed_at', 'N/A')[:19]}")
    print(f"{'='*50}")
    for reason in state.get("reasons", []):
        print(f"  {reason}")
    print(f"{'='*50}")
    print(f"  Empfehlung: {state.get('suggestion', '')}")
    print(f"{'='*50}\n")


if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.WARNING)
    state = assess_market_condition(edge_observations_count=0)
    print_condition(state)
