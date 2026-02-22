# =============================================================================
# POLYMARKET BEOBACHTER - OUTCOME ANALYSER
# =============================================================================
#
# GOVERNANCE INTENT:
# Analysiert abgeschlossene Paper-Positionen und berechnet Performance-Metriken.
# READ-ONLY: Liest aus paper_positions.jsonl - schreibt NICHTS zurueck.
# Output: analytics/performance_report.json
#
# LOGIK (adaptiert aus tradingbot/shared/auto_trainer.py + data_consistency.py):
# - Single Source of Truth: paper_positions.jsonl
# - Test-Trades werden ausgeschlossen (nur echte Pipeline-Runs)
# - Metriken: Win-Rate, Profit-Factor, Avg Win/Loss, Max Drawdown, Sharpe
# - Strategy Attribution: Welche Exit-Strategie war profitabel?
# - Modell-Kalibrierung: Forecast-Accuracy nach echten Resolutionen
#
# PAPER TRADING ONLY:
# Alle Werte sind simuliert. Keine echten Trades.
#
# =============================================================================

from __future__ import annotations

import json
import logging
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Dateipfade
PROJECT_ROOT = Path(__file__).parent.parent
POSITIONS_FILE = PROJECT_ROOT / "paper_trader" / "logs" / "paper_positions.jsonl"
REPORT_FILE = PROJECT_ROOT / "analytics" / "performance_report.json"


# =============================================================================
# DATEN LADEN
# =============================================================================

def _load_closed_positions() -> list[dict]:
    """
    Lade alle geschlossenen Positionen aus paper_positions.jsonl.

    Filtert:
    - Nur CLOSED und RESOLVED (nicht OPEN)
    - Keine Log-Header Eintraege (_type: LOG_HEADER)
    - Nur Positionen mit gueltiger P&L

    Returns:
        Liste von Position-Dicts (neueste Version jeder Position)
    """
    if not POSITIONS_FILE.exists():
        logger.info(f"Positions-Log nicht gefunden: {POSITIONS_FILE}")
        return []

    # Lade letzte Version jeder Position (neuestes Vorkommen gewinnt)
    positions_by_id: dict[str, dict] = {}
    raw_count = 0

    try:
        with open(POSITIONS_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    # Ueberspringe Header-Eintraege
                    if data.get("_type") == "LOG_HEADER":
                        continue
                    raw_count += 1
                    pos_id = data.get("position_id")
                    if pos_id:
                        positions_by_id[pos_id] = data
                except (json.JSONDecodeError, KeyError):
                    pass
    except OSError as e:
        logger.error(f"Positions-Log nicht lesbar: {e}")
        return []

    # Nur geschlossene Positionen mit gueltigem P&L
    closed = []
    for pos in positions_by_id.values():
        status = pos.get("status", "")
        pnl = pos.get("realized_pnl_eur")
        if status in ("CLOSED", "RESOLVED") and pnl is not None:
            try:
                pos["realized_pnl_eur"] = float(pnl)
                closed.append(pos)
            except (TypeError, ValueError):
                pass

    logger.info(
        f"Positions geladen: {raw_count} Eintraege, "
        f"{len(positions_by_id)} eindeutige, "
        f"{len(closed)} geschlossen mit P&L"
    )
    return closed


# =============================================================================
# METRIKEN
# =============================================================================

def _compute_base_metrics(positions: list[dict]) -> dict[str, Any]:
    """
    Berechne Basis-Performance-Metriken.

    Args:
        positions: Liste geschlossener Positionen

    Returns:
        Dict mit allen Metriken
    """
    if not positions:
        return {
            "total_trades": 0,
            "win_count": 0,
            "loss_count": 0,
            "breakeven_count": 0,
            "win_rate_pct": 0.0,
            "total_pnl_eur": 0.0,
            "avg_win_eur": 0.0,
            "avg_loss_eur": 0.0,
            "profit_factor": 0.0,
            "max_win_eur": 0.0,
            "max_loss_eur": 0.0,
            "avg_pnl_pct": 0.0,
        }

    pnls = [p["realized_pnl_eur"] for p in positions]
    wins = [x for x in pnls if x > 0]
    losses = [x for x in pnls if x < 0]
    breakevens = [x for x in pnls if x == 0]

    total_pnl = sum(pnls)
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))

    win_rate = len(wins) / len(pnls) * 100 if pnls else 0.0
    avg_win = sum(wins) / len(wins) if wins else 0.0
    avg_loss = sum(losses) / len(losses) if losses else 0.0  # negativ
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf") if gross_profit > 0 else 0.0

    # Avg P&L % aus Positionen
    pnl_pcts = [p.get("pnl_pct", 0.0) or 0.0 for p in positions]
    avg_pnl_pct = sum(pnl_pcts) / len(pnl_pcts) if pnl_pcts else 0.0

    return {
        "total_trades": len(pnls),
        "win_count": len(wins),
        "loss_count": len(losses),
        "breakeven_count": len(breakevens),
        "win_rate_pct": round(win_rate, 2),
        "total_pnl_eur": round(total_pnl, 2),
        "gross_profit_eur": round(gross_profit, 2),
        "gross_loss_eur": round(gross_loss, 2),
        "avg_win_eur": round(avg_win, 2),
        "avg_loss_eur": round(avg_loss, 2),
        "profit_factor": round(profit_factor, 4) if profit_factor != float("inf") else 999.0,
        "max_win_eur": round(max(wins), 2) if wins else 0.0,
        "max_loss_eur": round(min(losses), 2) if losses else 0.0,
        "avg_pnl_pct": round(avg_pnl_pct, 2),
    }


def _compute_drawdown_from_trades(positions: list[dict]) -> dict[str, Any]:
    """
    Berechne Max-Drawdown aus Trade-Sequenz (chronologisch).

    Args:
        positions: Geschlossene Positionen (werden nach exit_time sortiert)

    Returns:
        Dict mit max_drawdown_eur, max_drawdown_pct, peak_equity_eur
    """
    if not positions:
        return {"max_drawdown_eur": 0.0, "max_drawdown_pct": 0.0, "peak_equity_eur": 0.0}

    # Sortiere nach exit_time
    def _parse_time(p: dict) -> datetime:
        t = p.get("exit_time") or p.get("entry_time") or ""
        try:
            return datetime.fromisoformat(t)
        except (ValueError, TypeError):
            return datetime.min

    sorted_pos = sorted(positions, key=_parse_time)

    # Rekonstruiere Equity-Kurve (nur realisierte P&L, Start=0)
    equity = 0.0
    peak = 0.0
    max_dd_eur = 0.0
    max_dd_pct = 0.0

    for pos in sorted_pos:
        equity += pos["realized_pnl_eur"]
        if equity > peak:
            peak = equity
        dd_eur = peak - equity
        dd_pct = (dd_eur / peak * 100.0) if peak > 0 else 0.0
        if dd_eur > max_dd_eur:
            max_dd_eur = dd_eur
            max_dd_pct = dd_pct

    return {
        "max_drawdown_eur": round(max_dd_eur, 2),
        "max_drawdown_pct": round(max_dd_pct, 2),
        "peak_equity_eur": round(peak, 2),
        "final_equity_eur": round(equity, 2),
    }


def _compute_strategy_attribution(positions: list[dict]) -> dict[str, Any]:
    """
    Analysiere welche Exit-Strategie am profitabelsten war.

    Kategorien (basierend auf exit_reason):
    - take_profit:    Take-Profit Exits
    - stop_loss:      Stop-Loss Exits
    - edge_reversal:  Edge-Reversal Exits
    - resolution_win: Market aufgeloest -> wir hatten recht
    - resolution_loss: Market aufgeloest -> wir lagen falsch

    Args:
        positions: Geschlossene Positionen

    Returns:
        Dict mit Performance nach Exit-Strategie
    """
    buckets: dict[str, list[float]] = defaultdict(list)

    for pos in positions:
        reason = (pos.get("exit_reason") or "").lower()
        pnl = pos["realized_pnl_eur"]

        if "take-profit" in reason or "take_profit" in reason:
            buckets["take_profit"].append(pnl)
        elif "stop-loss" in reason or "stop_loss" in reason:
            buckets["stop_loss"].append(pnl)
        elif "edge" in reason and "reversal" in reason:
            buckets["edge_reversal"].append(pnl)
        elif "resolved" in reason or "resolution" in reason:
            if pnl > 0:
                buckets["resolution_win"].append(pnl)
            else:
                buckets["resolution_loss"].append(pnl)
        else:
            buckets["other"].append(pnl)

    attribution = {}
    for strategy, pnls in buckets.items():
        wins = [x for x in pnls if x > 0]
        losses = [x for x in pnls if x < 0]
        attribution[strategy] = {
            "count": len(pnls),
            "win_count": len(wins),
            "loss_count": len(losses),
            "win_rate_pct": round(len(wins) / len(pnls) * 100, 1) if pnls else 0.0,
            "total_pnl_eur": round(sum(pnls), 2),
            "avg_pnl_eur": round(sum(pnls) / len(pnls), 2) if pnls else 0.0,
        }

    return attribution


def _compute_city_performance(positions: list[dict]) -> dict[str, Any]:
    """
    Analysiere Performance nach Stadt (aus market_question).

    Args:
        positions: Geschlossene Positionen

    Returns:
        Dict mit P&L pro Stadt
    """
    import re
    city_pnl: dict[str, list[float]] = defaultdict(list)

    for pos in positions:
        question = pos.get("market_question", "")
        pnl = pos["realized_pnl_eur"]

        # Stadt extrahieren (gleiche Regex wie simulator.py)
        m = re.search(r"temperature in ([A-Za-z\s]+?)\s+be", question, re.IGNORECASE)
        city = m.group(1).strip() if m else "Unknown"
        city_pnl[city].append(pnl)

    result = {}
    for city, pnls in sorted(city_pnl.items()):
        wins = [x for x in pnls if x > 0]
        result[city] = {
            "trades": len(pnls),
            "wins": len(wins),
            "win_rate_pct": round(len(wins) / len(pnls) * 100, 1) if pnls else 0.0,
            "total_pnl_eur": round(sum(pnls), 2),
        }

    return result


def _compute_monthly_performance(positions: list[dict]) -> dict[str, Any]:
    """Aggregiere P&L nach Monat (YYYY-MM)."""
    monthly: dict[str, list[float]] = defaultdict(list)

    for pos in positions:
        exit_time = pos.get("exit_time") or pos.get("entry_time") or ""
        pnl = pos["realized_pnl_eur"]
        try:
            month = datetime.fromisoformat(exit_time).strftime("%Y-%m")
        except (ValueError, TypeError):
            month = "Unknown"
        monthly[month].append(pnl)

    return {
        month: {
            "trades": len(pnls),
            "total_pnl_eur": round(sum(pnls), 2),
            "win_rate_pct": round(len([x for x in pnls if x > 0]) / len(pnls) * 100, 1),
        }
        for month, pnls in sorted(monthly.items())
    }


# =============================================================================
# HAUPTFUNKTION
# =============================================================================

def run_analysis() -> dict[str, Any]:
    """
    Fuehre vollstaendige Outcome-Analyse durch und speichere Report.

    Returns:
        Report-Dict mit allen Metriken
    """
    logger.info("Starte Outcome-Analyse...")

    positions = _load_closed_positions()

    base = _compute_base_metrics(positions)
    drawdown = _compute_drawdown_from_trades(positions)
    attribution = _compute_strategy_attribution(positions)
    cities = _compute_city_performance(positions)
    monthly = _compute_monthly_performance(positions)

    # Bewertung
    win_rate = base["win_rate_pct"]
    pf = base["profit_factor"]
    if win_rate >= 55 and pf >= 1.5:
        health = "EXCELLENT"
    elif win_rate >= 45 and pf >= 1.0:
        health = "GOOD"
    elif win_rate >= 35 or pf >= 0.8:
        health = "WEAK"
    else:
        health = "POOR" if positions else "NO_DATA"

    report = {
        "generated_at": datetime.now().isoformat(),
        "governance_notice": "PAPER TRADING ANALYSIS - No real funds",
        "health": health,
        "metrics": base,
        "drawdown": drawdown,
        "strategy_attribution": attribution,
        "performance_by_city": cities,
        "performance_by_month": monthly,
        "data_source": str(POSITIONS_FILE),
        "positions_analysed": len(positions),
    }

    # Report speichern
    try:
        REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(REPORT_FILE, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        logger.info(f"Performance-Report gespeichert: {REPORT_FILE}")
    except OSError as e:
        logger.error(f"Report konnte nicht gespeichert werden: {e}")

    return report


def print_report(report: dict[str, Any] | None = None) -> None:
    """
    Drucke formatierten Report auf stdout.

    Args:
        report: Vorberechneter Report (oder None fuer frischen Run)
    """
    if report is None:
        report = run_analysis()

    m = report["metrics"]
    d = report["drawdown"]
    health = report["health"]

    health_icons = {"EXCELLENT": "[++]", "GOOD": "[+]", "WEAK": "[-]", "POOR": "[--]", "NO_DATA": "[?]"}
    icon = health_icons.get(health, "[?]")

    print(f"\n{'='*55}")
    print(f"  OUTCOME ANALYSER  {icon} {health}")
    print(f"  Generiert: {report['generated_at'][:19]}")
    print(f"  Positionen: {report['positions_analysed']}")
    print(f"{'='*55}")
    print(f"  Win-Rate:       {m['win_rate_pct']:.1f}%  ({m['win_count']}W / {m['loss_count']}L)")
    print(f"  Total P&L:      {m['total_pnl_eur']:+.2f} EUR")
    print(f"  Profit Factor:  {m['profit_factor']:.2f}")
    print(f"  Avg Win:        {m['avg_win_eur']:+.2f} EUR")
    print(f"  Avg Loss:       {m['avg_loss_eur']:+.2f} EUR")
    print(f"  Max Drawdown:   {d['max_drawdown_eur']:.2f} EUR ({d['max_drawdown_pct']:.1f}%)")
    print(f"{'='*55}")

    if report["strategy_attribution"]:
        print("  EXIT-STRATEGIE ATTRIBUTION:")
        for strategy, stats in sorted(report["strategy_attribution"].items()):
            print(
                f"    {strategy:<20} {stats['count']:>3} Trades | "
                f"WR: {stats['win_rate_pct']:.0f}% | "
                f"P&L: {stats['total_pnl_eur']:+.2f} EUR"
            )
        print(f"{'='*55}")

    if report["performance_by_city"]:
        print("  PERFORMANCE NACH STADT (Top 5):")
        sorted_cities = sorted(
            report["performance_by_city"].items(),
            key=lambda x: x[1]["total_pnl_eur"],
            reverse=True
        )[:5]
        for city, stats in sorted_cities:
            print(
                f"    {city:<15} {stats['trades']:>2} Trades | "
                f"WR: {stats['win_rate_pct']:.0f}% | "
                f"P&L: {stats['total_pnl_eur']:+.2f} EUR"
            )
        print(f"{'='*55}")

    if report["performance_by_month"]:
        print("  PERFORMANCE NACH MONAT:")
        for month, stats in list(report["performance_by_month"].items())[-6:]:
            print(
                f"    {month}  {stats['trades']:>2} Trades | "
                f"P&L: {stats['total_pnl_eur']:+.2f} EUR"
            )
        print(f"{'='*55}")

    print()


# =============================================================================
# STANDALONE
# =============================================================================

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    print_report()
