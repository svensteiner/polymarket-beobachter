# =============================================================================
# POLYMARKET BEOBACHTER - NO-FADE FORWARD SHADOW LANE (paper, read-only-ish)
# =============================================================================
#
# WHY (2026-06-14):
#   edge_research found a real favorite-longshot NO-fade edge (market overprices
#   10-20% weather longshots; buying NO held-to-resolution nets +3.3%/share). The
#   adversarial verification said it is NOT yet harvestable: the in-sample result
#   is one weather regime (May), OOS fails t>2, and real fill cost is unmeasured.
#
#   To get to a harvestable edge fastest, this lane does the two things the
#   verifiers demanded, FORWARD and frozen from today:
#     (1) it records every qualifying market as a NO-fade SHADOW position the
#         moment the live bot first sees it in-band (genuine out-of-sample data),
#     (2) it captures the REAL CLOB order-book NO-fill cost at entry (clob_book),
#         so modeled vs measured cost can be compared.
#
#   It is fully SELF-CONTAINED: its own ledger (data/no_fade_shadow.jsonl), its own
#   resolution close-out against official resolutions, and its own report
#   (analytics/no_fade_forward.md, refreshed every cycle). It NEVER touches the
#   production simulator, guardrails, or capital. PAPER ONLY. No real money.
#
#   Strategy (verified universe): side=NO, type in {exact, between}, P(YES) in
#   [0.10, 0.20), lead > MIN_LEAD_HOURS, HELD TO RESOLUTION (no TP/SL — mid-trade
#   exits on resolution-day spikes would destroy the edge).
# =============================================================================

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import time
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LEDGER_PATH = PROJECT_ROOT / "data" / "no_fade_shadow.jsonl"
OBS_LOG = PROJECT_ROOT / "logs" / "weather_observations.jsonl"
RESOLUTIONS_PATH = PROJECT_ROOT / "data" / "outcomes" / "resolutions.jsonl"
OUT_MD = PROJECT_ROOT / "analytics" / "no_fade_forward.md"

# Verified universe.
BAND = (0.10, 0.20)
TYPES = ("exact", "between")
MIN_LEAD_HOURS = 6.0
# Only act on markets seen in the current cycle (forward-only; never replay history).
ENTRY_RECENCY_MIN = 30.0
# Cost model (modeled leg). Real leg comes from the live CLOB book.
HALF_SPREAD_MODEL = 0.005
FLAT_NOTIONAL_EUR = 10.0
# Bound live book probes per cycle so the lane stays cheap and never hangs.
MAX_BOOK_FETCHES_PER_CYCLE = 25
# HARD wall-clock budget for all CLOB probes in one cycle. Beyond this, remaining
# markets are recorded modeled-only. Keeps the pipeline snappy even if Gamma/CLOB
# are slow — the 20-min watchdog has huge margin, but cycles must stay ~2 min.
BOOK_DEADLINE_SECONDS = 25.0
# Gate-3 regime guard: when the rolling calibration gap turns negative, this flag
# tells the lane to stop opening NEW positions (open ones still resolve normally).
GAP_MONITOR_JSON = PROJECT_ROOT / "analytics" / "gap_monitor.json"


def _taker_fee(price: float) -> float:
    try:
        from core.fee_model import polymarket_taker_fee
        return float(polymarket_taker_fee(price))
    except Exception:
        p = max(0.001, min(0.999, price))
        return 0.02 * p * (1.0 - p) / 0.25


def _event_type(desc: Optional[str]) -> str:
    d = (desc or "").lower()
    if "between" in d:
        return "between"
    if re.search(r"or\s+(?:below|less|under|lower)|\bbelow\b", d):
        return "at_or_below"
    if re.search(r"or\s+(?:above|higher|more|over)|\babove\b|exceed", d):
        return "at_or_above"
    return "exact"


def _parse_iso(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


# --------------------------------------------------------------------------- #
# Ledger IO
# --------------------------------------------------------------------------- #
def _load_ledger() -> List[Dict[str, Any]]:
    if not LEDGER_PATH.exists():
        return []
    rows: List[Dict[str, Any]] = []
    for line in LEDGER_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def _append_ledger(record: Dict[str, Any]) -> None:
    LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(LEDGER_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _rewrite_ledger(records: List[Dict[str, Any]]) -> None:
    LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(LEDGER_PATH.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            for rec in records:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        os.replace(tmp, str(LEDGER_PATH))
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _load_resolutions() -> Dict[str, str]:
    out: Dict[str, str] = {}
    if not RESOLUTIONS_PATH.exists():
        return out
    for line in RESOLUTIONS_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        if r.get("resolved") and r.get("resolution") in ("YES", "NO"):
            out[str(r.get("market_id"))] = r["resolution"]
    return out


# --------------------------------------------------------------------------- #
# Entry
# --------------------------------------------------------------------------- #
def _latest_in_band_candidates() -> List[Dict[str, Any]]:
    """Most-recent observation per market_id from the CURRENT cycle that qualifies."""
    if not OBS_LOG.exists():
        return []
    best: Dict[str, Tuple[str, Dict[str, Any]]] = {}
    for line in OBS_LOG.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            o = json.loads(line)
        except json.JSONDecodeError:
            continue
        ts = o.get("timestamp_utc") or ""
        mid = str(o.get("market_id") or "")
        if not mid:
            continue
        cur = best.get(mid)
        if cur is None or ts > cur[0]:
            best[mid] = (ts, o)

    now = datetime.now(timezone.utc)
    out: List[Dict[str, Any]] = []
    for mid, (ts, o) in best.items():
        if o.get("action") == "NO_SIGNAL":
            continue
        kp = o.get("market_probability")
        h = o.get("hours_to_resolution")
        if kp is None or h is None:
            continue
        try:
            kp = float(kp); h = float(h)
        except (TypeError, ValueError):
            continue
        if not (BAND[0] <= kp < BAND[1]) or h <= MIN_LEAD_HOURS:
            continue
        if _event_type(o.get("event_description")) not in TYPES:
            continue
        dt = _parse_iso(ts)
        if dt is None or (now - dt).total_seconds() > ENTRY_RECENCY_MIN * 60:
            continue  # forward-only: ignore stale history
        out.append(o)
    return out


def _auto_paused() -> bool:
    """Gate-3: read the regime guard. Fail-open — missing/unreadable => not paused."""
    try:
        if GAP_MONITOR_JSON.exists():
            data = json.loads(GAP_MONITOR_JSON.read_text(encoding="utf-8"))
            return bool(data.get("auto_pause"))
    except Exception:
        pass
    return False


def record_entries() -> int:
    """Record qualifying current-cycle markets as NO-fade shadow positions."""
    if _auto_paused():
        logger.info("NOFADE_PAUSE: gap-monitor regime guard active — keine neuen Entries.")
        return 0
    existing = {str(r.get("market_id")) for r in _load_ledger()}
    candidates = _latest_in_band_candidates()
    fetches = 0
    entered = 0
    t0 = time.monotonic()
    for o in candidates:
        mid = str(o.get("market_id"))
        if mid in existing:
            continue
        kp = float(o["market_probability"])
        modeled_cost = min(0.999, (1.0 - kp) + HALF_SPREAD_MODEL + _taker_fee(kp))

        real_book: Dict[str, Any] = {"ok": False, "reason": "not_fetched"}
        within_budget = (time.monotonic() - t0) < BOOK_DEADLINE_SECONDS
        if fetches < MAX_BOOK_FETCHES_PER_CYCLE and within_budget:
            try:
                from paper_trader.clob_book import fetch_no_book_cost
                real_book = fetch_no_book_cost(mid).to_dict()
            except Exception as e:  # fail-open
                real_book = {"ok": False, "reason": f"{type(e).__name__}"}
            fetches += 1
        elif not within_budget:
            real_book = {"ok": False, "reason": "cycle_deadline"}

        now_iso = datetime.now(timezone.utc).isoformat()
        record = {
            "shadow_id": f"NOFADE-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}",
            "entry_time": now_iso,
            "market_id": mid,
            "city": o.get("city") or "UNKNOWN",
            "market_type": _event_type(o.get("event_description")),
            "question": str(o.get("event_description") or "")[:140],
            "side": "NO",
            "market_p_yes": kp,
            "hours_to_resolution": float(o.get("hours_to_resolution") or 0.0),
            "modeled_no_cost": round(modeled_cost, 4),
            "real_no_cost": real_book.get("no_best_ask"),
            "real_spread": real_book.get("real_spread"),
            "real_ask_depth_shares": real_book.get("ask_depth_shares"),
            "real_book_ok": bool(real_book.get("ok")),
            "real_book_reason": real_book.get("reason"),
            "notional_eur": FLAT_NOTIONAL_EUR,
            "status": "OPEN",
            "resolution": None,
            "pnl_modeled_per_share": None,
            "pnl_real_per_share": None,
            "resolved_at": None,
        }
        _append_ledger(record)
        existing.add(mid)
        entered += 1
        logger.info(
            "NOFADE_ENTER: %s | %s %s kp=%.3f modeled_no=%.3f real_no=%s depth=%s",
            record["shadow_id"], record["city"], record["market_type"], kp,
            modeled_cost, real_book.get("no_best_ask"), real_book.get("ask_depth_shares"),
        )
    return entered


# --------------------------------------------------------------------------- #
# Close-out
# --------------------------------------------------------------------------- #
def close_resolved() -> int:
    records = _load_ledger()
    if not records:
        return 0
    resolutions = _load_resolutions()
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    closed = 0
    changed = False
    for r in records:
        if r.get("status") != "OPEN":
            continue
        mid = str(r.get("market_id"))
        res = resolutions.get(mid)
        if res in ("YES", "NO"):
            payoff = 1.0 if res == "NO" else 0.0  # NO side wins when market resolves NO
            mc = r.get("modeled_no_cost")
            rc = r.get("real_no_cost")
            r["status"] = "RESOLVED"
            r["resolution"] = res
            r["pnl_modeled_per_share"] = round(payoff - mc, 4) if mc is not None else None
            r["pnl_real_per_share"] = round(payoff - rc, 4) if rc is not None else None
            r["resolved_at"] = now_iso
            closed += 1
            changed = True
            continue
        # Stale-expire: entry + lead + 48h passed without an official resolution.
        entry_dt = _parse_iso(r.get("entry_time"))
        lead = float(r.get("hours_to_resolution") or 0.0)
        if entry_dt is not None and now > entry_dt + timedelta(hours=lead + 48):
            r["status"] = "EXPIRED"
            r["resolved_at"] = now_iso
            changed = True
    if changed:
        _rewrite_ledger(records)
    return closed


# --------------------------------------------------------------------------- #
# Summary + report
# --------------------------------------------------------------------------- #
def _mean(xs: List[float]) -> Optional[float]:
    return sum(xs) / len(xs) if xs else None


def summary() -> Dict[str, Any]:
    records = _load_ledger()
    open_recs = [r for r in records if r.get("status") == "OPEN"]
    resolved = [r for r in records if r.get("status") == "RESOLVED"]
    wins = [r for r in resolved if r.get("resolution") == "NO"]

    mod = [r["pnl_modeled_per_share"] for r in resolved if r.get("pnl_modeled_per_share") is not None]
    real = [r["pnl_real_per_share"] for r in resolved if r.get("pnl_real_per_share") is not None]
    spreads = [r["real_spread"] for r in records if r.get("real_spread") is not None]
    book_ok = [r for r in records if r.get("real_book_ok")]

    first_entry = min((r.get("entry_time") for r in records if r.get("entry_time")), default=None)

    # Entries in the last 7 days — surfaces a stalled inflow (e.g. a broken
    # collector starving the lane) at a glance.
    now = datetime.now(timezone.utc)
    entries_7d = 0
    for r in records:
        dt = _parse_iso(r.get("entry_time"))
        if dt is not None and (now - dt).total_seconds() <= 7 * 86400:
            entries_7d += 1

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "first_entry": first_entry,
        "total": len(records),
        "open": len(open_recs),
        "resolved": len(resolved),
        "entries_last_7d": entries_7d,
        "no_win_rate": round(len(wins) / len(resolved), 4) if resolved else None,
        "net_modeled_per_share": round(_mean(mod), 5) if mod else None,
        "net_real_per_share": round(_mean(real), 5) if real else None,
        "n_with_real_cost": len(real),
        "real_book_capture_rate": round(len(book_ok) / len(records), 3) if records else None,
        "avg_real_spread": round(_mean(spreads), 4) if spreads else None,
        "median_real_spread": round(sorted(spreads)[len(spreads) // 2], 4) if spreads else None,
    }


def _render_md(s: Dict[str, Any]) -> str:
    def fmt(x: Any, pct: bool = False) -> str:
        if x is None:
            return "—"
        return f"{x*100:+.2f}%" if pct else f"{x}"

    lines = [
        "# NO-Fade Forward Test — Live Paper Shadow",
        "",
        f"**Generiert:** {s['generated_at']}  ",
        f"**Forward-Start:** {s.get('first_entry') or '— (noch keine Entries)'}  ",
        "",
        "> Self-contained Paper-Shadow der verifizierten Edge: **NO** auf `exact`+`between`, "
        "P(YES) 10–20%, Lead >6h, **bis Resolution gehalten**. Eigenes Ledger, kein Eingriff in "
        "den Live-Simulator. Misst (1) Forward-PnL out-of-sample und (2) **echte** CLOB-Fill-Kosten. "
        "Kein echtes Kapital.",
        "",
        "## Status",
        "",
        f"- Positionen gesamt: **{s['total']}** (offen {s['open']}, aufgelöst {s['resolved']})",
        f"- Entries letzte 7 Tage: **{s.get('entries_last_7d', 0)}** "
        f"{'⚠️ Zufluss versiegt — Collector prüfen!' if s.get('entries_last_7d', 0) == 0 else ''}",
        f"- NO-Win-Rate: **{fmt(s['no_win_rate'], pct=True) if s['no_win_rate'] is not None else '—'}**",
        f"- Netto **modelliert** (0,5c-Spread): **{fmt(s['net_modeled_per_share'], pct=True)}** /Share",
        f"- Netto **REAL** (echte CLOB-Fills, n={s['n_with_real_cost']}): **{fmt(s['net_real_per_share'], pct=True)}** /Share",
        "",
        "## Gate 2 — echte Ausführungskosten",
        "",
        f"- CLOB-Book-Capture-Rate: **{fmt(s['real_book_capture_rate'])}**",
        f"- Realer NO-Spread: Ø **{fmt(s['avg_real_spread'])}**, Median **{fmt(s['median_real_spread'])}**",
        "",
        "**Lesart:** Liegt *Netto REAL* dauerhaft >0 und der reale Spread < ~1,6c, überlebt die Edge "
        "echte Fills (Gate 2 frei). Bricht *Netto REAL* gegenüber *Netto modelliert* ein, war der "
        "+3,3%-Befund ein Artefakt des synthetischen Spreads.",
        "",
        "## Gate 1 — Forward-Evidenz",
        "",
        f"Cutoff eingefroren beim ersten Entry. Braucht ~150+ aufgelöste Bets über ≥2 Kalendermonate "
        f"mit Cluster-t>2, bevor die Edge als bewiesen gilt. Aktuell aufgelöst: **{s['resolved']}**.",
        "",
        "---",
        "*PAPER ONLY. Echtes Kapital bleibt eingefroren bis Gate 1 + Gate 2 frei sind.*",
        "",
    ]
    return "\n".join(lines)


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)


def run() -> Dict[str, Any]:
    """One cycle: record new entries, close resolved, refresh the report."""
    entered = 0
    closed = 0
    try:
        entered = record_entries()
    except Exception as e:  # fail-open
        logger.debug("no_fade_lane.record_entries failed: %s", e)
    try:
        closed = close_resolved()
    except Exception as e:
        logger.debug("no_fade_lane.close_resolved failed: %s", e)
    s = summary()
    s["entered_this_cycle"] = entered
    s["closed_this_cycle"] = closed
    try:
        _atomic_write(OUT_MD, _render_md(s))
    except Exception as e:
        logger.debug("no_fade_lane report write failed: %s", e)
    return s


def main() -> None:
    s = run()
    print(json.dumps(s, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
