"""
paper_trader/bot_health_monitor.py - Temporäre Guardrails auf Basis der Bot-Gesundheit.

Ziel:
- Wiederkehrende Verlust- oder Failure-Muster erkennen
- Zeitlich begrenzte Schutzregeln aktivieren
- Keine persistente Strategie-Config mutieren

Schutzregeln wirken nur im Paper-Trader:
- Neue Entries optional blockieren
- Averaging Down optional blockieren
- Maximale erlaubte Entry-Preise temporär deckeln
"""

from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent
STATE_FILE = PROJECT_ROOT / "logs" / "bot_health.json"
AUDIT_DIR = PROJECT_ROOT / "logs" / "audit"
POSITIONS_FILE = PROJECT_ROOT / "paper_trader" / "logs" / "paper_positions.jsonl"
REPORT_FILE = PROJECT_ROOT / "analytics" / "performance_report.json"
ADVICE_FILE = PROJECT_ROOT / "output" / "strategy_advice.json"

RISK_HEALTHY = "HEALTHY"
RISK_ELEVATED = "ELEVATED"
RISK_CRITICAL = "CRITICAL"

_RECENT_RUN_WINDOW = 8
_RECENT_CLOSED_WINDOW = 8
_RECENT_CLOSED_LOOKBACK_DAYS = 7  # Only count positions closed in last N days for streak/rate checks


def _extract_city(question: str) -> str | None:
    if not question:
        return None
    match = re.search(r"temperature in ([A-Za-z\s]+?)\s+be", question, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return None


def _detect_market_type(question: str) -> str:
    if not question:
        return "unknown"
    q = question.lower()
    if "between" in q:
        return "between"
    if any(token in q for token in ("or below", "or less", "or under", "or lower")):
        return "at_or_below"
    if any(token in q for token in ("or above", "or higher", "or more", "or over", "be above", "exceed")):
        return "at_or_above"
    if re.search(r"\bbe\s+\d+|\bexactly\s+\d+", q):
        return "exact"
    return "unknown"


def _price_band(entry_price: float | None) -> str | None:
    if entry_price is None:
        return None
    price = float(entry_price)
    bands = [
        (0.00, 0.10),
        (0.10, 0.20),
        (0.20, 0.35),
        (0.35, 0.50),
        (0.50, 0.70),
        (0.70, 0.85),
        (0.85, 1.00),
    ]
    for low, high in bands:
        if low <= price < high or (high == 1.00 and price <= high):
            return f"{low:.2f}-{high:.2f}"
    return None


def _normalized_unique(items: list[Any] | None) -> list[str]:
    normalized: list[str] = []
    for item in items or []:
        text = str(item).strip()
        if text and text not in normalized:
            normalized.append(text)
    return normalized


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _iso_now() -> str:
    return _utc_now().isoformat()


def _load_json(path: Path) -> dict[str, Any]:
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except Exception as exc:
        logger.debug("JSON-Load fehlgeschlagen (%s): %s", path, exc)
    return {}


def _atomic_write(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _load_recent_runs(max_runs: int = _RECENT_RUN_WINDOW) -> list[dict[str, Any]]:
    if not AUDIT_DIR.exists():
        return []

    entries: list[dict[str, Any]] = []
    audit_files = sorted(AUDIT_DIR.glob("observer_*.jsonl"))[-5:]
    for audit_file in audit_files:
        try:
            with open(audit_file, "r", encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(data, dict) and data.get("event") == "OBSERVER_RUN":
                        entries.append(data)
        except OSError as exc:
            logger.debug("Audit-Read fehlgeschlagen (%s): %s", audit_file, exc)

    return entries[-max_runs:]


def _load_recent_closed_positions(
    max_positions: int = _RECENT_CLOSED_WINDOW,
    lookback_days: int = _RECENT_CLOSED_LOOKBACK_DAYS,
) -> list[dict[str, Any]]:
    if not POSITIONS_FILE.exists():
        return []

    latest: dict[str, dict[str, Any]] = {}
    try:
        with open(POSITIONS_FILE, "r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if data.get("_type") == "LOG_HEADER":
                    continue
                position_id = data.get("position_id")
                if position_id:
                    latest[position_id] = data
    except OSError as exc:
        logger.debug("Positions-Read fehlgeschlagen: %s", exc)
        return []

    def _close_ts(item: dict[str, Any]) -> datetime:
        return _parse_iso(item.get("exit_time")) or datetime.min.replace(tzinfo=UTC)

    cutoff = _utc_now() - timedelta(days=lookback_days)

    # Exclude EXPIRED (zombie cleanups) — these are not real trading results.
    # Apply time window: only positions closed within the lookback period.
    closed = [
        item for item in latest.values()
        if str(item.get("status", "")).upper() in {"CLOSED", "RESOLVED"}
        and item.get("realized_pnl_eur") is not None
        and _close_ts(item) >= cutoff
    ]
    closed.sort(key=_close_ts, reverse=True)
    return closed[:max_positions]


def _count_consecutive(values: list[bool], *, predicate_value: bool = True) -> int:
    streak = 0
    for value in values:
        if value is predicate_value:
            streak += 1
        else:
            break
    return streak


def derive_bot_health(
    current_summary: dict[str, Any],
    recent_runs: list[dict[str, Any]],
    performance_report: dict[str, Any],
    strategy_advice: dict[str, Any],
    recent_closed_positions: list[dict[str, Any]],
) -> dict[str, Any]:
    metrics = performance_report.get("metrics", {}) if isinstance(performance_report.get("metrics"), dict) else {}
    attribution = (
        performance_report.get("strategy_attribution", {})
        if isinstance(performance_report.get("strategy_attribution"), dict)
        else {}
    )

    total_trades = int(metrics.get("total_trades", 0) or 0)
    win_rate = float(metrics.get("win_rate_pct", 0.0) or 0.0)
    stop_loss_count = int((attribution.get("stop_loss") or {}).get("count", 0) or 0)
    stop_loss_ratio = (stop_loss_count / total_trades) if total_trades else 0.0
    drawdown_pct = float(current_summary.get("drawdown_pct", 0.0) or 0.0)
    advisor_mode = str(strategy_advice.get("mode", "observe")).upper()
    segment_risk_flags = (
        strategy_advice.get("segment_risk_flags", {})
        if isinstance(strategy_advice.get("segment_risk_flags"), dict)
        else {}
    )
    suggested_city_cooldowns = _normalized_unique(segment_risk_flags.get("suggested_city_cooldowns", []))
    suggested_market_type_cooldowns = _normalized_unique(segment_risk_flags.get("suggested_market_type_cooldowns", []))
    suggested_price_band_blocks = _normalized_unique(segment_risk_flags.get("suggested_price_band_blocks", []))

    run_summaries = [entry.get("summary", {}) for entry in recent_runs if isinstance(entry, dict)]
    consecutive_non_ok_runs = _count_consecutive(
        [str(summary.get("state", "OK")).upper() != "OK" for summary in reversed(run_summaries)]
    )
    consecutive_zero_edge_runs = _count_consecutive(
        [int(summary.get("edge_observations", 0) or 0) == 0 for summary in reversed(run_summaries)]
    )
    failure_runs_in_window = sum(
        1 for summary in run_summaries
        if str(summary.get("state", "OK")).upper() != "OK"
    )

    recent_pnls = [float(pos.get("realized_pnl_eur", 0.0) or 0.0) for pos in recent_closed_positions]
    recent_loss_streak = _count_consecutive([pnl <= 0.0 for pnl in recent_pnls])
    high_price_open_positions = int(current_summary.get("high_price_open_positions", 0) or 0)

    # Recent win rate — only computed when we have enough recent data (>= 5 positions in window).
    # Uses time-windowed data, not all-time metrics, to avoid bug-era contamination.
    _recent_wins = sum(1 for pnl in recent_pnls if pnl > 0)
    recent_win_rate: float | None = (
        (_recent_wins / len(recent_pnls) * 100.0) if len(recent_pnls) >= 5 else None
    )
    advisor_protect_wr_trigger = (
        advisor_mode == "PROTECT"
        and recent_win_rate is not None
        and recent_win_rate < 10.0
    )

    status = RISK_HEALTHY
    ttl_hours = 0
    triggers: list[str] = []
    guardrails = {
        "block_new_entries": False,
        "block_averaging_down": False,
        "max_entry_price": None,
        "blocked_cities": [],
        "blocked_market_types": [],
        "blocked_price_bands": [],
    }

    if (
        drawdown_pct >= 20.0
        or recent_loss_streak >= 4
        or consecutive_non_ok_runs >= 2
        or advisor_protect_wr_trigger
    ):
        status = RISK_CRITICAL
        ttl_hours = 6
        guardrails = {
            "block_new_entries": True,
            "block_averaging_down": True,
            "max_entry_price": 0.75,
            "blocked_cities": suggested_city_cooldowns[:3],
            "blocked_market_types": suggested_market_type_cooldowns[:3],
            "blocked_price_bands": suggested_price_band_blocks[:3],
        }
        if drawdown_pct >= 20.0:
            triggers.append(f"drawdown_{drawdown_pct:.1f}pct")
        if recent_loss_streak >= 4:
            triggers.append(f"loss_streak_{recent_loss_streak}")
        if consecutive_non_ok_runs >= 2:
            triggers.append(f"non_ok_runs_{consecutive_non_ok_runs}")
        if advisor_protect_wr_trigger:
            triggers.append("advisor_protect_with_low_wr")
    elif (
        drawdown_pct >= 10.0
        or recent_loss_streak >= 2
        or consecutive_zero_edge_runs >= 4
        or stop_loss_ratio >= 0.60
        or advisor_mode == "PROTECT"
        or high_price_open_positions >= 2
    ):
        status = RISK_ELEVATED
        ttl_hours = 4
        guardrails = {
            "block_new_entries": False,
            "block_averaging_down": True,
            "max_entry_price": 0.85,
            "blocked_cities": suggested_city_cooldowns[:2],
            "blocked_market_types": suggested_market_type_cooldowns[:2],
            "blocked_price_bands": suggested_price_band_blocks[:2],
        }
        if drawdown_pct >= 10.0:
            triggers.append(f"drawdown_{drawdown_pct:.1f}pct")
        if recent_loss_streak >= 2:
            triggers.append(f"loss_streak_{recent_loss_streak}")
        if consecutive_zero_edge_runs >= 4:
            triggers.append(f"edge_drought_{consecutive_zero_edge_runs}")
        if stop_loss_ratio >= 0.60:
            triggers.append(f"stop_loss_ratio_{stop_loss_ratio:.0%}")
        if advisor_mode == "PROTECT":
            triggers.append("advisor_protect")
        if high_price_open_positions >= 2:
            triggers.append(f"high_price_opens_{high_price_open_positions}")

    active_until = (_utc_now() + timedelta(hours=ttl_hours)).isoformat() if ttl_hours else None
    active_guardrails = [
        name for name, enabled in guardrails.items()
        if enabled not in (False, None)
    ]
    if guardrails.get("max_entry_price") is not None:
        active_guardrails.append(f"max_entry_price<={guardrails['max_entry_price']:.2f}")
    if guardrails.get("blocked_cities"):
        active_guardrails.append(f"cities={len(guardrails['blocked_cities'])}")
    if guardrails.get("blocked_market_types"):
        active_guardrails.append(f"market_types={len(guardrails['blocked_market_types'])}")
    if guardrails.get("blocked_price_bands"):
        active_guardrails.append(f"price_bands={len(guardrails['blocked_price_bands'])}")

    recent_wr_display = f"{recent_win_rate:.1f}%" if recent_win_rate is not None else f"{win_rate:.1f}%(all-time)"
    summary = (
        f"{status}: DD {drawdown_pct:.1f}% | WR {recent_wr_display} | "
        f"Loss-Streak {recent_loss_streak} | Guardrails {', '.join(active_guardrails) if active_guardrails else 'none'}"
    )

    return {
        "generated_at": _iso_now(),
        "status": status,
        "summary": summary,
        "active_until": active_until,
        "guardrails": guardrails,
        "guardrails_active": status in {RISK_ELEVATED, RISK_CRITICAL},
        "triggers": triggers,
        "metrics_snapshot": {
            "drawdown_pct": round(drawdown_pct, 2),
            "win_rate_pct": round(win_rate, 2),
            "stop_loss_ratio": round(stop_loss_ratio, 3),
            "recent_loss_streak": recent_loss_streak,
            "consecutive_non_ok_runs": consecutive_non_ok_runs,
            "consecutive_zero_edge_runs": consecutive_zero_edge_runs,
            "failure_runs_in_window": failure_runs_in_window,
            "high_price_open_positions": high_price_open_positions,
            "advisor_mode": advisor_mode,
            "blocked_cities_count": len(guardrails.get("blocked_cities", [])),
            "blocked_market_types_count": len(guardrails.get("blocked_market_types", [])),
            "blocked_price_bands_count": len(guardrails.get("blocked_price_bands", [])),
        },
    }


def load_bot_health() -> dict[str, Any]:
    state = _load_json(STATE_FILE)
    if not state:
        return {
            "status": RISK_HEALTHY,
            "summary": "HEALTHY: no active guardrails",
            "active_until": None,
            "guardrails": {
                "block_new_entries": False,
                "block_averaging_down": False,
                "max_entry_price": None,
                "blocked_cities": [],
                "blocked_market_types": [],
                "blocked_price_bands": [],
            },
            "guardrails_active": False,
            "triggers": [],
            "metrics_snapshot": {},
        }

    expiry = _parse_iso(state.get("active_until"))
    if expiry and _utc_now() > expiry:
        state["guardrails_active"] = False
        state["guardrails"] = {
            "block_new_entries": False,
            "block_averaging_down": False,
            "max_entry_price": None,
            "blocked_cities": [],
            "blocked_market_types": [],
            "blocked_price_bands": [],
        }
        state["summary"] = f"{state.get('status', RISK_HEALTHY)}: guardrails expired"
    return state


def update_bot_health(current_summary: dict[str, Any]) -> dict[str, Any]:
    performance_report = _load_json(REPORT_FILE)
    strategy_advice = _load_json(ADVICE_FILE)
    recent_runs = _load_recent_runs()
    recent_closed_positions = _load_recent_closed_positions()

    state = derive_bot_health(
        current_summary=current_summary,
        recent_runs=recent_runs,
        performance_report=performance_report,
        strategy_advice=strategy_advice,
        recent_closed_positions=recent_closed_positions,
    )
    _atomic_write(STATE_FILE, state)
    logger.info(
        "BotHealthMonitor: status=%s triggers=%s",
        state.get("status"),
        ",".join(state.get("triggers", [])) or "none",
    )
    return state


def check_can_open_entry(
    *,
    entry_price: float | None = None,
    is_addon: bool = False,
    market_question: str | None = None,
    market_type: str | None = None,
    city: str | None = None,
) -> tuple[bool, str]:
    state = load_bot_health()
    if not state.get("guardrails_active", False):
        return True, "OK"

    guardrails = state.get("guardrails", {}) if isinstance(state.get("guardrails"), dict) else {}
    status = state.get("status", RISK_HEALTHY)
    triggers = ", ".join(state.get("triggers", [])) or "none"

    if is_addon and guardrails.get("block_averaging_down", False):
        return False, f"BotHealthMonitor {status}: averaging down temporarily blocked ({triggers})"

    if not is_addon and guardrails.get("block_new_entries", False):
        return False, f"BotHealthMonitor {status}: new entries temporarily blocked ({triggers})"

    blocked_cities = _normalized_unique(guardrails.get("blocked_cities", []))
    blocked_market_types = _normalized_unique(guardrails.get("blocked_market_types", []))
    blocked_price_bands = _normalized_unique(guardrails.get("blocked_price_bands", []))

    resolved_city = city or _extract_city(market_question or "")
    if resolved_city and any(resolved_city.lower() == blocked.lower() for blocked in blocked_cities):
        return False, f"BotHealthMonitor {status}: city {resolved_city} temporarily blocked ({triggers})"

    resolved_market_type = market_type or _detect_market_type(market_question or "")
    if resolved_market_type and any(resolved_market_type.lower() == blocked.lower() for blocked in blocked_market_types):
        return False, f"BotHealthMonitor {status}: market type {resolved_market_type} temporarily blocked ({triggers})"

    resolved_price_band = _price_band(entry_price)
    if resolved_price_band and resolved_price_band in blocked_price_bands:
        return False, f"BotHealthMonitor {status}: price band {resolved_price_band} temporarily blocked ({triggers})"

    max_entry_price = guardrails.get("max_entry_price")
    if entry_price is not None and max_entry_price is not None and entry_price > float(max_entry_price):
        return (
            False,
            f"BotHealthMonitor {status}: entry price {entry_price:.4f} exceeds temporary cap {float(max_entry_price):.4f}",
        )

    return True, "OK"
