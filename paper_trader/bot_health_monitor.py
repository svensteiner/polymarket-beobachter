# =============================================================================
# POLYMARKET BEOBACHTER - BOT HEALTH MONITOR (v2)
# =============================================================================
#
# GOVERNANCE INTENT:
# This module provides temporary guardrails based on bot health metrics.
# It can temporarily restrict new entries without mutating the main config.
#
# FEATURES (v2):
# - Echte Metriken aus Position-Log (Win Rate, Consecutive Losses)
# - Persistenz (State ueberlebt Neustart)
# - Telegram Alerts bei Health-Aenderung
# - Cooldown vor Recovery (X gesunde Runs)
#
# =============================================================================

import json
import logging
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Tuple, Optional, Dict, Any, List

logger = logging.getLogger(__name__)

# Pfade
DATA_DIR = Path(__file__).parent.parent / "data"
HEALTH_STATE_PATH = DATA_DIR / "bot_health_state.json"

# Schwellwerte
CONSECUTIVE_LOSSES_THRESHOLD = 3  # Ab 3 Verlusten: DEGRADED
WIN_RATE_THRESHOLD = 0.35  # Unter 35% Win Rate: DEGRADED
MIN_TRADES_FOR_WIN_RATE = 5  # Mindestens 5 Trades fuer Win Rate
DAILY_DRAWDOWN_THRESHOLD = 5.0  # Ab 5% Daily DD: DEGRADED
RECOVERY_RUNS_REQUIRED = 3  # 3 gesunde Runs vor Recovery


@dataclass
class BotHealthState:
    """Current health state of the bot."""
    status: str = "HEALTHY"  # HEALTHY, DEGRADED, CRITICAL
    is_healthy: bool = True
    consecutive_losses: int = 0
    win_rate: float = 1.0
    total_closed_trades: int = 0
    daily_drawdown_pct: float = 0.0
    max_entry_price: Optional[float] = None
    guardrails_active: bool = False
    reasons: List[str] = None
    healthy_runs_count: int = 0  # Zaehler fuer Recovery
    last_status: str = "HEALTHY"  # Fuer Alert-Vergleich
    last_alert_time: str = ""  # Wann letzter Alert gesendet (Anti-Spam)
    last_updated: str = ""

    def __post_init__(self):
        if self.reasons is None:
            self.reasons = []


# Minimum Zeit zwischen Alerts (in Sekunden)
ALERT_COOLDOWN_SECONDS = 3600  # 1 Stunde


def _load_health_state() -> BotHealthState:
    """Lade persistierten Health State."""
    if not HEALTH_STATE_PATH.exists():
        return BotHealthState()

    try:
        with open(HEALTH_STATE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return BotHealthState(
            status=data.get("status", "HEALTHY"),
            is_healthy=data.get("is_healthy", True),
            consecutive_losses=data.get("consecutive_losses", 0),
            win_rate=data.get("win_rate", 1.0),
            total_closed_trades=data.get("total_closed_trades", 0),
            daily_drawdown_pct=data.get("daily_drawdown_pct", 0.0),
            max_entry_price=data.get("max_entry_price"),
            guardrails_active=data.get("guardrails_active", False),
            reasons=data.get("reasons", []),
            healthy_runs_count=data.get("healthy_runs_count", 0),
            last_status=data.get("last_status", "HEALTHY"),
            last_alert_time=data.get("last_alert_time", ""),
            last_updated=data.get("last_updated", ""),
        )
    except Exception as e:
        logger.warning(f"Health State nicht lesbar: {e}")
        return BotHealthState()


def _save_health_state(state: BotHealthState) -> None:
    """Speichere Health State persistent."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    state.last_updated = datetime.now().isoformat()

    try:
        with open(HEALTH_STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(asdict(state), f, indent=2, default=str)
    except Exception as e:
        logger.warning(f"Health State nicht speicherbar: {e}")


def _compute_metrics_from_positions() -> Dict[str, Any]:
    """
    Berechne echte Metriken aus dem Position-Log.

    Returns:
        Dict mit win_rate, consecutive_losses, total_closed
    """
    try:
        from paper_trader.logger import PaperTradingLogger

        paper_logger = PaperTradingLogger()
        all_positions = paper_logger.read_all_positions()

        # Nur geschlossene Positionen (haben exit_time und realized_pnl)
        closed = [p for p in all_positions if p.status == "CLOSED" and p.realized_pnl_eur is not None]

        if not closed:
            return {
                "win_rate": 1.0,
                "consecutive_losses": 0,
                "total_closed": 0,
                "recent_pnl": [],
            }

        # Sortiere nach Exit-Zeit (neueste zuerst)
        closed_sorted = sorted(
            closed,
            key=lambda p: p.exit_time or "",
            reverse=True
        )

        # Win Rate (letzte 20 Trades)
        recent = closed_sorted[:20]
        wins = sum(1 for p in recent if (p.realized_pnl_eur or 0) > 0)
        win_rate = wins / len(recent) if recent else 1.0

        # Consecutive Losses (von neueste rueckwaerts zaehlen)
        consecutive_losses = 0
        for p in closed_sorted:
            if (p.realized_pnl_eur or 0) < 0:
                consecutive_losses += 1
            else:
                break  # Erster Gewinn stoppt die Zaehlung

        # Recent P&L fuer Trend-Analyse
        recent_pnl = [(p.realized_pnl_eur or 0) for p in closed_sorted[:10]]

        return {
            "win_rate": round(win_rate, 3),
            "consecutive_losses": consecutive_losses,
            "total_closed": len(closed),
            "recent_pnl": recent_pnl,
        }

    except Exception as e:
        logger.warning(f"Metriken-Berechnung fehlgeschlagen: {e}")
        return {
            "win_rate": 1.0,
            "consecutive_losses": 0,
            "total_closed": 0,
            "recent_pnl": [],
        }


def _send_health_alert(old_status: str, new_status: str, reasons: List[str]) -> bool:
    """
    Sende Telegram Alert bei Status-Aenderung.

    Returns:
        True wenn Alert gesendet wurde, False wenn uebersprungen
    """
    try:
        from notifications.telegram import send_message, is_configured

        if not is_configured():
            return False

        # Check 1: Kein Alert wenn Status gleich
        if old_status == new_status:
            return False

        # Check 2: Cooldown pruefen (Anti-Spam)
        state = _load_health_state()
        if state.last_alert_time:
            try:
                last_alert = datetime.fromisoformat(state.last_alert_time)
                seconds_since = (datetime.now() - last_alert).total_seconds()
                if seconds_since < ALERT_COOLDOWN_SECONDS:
                    logger.debug(
                        f"Alert uebersprungen: Cooldown ({seconds_since:.0f}s < {ALERT_COOLDOWN_SECONDS}s)"
                    )
                    return False
            except ValueError:
                pass  # Ungültiges Datum, ignorieren

        # Emoji basierend auf Richtung
        if new_status == "HEALTHY":
            emoji = "✅"
            title = "BOT RECOVERED"
        elif new_status == "DEGRADED":
            emoji = "⚠️"
            title = "BOT DEGRADED"
        else:  # CRITICAL
            emoji = "🚨"
            title = "BOT CRITICAL"

        reason_text = ", ".join(reasons) if reasons else "OK"

        text = (
            f"{emoji} <b>{title}</b>\n"
            f"Status: {old_status} → {new_status}\n"
            f"Grund: {reason_text}"
        )

        # Bei CRITICAL mit Ton, sonst leise
        silent = new_status != "CRITICAL"
        send_message(text, disable_notification=silent)

        logger.info(f"Health Alert gesendet: {old_status} -> {new_status}")
        return True

    except Exception as e:
        logger.debug(f"Health Alert fehlgeschlagen: {e}")
        return False


def check_can_open_entry(
    entry_price: Optional[float] = None,
    is_addon: bool = False,
) -> Tuple[bool, str]:
    """
    Check if a new entry (or addon) is allowed based on current bot health.

    Args:
        entry_price: The proposed entry price (optional)
        is_addon: Whether this is an addon to existing position

    Returns:
        Tuple of (is_allowed, reason)
    """
    state = _load_health_state()

    # If bot is healthy, allow all entries
    if state.is_healthy:
        return (True, "OK")

    # If max_entry_price is set and entry_price exceeds it
    if (
        entry_price is not None
        and state.max_entry_price is not None
        and entry_price > state.max_entry_price
    ):
        return (
            False,
            f"Entry {entry_price:.2f} > Health-Limit {state.max_entry_price:.2f}"
        )

    # Check consecutive losses
    if state.consecutive_losses >= 5:
        return (
            False,
            f"Zu viele Verluste ({state.consecutive_losses}x)"
        )

    # Check daily drawdown
    if state.daily_drawdown_pct >= 10.0:
        return (
            False,
            f"Daily DD zu hoch ({state.daily_drawdown_pct:.1f}%)"
        )

    return (True, "OK - mit Einschraenkungen")


def update_bot_health(summary: Dict[str, Any]) -> Dict[str, Any]:
    """
    Update bot health state based on real metrics from position log.

    Args:
        summary: Performance summary dict from orchestrator

    Returns:
        Dict with status, summary, guardrails_active keys for orchestrator
    """
    # Lade vorherigen State fuer Vergleich
    prev_state = _load_health_state()
    old_status = prev_state.status

    # Berechne echte Metriken aus Position-Log
    metrics = _compute_metrics_from_positions()

    # Zusaetzliche Metriken aus Summary
    drawdown_pct = summary.get("drawdown_pct", 0.0)
    drawdown_recovery = summary.get("drawdown_recovery_mode", False)

    # Bestimme Health Status
    is_healthy = True
    reasons = []

    # Check 1: Consecutive Losses
    if metrics["consecutive_losses"] >= CONSECUTIVE_LOSSES_THRESHOLD:
        is_healthy = False
        reasons.append(f"{metrics['consecutive_losses']}x Verlust")

    # Check 2: Win Rate (nur wenn genug Trades)
    if metrics["total_closed"] >= MIN_TRADES_FOR_WIN_RATE:
        if metrics["win_rate"] < WIN_RATE_THRESHOLD:
            is_healthy = False
            reasons.append(f"WR {metrics['win_rate']:.0%}")

    # Check 3: Drawdown
    if drawdown_pct >= DAILY_DRAWDOWN_THRESHOLD:
        is_healthy = False
        reasons.append(f"DD {drawdown_pct:.1f}%")

    # Check 4: Recovery Mode
    if drawdown_recovery:
        is_healthy = False
        reasons.append("Recovery-Mode")

    # Bestimme Status-Level
    if is_healthy:
        status = "HEALTHY"
    elif len(reasons) >= 2 or metrics["consecutive_losses"] >= 5:
        status = "CRITICAL"
    else:
        status = "DEGRADED"

    # Recovery-Logik: Zaehle gesunde Runs
    if is_healthy:
        healthy_runs = prev_state.healthy_runs_count + 1
    else:
        healthy_runs = 0

    # Guardrails
    guardrails_active = False
    max_entry_price = None

    if not is_healthy:
        guardrails_active = True
        if status == "CRITICAL":
            max_entry_price = 0.25  # Sehr konservativ
        else:
            max_entry_price = 0.35  # Moderat konservativ

    # Telegram Alert bei Status-Aenderung (VOR State-Update fuer Cooldown-Check)
    alert_sent = False
    if status != old_status:
        alert_sent = _send_health_alert(old_status, status, reasons)

    # Neuer State
    new_state = BotHealthState(
        status=status,
        is_healthy=is_healthy,
        consecutive_losses=metrics["consecutive_losses"],
        win_rate=metrics["win_rate"],
        total_closed_trades=metrics["total_closed"],
        daily_drawdown_pct=drawdown_pct,
        max_entry_price=max_entry_price,
        guardrails_active=guardrails_active,
        reasons=reasons,
        healthy_runs_count=healthy_runs,
        last_status=old_status,
        last_alert_time=datetime.now().isoformat() if alert_sent else prev_state.last_alert_time,
    )

    # Speichern
    _save_health_state(new_state)

    reason_text = ", ".join(reasons) if reasons else "OK"

    logger.info(
        "Bot health: %s (WR=%.0f%%, Losses=%d, DD=%.1f%%, Runs=%d)",
        status,
        metrics["win_rate"] * 100,
        metrics["consecutive_losses"],
        drawdown_pct,
        healthy_runs,
    )

    # Return dict for orchestrator compatibility
    return {
        "status": status,
        "summary": reason_text,
        "guardrails_active": guardrails_active,
        "is_healthy": is_healthy,
        "consecutive_losses": metrics["consecutive_losses"],
        "win_rate": metrics["win_rate"],
        "total_closed_trades": metrics["total_closed"],
        "daily_drawdown_pct": drawdown_pct,
        "max_entry_price": max_entry_price,
        "healthy_runs_count": healthy_runs,
    }


def get_health_state() -> BotHealthState:
    """Get current bot health state (from persistent storage)."""
    return _load_health_state()


def reset_health_state() -> None:
    """Reset health state to default (healthy)."""
    new_state = BotHealthState()
    _save_health_state(new_state)
    logger.info("Bot health state reset to healthy")

    # Alert senden
    _send_health_alert("UNKNOWN", "HEALTHY", ["Manual Reset"])


def get_health_summary() -> str:
    """Kurze Zusammenfassung fuer Status-Ausgabe."""
    state = _load_health_state()

    parts = [state.status]

    if state.total_closed_trades > 0:
        parts.append(f"WR:{state.win_rate:.0%}")

    if state.consecutive_losses > 0:
        parts.append(f"L:{state.consecutive_losses}")

    if state.guardrails_active:
        parts.append("Guardrails")

    return " | ".join(parts)
