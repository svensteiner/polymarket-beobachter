# =============================================================================
# POLYMARKET BEOBACHTER - EDGE SALVAGE (walk-forward selection test, read-only)
# =============================================================================
#
# WHY (2026-07-14):
#   The naive NO-fade (band 0.10-0.20, held to resolution) is +2.87%/share in
#   sample but only +1.54% net / cluster-t=1.45 out-of-sample (post 2026-06-01),
#   and NEGATIVE in the live forward lane. forward_reconciliation showed the gap
#   is a win-rate collapse, not cost. Open question: does *disciplined selection*
#   (only the structurally-strong types/cities) survive out-of-sample, or is the
#   whole thing regime-dependent?
#
# METHOD — strict walk-forward, no leakage, no p-hacking:
#   1. Split records at the frozen cutoff 2026-06-01 into TRAIN / TEST.
#   2. Define each selection rule using TRAIN ONLY (thresholds fixed a priori,
#      NOT tuned to maximise TEST).
#   3. Evaluate each rule exactly ONCE on TEST (the held-out out-of-sample set).
#   4. Verdict: a rule "survives" only if OOS net beats the cost floor (~1.47c)
#      AND cluster-t > 2. Report honestly even when nothing survives, and flag
#      the multiple-comparisons caveat (testing several rules inflates the best t).
#
#   READ-ONLY. Reuses edge_research's loaders/simulator. Writes
#   analytics/edge_salvage.md + .json. Never trades, never mutates thresholds.
# =============================================================================

from __future__ import annotations

import json
import logging
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List

from analytics.edge_research import build_records, _simulate

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUT_MD = PROJECT_ROOT / "analytics" / "edge_salvage.md"
OUT_JSON = PROJECT_ROOT / "analytics" / "edge_salvage.json"

CUTOFF = "2026-06-01"            # frozen OOS split (matches edge_research)
BAND = (0.10, 0.20)             # the headline longshot band
COST_FLOOR = 0.0147             # net must clear this to be worth trading
# TRAIN-side selection thresholds — fixed a priori, deliberately NOT optimised.
CITY_MIN_N_TRAIN = 20
CITY_MIN_T_TRAIN = 1.5


def _in_band(r: Dict[str, Any]) -> bool:
    return BAND[0] <= r["market_p"] < BAND[1]


def _split(records: List[Dict[str, Any]]):
    train, test = [], []
    for r in records:
        ts = r.get("ts") or ""
        (test if ts >= CUTOFF else train).append(r)
    return train, test


def _train_strong_cities(train: List[Dict[str, Any]]) -> List[str]:
    """Cities whose in-band NO-fade is significant on TRAIN (t>=1.5, n>=20)."""
    by_city: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in train:
        if _in_band(r):
            by_city[r["city"]].append(r)
    strong = []
    for city, rows in by_city.items():
        if len(rows) < CITY_MIN_N_TRAIN:
            continue
        res = _simulate(rows, lambda r: True, "NO")
        t = res.get("cluster_tstat")
        if t is not None and t >= CITY_MIN_T_TRAIN and res.get("avg_pnl_per_share_net", 0) > COST_FLOOR:
            strong.append(city)
    return sorted(strong)


def _verdict(res: Dict[str, Any]) -> str:
    if res.get("n", 0) == 0:
        return "n/a (leer)"
    net = res.get("avg_pnl_per_share_net")
    t = res.get("cluster_tstat")
    if net is not None and t is not None and net > COST_FLOOR and t > 2.0:
        return "✅ ÜBERLEBT OOS (net>Kosten, t>2)"
    if net is not None and net > COST_FLOOR:
        return "🟡 net>Kosten, aber t<=2 (nicht signifikant)"
    return "❌ scheitert OOS (net<=Kosten)"


def run() -> Dict[str, Any]:
    records = build_records(24.0)
    train, test = _split(records)

    strong_cities = _train_strong_cities(train)
    strong_set = set(strong_cities)

    # Rules: (name, selector). Selectors reference ONLY train-derived facts.
    rules: List[tuple] = [
        ("baseline_band_10_20", lambda r: _in_band(r)),
        ("exact_only", lambda r: _in_band(r) and r["type"] == "exact"),
        ("train_strong_cities", lambda r: _in_band(r) and r["city"] in strong_set),
        ("exact_and_strong_cities",
         lambda r: _in_band(r) and r["type"] == "exact" and r["city"] in strong_set),
        # Control: model-assisted. Model is anti-calibrated, so expected to NOT help.
        ("model_confirm_control",
         lambda r: _in_band(r) and r.get("model_p") is not None and r["model_p"] < r["market_p"] - 0.03),
    ]

    # Cost-stress half-spreads: 0.5c (optimistic synthetic) up to 3c (real spreads
    # measured ~3.6c in the live lane). The edge is only real if it clears cost at
    # a REALISTIC ~2c half-spread, not just the synthetic 0.5c.
    STRESS_SPREADS = [0.005, 0.01, 0.02, 0.03]

    results = []
    for name, sel in rules:
        train_res = _simulate(train, sel, "NO")
        test_res = _simulate(test, sel, "NO")
        cost_stress = []
        for hs in STRESS_SPREADS:
            sr = _simulate(test, sel, "NO", half_spread=hs)
            cost_stress.append({
                "half_spread": hs,
                "net": sr.get("avg_pnl_per_share_net"),
                "cluster_tstat": sr.get("cluster_tstat"),
                "survives_t2": bool(
                    sr.get("cluster_tstat") is not None and sr["cluster_tstat"] > 2.0
                    and sr.get("avg_pnl_per_share_net", 0) > 0
                ),
            })
        results.append({
            "rule": name,
            "train": train_res,
            "test": test_res,
            "cost_stress": cost_stress,
            "verdict": _verdict(test_res),
            # Realistic verdict: must still clear t>2 at a 2c half-spread.
            "survives_realistic_cost": next(
                (c["survives_t2"] for c in cost_stress if c["half_spread"] == 0.02), False
            ),
        })

    # A survivor must clear the walk-forward OOS test AND still work at realistic 2c cost.
    survivors = [r["rule"] for r in results
                 if r["rule"] != "baseline_band_10_20"
                 and r["verdict"].startswith("✅")
                 and r["survives_realistic_cost"]]

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "cutoff": CUTOFF,
        "n_records": len(records),
        "n_train": len(train),
        "n_test": len(test),
        "cost_floor": COST_FLOOR,
        "train_strong_cities": strong_cities,
        "results": results,
        "survivors": survivors,
        "n_rules_tested": len(rules) - 1,
    }


def _pct(x: Any) -> str:
    return "—" if x is None else f"{x*100:+.2f}%"


def _row(res: Dict[str, Any]) -> str:
    if res.get("n", 0) == 0:
        return "0 | — | — | —"
    return (f"{res['n']} | {_pct(res.get('avg_pnl_per_share_net'))} | "
            f"{res.get('win_rate', 0)*100:.1f}% | "
            f"{res.get('cluster_tstat') if res.get('cluster_tstat') is not None else '—'}")


def _render_md(s: Dict[str, Any]) -> str:
    lines = [
        "# Edge Salvage — Walk-Forward-Selektionstest",
        "",
        f"**Generiert:** {s['generated_at']}  ",
        f"**OOS-Cutoff:** {s['cutoff']} · TRAIN n={s['n_train']} · TEST n={s['n_test']}  ",
        "",
        "> Frage: Rettet *disziplinierte Selektion* (nur strukturell starke Typen/"
        "Städte) die NO-Fade-Edge out-of-sample — oder ist sie regime-abhängig? "
        "Regeln werden **nur auf TRAIN** definiert und **genau einmal** auf TEST "
        "geprüft. Überleben = OOS-net > Kostenschwelle (1,47c) UND Cluster-t > 2.",
        "",
        f"**TRAIN-starke Städte (t≥{CITY_MIN_T_TRAIN}, n≥{CITY_MIN_N_TRAIN}):** "
        f"{', '.join(s['train_strong_cities']) or '— (keine)'}",
        "",
        "## Ergebnis (TEST = out-of-sample)",
        "",
        "| Regel | n | Netto/Share | Win-Rate | Cluster-t | Verdikt |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for r in s["results"]:
        t = r["test"]
        cells = _row(t)
        lines.append(f"| `{r['rule']}` | {cells} | {r['verdict']} |")

    lines += [
        "",
        "## Zum Vergleich: dieselben Regeln IN-SAMPLE (TRAIN)",
        "",
        "| Regel | n | Netto/Share | Win-Rate | Cluster-t |",
        "|---|---:|---:|---:|---:|",
    ]
    for r in s["results"]:
        lines.append(f"| `{r['rule']}` | {_row(r['train'])} |")

    # Cost-stress table (the decisive realism check).
    lines += [
        "",
        "## Kosten-Stress OOS (net / t je Half-Spread)",
        "",
        "> Realer NO-Spread in der Live-Lane ~3,6c. Die Edge zählt nur, wenn sie "
        "bei **2c** noch t>2 hält — nicht nur beim synthetischen 0,5c.",
        "",
        "| Regel | 0,5c | 1c | 2c | 3c | @2c real? |",
        "|---|---:|---:|---:|---:|:--:|",
    ]
    for r in s["results"]:
        cs = {c["half_spread"]: c for c in r["cost_stress"]}
        def cell(hs):
            c = cs.get(hs, {})
            net = c.get("net")
            t = c.get("cluster_tstat")
            return f"{_pct(net)} (t={t})" if net is not None else "—"
        ok = "✅" if r.get("survives_realistic_cost") else "❌"
        lines.append(
            f"| `{r['rule']}` | {cell(0.005)} | {cell(0.01)} | {cell(0.02)} | {cell(0.03)} | {ok} |"
        )

    surv = s["survivors"]
    lines += [
        "",
        "## Verdikt",
        "",
    ]
    if surv:
        lines.append(
            f"**{len(surv)} Regel(n) überleben OOS:** {', '.join(surv)}. "
            "→ Kandidat für die Forward-Lane. ABER: "
            f"{s['n_rules_tested']} Regeln getestet — ein einzelnes t>2 unter mehreren "
            "Tests ist mit Vorsicht zu lesen (Multiple-Comparison). Erst forward "
            "bestätigen, bevor Kapital."
        )
    else:
        lines.append(
            "**Keine Regel überlebt OOS mit t>2 über der Kostenschwelle.** "
            "Disziplinierte Selektion rettet die Edge nicht — der In-Sample-Vorteil "
            "ist regime-/selektionsbedingt und reproduziert sich nicht out-of-sample. "
            "Deckt sich mit forward_reconciliation (Win-Rate-Kollaps, fehlendes "
            "Mai-Regime). Kein Live-Kapital gerechtfertigt."
        )
    lines += [
        "",
        "---",
        "*READ-ONLY. PAPER ONLY. Kein Live-Trade-Signal. Walk-forward, kein Look-ahead.*",
        "",
    ]
    return "\n".join(lines)


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)


def main() -> None:
    s = run()
    _atomic_write(OUT_MD, _render_md(s))
    _atomic_write(OUT_JSON, json.dumps(s, indent=2, ensure_ascii=False))
    # Console summary
    print(f"TRAIN n={s['n_train']}  TEST n={s['n_test']}  cutoff={s['cutoff']}")
    print(f"TRAIN-strong cities: {s['train_strong_cities']}")
    for r in s["results"]:
        t = r["test"]
        print(f"  {r['rule']:26s} OOS n={t.get('n',0):4d} "
              f"net={_pct(t.get('avg_pnl_per_share_net'))} "
              f"t={t.get('cluster_tstat')}  {r['verdict']}")
    print(f"SURVIVORS: {s['survivors'] or 'NONE'}")


if __name__ == "__main__":
    main()
