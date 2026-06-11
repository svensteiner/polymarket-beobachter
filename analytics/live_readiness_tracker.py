"""
LIVE-READINESS TRACKER
======================

Dokumentiert nach jedem Pipeline-Run den Fortschritt zu den 6 Live-Go-Meilensteinen,
damit wir entscheiden koennen wann mit echtem Kapital (100-200 EUR) live gegangen
werden kann. Paper-Bot laeuft parallel weiter.

LIVE-GO-MEILENSTEINE (siehe memory project_live_decision.md):
  M1: Dallas-Resolution abgeschlossen (1x)
  M2: >= 15 geschlossene YES-Trades
  M3: WR >= 75% ueber die letzten 15 YES-Trades
  M4: >= 30 geschlossene YES-Trades
  M5: Paper-P&L gesamt positiv
  M6: 14 Tage System-Stabilitaet ohne kritische Bugs

Output:
  analytics/live_readiness.json  - maschinenlesbar
  analytics/live_readiness.txt   - Status-Block fuer Konsole / Telegram
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
POSITIONS_PATH = PROJECT_ROOT / "paper_trader" / "logs" / "paper_positions.jsonl"
HEALTH_STATE_PATH = PROJECT_ROOT / "logs" / "health_state.json"
JSON_OUTPUT_PATH = PROJECT_ROOT / "analytics" / "live_readiness.json"
TXT_OUTPUT_PATH = PROJECT_ROOT / "analytics" / "live_readiness.txt"
# 2026-06-10 no-forward-edge decision: the hard live gate. No real capital until
# analytics/forward_validation.py reports model-beats-market skill (live_eligible).
FORWARD_VALIDATION_PATH = PROJECT_ROOT / "analytics" / "forward_validation.json"

REQUIRED_YES_TRADES_M2 = 15
REQUIRED_YES_TRADES_M4 = 30
REQUIRED_WR_M3 = 0.75
REQUIRED_STABILITY_DAYS_M6 = 14


@dataclass(frozen=True)
class Milestone:
    """Status eines einzelnen Meilensteins."""

    key: str
    title: str
    target: str
    actual: str
    achieved: bool
    progress_pct: float  # 0.0 - 100.0


@dataclass(frozen=True)
class ReadinessReport:
    generated_at: str
    closed_yes_trades: int
    last15_yes_wr_pct: Optional[float]
    last15_yes_pnl_eur: Optional[float]
    total_paper_pnl_eur: float
    closed_positions_count: int
    system_stability_days: float
    milestones: List[Milestone]
    overall_progress_pct: float
    milestones_done: int
    milestones_total: int
    estimated_go_live_date: Optional[str]
    blocking_issues: List[str] = field(default_factory=list)
    governance_notice: str = "PAPER TRADING ANALYSIS - kein Live-Trade-Trigger"


def _safe_iter_jsonl(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    records: List[Dict[str, Any]] = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError as exc:
        logger.warning("Konnte %s nicht lesen: %s", path, exc)
    return records


def _latest_positions(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Letzter Stand pro position_id (Log ist append-only)."""
    by_id: Dict[str, Dict[str, Any]] = {}
    for rec in records:
        pid = rec.get("position_id")
        if not pid:
            continue
        by_id[pid] = rec
    return list(by_id.values())


def _parse_iso(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    try:
        cleaned = ts.strip().rstrip("Z")
        dt = datetime.fromisoformat(cleaned)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (ValueError, AttributeError):
        return None


def _system_stability_days() -> float:
    """Tage seit letztem dokumentierten kritischen Bug.

    Heuristik: nutze logs/health_state.json (last_degraded_at), fallback auf
    aeltesten observer.log-Eintrag. Bei fehlenden Daten -> 0.0.
    """
    try:
        if HEALTH_STATE_PATH.exists():
            data = json.loads(HEALTH_STATE_PATH.read_text(encoding="utf-8"))
            last_bad = data.get("last_degraded_at") or data.get("last_critical_at")
            dt = _parse_iso(last_bad) if last_bad else None
            if dt is not None:
                delta = datetime.now(timezone.utc) - dt
                return max(0.0, delta.total_seconds() / 86400.0)
    except (OSError, json.JSONDecodeError) as exc:
        logger.debug("health_state nicht lesbar: %s", exc)
    # Konservativ: 0 Tage bekannt-stabil
    return 0.0


def _dallas_resolution_done(closed: List[Dict[str, Any]]) -> bool:
    """M1: Mind. eine Dallas-Position wurde resolved (Status RESOLVED oder exit_reason mit Resolution)."""
    for rec in closed:
        question = (rec.get("market_question") or "").lower()
        if "dallas" not in question:
            continue
        status = (rec.get("status") or "").upper()
        reason = (rec.get("exit_reason") or "").lower()
        if status == "RESOLVED" or "resol" in reason:
            return True
    return False


def _yes_wr_pct(yes_records: List[Dict[str, Any]]) -> Optional[float]:
    if not yes_records:
        return None
    wins = sum(1 for r in yes_records if float(r.get("realized_pnl_eur") or 0) > 0)
    return round(100.0 * wins / len(yes_records), 2)


def _yes_total_pnl(yes_records: List[Dict[str, Any]]) -> Optional[float]:
    if not yes_records:
        return None
    return round(sum(float(r.get("realized_pnl_eur") or 0) for r in yes_records), 2)


def _build_milestones(
    *,
    dallas_done: bool,
    closed_yes: int,
    last15_wr: Optional[float],
    total_pnl: float,
    stability_days: float,
) -> List[Milestone]:
    milestones: List[Milestone] = []

    milestones.append(
        Milestone(
            key="M1_dallas_resolved",
            title="Dallas-Resolution abgeschlossen",
            target="1 Dallas-Trade resolved",
            actual="JA" if dallas_done else "NEIN",
            achieved=dallas_done,
            progress_pct=100.0 if dallas_done else 0.0,
        )
    )

    m2_progress = min(100.0, 100.0 * closed_yes / REQUIRED_YES_TRADES_M2)
    milestones.append(
        Milestone(
            key="M2_15_yes_trades",
            title="15 geschlossene YES-Trades",
            target=f"{REQUIRED_YES_TRADES_M2} Trades",
            actual=f"{closed_yes} Trades",
            achieved=closed_yes >= REQUIRED_YES_TRADES_M2,
            progress_pct=round(m2_progress, 1),
        )
    )

    m3_actual = f"{last15_wr:.1f}%" if last15_wr is not None else "n/a (zu wenig Daten)"
    if last15_wr is None or closed_yes < REQUIRED_YES_TRADES_M2:
        m3_progress = 0.0
        m3_done = False
    else:
        m3_progress = min(100.0, 100.0 * last15_wr / (REQUIRED_WR_M3 * 100.0))
        m3_done = last15_wr >= REQUIRED_WR_M3 * 100.0
    milestones.append(
        Milestone(
            key="M3_wr_75pct_last15",
            title="WR >= 75% ueber letzte 15 YES-Trades",
            target=f">= {REQUIRED_WR_M3*100:.0f}%",
            actual=m3_actual,
            achieved=m3_done,
            progress_pct=round(m3_progress, 1),
        )
    )

    m4_progress = min(100.0, 100.0 * closed_yes / REQUIRED_YES_TRADES_M4)
    milestones.append(
        Milestone(
            key="M4_30_yes_trades",
            title="30 geschlossene YES-Trades",
            target=f"{REQUIRED_YES_TRADES_M4} Trades",
            actual=f"{closed_yes} Trades",
            achieved=closed_yes >= REQUIRED_YES_TRADES_M4,
            progress_pct=round(m4_progress, 1),
        )
    )

    # M5: P&L positiv. Fortschritt skaliert linear bis 0 EUR (negativ -> 0%, 0 -> 100%, >0 -> 100%).
    if total_pnl >= 0:
        m5_progress = 100.0
    else:
        # 100 EUR Verlust = 0%, 0 EUR = 100% — Skalierung damit man sieht wir naehern uns
        m5_progress = max(0.0, 100.0 + total_pnl)
    milestones.append(
        Milestone(
            key="M5_paper_pnl_positive",
            title="Paper-P&L gesamt positiv",
            target=">= 0.00 EUR",
            actual=f"{total_pnl:+.2f} EUR",
            achieved=total_pnl >= 0,
            progress_pct=round(min(100.0, m5_progress), 1),
        )
    )

    m6_progress = min(100.0, 100.0 * stability_days / REQUIRED_STABILITY_DAYS_M6)
    milestones.append(
        Milestone(
            key="M6_14_days_stable",
            title="14 Tage System-Stabilitaet",
            target=f"{REQUIRED_STABILITY_DAYS_M6} Tage ohne kritische Bugs",
            actual=f"{stability_days:.1f} Tage",
            achieved=stability_days >= REQUIRED_STABILITY_DAYS_M6,
            progress_pct=round(m6_progress, 1),
        )
    )

    return milestones


def _estimate_go_live(
    *, closed_yes: int, total_pnl: float, milestones: List[Milestone]
) -> Optional[str]:
    """Heuristische Schaetzung: Tage bis alle Meilensteine erreichbar sind.

    Annahmen aus dem Live-Decision-Memo: ca. 4 Wochen pro 15 YES-Trades,
    8-10 Wochen bis Paper-P&L positiv. Wir nehmen das langsamste offene
    Milestone als limitierenden Faktor.
    """
    today = datetime.now(timezone.utc).date()
    open_ms = [m for m in milestones if not m.achieved]
    if not open_ms:
        return today.isoformat()

    weeks_remaining = 0
    for m in open_ms:
        if m.key == "M2_15_yes_trades":
            remaining_trades = max(0, REQUIRED_YES_TRADES_M2 - closed_yes)
            weeks_remaining = max(weeks_remaining, remaining_trades * 4 / 15)
        elif m.key == "M4_30_yes_trades":
            remaining_trades = max(0, REQUIRED_YES_TRADES_M4 - closed_yes)
            weeks_remaining = max(weeks_remaining, remaining_trades * 4 / 15)
        elif m.key == "M5_paper_pnl_positive":
            # Wenn P&L stark negativ, brauchen wir mehr Zeit
            weeks_remaining = max(weeks_remaining, 8.0 if total_pnl < -50 else 4.0)
        elif m.key == "M6_14_days_stable":
            # Letzte gesetzte Stabilitaetstage
            for ms in milestones:
                if ms.key == "M6_14_days_stable":
                    days_have = float(ms.actual.split()[0]) if ms.actual.split() else 0.0
                    days_need = max(0.0, REQUIRED_STABILITY_DAYS_M6 - days_have)
                    weeks_remaining = max(weeks_remaining, days_need / 7.0)
        elif m.key == "M1_dallas_resolved":
            weeks_remaining = max(weeks_remaining, 1.0)
        elif m.key == "M3_wr_75pct_last15":
            # Erst nach M2 sinnvoll bewertbar
            weeks_remaining = max(weeks_remaining, 4.0)

    eta = today + timedelta(weeks=int(round(weeks_remaining)))
    return eta.isoformat()


def _build_blocking_issues(positions: List[Dict[str, Any]]) -> List[str]:
    """Konkret aktionable Probleme aus dem Trade-Log."""
    issues: List[str] = []
    closed = [p for p in positions if (p.get("status") or "").upper() in ("CLOSED", "RESOLVED")]
    if not closed:
        issues.append("Noch keine geschlossenen Trades — Pipeline produziert keine Daten.")
        return issues
    losers = [p for p in closed if float(p.get("realized_pnl_eur") or 0) < 0]
    if closed and len(losers) / len(closed) > 0.65:
        issues.append(
            f"Loss-Rate {len(losers)}/{len(closed)} = "
            f"{100*len(losers)/len(closed):.0f}% — Strategie verliert systematisch."
        )
    # Letzte 7 Tage = aktive Produktivitaet?
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    recent = [p for p in closed if (_parse_iso(p.get("exit_time")) or datetime.min.replace(tzinfo=timezone.utc)) > cutoff]
    if not recent:
        issues.append("0 Trades in letzten 7 Tagen — Pipeline ist im Lockdown oder ohne Eligibles.")
    return issues


def _forward_edge_status() -> tuple[bool, str]:
    """Forward-validation live gate. Returns (blocked, reason).

    No real capital may be deployed until analytics/forward_validation.py reports
    live_eligible (model forecast Brier beats the MARKET Brier out-of-sample).
    A missing or unreadable report counts as blocked — edge not yet proven.
    """
    if not FORWARD_VALIDATION_PATH.exists():
        return (True, "Forward-Edge ungeprueft — analytics/forward_validation.py nie gelaufen.")
    try:
        data = json.loads(FORWARD_VALIDATION_PATH.read_text(encoding="utf-8"))
    except Exception:
        return (True, "Forward-Edge-Report unlesbar — Go-Live gesperrt.")
    if data.get("live_eligible") is True:
        return (False, "")
    reasons = data.get("live_block_reasons") or ["Modell schlaegt Markt nicht."]
    return (True, "Forward-Edge NICHT bewiesen — " + "; ".join(str(r) for r in reasons))


def generate_report() -> ReadinessReport:
    raw = _safe_iter_jsonl(POSITIONS_PATH)
    positions = _latest_positions(raw)

    closed = [
        p for p in positions
        if (p.get("status") or "").upper() in ("CLOSED", "RESOLVED")
    ]
    closed.sort(key=lambda p: _parse_iso(p.get("exit_time")) or datetime.min.replace(tzinfo=timezone.utc))

    yes_closed = [p for p in closed if (p.get("side") or "").upper() == "YES"]
    last15 = yes_closed[-15:]

    total_pnl = round(sum(float(p.get("realized_pnl_eur") or 0) for p in closed), 2)
    stability_days = _system_stability_days()

    milestones = _build_milestones(
        dallas_done=_dallas_resolution_done(closed),
        closed_yes=len(yes_closed),
        last15_wr=_yes_wr_pct(last15),
        total_pnl=total_pnl,
        stability_days=stability_days,
    )

    done = sum(1 for m in milestones if m.achieved)
    overall = round(sum(m.progress_pct for m in milestones) / len(milestones), 1)

    # Hard live gate (2026-06-10): forward-edge proof overrides the milestone ETA.
    # Even with all 6 milestones green, NO real capital until the model beats the
    # market out-of-sample. Positive paper P&L is explicitly NOT sufficient.
    fe_blocked, fe_reason = _forward_edge_status()
    blocking = _build_blocking_issues(positions)
    if fe_blocked:
        blocking.insert(0, "GO-LIVE GESPERRT: " + fe_reason)
        estimated_eta: Optional[str] = "GESPERRT — Forward-Edge unbewiesen"
        governance = (
            "PAPER TRADING ANALYSIS — GO-LIVE GESPERRT bis "
            "analytics/forward_validation.py live_eligible meldet. "
            "Positives Paper-P&L ist KEIN Edge-Beweis."
        )
    else:
        estimated_eta = _estimate_go_live(
            closed_yes=len(yes_closed),
            total_pnl=total_pnl,
            milestones=milestones,
        )
        governance = "PAPER TRADING ANALYSIS - kein Live-Trade-Trigger"

    report = ReadinessReport(
        generated_at=datetime.now(timezone.utc).isoformat(),
        closed_yes_trades=len(yes_closed),
        last15_yes_wr_pct=_yes_wr_pct(last15),
        last15_yes_pnl_eur=_yes_total_pnl(last15),
        total_paper_pnl_eur=total_pnl,
        closed_positions_count=len(closed),
        system_stability_days=round(stability_days, 2),
        milestones=milestones,
        overall_progress_pct=overall,
        milestones_done=done,
        milestones_total=len(milestones),
        estimated_go_live_date=estimated_eta,
        blocking_issues=blocking,
        governance_notice=governance,
    )
    return report


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp, str(path))
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _render_text(report: ReadinessReport) -> str:
    lines: List[str] = []
    lines.append("=" * 60)
    lines.append("LIVE-READINESS TRACKER")
    lines.append(f"Generiert: {report.generated_at}")
    lines.append("=" * 60)
    lines.append(
        f"Fortschritt: {report.overall_progress_pct:.1f}% | "
        f"{report.milestones_done}/{report.milestones_total} Meilensteine erfuellt"
    )
    if report.estimated_go_live_date:
        lines.append(f"Geschaetztes Go-Live: {report.estimated_go_live_date}")
    lines.append("")
    lines.append(
        f"Closed Trades: {report.closed_positions_count} "
        f"(YES: {report.closed_yes_trades})"
    )
    lines.append(f"Total Paper-P&L: {report.total_paper_pnl_eur:+.2f} EUR")
    if report.last15_yes_wr_pct is not None:
        lines.append(
            f"Letzte 15 YES: WR={report.last15_yes_wr_pct:.1f}% | "
            f"P&L={report.last15_yes_pnl_eur:+.2f} EUR"
        )
    lines.append(f"System-Stabilitaet: {report.system_stability_days:.1f} Tage")
    lines.append("")
    lines.append("MEILENSTEINE:")
    for m in report.milestones:
        mark = "[X]" if m.achieved else "[ ]"
        lines.append(
            f"  {mark} {m.key}: {m.title}"
        )
        lines.append(
            f"      Ziel: {m.target} | Aktuell: {m.actual} | {m.progress_pct:.1f}%"
        )
    if report.blocking_issues:
        lines.append("")
        lines.append("BLOCKER:")
        for b in report.blocking_issues:
            lines.append(f"  - {b}")
    lines.append("")
    lines.append("Hinweis: " + report.governance_notice)
    return "\n".join(lines) + "\n"


def _milestones_to_dict(report: ReadinessReport) -> Dict[str, Any]:
    data = asdict(report)
    return data


def write_report(report: Optional[ReadinessReport] = None) -> ReadinessReport:
    if report is None:
        report = generate_report()
    _atomic_write(JSON_OUTPUT_PATH, json.dumps(_milestones_to_dict(report), indent=2))
    _atomic_write(TXT_OUTPUT_PATH, _render_text(report))
    logger.info(
        "Live-Readiness: %.1f%% | %d/%d Meilensteine | ETA %s",
        report.overall_progress_pct,
        report.milestones_done,
        report.milestones_total,
        report.estimated_go_live_date,
    )
    return report


def update_live_readiness() -> Dict[str, Any]:
    """Convenience-Wrapper fuer den Orchestrator."""
    report = write_report()
    return {
        "overall_progress_pct": report.overall_progress_pct,
        "milestones_done": report.milestones_done,
        "milestones_total": report.milestones_total,
        "total_paper_pnl_eur": report.total_paper_pnl_eur,
        "closed_yes_trades": report.closed_yes_trades,
        "estimated_go_live_date": report.estimated_go_live_date,
        "blocking_issues": report.blocking_issues,
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    report = write_report()
    print(_render_text(report))
