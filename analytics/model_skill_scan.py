# =============================================================================
# POLYMARKET BEOBACHTER - CONDITIONAL MODEL-SKILL SCAN (read-only)  [Plan B4]
# =============================================================================
#
# WHY (2026-07-28, plan B4):
#   forward_validation.py already proved the forecast model has NO GLOBAL
#   calibration edge: model Brier (0.161) >= market Brier (0.147) over the whole
#   universe. But "no edge on average" does not rule out a NICHE. Maybe the model
#   beats the market in exactly one corner — a particular city, a particular
#   market type — even while it loses everywhere else. If such a cell exists and
#   survives out-of-sample + a multiple-comparison correction, it would be the
#   project's FIRST genuine forecasting edge.
#
#   This scan looks for that niche honestly:
#     - Metric: the PAIRED Brier difference per market
#         d = (market_p - y)^2 - (model_p - y)^2      (d > 0  =>  model sharper)
#       Paired, so it cancels the intrinsic difficulty of each market.
#     - Raster: (city x type). Lead is deliberately NOT a cell dimension — the
#       records are anchored at a ~24h lead (p25=17h, p75=25h), so a lead split
#       would only shred cells below usable n without adding real variation.
#       Month is used as a REGIME robustness cut, not a cell dimension (a July
#       cell would live entirely in the test window and could not be selected).
#     - Walk-forward, no look-ahead: a cell is a CANDIDATE only if it is positive
#       on TRAIN (< cutoff) with enough data; it is then evaluated EXACTLY ONCE
#       on the held-out TEST window.
#     - Cluster-t by (city, date): correlated same-day markets count once.
#     - Benjamini-Hochberg across all candidate cells' test p-values: a single
#       t>2 among many cells is noise, not skill.
#
#   READ-ONLY. Never trades, never mutates thresholds. Fail-open. Writes:
#     - analytics/model_skill_scan.json   (machine-readable)
#     - analytics/model_skill_scan.md     (human report)
# =============================================================================

from __future__ import annotations

import json
import logging
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from analytics.edge_research import build_records
from analytics.edge_scanner import benjamini_hochberg, two_sided_p

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUT_JSON = PROJECT_ROOT / "analytics" / "model_skill_scan.json"
OUT_MD = PROJECT_ROOT / "analytics" / "model_skill_scan.md"

CUTOFF = "2026-06-01"      # frozen out-of-sample split (same as edge_scanner)
ALPHA = 0.05              # BH false-discovery rate
MIN_N = 30               # minimum markets per cell (train AND test) to test it
MIN_CLUSTERS = 8         # below this, a cell's cluster-t is meaningless
LEAD_HOURS = 24.0


# --------------------------------------------------------------------------- #
# Core metric: paired Brier difference, cluster-aware t-stat
# --------------------------------------------------------------------------- #
def _brier_diff(r: Dict[str, Any]) -> Optional[float]:
    """d = market_Brier - model_Brier for one market. Positive => model sharper."""
    y = r.get("outcome")
    mp = r.get("market_p")
    fp = r.get("model_p")
    if y is None or mp is None or fp is None:
        return None
    return (mp - y) ** 2 - (fp - y) ** 2


def _cluster_stats(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Mean paired Brier diff + cluster-aware one-sample t across (city, date)."""
    diffs: List[float] = []
    clusters: Dict[str, List[float]] = {}
    bm = 0.0   # market Brier accumulator
    bf = 0.0   # model  Brier accumulator
    for r in records:
        d = _brier_diff(r)
        if d is None:
            continue
        y, mp, fp = r["outcome"], r["market_p"], r["model_p"]
        bm += (mp - y) ** 2
        bf += (fp - y) ** 2
        diffs.append(d)
        key = f"{r.get('city')}|{(r.get('ts') or '')[:10]}"
        clusters.setdefault(key, []).append(d)

    n = len(diffs)
    if n == 0:
        return {"n": 0}

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
        "market_brier": round(bm / n, 5),
        "model_brier": round(bf / n, 5),
        "mean_diff": round(sum(diffs) / n, 6),      # >0 => model beats market
        "cluster_mean_diff": round(cm, 6),
        "cluster_tstat": round(tstat, 3) if tstat is not None else None,
    }


# --------------------------------------------------------------------------- #
# Cells + walk-forward scan
# --------------------------------------------------------------------------- #
def _cell_key(r: Dict[str, Any]) -> Tuple[str, str]:
    return (str(r.get("city") or "UNKNOWN"), str(r.get("type") or "unknown"))


def _monthly_diffs(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for r in records:
        groups.setdefault((r.get("ts") or "")[:7], []).append(r)
    out = []
    for month, rs in sorted(groups.items()):
        if not month:
            continue
        st = _cluster_stats(rs)
        out.append({
            "month": month,
            "n": st.get("n", 0),
            "mean_diff": st.get("mean_diff"),
            "model_brier": st.get("model_brier"),
            "market_brier": st.get("market_brier"),
        })
    return out


def scan() -> Dict[str, Any]:
    records = build_records(LEAD_HOURS)
    records = [r for r in records if _brier_diff(r) is not None]

    train = [r for r in records if (r.get("ts") or "") < CUTOFF]
    test = [r for r in records if (r.get("ts") or "") >= CUTOFF]

    # Global baseline (the number forward_validation already reported, recomputed
    # here on the same lead-anchored universe so the scan is self-contained).
    global_all = _cluster_stats(records)
    global_train = _cluster_stats(train)
    global_test = _cluster_stats(test)

    # --- Candidate cells: positive on TRAIN with enough data (no look-ahead) ---
    train_cells: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
    for r in train:
        train_cells.setdefault(_cell_key(r), []).append(r)
    test_cells: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
    for r in test:
        test_cells.setdefault(_cell_key(r), []).append(r)

    rows: List[Dict[str, Any]] = []
    for key, tr_rs in sorted(train_cells.items()):
        tr = _cluster_stats(tr_rs)
        te_rs = test_cells.get(key, [])
        te = _cluster_stats(te_rs)
        city, typ = key
        candidate = (tr.get("n", 0) >= MIN_N and (tr.get("mean_diff") or -1) > 0)
        testable = (te.get("n", 0) >= MIN_N
                    and (te.get("n_clusters") or 0) >= MIN_CLUSTERS)

        # p-value only for candidates that are also testable; one-sided interest
        # (a significantly NEGATIVE cell is not skill).
        p = None
        if candidate and testable:
            df = max(0, (te.get("n_clusters") or 0) - 1)
            p = two_sided_p(te.get("cluster_tstat"), df)
            if p is not None and (te.get("cluster_tstat") or 0) <= 0:
                p = 1.0

        rows.append({
            "city": city,
            "type": typ,
            "train": tr,
            "test": te,
            "is_candidate": bool(candidate),
            "is_testable": bool(testable),
            "p_value": round(p, 6) if p is not None else None,
        })

    # BH across the candidate+testable cells only (those are the actual tests).
    pv = [r["p_value"] for r in rows]
    passed, qvals = benjamini_hochberg(pv)
    survivors: List[Dict[str, Any]] = []
    for r, ok, q in zip(rows, passed, qvals):
        r["q_value"] = q
        te = r["test"]
        skill = (r["is_candidate"] and r["is_testable"]
                 and (te.get("mean_diff") or -1) > 0
                 and (te.get("cluster_tstat") or 0) > 2.0)
        r["bh_pass"] = bool(ok and skill)
        if r["bh_pass"]:
            survivors.append(r)

    # Regime robustness for any survivor (must not hang on one month).
    for r in survivors:
        cell_recs = [x for x in records
                     if _cell_key(x) == (r["city"], r["type"])]
        r["monthly"] = _monthly_diffs(cell_recs)

    n_tested = sum(1 for r in rows if r["p_value"] is not None)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "cutoff": CUTOFF,
        "lead_hours": LEAD_HOURS,
        "n_records": len(records),
        "n_train": len(train),
        "n_test": len(test),
        "min_n_per_cell": MIN_N,
        "alpha": ALPHA,
        "global_all": global_all,
        "global_train": global_train,
        "global_test": global_test,
        "n_cells": len(rows),
        "n_cells_tested": n_tested,
        "cells": rows,
        "survivors": [{"city": s["city"], "type": s["type"],
                       "test": s["test"], "q_value": s["q_value"],
                       "monthly": s.get("monthly")} for s in survivors],
    }


# --------------------------------------------------------------------------- #
# Render
# --------------------------------------------------------------------------- #
def _fmt(x: Any, nd: int = 5) -> str:
    return "—" if x is None else f"{x:+.{nd}f}"


def _render_md(s: Dict[str, Any]) -> str:
    ga, gtr, gte = s["global_all"], s["global_train"], s["global_test"]
    lines = [
        "# Conditional Model-Skill Scan — findet der Forecaster EINE Nische?",
        "",
        f"**Generiert:** {s['generated_at']}  ",
        f"**Lead:** ~{s['lead_hours']}h · **OOS-Cutoff:** {s['cutoff']} · "
        f"TRAIN n={s['n_train']} · TEST n={s['n_test']}  ",
        f"**Raster:** Stadt × Typ · min n/Zelle = {s['min_n_per_cell']} · "
        f"FDR-Korrektur: Benjamini-Hochberg @ α={s['alpha']}",
        "",
        "> **Metrik:** gepaarte Brier-Differenz je Markt "
        "`d = (Markt_p − y)² − (Modell_p − y)²`. **d > 0 ⇒ Modell schärfer als Markt.** "
        "Walk-forward: Zelle ist Kandidat nur, wenn sie auf TRAIN positiv ist; genau "
        "**einmal** auf TEST ausgewertet. Cluster-t nach (Stadt, Datum). Nur was die "
        "BH-Korrektur übersteht, zählt.",
        "",
        "## Globale Grundlinie (recomputed auf lead-anchored Universum)",
        "",
        "| Fenster | n | Markt-Brier | Modell-Brier | Δ (Markt−Modell) | Cluster-t |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for label, g in [("Gesamt", ga), ("Train", gtr), ("TEST (OOS)", gte)]:
        lines.append(
            f"| {label} | {g.get('n',0)} | {g.get('market_brier','—')} | "
            f"{g.get('model_brier','—')} | {_fmt(g.get('mean_diff'),6)} | "
            f"{g.get('cluster_tstat','—')} |"
        )
    lines += [
        "",
        "*Δ < 0 heißt: der Markt ist im Schnitt schärfer als das Modell (Modell-Brier höher). "
        "Das ist der bekannte globale Befund — die Frage ist, ob es eine Ausnahme-Zelle gibt.*",
        "",
        "## Kandidaten-Zellen (auf TRAIN positiv, auf TEST ausgewertet)",
        "",
        "| Stadt | Typ | n(tr) | Δ(tr) | n(te) | Δ(te) | Cluster-t(te) | p | q (BH) | Verdikt |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    # Show every candidate that was testable, ranked by test mean_diff desc.
    shown = [r for r in s["cells"] if r["p_value"] is not None]
    shown.sort(key=lambda r: -(r["test"].get("mean_diff") or -9))
    if not shown:
        lines.append("| _keine testbare Kandidaten-Zelle_ | | | | | | | | | |")
    for r in shown:
        tr, te = r["train"], r["test"]
        if r.get("bh_pass"):
            verdict = "✅ SKILL (BH-signifikant)"
        elif (te.get("mean_diff") or -1) > 0:
            verdict = "🟡 positiv, nicht signifikant"
        else:
            verdict = "❌ negativ auf TEST"
        lines.append(
            f"| {r['city']} | {r['type']} | {tr.get('n',0)} | {_fmt(tr.get('mean_diff'),4)} | "
            f"{te.get('n',0)} | {_fmt(te.get('mean_diff'),4)} | "
            f"{te.get('cluster_tstat','—')} | "
            f"{r['p_value'] if r['p_value'] is not None else '—'} | "
            f"{r['q_value'] if r['q_value'] is not None else '—'} | {verdict} |"
        )

    lines += ["", "## Verdikt", ""]
    surv = s["survivors"]
    if surv:
        names = ", ".join(f"`{x['city']}×{x['type']}`" for x in surv)
        lines.append(
            f"**{len(surv)} Zelle(n) überleben** BH-korrigiert mit Modell-Brier < Markt-Brier "
            f"OOS: {names}. → Kandidat für Regime-Prüfung und Forward-Shadow. "
            "**KEIN Kapital**, bevor die Nische über ≥2 Monate hält und forward bestätigt ist."
        )
        for x in surv:
            lines += ["", f"### Regime-Check {x['city']}×{x['type']}", "",
                      "| Monat | n | Δ (Markt−Modell) | Modell-Brier | Markt-Brier |",
                      "|---|---:|---:|---:|---:|"]
            for m in (x.get("monthly") or []):
                lines.append(
                    f"| {m['month']} | {m['n']} | {_fmt(m.get('mean_diff'),4)} | "
                    f"{m.get('model_brier','—')} | {m.get('market_brier','—')} |"
                )
    else:
        lines.append(
            f"**Keine der {s['n_cells_tested']} getesteten Kandidaten-Zellen** "
            f"(von {s['n_cells']} Stadt×Typ-Zellen) zeigt OOS signifikanten Modell-Skill "
            "nach BH-Korrektur. Das bestätigt: der Forecaster hat **keine handelbare "
            "Prognose-Nische** — global anti-kalibriert, und auch konditional keine Ausnahme. "
            "Ehrliches Nein."
        )
    lines += [
        "",
        "---",
        "*READ-ONLY · Walk-forward, kein Look-ahead · gepaarte Brier-Differenz · "
        "Lead fix ~24h (Daten zu eng geclustert für Lead-Raster) · Monat = Regime-Schnitt, "
        "keine Zell-Dimension.*",
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
        _atomic_write(OUT_JSON, json.dumps(s, indent=2, ensure_ascii=False))
        _atomic_write(OUT_MD, _render_md(s))
    except Exception as e:  # fail-open
        logger.debug("model_skill_scan write failed: %s", e)
    return s


def main() -> None:
    s = run()
    ga, gte = s["global_all"], s["global_test"]
    print(f"records={s['n_records']} train={s['n_train']} test={s['n_test']}")
    print(f"global  : market_brier={ga.get('market_brier')} model_brier={ga.get('model_brier')} "
          f"mean_diff={ga.get('mean_diff')} t={ga.get('cluster_tstat')}")
    print(f"global OOS: market_brier={gte.get('market_brier')} model_brier={gte.get('model_brier')} "
          f"mean_diff={gte.get('mean_diff')} t={gte.get('cluster_tstat')}")
    print(f"cells={s['n_cells']} tested(candidate+testable)={s['n_cells_tested']}")
    print()
    shown = [r for r in s["cells"] if r["p_value"] is not None]
    shown.sort(key=lambda r: -(r["test"].get("mean_diff") or -9))
    for r in shown:
        te = r["test"]
        print(f"  {r['city']:16s} {r['type']:12s} n_te={te.get('n',0):4d} "
              f"diff_te={_fmt(te.get('mean_diff'),4):>9} t={str(te.get('cluster_tstat')):>7} "
              f"q={str(r.get('q_value')):>8} {'PASS' if r.get('bh_pass') else ''}")
    print()
    print("SURVIVORS:", [f"{x['city']}x{x['type']}" for x in s["survivors"]] or "NONE")


if __name__ == "__main__":
    main()
