# =============================================================================
# POLYMARKET BEOBACHTER - EDGE RESEARCH (read-only)
# =============================================================================
#
# PURPOSE (2026-06-14):
#   forward_validation.py proved the forecast model has NO calibration edge over
#   the market (model Brier 0.161 >= market Brier 0.147 on 2583 markets). That
#   test measures *Brier* (calibration). It does NOT measure whether a fixed
#   *directional* strategy is profitable. A bet that fades over-priced longshots
#   with NO can be +EV even when its Brier looks worse, because Brier punishes
#   the rare confident-wrong outcomes while a NO-fade only cares about realised
#   win/loss.
#
#   This module hunts for genuine, forward-validated, MODEL-FREE and
#   model-assisted directional edge using the same ground truth as the gate:
#   official Polymarket resolutions (data/outcomes/resolutions.jsonl) joined to
#   ~93k weather observations at a fixed lead time.
#
#   It is READ-ONLY. It never trades and never mutates thresholds. It writes:
#     - analytics/edge_research.json  (machine-readable)
#     - analytics/edge_research.md    (always-current human report)
#
#   THE CORE HYPOTHESIS (favorite-longshot bias):
#     Weather markets priced ~10-20% resolve YES far less often (~10%) than the
#     price implies. Systematically buying NO on these longshots, held to
#     resolution, harvests that gap. The raw 31-member GFS ensemble can sharpen
#     the selection (only fade where the ensemble also says "unlikely").
# =============================================================================

from __future__ import annotations

import glob
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RESOLUTIONS_PATH = PROJECT_ROOT / "data" / "outcomes" / "resolutions.jsonl"
OBS_GLOB = str(PROJECT_ROOT / "logs" / "weather_observations*.jsonl")
OUT_JSON = PROJECT_ROOT / "analytics" / "edge_research.json"
OUT_MD = PROJECT_ROOT / "analytics" / "edge_research.md"

# Fair, tradeable comparison point: forecast + price ~this many hours before the
# market resolves. Both still carry uncertainty here.
DEFAULT_LEAD_HOURS = 24.0

# Out-of-sample time split. Everything strictly before is "train" context, on/
# after is the held-out window used to confirm the edge did not vanish.
OOS_CUTOFF_ISO = "2026-06-01T00:00:00+00:00"

# Transaction-cost model for the NO-fade simulation. Half-spread is the synthetic
# +/-1c the snapshot layer applies; fee uses the real non-linear Polymarket taker
# fee (max ~2% at p=0.5, ~0.7% at p=0.1). All edges are reported gross AND net.
HALF_SPREAD = 0.005


def _num(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_iso(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None


def _taker_fee(price: float) -> float:
    """Polymarket non-linear taker fee, mirrors core.fee_model."""
    p = max(0.001, min(0.999, price))
    return 0.02 * p * (1.0 - p) / 0.25


def _wilson(k: int, n: int, z: float = 1.96) -> Tuple[float, float]:
    """Wilson score interval for a binomial proportion (k successes of n)."""
    if n == 0:
        return (0.0, 0.0)
    phat = k / n
    denom = 1 + z * z / n
    centre = (phat + z * z / (2 * n)) / denom
    half = (z * math.sqrt(phat * (1 - phat) / n + z * z / (4 * n * n))) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def _event_type(desc: Optional[str]) -> str:
    d = (desc or "").lower()
    if "between" in d:
        return "between"
    if re.search(r"or\s+(?:below|less|under|lower)|\bbelow\b", d):
        return "at_or_below"
    if re.search(r"or\s+(?:above|higher|more|over)|\babove\b|exceed", d):
        return "at_or_above"
    return "exact"


# --------------------------------------------------------------------------- #
# Data loading
# --------------------------------------------------------------------------- #
def load_resolutions(path: Path = RESOLUTIONS_PATH) -> Dict[str, int]:
    out: Dict[str, int] = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        if r.get("resolved") and r.get("resolution") in ("YES", "NO"):
            out[str(r.get("market_id"))] = 1 if r["resolution"] == "YES" else 0
    return out


def build_records(lead_hours: float = DEFAULT_LEAD_HOURS) -> List[Dict[str, Any]]:
    """One observation per resolved market, the one closest to `lead_hours`.

    Each record is a tradeable snapshot: market price + model/raw probability at
    ~lead_hours before resolution, joined to the official YES/NO outcome.
    """
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
            h = _num(o.get("hours_to_resolution"))
            kp = _num(o.get("market_probability"))
            mp = _num(o.get("model_probability"))
            if h is None or kp is None or mp is None:
                continue
            if not (0.0 < kp < 1.0):
                continue
            dist = abs(h - lead_hours)
            cur = best.get(mid)
            if cur is None or dist < cur[0]:
                best[mid] = (dist, o)

    records: List[Dict[str, Any]] = []
    for mid, (_, o) in best.items():
        records.append({
            "market_id": mid,
            "city": o.get("city") or "UNKNOWN",
            "type": _event_type(o.get("event_description")),
            "market_p": float(o["market_probability"]),
            "model_p": float(o["model_probability"]),
            "raw_p": _num(o.get("raw_member_probability")),
            "outcome": resolutions[mid],
            "hours": _num(o.get("hours_to_resolution")),
            "ts": o.get("timestamp_utc"),
            "obs_date": (o.get("timestamp_utc") or "")[:10],
        })
    return records


# --------------------------------------------------------------------------- #
# Calibration curve (model-free favorite-longshot diagnostic)
# --------------------------------------------------------------------------- #
CAL_BINS = [
    (0.00, 0.05), (0.05, 0.10), (0.10, 0.15), (0.15, 0.20), (0.20, 0.30),
    (0.30, 0.40), (0.40, 0.50), (0.50, 0.65), (0.65, 0.80), (0.80, 1.00),
]


def calibration_curve(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows = []
    for lo, hi in CAL_BINS:
        sub = [r for r in records if lo <= r["market_p"] < hi]
        if not sub:
            continue
        n = len(sub)
        k_yes = sum(r["outcome"] for r in sub)
        avg_p = sum(r["market_p"] for r in sub) / n
        yes_rate = k_yes / n
        lo_ci, hi_ci = _wilson(k_yes, n)
        # NO-fade EV per share at the bin-average price (gross of costs).
        no_ev = (1 - yes_rate) - (1 - avg_p)
        rows.append({
            "bin": f"{lo:.2f}-{hi:.2f}",
            "n": n,
            "avg_market_p": round(avg_p, 4),
            "empirical_yes_rate": round(yes_rate, 4),
            "yes_rate_ci95": [round(lo_ci, 4), round(hi_ci, 4)],
            "price_minus_yesrate": round(avg_p - yes_rate, 4),
            "no_fade_ev_per_share": round(no_ev, 4),
            # Edge is "real" when the price sits ABOVE the upper CI of the true rate.
            "market_overprices_yes": (avg_p > hi_ci),
        })
    return rows


# --------------------------------------------------------------------------- #
# Strategy simulation
# --------------------------------------------------------------------------- #
def _simulate(
    records: List[Dict[str, Any]],
    select: Callable[[Dict[str, Any]], bool],
    side: str,  # "YES" or "NO"
    half_spread: float = HALF_SPREAD,
) -> Dict[str, Any]:
    """Simulate a fixed-direction strategy, gross and net of costs.

    For one share: you pay the side's price (+half-spread+fee) and receive 1.0 if
    your side wins, else 0. Net P&L per share = payoff - cost. `half_spread` is
    exposed so the cost-stress sweep can probe how far the edge survives wider,
    more realistic spreads (the project has no real order-book depth).
    """
    n = 0
    wins = 0
    gross = 0.0
    net = 0.0
    pnls_net: List[float] = []
    clusters: Dict[str, List[float]] = {}
    for r in records:
        if not select(r):
            continue
        kp = r["market_p"]
        won = (r["outcome"] == 1) if side == "YES" else (r["outcome"] == 0)
        price = kp if side == "YES" else (1 - kp)
        cost_gross = price
        cost_net = price + half_spread + _taker_fee(kp)
        payoff = 1.0 if won else 0.0
        g = payoff - cost_gross
        npl = payoff - cost_net
        n += 1
        wins += 1 if won else 0
        gross += g
        net += npl
        pnls_net.append(npl)
        key = f"{r['city']}|{(r.get('ts') or '')[:10]}"
        clusters.setdefault(key, []).append(npl)

    if n == 0:
        return {"n": 0}

    # Cluster-aware significance: average net P&L per (city, date) cluster, then a
    # one-sample t-stat across clusters. Correlated buckets in the same set count
    # once, so this is a conservative read of the edge's reliability.
    cluster_means = [sum(v) / len(v) for v in clusters.values()]
    nc = len(cluster_means)
    cm = sum(cluster_means) / nc
    if nc > 1:
        var = sum((x - cm) ** 2 for x in cluster_means) / (nc - 1)
        se = math.sqrt(var / nc)
        tstat = cm / se if se > 0 else None
    else:
        tstat = None

    return {
        "n": n,
        "n_clusters": nc,
        "side": side,
        "win_rate": round(wins / n, 4),
        "avg_pnl_per_share_gross": round(gross / n, 5),
        "avg_pnl_per_share_net": round(net / n, 5),
        "total_pnl_net_per_1eur_stake": round(net / n, 5),  # per-1-share == per-1-EUR notional
        "roi_net_pct": round(100 * net / sum(
            (r["market_p"] if side == "YES" else 1 - r["market_p"])
            for r in records if select(r)
        ), 3) if n else None,
        "cluster_mean_net": round(cm, 5),
        "cluster_tstat": round(tstat, 3) if tstat is not None else None,
    }


def _no_longshot(lo: float, hi: float) -> Callable[[Dict[str, Any]], bool]:
    return lambda r: lo <= r["market_p"] < hi


def strategy_panel(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Headline strategies, all held to resolution."""
    panel: Dict[str, Any] = {}

    # S0: follow the model with YES (proxy for the bot's current behaviour).
    panel["S0_yes_follow_model"] = _simulate(
        records,
        lambda r: r["model_p"] > r["market_p"] + 0.05 and r["market_p"] <= 0.35,
        "YES",
    )
    # S1: model-free NO-fade of the 10-20% longshot band (the headline edge).
    panel["S1_no_fade_longshot_10_20"] = _simulate(records, _no_longshot(0.10, 0.20), "NO")
    # S1b: widen to the full 5-30% band.
    panel["S1b_no_fade_longshot_5_30"] = _simulate(records, _no_longshot(0.05, 0.30), "NO")
    # S2: model-assisted NO-fade — only where the post-shrinkage model also fades.
    panel["S2_no_fade_model_confirm"] = _simulate(
        records,
        lambda r: 0.05 <= r["market_p"] < 0.30 and r["model_p"] < r["market_p"] - 0.03,
        "NO",
    )
    # S3: raw-ensemble-assisted NO-fade (subset with raw signal logged).
    panel["S3_no_fade_raw_confirm"] = _simulate(
        records,
        lambda r: r["raw_p"] is not None and 0.05 <= r["market_p"] < 0.35
        and r["raw_p"] < r["market_p"] - 0.05,
        "NO",
    )
    return panel


def breakdown(records: List[Dict[str, Any]],
              select: Callable[[Dict[str, Any]], bool],
              key: str) -> List[Dict[str, Any]]:
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for r in records:
        if select(r):
            groups.setdefault(str(r[key]), []).append(r)
    out = []
    for g, rs in groups.items():
        sim = _simulate(rs, lambda r: True, "NO")
        if sim.get("n", 0) >= 8:
            out.append({key: g, **{k: sim[k] for k in
                        ("n", "win_rate", "avg_pnl_per_share_net", "cluster_tstat")}})
    out.sort(key=lambda x: x["avg_pnl_per_share_net"], reverse=True)
    return out


def oos_split(records: List[Dict[str, Any]],
              select: Callable[[Dict[str, Any]], bool],
              side: str = "NO") -> Dict[str, Any]:
    cutoff = _parse_iso(OOS_CUTOFF_ISO)
    early, late = [], []
    for r in records:
        if not select(r):
            continue
        ts = _parse_iso(r.get("ts"))
        (late if (ts and cutoff and ts >= cutoff) else early).append(r)
    return {
        "cutoff": OOS_CUTOFF_ISO,
        "train_before": _simulate(early, lambda r: True, side),
        "oos_after": _simulate(late, lambda r: True, side),
    }


# --------------------------------------------------------------------------- #
# Lead-time sweep of the longshot calibration gap
# --------------------------------------------------------------------------- #
def lead_sweep(leads: Optional[List[float]] = None) -> List[Dict[str, Any]]:
    leads = leads or [6.0, 12.0, 24.0, 48.0, 96.0]
    out = []
    for L in leads:
        recs = build_records(lead_hours=L)
        band = [r for r in recs if 0.10 <= r["market_p"] < 0.20]
        if not band:
            out.append({"lead_hours": L, "n_band": 0})
            continue
        n = len(band)
        avg_p = sum(r["market_p"] for r in band) / n
        yr = sum(r["outcome"] for r in band) / n
        out.append({
            "lead_hours": L,
            "n_band_10_20": n,
            "avg_market_p": round(avg_p, 4),
            "empirical_yes_rate": round(yr, 4),
            "no_fade_ev_per_share": round((1 - yr) - (1 - avg_p), 4),
        })
    return out


# --------------------------------------------------------------------------- #
# Headline universe + honesty gates (added after adversarial verification)
# --------------------------------------------------------------------------- #
# The structurally-correct, verified universe: the favorite-longshot fade only
# holds on mutually-exclusive 'exact'+'between' markets; 'at_or_above'/'at_or_below'
# are negative and structurally different. Restricting here makes the edge both
# more correct AND stronger (verifier: +3.34%/share, t=3.40).
HEADLINE_TYPES = ("exact", "between")
HEADLINE_BAND = (0.10, 0.20)
# Average per-bet transaction cost (half-spread + in-band taker fee). Net P&L must
# clear this to be economically meaningful, not just statistically positive.
COST_FLOOR = 0.0147
# Cost-stress: the project has NO real order-book depth (snapshot synthesises a
# +/-1c placeholder), so the true half-spread on a thin 0.80-0.90 NO leg is
# unmeasured. We probe how far the edge survives wider spreads.
STRESS_SPREADS = (0.005, 0.01, 0.02, 0.03, 0.05)


def _headline_select(r: Dict[str, Any]) -> bool:
    lo, hi = HEADLINE_BAND
    return r["type"] in HEADLINE_TYPES and lo <= r["market_p"] < hi


def monthly_breakdown(records: List[Dict[str, Any]],
                      select: Callable[[Dict[str, Any]], bool],
                      side: str = "NO") -> List[Dict[str, Any]]:
    """Per calendar-month net P&L + calibration gap for the selected universe.

    The single most important robustness cut: the verifier showed the whole edge
    is carried by one month (May); April was NEGATIVE. Surfacing this keeps the
    md report honest about regime concentration.
    """
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for r in records:
        if not select(r):
            continue
        groups.setdefault((r.get("ts") or "")[:7], []).append(r)
    out = []
    for month, rs in sorted(groups.items()):
        if not month:
            continue
        sim = _simulate(rs, lambda r: True, side)
        n = len(rs)
        avg_p = sum(x["market_p"] for x in rs) / n
        yr = sum(x["outcome"] for x in rs) / n
        out.append({
            "month": month,
            "n": n,
            "avg_market_p": round(avg_p, 4),
            "yes_rate": round(yr, 4),
            "gap": round(avg_p - yr, 4),
            "net": sim.get("avg_pnl_per_share_net"),
            "tstat": sim.get("cluster_tstat"),
        })
    return out


def cost_stress(records: List[Dict[str, Any]],
                select: Callable[[Dict[str, Any]], bool],
                side: str = "NO") -> List[Dict[str, Any]]:
    out = []
    for hs in STRESS_SPREADS:
        sim = _simulate(records, select, side, half_spread=hs)
        out.append({
            "half_spread": hs,
            "net": sim.get("avg_pnl_per_share_net"),
            "tstat": sim.get("cluster_tstat"),
            "survives_t2": (sim.get("cluster_tstat") or 0) > 2.0
            and (sim.get("avg_pnl_per_share_net") or 0) > 0,
        })
    return out


def _drop_largest_month_net(records: List[Dict[str, Any]],
                            months: List[Dict[str, Any]]) -> Optional[float]:
    """Net P&L after removing the single largest-n month (jackknife)."""
    if not months:
        return None
    biggest = max(months, key=lambda m: m["n"])["month"]
    sim = _simulate(records, lambda r: _headline_select(r)
                    and (r.get("ts") or "")[:7] != biggest, "NO")
    return sim.get("avg_pnl_per_share_net")


# --------------------------------------------------------------------------- #
# Top-level
# --------------------------------------------------------------------------- #
def evaluate() -> Dict[str, Any]:
    records = build_records()
    cal = calibration_curve(records)
    panel = strategy_panel(records)
    cities = breakdown(records, _headline_select, "city")
    types = breakdown(records, _no_longshot(0.10, 0.20), "type")
    oos = oos_split(records, _headline_select)
    sweep = lead_sweep()

    # Headline = the verified exact+between 10-20% NO-fade.
    headline = _simulate(records, _headline_select, "NO")
    months = monthly_breakdown(records, _headline_select)
    stress = cost_stress(records, _headline_select)
    drop_month_net = _drop_largest_month_net(records, months)

    # ---- Two honest signals (synthesis of the adversarial verification) ----
    # (1) Is the favorite-longshot calibration GAP statistically real & clean?
    cal_by_bin = {c["bin"]: c for c in cal}
    gap_real = bool(
        cal_by_bin.get("0.10-0.15", {}).get("market_overprices_yes")
        and cal_by_bin.get("0.15-0.20", {}).get("market_overprices_yes")
    )

    # (2) Is it HARVESTABLE — survives OOS, regime, and realistic cost?
    months_material = [m for m in months if m["n"] >= 30]
    all_months_positive = bool(months_material) and all(
        (m["net"] or 0) > 0 for m in months_material
    )
    stat_ok = (headline.get("n", 0) >= 200 and (headline.get("avg_pnl_per_share_net") or 0) > 0
               and (headline.get("cluster_tstat") or 0) > 2.0)
    oos_ok = ((oos["oos_after"].get("avg_pnl_per_share_net") or -1) > 0
              and (oos["oos_after"].get("cluster_tstat") or 0) > 2.0)
    drop_ok = (drop_month_net or 0) > COST_FLOOR
    cost_ok = next((s["survives_t2"] for s in stress if s["half_spread"] == 0.02), False)

    blockers: List[str] = []
    if not stat_ok:
        blockers.append("In-Sample-Statistik unter Schwelle (n>=200, net>0, Cluster-t>2).")
    if not oos_ok:
        blockers.append(
            f"OOS (nach {OOS_CUTOFF_ISO[:10]}) erreicht Cluster-t>2 NICHT "
            f"(t={oos['oos_after'].get('cluster_tstat')}, n={oos['oos_after'].get('n')})."
        )
    if not all_months_positive:
        neg = [m["month"] for m in months_material if (m["net"] or 0) <= 0]
        blockers.append(f"Nicht jeder Monat (n>=30) ist netto positiv — negativ: {neg or 'n/a'}.")
    if not drop_ok:
        blockers.append(
            f"Ohne groessten Monat faellt net auf {round(drop_month_net or 0, 4)} "
            f"(<= Kostenschwelle {COST_FLOOR}) — Edge haengt an einem Regime."
        )
    if not cost_ok:
        blockers.append("Bei realistischem 2c-Half-Spread bricht t>2 weg (echte Order-Book-Tiefe fehlt).")

    edge_harvestable = len(blockers) == 0

    if edge_harvestable:
        status = "ERNTBAR — alle Gates frei"
    elif gap_real:
        status = "ECHTE VERZERRUNG, NOCH NICHT ERNTBAR (Regime + Ausfuehrungskosten ungeklaert)"
    else:
        status = "KEIN belastbarer Edge"

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "lead_hours": DEFAULT_LEAD_HOURS,
        "n_records": len(records),
        "status": status,
        "calibration_gap_real": gap_real,
        "edge_harvestable": edge_harvestable,
        "edge_confirmed": edge_harvestable,  # back-compat: only true when harvestable
        "harvest_blockers": blockers,
        "headline_strategy": "NO-fade exact+between, P(YES) 0.10-0.20, held to resolution",
        "headline": headline,
        "calibration_curve": cal,
        "strategy_panel": panel,
        "monthly": months,
        "drop_largest_month_net": drop_month_net,
        "cost_stress": stress,
        "by_city_no_fade_10_20": cities,
        "by_type_no_fade_10_20": types,
        "out_of_sample": oos,
        "lead_sweep": sweep,
        "cost_model": {
            "half_spread_assumed": HALF_SPREAD,
            "cost_floor": COST_FLOOR,
            "fee": "polymarket non-linear taker (max 2% @ p=0.5)",
            "warning": (
                "Half-spread VALIDATED against real CLOB fills 2026-07-27 "
                "(analytics/cost_model.py, n=263): median real premium over raw price "
                "implies half-spread 0.0051 — the 0.005 assumption holds at the median. "
                "BUT the tail is fat (p90 implies ~0.045), and best-ask prices only apply "
                "to fills within the quoted depth."
            ),
        },
        "notice": (
            "READ-ONLY directional-edge research. The calibration GAP is real and clean "
            "(no look-ahead, official resolutions). 'edge_harvestable' stays False until it "
            "survives OOS t>2, every month positive, drop-largest-month above cost, AND a 2c "
            "spread — none of which holds yet. NOT a live-trade authorisation."
        ),
    }


def render_md(report: Dict[str, Any]) -> str:
    oos = report["out_of_sample"]
    lines = [
        "# Edge Research — Polymarket Beobachter",
        "",
        f"**Generiert:** {report['generated_at']}  ",
        f"**Lead:** ~{report['lead_hours']}h vor Resolution · **Markt-Sample:** {report['n_records']}  ",
        f"**STATUS:** {report['status']}",
        "",
        f"- **Kalibrierungs-Verzerrung real?** {'✅ JA' if report['calibration_gap_real'] else '❌ NEIN'} "
        "— der Markt überpreist 10–20%-Longshots statistisch sauber (kein Look-ahead, offizielle Resolutions).",
        f"- **Edge erntbar?** {'✅ JA' if report['edge_harvestable'] else '❌ NOCH NICHT'} "
        "— muss OOS t>2, jeden Monat positiv, drop-größter-Monat über Kosten UND 2c-Spread überleben.",
        "",
    ]
    if report.get("harvest_blockers"):
        lines.append("**Offene Blocker bis erntbar:**")
        for b in report["harvest_blockers"]:
            lines.append(f"- ⛔ {b}")
        lines.append("")
    lines += [
        "> ⚠️ **Ausführungskosten ungemessen:** Es gibt keine echte Order-Book-Tiefe im System; "
        "der Half-Spread ist ein synthetischer ±1c-Platzhalter. Der Netto-Edge hängt daran. "
        "READ-ONLY Research — **keine** Live-Trade-Freigabe.",
        "",
        "## 1. Favorite-Longshot-Kalibrierung (modell-frei)",
        "",
        "Markt-Preis-Bin → tatsächliche YES-Rate. Liegt der Preis über dem 95%-CI der echten "
        "Rate, überpreist der Markt YES → NO faden ist +EV.",
        "",
        "| Preis-Bin | n | Ø Preis | YES-Rate | 95%-CI | Preis−Rate | NO-EV/Share | Markt überpreist? |",
        "|---|---:|---:|---:|---|---:|---:|:--:|",
    ]
    for c in report["calibration_curve"]:
        ci = f"{c['yes_rate_ci95'][0]:.3f}–{c['yes_rate_ci95'][1]:.3f}"
        flag = "✅" if c["market_overprices_yes"] else "·"
        lines.append(
            f"| {c['bin']} | {c['n']} | {c['avg_market_p']:.3f} | {c['empirical_yes_rate']:.3f} "
            f"| {ci} | {c['price_minus_yesrate']:+.3f} | {c['no_fade_ev_per_share']:+.4f} | {flag} |"
        )
    lines += [
        "",
        "## 2. Strategie-Panel (bis Resolution gehalten, netto nach Spread+Fee)",
        "",
        "| Strategie | Seite | n | Cluster | Win% | PnL/Share brutto | PnL/Share netto | ROI% netto | t-Stat |",
        "|---|:--:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name, s in report["strategy_panel"].items():
        if s.get("n", 0) == 0:
            lines.append(f"| {name} | — | 0 | | | | | | |")
            continue
        lines.append(
            f"| {name} | {s.get('side','')} | {s['n']} | {s.get('n_clusters','')} "
            f"| {s['win_rate']*100:.1f} | {s['avg_pnl_per_share_gross']:+.4f} "
            f"| {s['avg_pnl_per_share_net']:+.4f} | {s.get('roi_net_pct','')} "
            f"| {s.get('cluster_tstat','')} |"
        )
    lines += [
        "",
        "## 3. Out-of-Sample (NO-Fade 10–20%)",
        "",
        f"Cutoff **{oos['cutoff']}** — die Edge muss im gehaltenen Fenster überleben.",
        "",
        "| Fenster | n | Win% | PnL/Share netto | t-Stat |",
        "|---|---:|---:|---:|---:|",
    ]
    for label, key in [("Train (vor Cutoff)", "train_before"), ("OOS (nach Cutoff)", "oos_after")]:
        s = oos[key]
        if s.get("n", 0) == 0:
            lines.append(f"| {label} | 0 | | | |")
        else:
            lines.append(
                f"| {label} | {s['n']} | {s['win_rate']*100:.1f} "
                f"| {s['avg_pnl_per_share_net']:+.4f} | {s.get('cluster_tstat','')} |"
            )
    lines += ["", "## 4. Monats-Stabilität (Headline-Edge) — der härteste Test", "",
              "Edge muss in **jedem** Monat positiv sein. Hängt sie an einem Regime, ist sie nicht erntbar.",
              "",
              "| Monat | n | Ø Preis | YES-Rate | Gap | PnL/Share netto | t-Stat |",
              "|---|---:|---:|---:|---:|---:|---:|"]
    for m in report.get("monthly", []):
        net = m.get("net")
        lines.append(
            f"| {m['month']} | {m['n']} | {m['avg_market_p']:.3f} | {m['yes_rate']:.3f} "
            f"| {m['gap']:+.4f} | {net:+.4f} | {m.get('tstat','')} |"
            if net is not None else
            f"| {m['month']} | {m['n']} | {m['avg_market_p']:.3f} | {m['yes_rate']:.3f} "
            f"| {m['gap']:+.4f} | — | |"
        )
    dml = report.get("drop_largest_month_net")
    lines.append("")
    lines.append(
        f"**Ohne größten Monat:** net {dml:+.4f}/Share "
        f"(Kostenschwelle {report['cost_model']['cost_floor']}) → "
        f"{'über Kosten' if (dml or 0) > report['cost_model']['cost_floor'] else 'UNTER Kosten — Edge regime-abhängig'}"
        if dml is not None else "**Ohne größten Monat:** n/a"
    )

    lines += ["", "## 5. Kosten-Stress (echte Order-Book-Tiefe fehlt!)", "",
              "Netto-Edge bei breiterem Half-Spread. Break-even-Zone zeigt, wie fragil die Edge gegen reale Fills ist.",
              "",
              "| Half-Spread | PnL/Share netto | t-Stat | übersteht t>2? |", "|---:|---:|---:|:--:|"]
    for s in report.get("cost_stress", []):
        net = s.get("net")
        flag = "✅" if s.get("survives_t2") else "❌"
        lines.append(
            f"| {s['half_spread']*100:.1f}c | {net:+.4f} | {s.get('tstat','')} | {flag} |"
            if net is not None else f"| {s['half_spread']*100:.1f}c | — | | ❌ |"
        )

    lines += ["", "## 6. Beste Städte (NO-Fade exact+between 10–20%, n≥8)", "",
              "| Stadt | n | Win% | PnL/Share netto | t-Stat |", "|---|---:|---:|---:|---:|"]
    for c in report["by_city_no_fade_10_20"][:12]:
        lines.append(
            f"| {c['city']} | {c['n']} | {c['win_rate']*100:.1f} "
            f"| {c['avg_pnl_per_share_net']:+.4f} | {c.get('cluster_tstat','')} |"
        )
    lines += ["", "## 7. Markttyp (NO-Fade 10–20%)", "",
              "| Typ | n | Win% | PnL/Share netto | t-Stat |", "|---|---:|---:|---:|---:|"]
    for t in report["by_type_no_fade_10_20"]:
        lines.append(
            f"| {t['type']} | {t['n']} | {t['win_rate']*100:.1f} "
            f"| {t['avg_pnl_per_share_net']:+.4f} | {t.get('cluster_tstat','')} |"
        )
    lines += ["", "## 8. Lead-Time-Sweep (10–20%-Band)", "",
              "| Lead h | n | Ø Preis | YES-Rate | NO-EV/Share |", "|---:|---:|---:|---:|---:|"]
    for s in report["lead_sweep"]:
        if s.get("n_band_10_20", s.get("n_band", 0)) == 0:
            lines.append(f"| {s['lead_hours']} | 0 | | | |")
        else:
            lines.append(
                f"| {s['lead_hours']} | {s['n_band_10_20']} | {s['avg_market_p']:.3f} "
                f"| {s['empirical_yes_rate']:.3f} | {s['no_fade_ev_per_share']:+.4f} |"
            )
    lines += ["", "---",
              f"*Kostenmodell: Half-Spread {report['cost_model']['half_spread_assumed']} "
              f"(gegen echte CLOB-Fills validiert, Median — Tail p90 ~0.045), "
              f"Fee = {report['cost_model']['fee']}.*", ""]
    return "\n".join(lines)


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)


def run() -> Dict[str, Any]:
    report = evaluate()
    _atomic_write(OUT_JSON, json.dumps(report, indent=2, ensure_ascii=False))
    _atomic_write(OUT_MD, render_md(report))
    return report


def main() -> None:
    report = run()
    print(render_md(report))


if __name__ == "__main__":
    main()
