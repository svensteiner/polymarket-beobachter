# =============================================================================
# POLYMARKET BEOBACHTER - DRAWDOWN PROTECTOR
# =============================================================================
#
# GOVERNANCE INTENT:
# Schuetzt das Portfolio vor uebermäßigen Verlusten durch Drawdown-Monitoring.
# READ-ONLY bezueglich Trading-Entscheidungen: liefert nur go/no-go Signal.
#
# LOGIK (adaptiert aus tradingbot/shared/portfolio_risk_manager.py):
# - DD > 5%  (RECOVERY_THRESHOLD): Keine neuen Positionen erlaubt
# - DD > 10% (REDUCE_THRESHOLD):   Positions-Sizing linear reduzieren
#
# EQUITY-HISTORY:
# Gespeichert in data/equity_snapshots.jsonl (append-only).
# Ein Snapshot pro Pipeline-Run.
#
# PAPER TRADING ONLY:
# Alle Werte sind simuliert - kein echtes Kapital.
#
# =============================================================================

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Tuple

logger = logging.getLogger(__name__)

# Schwellwerte (matching Tradingbot-Logik)
RECOVERY_THRESHOLD_PCT: float = 5.0   # Ab 5% DD: keine neuen Positionen
REDUCE_THRESHOLD_PCT: float = 10.0    # Ab 10% DD: lineare Größenreduktion

# Mindestanzahl Datenpunkte für verlässliche Berechnung
MIN_DATA_POINTS: int = 3

EQUITY_LOG_PATH = Path(__file__).parent.parent / "data" / "equity_snapshots.jsonl"


# =============================================================================
# EQUITY HISTORY
# =============================================================================

def record_equity_snapshot(equity_eur: float, reason: str = "") -> None:
    """
    Speichere aktuellen Equity-Wert in Append-Only Log.

    Wird einmal pro Pipeline-Run aufgerufen, NACHDEM Capital-Manager
    den State aktualisiert hat.

    Args:
        equity_eur: Aktueller Gesamtwert (available + allocated)
        reason: Optionale Beschreibung (z.B. "pipeline_run")
    """
    EQUITY_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "timestamp": datetime.now().isoformat(),
        "equity_eur": round(equity_eur, 2),
        "reason": reason,
    }
    try:
        with open(EQUITY_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
        logger.debug(f"Equity-Snapshot: {equity_eur:.2f} EUR ({reason})")
    except OSError as e:
        logger.warning(f"Equity-Snapshot nicht gespeichert: {e}")


def _load_equity_history(max_entries: int = 500) -> list:
    """
    Lade Equity-History aus Log-Datei.

    Args:
        max_entries: Maximal letzte N Eintraege laden

    Returns:
        Liste von Equity-Werten (chronologisch, aelteste zuerst)
    """
    if not EQUITY_LOG_PATH.exists():
        return []

    entries = []
    try:
        with open(EQUITY_LOG_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    equity = float(obj["equity_eur"])
                    if equity > 0:
                        entries.append(equity)
                except (json.JSONDecodeError, KeyError, ValueError):
                    pass
    except OSError as e:
        logger.warning(f"Equity-Log nicht lesbar: {e}")
        return []

    # Letzte N Eintraege
    return entries[-max_entries:] if len(entries) > max_entries else entries


# =============================================================================
# DRAWDOWN BERECHNUNG
# =============================================================================

def _compute_drawdown(equity_history: list) -> dict:
    """
    Berechne Drawdown-Metriken aus Equity-History (pure Python, kein numpy).

    Args:
        equity_history: Chronologische Liste von Equity-Werten

    Returns:
        Dict mit current_dd_pct, max_dd_pct, peak_eur, trough_eur
    """
    if len(equity_history) < 2:
        first = equity_history[0] if equity_history else 0.0
        return {
            "current_dd_pct": 0.0,
            "max_dd_pct": 0.0,
            "peak_eur": first,
            "trough_eur": first,
        }

    peak = equity_history[0]
    max_dd = 0.0
    current_dd = 0.0
    trough = equity_history[0]

    for i, equity in enumerate(equity_history):
        # Peak aktualisieren
        if equity > peak:
            peak = equity

        # Drawdown berechnen
        if peak > 0:
            dd = (peak - equity) / peak * 100.0
        else:
            dd = 0.0

        if dd > max_dd:
            max_dd = dd
            trough = equity

        # Letzter Wert = aktueller DD
        if i == len(equity_history) - 1:
            current_dd = dd

    return {
        "current_dd_pct": round(current_dd, 2),
        "max_dd_pct": round(max_dd, 2),
        "peak_eur": round(peak, 2),
        "trough_eur": round(trough, 2),
    }


# =============================================================================
# PUBLIC API
# =============================================================================

def get_drawdown_status() -> dict:
    """
    Berechne aktuellen Drawdown-Status inkl. Recovery-Mode und Size-Faktor.

    Returns:
        Dict mit:
            current_dd_pct   - Aktueller Drawdown in %
            max_dd_pct       - Maximaler historischer Drawdown in %
            peak_eur         - Equity-Hochpunkt
            trough_eur       - Equity-Tiefpunkt bei Max-DD
            is_recovery_mode - True wenn DD >= RECOVERY_THRESHOLD (5%)
            size_factor      - Positionsgroessen-Faktor (1.0=normal, 0.0=gestoppt)
            data_points      - Anzahl verfuegbarer Datenpunkte
            sufficient_data  - True wenn genug Datenpunkte fuer Berechnung
    """
    history = _load_equity_history()
    data_points = len(history)
    sufficient = data_points >= MIN_DATA_POINTS

    if not sufficient:
        return {
            "current_dd_pct": 0.0,
            "max_dd_pct": 0.0,
            "peak_eur": history[0] if history else 0.0,
            "trough_eur": history[0] if history else 0.0,
            "is_recovery_mode": False,
            "size_factor": 1.0,
            "data_points": data_points,
            "sufficient_data": False,
        }

    dd = _compute_drawdown(history)
    current_dd = dd["current_dd_pct"]

    # Recovery-Mode: keine neuen Positionen
    is_recovery = current_dd >= RECOVERY_THRESHOLD_PCT

    # Lineare Größenreduktion ab RECOVERY_THRESHOLD bis REDUCE_THRESHOLD
    if current_dd <= RECOVERY_THRESHOLD_PCT:
        size_factor = 1.0
    elif current_dd >= REDUCE_THRESHOLD_PCT:
        size_factor = 0.0
    else:
        # Linear skalieren zwischen RECOVERY (5%) und REDUCE (10%)
        range_pct = REDUCE_THRESHOLD_PCT - RECOVERY_THRESHOLD_PCT
        size_factor = 1.0 - (current_dd - RECOVERY_THRESHOLD_PCT) / range_pct

    return {
        "current_dd_pct": current_dd,
        "max_dd_pct": dd["max_dd_pct"],
        "peak_eur": dd["peak_eur"],
        "trough_eur": dd["trough_eur"],
        "is_recovery_mode": is_recovery,
        "size_factor": round(size_factor, 4),
        "data_points": data_points,
        "sufficient_data": sufficient,
    }


def check_can_open_position() -> Tuple[bool, str]:
    """
    Prüfe ob neue Positionen erlaubt sind (Recovery-Mode Guard).

    Returns:
        (can_open: bool, reason: str)
    """
    status = get_drawdown_status()

    if not status["sufficient_data"]:
        return (
            True,
            f"DD-Check: Zu wenig Daten ({status['data_points']}/{MIN_DATA_POINTS}), kein Schutz aktiv"
        )

    if status["is_recovery_mode"]:
        return (
            False,
            f"RECOVERY-MODUS: Drawdown {status['current_dd_pct']:.1f}% "
            f">= {RECOVERY_THRESHOLD_PCT}% Schwelle | "
            f"Peak: {status['peak_eur']:.0f} EUR"
        )

    return (
        True,
        f"DD {status['current_dd_pct']:.1f}% < {RECOVERY_THRESHOLD_PCT}% OK"
    )


def get_adjusted_size_factor() -> float:
    """
    Gibt den aktuellen Größenfaktor zurück.

    Bei DD < 5%:  1.0 (volle Größe)
    Bei DD 5-10%: Linear abnehmend (0.0–1.0)
    Bei DD >= 10%: 0.0 (kein Trading)

    Returns:
        Float zwischen 0.0 und 1.0
    """
    return get_drawdown_status()["size_factor"]
