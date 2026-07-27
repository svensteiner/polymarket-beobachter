# =============================================================================
# POLYMARKET BEOBACHTER - EDGE SCANNER HARNESS (read-only)
# =============================================================================
#
# WHY (2026-07-27, plan F2):
#   We keep testing edge hypotheses ad hoc. That is how you fool yourself: test
#   20 ideas, one shows t>2 by chance, and you call it an edge. It already
#   almost happened (exact-only NO-fade looked significant, then died forward).
#
#   This harness makes the search honest and repeatable:
#     - every hypothesis runs the SAME walk-forward protocol (train < cutoff,
#       evaluated once on the held-out test window),
#     - the HEADLINE cost is the empirically calibrated real fill cost
#       (analytics/cost_model.py), not the old synthetic 0.5c placeholder,
#     - all p-values get a Benjamini-Hochberg correction, so "significant"
#       accounts for how many ideas we tried,
#     - every hypothesis ever tested is appended to a persistent log, so the
#       multiple-comparison count can never quietly disappear.
#
#   Adding a hypothesis = adding one entry to HYPOTHESES. Nothing else changes.
#
#   READ-ONLY. Never trades, never mutates thresholds. Reuses edge_research's
#   record loader and cluster-aware simulator.
# =============================================================================

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from analytics import cost_model
from analytics.edge_research import build_records, _simulate, _parse_iso

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUT_MD = PROJECT_ROOT / "analytics" / "edge_scanner.md"
OUT_JSON = PROJECT_ROOT / "analytics" / "edge_scanner.json"
HYPOTHESIS_LOG = PROJECT_ROOT / "data" / "edge_hypotheses_log.jsonl"

CUTOFF = "2026-06-01"      # frozen out-of-sample split
ALPHA = 0.05               # BH false-discovery rate
MIN_CLUSTERS = 10          # below this, significance is meaningless


# --------------------------------------------------------------------------- #
# Statistics: t-distribution p-values + Benjamini-Hochberg
# --------------------------------------------------------------------------- #
def _betacf(a: float, b: float, x: float, itmax: int = 200, eps: float = 3e-12) -> float:
    """Continued fraction for the incomplete beta function (Lentz's method)."""
    tiny = 1e-30
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < tiny:
        d = tiny
    d = 1.0 / d
    h = d
    for m in range(1, itmax + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < tiny:
            d = tiny
        c = 1.0 + aa / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < tiny:
            d = tiny
        c = 1.0 + aa / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < eps:
            break
    return h


def _betai(a: float, b: float, x: float) -> float:
    """Regularized incomplete beta I_x(a, b)."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    lbeta = (math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
             + a * math.log(x) + b * math.log(1.0 - x))
    bt = math.exp(lbeta)
    if x < (a + 1.0) / (a + b + 2.0):
        return bt * _betacf(a, b, x) / a
    return 1.0 - bt * _betacf(b, a, 1.0 - x) / b


def two_sided_p(t: Optional[float], df: int) -> Optional[float]:
    """Two-sided p-value for a t-statistic. Conservative choice on purpose:
    we only care about positive edge, but a one-sided test would halve the p
    and make weak findings look better than they are."""
    if t is None or df <= 0:
        return None
    x = df / (df + t * t)
    return min(1.0, _betai(df / 2.0, 0.5, x))


def benjamini_hochberg(pvals: List[Optional[float]], alpha: float = ALPHA):
    """Return (passed_flags, q_values) controlling the false-discovery rate."""
    idx = [i for i, p in enumerate(pvals) if p is not None]
    m = len(idx)
    passed = [False] * len(pvals)
    qvals: List[Optional[float]] = [None] * len(pvals)
    if m == 0:
        return passed, qvals

    order = sorted(idx, key=lambda i: pvals[i])  # type: ignore[index]
    # BH step-up: largest rank k with p_(k) <= alpha*k/m
    kmax = 0
    for rank, i in enumerate(order, start=1):
        if pvals[i] <= alpha * rank / m:  # type: ignore[operator]
            kmax = rank
    for rank, i in enumerate(order, start=1):
        if rank <= kmax:
            passed[i] = True

    # Adjusted q-values (monotone from the largest p downwards)
    running = 1.0
    for rank in range(m, 0, -1):
        i = order[rank - 1]
        q = min(1.0, pvals[i] * m / rank)  # type: ignore[operator]
        running = min(running, q)
        qvals[i] = round(running, 5)
    return passed, qvals


# --------------------------------------------------------------------------- #
# Hypotheses
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Hypothesis:
    name: str
    description: str
    side: str                       # "YES" or "NO"
    select: Callable[[Dict[str, Any]], bool]
    family: str = "misc"


def _band(lo: float, hi: float) -> Callable[[Dict[str, Any]], bool]:
    return lambda r: lo <= r["market_p"] < hi


HYPOTHESES: List[Hypothesis] = [
    # --- Baselines: the known longshot bands (what we already believed) ------
    Hypothesis("no_fade_10_20", "NO-Fade Longshot-Band 10-20%", "NO",
               _band(0.10, 0.20), "longshot"),
    Hypothesis("no_fade_10_15", "NO-Fade 10-15%", "NO", _band(0.10, 0.15), "longshot"),
    Hypothesis("no_fade_15_20", "NO-Fade 15-20%", "NO", _band(0.15, 0.20), "longshot"),
    Hypothesis("no_fade_05_10", "NO-Fade 5-10% (tiefe Longshots)", "NO",
               _band(0.05, 0.10), "longshot"),
    Hypothesis("no_fade_20_30", "NO-Fade 20-30%", "NO", _band(0.20, 0.30), "longshot"),

    # --- B1: the OTHER end of the curve — are favorites UNDERpriced? --------
    Hypothesis("yes_favorite_80_plus", "YES auf starke Favoriten (P>=0.80)", "YES",
               lambda r: r["market_p"] >= 0.80, "favorite"),
    Hypothesis("yes_favorite_65_80", "YES auf Favoriten 65-80%", "YES",
               _band(0.65, 0.80), "favorite"),
    Hypothesis("yes_favorite_50_65", "YES auf leichte Favoriten 50-65%", "YES",
               _band(0.50, 0.65), "favorite"),

    # --- Market-type splits inside the longshot band -------------------------
    Hypothesis("no_fade_exact", "NO-Fade 10-20%, nur exact", "NO",
               lambda r: _band(0.10, 0.20)(r) and r["type"] == "exact", "type_split"),
    Hypothesis("no_fade_between", "NO-Fade 10-20%, nur between", "NO",
               lambda r: _band(0.10, 0.20)(r) and r["type"] == "between", "type_split"),
    Hypothesis("no_fade_boundary", "NO-Fade 10-20%, nur at_or_above/below", "NO",
               lambda r: _band(0.10, 0.20)(r)
               and r["type"] in ("at_or_above", "at_or_below"), "type_split"),

    # --- B3: regime-timed — only trade when the bias is actually present -----
    # trailing_gap is computed WITHOUT look-ahead (only markets already resolved).
    Hypothesis("no_fade_regime_gap_pos", "NO-Fade 10-20% nur wenn Trailing-Gap > 0", "NO",
               lambda r: _band(0.10, 0.20)(r)
               and (r.get("trailing_gap") or -1) > 0.0, "regime"),
    Hypothesis("no_fade_regime_gap_02", "NO-Fade 10-20% nur wenn Trailing-Gap > 0.02", "NO",
               lambda r: _band(0.10, 0.20)(r)
               and (r.get("trailing_gap") or -1) > 0.02, "regime"),
    Hypothesis("no_fade_exact_regime", "NO-Fade exact nur wenn Trailing-Gap > 0.02", "NO",
               lambda r: _band(0.10, 0.20)(r) and r["type"] == "exact"
               and (r.get("trailing_gap") or -1) > 0.02, "regime"),

    # --- Control: does our (anti-calibrated) model add anything? -------------
    Hypothesis("model_confirm_control", "NO-Fade nur wenn Modell auch fadet (Kontrolle)", "NO",
               lambda r: _band(0.10, 0.20)(r) and r.get("model_p") is not None
               and r["model_p"] < r["market_p"] - 0.03, "control"),
]


# --------------------------------------------------------------------------- #
# Feature enrichment (no look-ahead)
# --------------------------------------------------------------------------- #
def add_trailing_gap(records: List[Dict[str, Any]], window_days: float = 14.0,
                     min_n: int = 25) -> None:
    """Attach the rolling favorite-longshot gap KNOWN AT OBSERVATION TIME.

    gap = mean(market price) - mean(realised YES rate) over the trailing window,
    computed ONLY from markets that had already RESOLVED before this observation.
    Using concurrently-open markets would leak the future into the signal.
    """
    enriched = []
    for r in records:
        ts = _parse_iso(r.get("ts"))
        hours = r.get("hours")
        if ts is None:
            r["trailing_gap"] = None
            continue
        res_time = ts + timedelta(hours=float(hours)) if hours is not None else ts
        enriched.append((ts, res_time, r))

    # Sort by resolution time so we can sweep "already known" facts forward.
    known = sorted(enriched, key=lambda x: x[1])
    obs_order = sorted(enriched, key=lambda x: x[0])

    ptr = 0
    window: List[tuple] = []   # (res_time, market_p, outcome)
    for ts, _res, r in obs_order:
        # admit every market resolved strictly before this observation
        while ptr < len(known) and known[ptr][1] <= ts:
            _t, rt, kr = known[ptr]
            if 0.10 <= kr["market_p"] < 0.20:      # gap measured on the traded universe
                window.append((rt, kr["market_p"], kr["outcome"]))
            ptr += 1
        # drop anything older than the window
        cutoff_time = ts - timedelta(days=window_days)
        while window and window[0][0] < cutoff_time:
            window.pop(0)

        if len(window) >= min_n:
            avg_p = sum(w[1] for w in window) / len(window)
            yes_rate = sum(w[2] for w in window) / len(window)
            r["trailing_gap"] = round(avg_p - yes_rate, 5)
        else:
            r["trailing_gap"] = None


# --------------------------------------------------------------------------- #
# Scan
# --------------------------------------------------------------------------- #
def _verdict(test: Dict[str, Any], bh_pass: bool, floor: float) -> str:
    if test.get("n", 0) == 0:
        return "n/a (keine Trades)"
    if (test.get("n_clusters") or 0) < MIN_CLUSTERS:
        return "n/a (zu wenig Cluster)"
    net = test.get("avg_pnl_per_share_net")
    t = test.get("cluster_tstat")
    if net is None or t is None:
        return "n/a"
    if net <= 0:
        return "❌ negativ nach realen Kosten"
    if not bh_pass:
        return "🟡 positiv, aber nicht BH-signifikant"
    return "✅ ÜBERLEBT (BH-signifikant @ reale Kosten)"


def scan(hypotheses: Optional[List[Hypothesis]] = None) -> Dict[str, Any]:
    hyps = hypotheses if hypotheses is not None else HYPOTHESES

    records = build_records(24.0)
    add_trailing_gap(records)

    train = [r for r in records if (r.get("ts") or "") < CUTOFF]
    test = [r for r in records if (r.get("ts") or "") >= CUTOFF]

    lv = cost_model.levels()
    hs_real = float(lv["realistic"])
    hs_opt = float(lv["optimistic"])
    hs_stress = float(lv["stress"])
    floor = 0.0   # net>0 already accounts for cost; the floor is break-even

    rows: List[Dict[str, Any]] = []
    for h in hyps:
        tr = _simulate(train, h.select, h.side, half_spread=hs_real)
        te = _simulate(test, h.select, h.side, half_spread=hs_real)
        te_opt = _simulate(test, h.select, h.side, half_spread=hs_opt)
        te_str = _simulate(test, h.select, h.side, half_spread=hs_stress)

        df = max(0, (te.get("n_clusters") or 0) - 1)
        p = two_sided_p(te.get("cluster_tstat"), df)
        # one-sided interest: a significant NEGATIVE result is not an edge
        if p is not None and (te.get("cluster_tstat") or 0) <= 0:
            p = 1.0

        rows.append({
            "rule": h.name,
            "description": h.description,
            "family": h.family,
            "side": h.side,
            "train": tr,
            "test": te,
            "test_optimistic_cost": te_opt,
            "test_stress_cost": te_str,
            "p_value": round(p, 6) if p is not None else None,
        })

    passed, qvals = benjamini_hochberg([r["p_value"] for r in rows])
    for r, ok, q in zip(rows, passed, qvals):
        # require enough clusters for the t-stat to mean anything
        enough = (r["test"].get("n_clusters") or 0) >= MIN_CLUSTERS
        r["bh_pass"] = bool(ok and enough)
        r["q_value"] = q
        r["verdict"] = _verdict(r["test"], r["bh_pass"], floor)

    survivors = [r["rule"] for r in rows if r["verdict"].startswith("✅")]

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "cutoff": CUTOFF,
        "n_records": len(records),
        "n_train": len(train),
        "n_test": len(test),
        "cost_levels": {"optimistic": hs_opt, "realistic": hs_real, "stress": hs_stress},
        "cost_calibrated": bool(cost_model.measure().get("calibrated")),
        "alpha": ALPHA,
        "n_hypotheses": len(rows),
        "results": rows,
        "survivors": survivors,
    }


def _append_hypothesis_log(s: Dict[str, Any]) -> None:
    """Persist every hypothesis tested — the multiple-comparison count must never
    quietly vanish between sessions."""
    try:
        HYPOTHESIS_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(HYPOTHESIS_LOG, "a", encoding="utf-8") as f:
            for r in s["results"]:
                te = r["test"]
                f.write(json.dumps({
                    "ts": s["generated_at"],
                    "rule": r["rule"],
                    "family": r["family"],
                    "side": r["side"],
                    "cutoff": s["cutoff"],
                    "half_spread": s["cost_levels"]["realistic"],
                    "oos_n": te.get("n"),
                    "oos_net": te.get("avg_pnl_per_share_net"),
                    "oos_t": te.get("cluster_tstat"),
                    "p_value": r["p_value"],
                    "q_value": r["q_value"],
                    "bh_pass": r["bh_pass"],
                }, ensure_ascii=False) + "\n")
    except Exception as e:  # fail-open
        logger.debug("hypothesis log append failed: %s", e)


def _pct(x: Any) -> str:
    return "—" if x is None else f"{x*100:+.2f}%"


def _render_md(s: Dict[str, Any]) -> str:
    cl = s["cost_levels"]
    lines = [
        "# Edge Scanner — Walk-Forward-Leaderboard",
        "",
        f"**Generiert:** {s['generated_at']}  ",
        f"**OOS-Cutoff:** {s['cutoff']} · TRAIN n={s['n_train']} · TEST n={s['n_test']}  ",
        f"**Kostenniveau (Half-Spread):** realistisch **{cl['realistic']:.4f}** "
        f"(empirisch kalibriert: {s['cost_calibrated']}) · optimistisch {cl['optimistic']:.4f} "
        f"· Stress {cl['stress']:.4f}  ",
        f"**Hypothesen getestet:** {s['n_hypotheses']} · FDR-Korrektur: Benjamini-Hochberg @ α={s['alpha']}",
        "",
        "> Jede Hypothese durchläuft dasselbe Protokoll: auf TRAIN definiert, **einmal** "
        "auf TEST (out-of-sample) ausgewertet, zu **realen** Fill-Kosten. Weil wir viele "
        "Ideen testen, zählt nur, was die BH-Korrektur übersteht — ein einzelnes t>2 "
        "unter vielen Tests ist Rauschen.",
        "",
        "## Leaderboard (OOS @ realen Kosten, sortiert nach q-Wert)",
        "",
        "| Hypothese | n | Netto/Share | Win-Rate | Cluster-t | p | q (BH) | Verdikt |",
        "|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    ranked = sorted(
        s["results"],
        key=lambda r: (r["q_value"] if r["q_value"] is not None else 1.1,
                       -(r["test"].get("avg_pnl_per_share_net") or -9)),
    )
    for r in ranked:
        te = r["test"]
        wr = te.get("win_rate")
        lines.append(
            f"| `{r['rule']}` | {te.get('n', 0)} | {_pct(te.get('avg_pnl_per_share_net'))} | "
            f"{f'{wr*100:.1f}%' if wr is not None else '—'} | "
            f"{te.get('cluster_tstat') if te.get('cluster_tstat') is not None else '—'} | "
            f"{r['p_value'] if r['p_value'] is not None else '—'} | "
            f"{r['q_value'] if r['q_value'] is not None else '—'} | {r['verdict']} |"
        )

    lines += [
        "",
        "## Kostensensitivität (OOS-Netto je Kostenniveau)",
        "",
        "| Hypothese | optimistisch (0,5c) | **realistisch** | Stress (p90) |",
        "|---|---:|---:|---:|",
    ]
    for r in ranked:
        lines.append(
            f"| `{r['rule']}` | {_pct(r['test_optimistic_cost'].get('avg_pnl_per_share_net'))} "
            f"| **{_pct(r['test'].get('avg_pnl_per_share_net'))}** "
            f"| {_pct(r['test_stress_cost'].get('avg_pnl_per_share_net'))} |"
        )

    surv = s["survivors"]
    lines += ["", "## Verdikt", ""]
    if surv:
        lines.append(
            f"**{len(surv)} Hypothese(n) überleben** BH-korrigiert bei realen Kosten: "
            f"{', '.join('`'+x+'`' for x in surv)}. → Kandidat(en) für die Forward-Shadow-Lane. "
            "Kein Kapital, bevor Gate 1/2/3 frei sind."
        )
    else:
        lines.append(
            f"**Keine der {s['n_hypotheses']} Hypothesen überlebt** die BH-Korrektur bei "
            "realen Kosten. Das ist ein ehrliches Ergebnis, kein Fehler: Wir haben aktuell "
            "keine handelbare Edge. Weitersuchen, nichts riskieren."
        )
    lines += [
        "",
        "---",
        "*READ-ONLY · PAPER ONLY · Walk-forward, kein Look-ahead · "
        "Alle je getesteten Hypothesen: `data/edge_hypotheses_log.jsonl`*",
        "",
    ]
    return "\n".join(lines)


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)


def run() -> Dict[str, Any]:
    s = scan()
    try:
        _atomic_write(OUT_MD, _render_md(s))
        _atomic_write(OUT_JSON, json.dumps(s, indent=2, ensure_ascii=False))
        _append_hypothesis_log(s)
    except Exception as e:
        logger.debug("edge_scanner write failed: %s", e)
    return s


def main() -> None:
    s = run()
    cl = s["cost_levels"]
    print(f"records={s['n_records']} train={s['n_train']} test={s['n_test']}")
    print(f"cost: realistic half_spread={cl['realistic']} (calibrated={s['cost_calibrated']})")
    print(f"hypotheses tested: {s['n_hypotheses']}  (BH alpha={s['alpha']})")
    print()
    ranked = sorted(s["results"], key=lambda r: (r["q_value"] if r["q_value"] is not None else 1.1))
    for r in ranked:
        te = r["test"]
        net = te.get("avg_pnl_per_share_net")
        print(f"  {r['rule']:26s} n={te.get('n',0):4d} "
              f"net={_pct(net):>8} t={str(te.get('cluster_tstat')):>7} "
              f"q={str(r['q_value']):>8}  {r['verdict']}")
    print()
    print("SURVIVORS:", s["survivors"] or "NONE")


if __name__ == "__main__":
    main()
