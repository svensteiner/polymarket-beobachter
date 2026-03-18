"""
analytics/strategy_advisor.py - Persistente Strategie-Empfehlungen fuer den Polymarket Beobachter.

Adaptiert aus der Idee des Marketing-Bot `StrategyAdvisor`:
- Beobachtet Performance und Exposure
- Schreibt konkrete, persistente Empfehlungen
- Nimmt KEINE Aenderungen selbst vor

Output:
- output/strategy_advice.json
- output/strategy_advice.txt
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent
REPORT_FILE = PROJECT_ROOT / "analytics" / "performance_report.json"
POSITIONS_FILE = PROJECT_ROOT / "paper_trader" / "logs" / "paper_positions.jsonl"
CAPITAL_FILE = PROJECT_ROOT / "data" / "capital_config.json"
CONFIG_FILE = PROJECT_ROOT / "config" / "weather.yaml"
ADVICE_JSON_FILE = PROJECT_ROOT / "output" / "strategy_advice.json"
ADVICE_TEXT_FILE = PROJECT_ROOT / "output" / "strategy_advice.txt"
SEGMENT_ANALYSIS_FILE = PROJECT_ROOT / "output" / "segment_analysis.json"

CONFIG_KEYS = (
    "MIN_EDGE",
    "MIN_EDGE_ABSOLUTE",
    "MIN_TIME_TO_RESOLUTION_HOURS",
    "SAFETY_BUFFER_HOURS",
    "MIN_ODDS",
    "MAX_ODDS",
)


def _load_json(path: Path) -> dict[str, Any]:
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except Exception as exc:
        logger.debug("JSON-Load fehlgeschlagen (%s): %s", path, exc)
    return {}


def _load_latest_positions() -> list[dict[str, Any]]:
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
        logger.debug("Positions-Load fehlgeschlagen: %s", exc)
    return list(latest.values())


def _read_config_values() -> dict[str, float]:
    values: dict[str, float] = {}
    if not CONFIG_FILE.exists():
        return values

    patterns = {
        key: re.compile(rf"^\s*{re.escape(key)}:\s*([0-9]+(?:\.[0-9]+)?)\s*$")
        for key in CONFIG_KEYS
    }

    try:
        for raw_line in CONFIG_FILE.read_text(encoding="utf-8").splitlines():
            line = raw_line.split("#", 1)[0].rstrip()
            for key, pattern in patterns.items():
                match = pattern.match(line)
                if match:
                    values[key] = float(match.group(1))
    except OSError as exc:
        logger.debug("Config-Read fehlgeschlagen: %s", exc)

    return values


def _load_segment_analysis() -> dict[str, Any]:
    return _load_json(SEGMENT_ANALYSIS_FILE)


def _extract_city(question: str) -> str:
    match = re.search(r"temperature in ([A-Za-z\s]+?)\s+be", question or "", re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return "Unknown"


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _round_up(value: float, step: float = 0.01, upper: float | None = None) -> float:
    rounded = round(value / step) * step
    if upper is not None:
        rounded = min(upper, rounded)
    return round(rounded, 4)


def derive_strategy_advice(
    report: dict[str, Any],
    positions: list[dict[str, Any]],
    capital: dict[str, Any],
    config_values: dict[str, float],
    segment_analysis: dict[str, Any] | None = None,
) -> dict[str, Any]:
    metrics = report.get("metrics", {}) if isinstance(report.get("metrics"), dict) else {}
    attribution = report.get("strategy_attribution", {}) if isinstance(report.get("strategy_attribution"), dict) else {}
    city_stats = report.get("performance_by_city", {}) if isinstance(report.get("performance_by_city"), dict) else {}
    calibration = report.get("calibration", {}) if isinstance(report.get("calibration"), dict) else {}
    segment_analysis = segment_analysis or {}
    risk_flags = segment_analysis.get("risk_flags", {}) if isinstance(segment_analysis.get("risk_flags"), dict) else {}
    total_trades = int(metrics.get("total_trades", 0) or 0)
    if total_trades > 0:
        try:
            from analytics.edge_memory import get_edge_summary
            edge_summary = get_edge_summary(min_trades=2, limit=6)
        except Exception:
            edge_summary = []
    else:
        edge_summary = []
    win_rate = _safe_float(metrics.get("win_rate_pct"))
    total_pnl = _safe_float(metrics.get("total_pnl_eur"))
    stop_loss_count = int((attribution.get("stop_loss") or {}).get("count", 0) or 0)
    resolution_loss_count = int((attribution.get("resolution_loss") or {}).get("count", 0) or 0)
    stop_loss_ratio = (stop_loss_count / total_trades) if total_trades else 0.0

    open_positions = [p for p in positions if str(p.get("status", "")).upper() == "OPEN"]
    closed_positions = [p for p in positions if str(p.get("status", "")).upper() in {"CLOSED", "RESOLVED", "EXPIRED"}]
    expired_like = [
        p for p in closed_positions
        if "expired" in str(p.get("exit_reason", "")).lower()
        or "zombie" in str(p.get("exit_reason", "")).lower()
    ]
    rich_open_positions = [
        p for p in open_positions
        if _safe_float(p.get("entry_price")) >= 0.85
    ]

    weak_cities = sorted(
        [
            {
                "city": city,
                "trades": int(stats.get("trades", 0) or 0),
                "win_rate_pct": _safe_float(stats.get("win_rate_pct")),
                "total_pnl_eur": _safe_float(stats.get("total_pnl_eur")),
            }
            for city, stats in city_stats.items()
            if isinstance(stats, dict)
            and int(stats.get("trades", 0) or 0) >= 3
            and _safe_float(stats.get("total_pnl_eur")) < 0
        ],
        key=lambda item: (item["total_pnl_eur"], item["win_rate_pct"]),
    )[:3]

    initial_capital = _safe_float(capital.get("initial_capital_eur"))
    allocated_capital = _safe_float(capital.get("allocated_capital_eur"))
    allocation_pct = (allocated_capital / initial_capital * 100.0) if initial_capital > 0 else 0.0

    min_edge = config_values.get("MIN_EDGE", 0.12)
    min_edge_abs = config_values.get("MIN_EDGE_ABSOLUTE", 0.05)
    min_time = config_values.get("MIN_TIME_TO_RESOLUTION_HOURS", 24.0)
    safety_buffer = config_values.get("SAFETY_BUFFER_HOURS", 24.0)

    if total_trades == 0:
        mode = "observe"
    elif win_rate < 20.0 or total_pnl <= -1000.0 or stop_loss_ratio >= 0.50:
        mode = "protect"
    elif win_rate < 45.0 or total_pnl < 0.0:
        mode = "balance"
    else:
        mode = "attack"

    issues: list[str] = []
    recommendations: list[dict[str, Any]] = []
    weak_edge_buckets = [item for item in edge_summary if _safe_float(item.get("avg_pnl_eur")) < 0]
    strong_edge_buckets = [item for item in edge_summary if _safe_float(item.get("avg_pnl_eur")) > 0]

    def add_recommendation(priority: str, area: str, action: str, reason: str, suggested_changes: dict[str, Any] | None = None) -> None:
        recommendations.append(
            {
                "priority": priority,
                "area": area,
                "action": action,
                "reason": reason,
                "suggested_changes": suggested_changes or {},
            }
        )

    if total_trades >= 10 and (win_rate < 35.0 or stop_loss_ratio >= 0.45):
        issues.append("entry_quality_too_weak")
        add_recommendation(
            "HIGH",
            "entries",
            "Eintrittsfilter anziehen und nur groessere Fehlbewertungen handeln",
            (
                f"Win-Rate {win_rate:.1f}% bei Stop-Loss-Anteil {stop_loss_ratio:.0%}. "
                "Das spricht eher fuer schlechte Entry-Selektion als fuer zu spaete Exits."
            ),
            {
                "MIN_EDGE": _round_up(min_edge + 0.05, upper=0.40),
                "MIN_EDGE_ABSOLUTE": _round_up(min_edge_abs + 0.02, upper=0.20),
            },
        )

    if resolution_loss_count >= 5 or len(expired_like) >= 4:
        issues.append("time_to_resolution_risk")
        add_recommendation(
            "HIGH",
            "timing",
            "Restlaufzeit konservativer machen und Zombie-/Expiry-Risiko reduzieren",
            (
                f"{resolution_loss_count} Resolution-Losses und {len(expired_like)} Expiry-/Zombie-Exits. "
                "Märkte werden zu lange oder zu spaet gehalten."
            ),
            {
                "MIN_TIME_TO_RESOLUTION_HOURS": int(max(min_time, min_time + 12)),
                "SAFETY_BUFFER_HOURS": int(max(safety_buffer, safety_buffer + 12)),
            },
        )

    if weak_cities:
        issues.append("city_concentration_drag")
        city_names = [item["city"] for item in weak_cities]
        add_recommendation(
            "MEDIUM",
            "universe",
            "Schwache Staedte temporaer auf Cooldown setzen",
            (
                "Mehrere Staedte liefern wiederholt negatives P&L. "
                "Erst nach neuer Datenlage wieder freigeben."
            ),
            {"cooldown_cities": city_names},
        )

    if rich_open_positions:
        issues.append("high_price_exposure")
        add_recommendation(
            "HIGH",
            "execution",
            "Entry-Preis-Guardrail pruefen",
            (
                f"{len(rich_open_positions)} offene Positionen wurden mit Entry >= 0.85 eroeffnet. "
                "Das passt nicht zu einem konservativen Risk/Reward-Profil und sollte auditiert werden."
            ),
            {
                "affected_positions": [p.get("position_id") for p in rich_open_positions[:5]],
                "example_prices": [round(_safe_float(p.get("entry_price")), 4) for p in rich_open_positions[:5]],
            },
        )

    if weak_edge_buckets:
        issues.append("negative_edge_buckets")
        add_recommendation(
            "HIGH",
            "edge_memory",
            "Wiederholt negative Setup-Buckets automatisch sperren",
            (
                "Mehrere wiederkehrende Kombinationen aus Confidence, Markt-Typ und Side "
                "zeigen negatives Edge und sollten im Intake geblockt bleiben."
            ),
            {
                "blocked_edge_buckets": [item["bucket"] for item in weak_edge_buckets[:3]],
            },
        )

    if strong_edge_buckets:
        add_recommendation(
            "MEDIUM",
            "position_sizing",
            "Positive Edge-Buckets moderat groesser handeln",
            (
                "Einige Setup-Familien zeigen wiederholt positive Edge und koennen "
                "mit leicht erhoehter Positionsgroesse bevorzugt werden."
            ),
            {
                "preferred_edge_buckets": [item["bucket"] for item in strong_edge_buckets[:3]],
            },
        )

    risky_price_bands = risk_flags.get("risky_price_bands", [])
    if risky_price_bands:
        issues.append("price_band_breakdown")
        top_band = risky_price_bands[0]
        add_recommendation(
            "HIGH",
            "pricing",
            "Teure oder instabile Preisbaender aktiv blocken",
            (
                f"Preisband {top_band.get('segment', 'N/A')} zeigt "
                f"{top_band.get('trades', 0)} Trades bei {top_band.get('total_pnl_eur', 0.0):+.2f} EUR."
            ),
            {
                "blocked_price_bands": risk_flags.get("suggested_price_band_blocks", []),
                "suggested_max_entry_price": risk_flags.get("suggested_max_entry_price", 0.85),
            },
        )

    risky_market_types = risk_flags.get("risky_market_types", [])
    if risky_market_types:
        issues.append("market_type_drag")
        top_type = risky_market_types[0]
        add_recommendation(
            "MEDIUM",
            "market_type",
            "Schwache Markt-Typen im Schutzmodus abkuehlen",
            (
                f"Markt-Typ {top_type.get('segment', 'N/A')} liefert "
                f"{top_type.get('total_pnl_eur', 0.0):+.2f} EUR bei {top_type.get('trades', 0)} Trades."
            ),
            {
                "cooldown_market_types": risk_flags.get("suggested_market_type_cooldowns", []),
            },
        )

    if allocation_pct >= 30.0 and mode == "protect":
        issues.append("capital_locked_during_drawdown")
        add_recommendation(
            "MEDIUM",
            "capital",
            "Positionszahl waehrend Schutzmodus weiter deckeln",
            (
                f"{allocation_pct:.1f}% des Kapitals ist trotz Schutzmodus gebunden. "
                "Neue Entries sollten nur bei sehr klarer Edge zugelassen werden."
            ),
            {
                "max_open_positions_review": True,
                "max_daily_trades_review": True,
            },
        )

    brier_interpretation = str(calibration.get("interpretation", "") or "").upper()
    if total_trades >= 10 and brier_interpretation in {"GOOD", "EXCELLENT"} and total_pnl < 0:
        issues.append("selection_execution_gap")
        add_recommendation(
            "HIGH",
            "diagnostics",
            "Forecast-Qualitaet nicht mit Trading-Qualitaet verwechseln",
            (
                f"Kalibrierung ist {brier_interpretation}, aber P&L bleibt negativ. "
                "Der Flaschenhals liegt eher bei Marktselektion, Preisniveau oder Exit-Handling."
            ),
        )

    if not recommendations:
        add_recommendation(
            "LOW",
            "monitoring",
            "Weiter Daten sammeln, noch kein harter Eingriff noetig",
            "Aktuelle Datenlage liefert keinen klaren, dominanten Handlungsbedarf.",
        )

    summary = (
        f"{mode.upper()}: Win-Rate {win_rate:.1f}% | P&L {total_pnl:+.2f} EUR | "
        f"{len(open_positions)} offene Positionen | {len(recommendations)} Empfehlung(en)"
    )

    return {
        "generated_at": datetime.now().isoformat(),
        "mode": mode,
        "summary": summary,
        "metrics_snapshot": {
            "total_trades": total_trades,
            "win_rate_pct": round(win_rate, 2),
            "total_pnl_eur": round(total_pnl, 2),
            "stop_loss_ratio": round(stop_loss_ratio, 3),
            "resolution_loss_count": resolution_loss_count,
            "open_positions": len(open_positions),
            "high_price_open_positions": len(rich_open_positions),
            "allocated_capital_pct": round(allocation_pct, 2),
            "calibration_interpretation": brier_interpretation or "UNKNOWN",
            "top_edge_bucket": strong_edge_buckets[0]["bucket"] if strong_edge_buckets else None,
            "worst_edge_bucket": weak_edge_buckets[0]["bucket"] if weak_edge_buckets else None,
        },
        "issues": issues,
        "weak_cities": weak_cities,
        "segment_risk_flags": risk_flags,
        "edge_summary": edge_summary,
        "recommendations": recommendations,
    }


def _format_text(advice: dict[str, Any]) -> str:
    metrics = advice.get("metrics_snapshot", {})
    lines = [
        "POLYMARKET STRATEGY ADVISOR",
        "=" * 40,
        f"Generated: {advice.get('generated_at', 'N/A')}",
        f"Mode:      {str(advice.get('mode', 'observe')).upper()}",
        f"Summary:   {advice.get('summary', '')}",
        "",
        "Metrics",
        "-" * 40,
        f"Trades:               {metrics.get('total_trades', 0)}",
        f"Win-Rate:             {metrics.get('win_rate_pct', 0.0):.2f}%",
        f"Total P&L:            {metrics.get('total_pnl_eur', 0.0):+.2f} EUR",
        f"Stop-Loss Ratio:      {metrics.get('stop_loss_ratio', 0.0):.1%}",
        f"Open Positions:       {metrics.get('open_positions', 0)}",
        f"High-Price Opens:     {metrics.get('high_price_open_positions', 0)}",
        f"Allocated Capital:    {metrics.get('allocated_capital_pct', 0.0):.1f}%",
        f"Calibration:          {metrics.get('calibration_interpretation', 'UNKNOWN')}",
        "",
        "Recommendations",
        "-" * 40,
    ]

    for idx, item in enumerate(advice.get("recommendations", []), start=1):
        lines.append(f"{idx}. [{item.get('priority', 'LOW')}] {item.get('action', '')}")
        lines.append(f"   Bereich: {item.get('area', '')}")
        lines.append(f"   Grund:   {item.get('reason', '')}")
        changes = item.get("suggested_changes", {})
        if changes:
            lines.append(f"   Vorschlag: {json.dumps(changes, ensure_ascii=False)}")

    weak_cities = advice.get("weak_cities", [])
    if weak_cities:
        lines.extend(["", "Weak Cities", "-" * 40])
        for item in weak_cities:
            lines.append(
                f"- {item.get('city')}: {item.get('trades')} Trades | "
                f"{item.get('win_rate_pct', 0.0):.1f}% WR | "
                f"{item.get('total_pnl_eur', 0.0):+.2f} EUR"
            )

    return "\n".join(lines) + "\n"


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)


def write_strategy_advice(advice: dict[str, Any]) -> None:
    _atomic_write(ADVICE_JSON_FILE, json.dumps(advice, indent=2, ensure_ascii=False))
    _atomic_write(ADVICE_TEXT_FILE, _format_text(advice))


def load_latest_advice() -> dict[str, Any]:
    return _load_json(ADVICE_JSON_FILE)


def run_strategy_advisor() -> dict[str, Any]:
    report = _load_json(REPORT_FILE)
    positions = _load_latest_positions()
    capital = _load_json(CAPITAL_FILE)
    config_values = _read_config_values()
    segment_analysis = _load_segment_analysis()

    advice = derive_strategy_advice(report, positions, capital, config_values, segment_analysis)
    write_strategy_advice(advice)
    logger.info(
        "Strategy-Advisor: mode=%s recommendations=%d",
        advice.get("mode", "observe"),
        len(advice.get("recommendations", [])),
    )
    return advice
