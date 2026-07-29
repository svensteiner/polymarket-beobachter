# =============================================================================
# POLYMARKET BEOBACHTER - ARB PARTITION COVERAGE (read-only)
# =============================================================================
#
# WHY (2026-07-29, plan B2-Fortsetzung):
#   `analytics/arb_capturability.py` grouped bucket markets into candidate
#   partitions with a HEURISTIC — (city, resolution-date, metric). That grouping
#   is a guess: it can merge markets that don't belong together and, worse, it
#   can never prove that we are looking at a COMPLETE partition. Its own verdict
#   said the fix is to "persist per-event the full bucket market-id list" so that
#   completeness becomes checkable *before* the trade instead of *from the
#   outcome* (which was the look-ahead trap that faked a +7.97% edge).
#
# WHAT THIS MODULE ADDS:
#   Polymarket already tells us the authoritative partition: every bucket of a
#   multi-outcome weather event carries the SAME `negRiskMarketID`. `negRisk`
#   markets are mutually-exclusive-and-exhaustive by construction — exactly one
#   bucket resolves YES, so the true YES-prices MUST sum to 1. The raw collector
#   snapshots (`data/collector/raw/*/markets_*.json`) already persist
#   `negRiskMarketID` for every market. So partition membership is now known
#   EX-ANTE, from market structure, with zero outcome conditioning.
#
# THE HONEST FINDING (see verdict at the bottom of the report):
#   Knowing the partition is necessary but not sufficient. To compute the
#   arbitrage sum S you need the price of EVERY bucket at one common moment. Our
#   observation log (`logs/weather_observations*.jsonl`) only records a price for
#   the ~3-5 buckets the observer actually evaluates out of the typical 11 — a
#   median price-coverage of ~27%. We never see a complete partition priced.
#
#   So the blocker for cross-market arbitrage is NOT "we don't know the
#   partition" (solved here) but "we only price ~a third of it". This module
#   measures that gap precisely and states the exact forward data requirement to
#   close it. It is built so that the moment coverage reaches 100% for some
#   partition, the same code emits a valid, look-ahead-free arb result.
#
#   READ-ONLY. Never trades, never changes state. Fail-open.
# =============================================================================

from __future__ import annotations

import glob
import json
import logging
import statistics
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from analytics import cost_model
from analytics.edge_research import load_resolutions, _num, _parse_iso, _taker_fee

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_GLOB = str(PROJECT_ROOT / "data" / "collector" / "raw" / "*" / "markets_*.json")
OBS_GLOB = str(PROJECT_ROOT / "logs" / "weather_observations*.jsonl")
OUT_MD = PROJECT_ROOT / "analytics" / "arb_partition_coverage.md"
OUT_JSON = PROJECT_ROOT / "analytics" / "arb_partition_coverage.json"

MIN_BUCKETS = 3            # a partition worth trading
LEAD_HOURS = 24.0          # price every bucket at ~the same moment before resolution
MAX_STALENESS_HOURS = 6.0  # priced buckets must be within this of each other


# ---------------------------------------------------------------------------
# 1) Authoritative partitions from raw collector snapshots (negRiskMarketID)
# ---------------------------------------------------------------------------

def _load_partitions() -> Dict[str, Dict[str, Any]]:
    """negRiskMarketID -> {members: {market_id: {question, bucket_label}}, title}.

    Reconstructed from every raw snapshot. A market_id seen in any snapshot with
    a negRiskMarketID counts as a member of that partition — membership is a
    structural fact and does not depend on the outcome.
    """
    parts: Dict[str, Dict[str, Any]] = {}
    for fname in sorted(glob.glob(RAW_GLOB)):
        try:
            data = json.loads(Path(fname).read_text(encoding="utf-8", errors="ignore"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, list):
            continue
        for m in data:
            nrid = m.get("negRiskMarketID")
            mid = str(m.get("id") or "")
            if not nrid or not mid:
                continue
            p = parts.setdefault(nrid, {"title": None, "members": {}})
            p["members"][mid] = {
                "question": m.get("question"),
                "bucket_label": m.get("groupItemTitle"),
            }
            if not p["title"]:
                p["title"] = m.get("_event_title")
    return parts


# ---------------------------------------------------------------------------
# 2) Prices (from observation log, one snapshot per market near LEAD_HOURS)
# ---------------------------------------------------------------------------

def _load_prices(lead_hours: float = LEAD_HOURS) -> Dict[str, Dict[str, Any]]:
    """market_id -> {market_p, ts} for the observation closest to `lead_hours`
    before resolution. Only resolved markets with a valid probability."""
    resolutions = load_resolutions()
    best: Dict[str, Tuple[float, Dict[str, Any]]] = {}
    for fname in sorted(glob.glob(OBS_GLOB)):
        try:
            text = Path(fname).read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                o = json.loads(line)
            except json.JSONDecodeError:
                continue
            mid = str(o.get("market_id"))
            if mid not in resolutions:
                continue
            kp = _num(o.get("market_probability"))
            h = _num(o.get("hours_to_resolution"))
            if kp is None or not (0.0 < kp < 1.0):
                continue
            dist = abs((h if h is not None else lead_hours) - lead_hours)
            cur = best.get(mid)
            if cur is None or dist < cur[0]:
                best[mid] = (dist, o)
    out: Dict[str, Dict[str, Any]] = {}
    for mid, (_, o) in best.items():
        out[mid] = {"market_p": float(o["market_probability"]), "ts": _parse_iso(o.get("timestamp_utc"))}
    return out


def _simultaneous(times: List[Optional[datetime]], n: int) -> bool:
    """All buckets priced within a short window (arbitrage needs simultaneity)."""
    ts = [t for t in times if t is not None]
    if len(ts) < n:
        return False
    return (max(ts) - min(ts)).total_seconds() <= MAX_STALENESS_HOURS * 3600


# ---------------------------------------------------------------------------
# 3) Analyse coverage + (if any complete partition exists) the honest arb
# ---------------------------------------------------------------------------

def analyse() -> Dict[str, Any]:
    parts = _load_partitions()
    prices = _load_prices()
    resolutions = load_resolutions()
    priced_ids = set(prices.keys())
    resolved_ids = set(resolutions.keys())

    hs = cost_model.realistic_half_spread()

    # Restrict to partitions that intersect our observed+resolved universe —
    # i.e. the daily city-temperature buckets we could actually trade. Non-city
    # events (yearly records, sea-ice) are never in the observation log.
    tradeable_universe = priced_ids & resolved_ids

    coverages: List[float] = []
    per_partition: List[Dict[str, Any]] = []
    complete_trades: List[Dict[str, Any]] = []

    for nrid, p in parts.items():
        members = set(p["members"].keys())
        n = len(members)
        if n < MIN_BUCKETS:
            continue
        if not (members & tradeable_universe):
            continue  # not part of the universe we observe/resolve at all

        n_priced = len(members & priced_ids)
        n_resolved = len(members & resolved_ids)
        cov = n_priced / n
        coverages.append(cov)

        complete = (n_priced == n) and (n_resolved == n)
        row = {
            "neg_risk_id": nrid,
            "title": (p["title"] or "")[:70],
            "n_buckets": n,
            "n_priced": n_priced,
            "n_resolved": n_resolved,
            "price_coverage": round(cov, 3),
            "complete": complete,
        }

        # If (and only if) the partition is fully priced AND fully resolved, we
        # can compute the honest, look-ahead-free arbitrage. This path currently
        # never triggers — it exists so the module produces a valid result the
        # moment forward data closes the coverage gap.
        if complete and _simultaneous([prices[m]["ts"] for m in members], n):
            S = sum(prices[m]["market_p"] for m in members)
            wins = sum(resolutions[m] for m in members)
            cost = sum(hs + _taker_fee(prices[m]["market_p"]) for m in members)
            if S < 1.0:
                side, net, gross = "BUY_ALL_YES", (wins - S - cost), (wins - S)
            else:
                side, net, gross = "BUY_ALL_NO", ((n - wins) - (n - S) - cost), (S - wins)
            row.update({
                "price_sum": round(S, 4),
                "winners": wins,
                "side": side,
                "gross_per_set": round(gross, 4),
                "net_per_set": round(net, 4),
            })
            complete_trades.append(row)

        per_partition.append(row)

    per_partition.sort(key=lambda r: -r["price_coverage"])
    nets = [t["net_per_set"] for t in complete_trades]

    def _med(xs: List[float]) -> Optional[float]:
        return round(statistics.median(xs), 3) if xs else None

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "half_spread_used": hs,
        "lead_hours": LEAD_HOURS,
        "raw_snapshots_used": len(glob.glob(RAW_GLOB)),
        "partitions_total": sum(1 for p in parts.values() if len(p["members"]) >= MIN_BUCKETS),
        "partitions_in_universe": len(per_partition),
        "complete_partitions": sum(1 for r in per_partition if r["complete"]),
        "price_coverage_min": round(min(coverages), 3) if coverages else None,
        "price_coverage_median": _med(coverages),
        "price_coverage_mean": round(statistics.mean(coverages), 3) if coverages else None,
        "price_coverage_max": round(max(coverages), 3) if coverages else None,
        "partitions_coverage_ge_80pct": sum(1 for c in coverages if c >= 0.8),
        "n_complete_trades": len(complete_trades),
        "avg_net_per_set": round(statistics.mean(nets), 4) if nets else None,
        "top_partitions": per_partition[:20],
        "complete_trades": complete_trades,
        "testable": bool(complete_trades),
    }


# ---------------------------------------------------------------------------
# 4) Report
# ---------------------------------------------------------------------------

def _render_md(s: Dict[str, Any]) -> str:
    def pct(x: Optional[float]) -> str:
        return "—" if x is None else f"{x*100:.1f}%"

    lines = [
        "# Cross-Market-Arbitrage — Partitions-Coverage (autoritativ via negRiskMarketID)",
        "",
        f"**Generiert:** {s['generated_at']}  ",
        f"**Roh-Snapshots ausgewertet:** {s['raw_snapshots_used']} · "
        f"Half-Spread {s['half_spread_used']:.4f} · Lead {s['lead_hours']}h  ",
        "",
        "> **Fortschritt gegenüber `arb_capturability.py`:** Dort wurden Buckets per "
        "Heuristik `(Stadt, Datum, Metrik)` gruppiert — eine Schätzung, die nie beweisen "
        "kann, dass man eine *vollständige* Partition sieht. Polymarket liefert die "
        "Partition aber autoritativ: alle Buckets eines Multi-Outcome-Events teilen dieselbe "
        "`negRiskMarketID` (`negRisk`-Märkte sind per Konstruktion disjunkt & vollständig, "
        "genau ein Bucket löst YES auf). Der Collector persistiert dieses Feld bereits in "
        "jedem Roh-Snapshot. **Partitions-Zugehörigkeit ist damit ex-ante bekannt — aus der "
        "Marktstruktur, ohne jede Outcome-Konditionierung.**",
        "",
        "## Datenlage",
        "",
        f"- negRisk-Partitionen gesamt (≥{MIN_BUCKETS} Buckets): **{s['partitions_total']}**",
        f"- davon in unserem beobachteten+aufgelösten Universum (tägliche Stadt-Temp): "
        f"**{s['partitions_in_universe']}**",
        f"- **vollständig bepreist UND aufgelöst: {s['complete_partitions']}**",
        "",
        "## Der harte Blocker: Preis-Coverage",
        "",
        "Um die Arbitrage-Summe S = Σ YES-Preise zu bilden, brauchen wir den Preis **jedes** "
        "Buckets zum selben Zeitpunkt. Unser Beobachtungs-Log erfasst aber nur die ~3-5 "
        "Buckets, die der Observer tatsächlich bewertet — von typisch 11:",
        "",
        "| Kennzahl | Wert |",
        "|---|---:|",
        f"| Preis-Coverage min | {pct(s['price_coverage_min'])} |",
        f"| Preis-Coverage **median** | **{pct(s['price_coverage_median'])}** |",
        f"| Preis-Coverage mean | {pct(s['price_coverage_mean'])} |",
        f"| Preis-Coverage max | {pct(s['price_coverage_max'])} |",
        f"| Partitionen mit Coverage ≥80% | {s['partitions_coverage_ge_80pct']} |",
        "",
        "## Partitionen (nach Coverage sortiert)",
        "",
        "| negRiskID | Event | Buckets | bepreist | aufgelöst | Coverage | komplett |",
        "|---|---|---:|---:|---:|---:|:---:|",
    ]
    for r in s["top_partitions"]:
        lines.append(
            f"| `{r['neg_risk_id'][:12]}` | {r['title']} | {r['n_buckets']} "
            f"| {r['n_priced']} | {r['n_resolved']} | {pct(r['price_coverage'])} "
            f"| {'✅' if r['complete'] else '—'} |"
        )

    lines += ["", "## Verdikt", ""]
    if s["testable"]:
        lines += [
            f"**{s['n_complete_trades']} vollständige Partition(en) — Arbitrage ehrlich "
            f"testbar.** Ø Netto nach Kosten pro Set: **{pct(s['avg_net_per_set'])}**. "
            "Vor jeder Schlussfolgerung: Order-Book-Tiefe je Bein prüfen (alle Beine müssen "
            "gleichzeitig füllbar sein), pro Monat ausweisen, dann als Forward-Shadow-Kohorte "
            "tracken. **Kein Kapital vor Gate 1/2/3.**",
        ]
    else:
        lines += [
            "**Arbitrage weiterhin NICHT testbar — aber der Grund ist jetzt präzise "
            "benannt und ein anderer als bisher angenommen.**",
            "",
            "- Das *Partitions-Problem* (welche Buckets gehören zusammen?) ist **gelöst**: "
            "`negRiskMarketID` liefert die vollständige, exhaustive Menge ex-ante. Die alte "
            "Heuristik und ihr Look-ahead-Risiko sind damit überflüssig.",
            f"- Der *tatsächliche* Blocker ist **Preis-Coverage**: wir bepreisen im Median nur "
            f"**{pct(s['price_coverage_median'])}** der Buckets einer Partition, im Maximum "
            f"**{pct(s['price_coverage_max'])}**, und **keine einzige** Partition ist "
            "vollständig bepreist. Wer eine unvollständige Bucket-Menge kauft, kennt S nicht "
            "und kann in ~⅔ der Fälle den Gewinner-Bucket gar nicht gekauft haben.",
            "",
            "**Konkreter, korrigierter nächster Schritt (ersetzt den alten Vorschlag in "
            "`arb_capturability.py`, Markt-IDs zu persistieren — das allein reicht NICHT):** "
            "Der Observer muss für *jeden* Bucket einer negRisk-Partition einen Preis-Snapshot "
            "zum gemeinsamen Lead-Zeitpunkt schreiben, nicht nur für die Buckets, die er "
            "handelbar findet. Erst wenn Preis-Coverage → 100% geht, produziert genau dieses "
            "Modul (ohne weitere Änderung) einen validen, look-ahead-freien Arb-Test. "
            "Das ist eine **Forward-Datenerfassungs-Aufgabe**, keine Analyse — und sie berührt "
            "den 15-Min-Zyklus, daher separat und bewusst zu entscheiden.",
        ]
    lines += ["", "---", "*READ-ONLY · PAPER ONLY · Partition autoritativ via negRiskMarketID*", ""]
    return "\n".join(lines)


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)


def run() -> Dict[str, Any]:
    s = analyse()
    try:
        _atomic_write(OUT_MD, _render_md(s))
        _atomic_write(OUT_JSON, json.dumps(s, indent=2, ensure_ascii=False))
    except Exception as e:  # fail-open: never break a caller
        logger.debug("arb_partition_coverage write failed: %s", e)
    return s


def main() -> None:
    s = run()
    print(f"partitions: total={s['partitions_total']} in_universe={s['partitions_in_universe']} "
          f"complete={s['complete_partitions']}")
    print(f"price-coverage: min={s['price_coverage_min']} median={s['price_coverage_median']} "
          f"max={s['price_coverage_max']} (>=80%: {s['partitions_coverage_ge_80pct']})")
    print(f"complete arb trades: {s['n_complete_trades']}  avg_net/set={s['avg_net_per_set']}")
    print("TESTABLE:", s["testable"])


if __name__ == "__main__":
    main()
