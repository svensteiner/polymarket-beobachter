# =============================================================================
# POLYMARKET BEOBACHTER - EDGE ROUTINE (3x daily, read-only analysis)
# =============================================================================
#
# WHY (2026-07-27):
#   The heavy edge scans deliberately do NOT run in the 15-minute pipeline (that
#   cycle must stay under ~2 minutes). But an analysis nobody re-runs goes stale
#   and silently stops reflecting reality — which is exactly how the NO-fade
#   candidate stayed "alive" in our heads for two weeks after the regime flipped.
#
#   This routine is the scheduled counterpart: it re-runs every heavy scan, then
#   does the part a raw scan cannot — it DIFFS against the previous run and says
#   what actually CHANGED and what to do next. State changes are the signal;
#   unchanged numbers are noise.
#
#   Watched transitions (the ones that would change our decisions):
#     - a hypothesis survives the BH-corrected walk-forward  -> real candidate
#     - the regime guard un-pauses (longshot gap turns positive again)
#     - the live candidate cohort crosses break-even
#     - arbitrage becomes capturable after real costs
#
#   READ-ONLY: runs analyses, writes reports. Never trades, never edits config.
# =============================================================================

from __future__ import annotations

import json
import logging
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATE_PATH = PROJECT_ROOT / "data" / "edge_routine_state.json"
HISTORY_PATH = PROJECT_ROOT / "data" / "edge_routine_history.jsonl"
DIGEST_MD = PROJECT_ROOT / "analytics" / "edge_routine_digest.md"
GAP_JSON = PROJECT_ROOT / "analytics" / "gap_monitor.json"
FWD_JSON = PROJECT_ROOT / "analytics" / "forward_reconciliation.json"
PLAN_MD = "reports/edge_search_plan_2026-07-27.md"


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.debug("read %s failed: %s", path, e)
    return {}


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)


# --------------------------------------------------------------------------- #
# Run the heavy scans (each isolated: one failure must not kill the routine)
# --------------------------------------------------------------------------- #
def _run_scans() -> Dict[str, Any]:
    results: Dict[str, Any] = {}
    errors: List[str] = []

    steps = [
        ("cost_model", "analytics.cost_model"),
        ("edge_scanner", "analytics.edge_scanner"),
        ("model_skill_scan", "analytics.model_skill_scan"),
        ("arb_capturability", "analytics.arb_capturability"),
        ("arb_partition_coverage", "analytics.arb_partition_coverage"),
        ("forward_reconciliation", "analytics.forward_reconciliation"),
    ]
    for name, module_path in steps:
        try:
            module = __import__(module_path, fromlist=["run"])
            results[name] = module.run()
        except Exception as e:
            errors.append(f"{name}: {type(e).__name__}: {e}")
            logger.warning("Scan %s failed: %s", name, e)
            logger.debug(traceback.format_exc())
            results[name] = {}
    results["_errors"] = errors
    return results


# --------------------------------------------------------------------------- #
# Condense to the handful of numbers that can change a decision
# --------------------------------------------------------------------------- #
def _snapshot(scans: Dict[str, Any]) -> Dict[str, Any]:
    sc = scans.get("edge_scanner") or {}
    skill = scans.get("model_skill_scan") or {}
    arb = scans.get("arb_capturability") or {}
    arbpart = scans.get("arb_partition_coverage") or {}
    cost = scans.get("cost_model") or {}
    gap = _read_json(GAP_JSON)
    fwd = _read_json(FWD_JSON)

    best_rule = None
    best_q = None
    best_net = None
    best_t = None
    for r in sorted(
        sc.get("results", []),
        key=lambda x: (x.get("q_value") if x.get("q_value") is not None else 1.1),
    ):
        te = r.get("test") or {}
        if te.get("n", 0) > 0:
            best_rule, best_q = r.get("rule"), r.get("q_value")
            best_net, best_t = te.get("avg_pnl_per_share_net"), te.get("cluster_tstat")
            break

    cohort = (fwd.get("cohorts") or {}).get("exact_tight_spread") or {}

    return {
        "ts": datetime.now(timezone.utc).isoformat(),
        "survivors": sc.get("survivors", []),
        "n_hypotheses": sc.get("n_hypotheses"),
        "oos_n": sc.get("n_test"),
        "best_rule": best_rule,
        "best_q": best_q,
        "best_net": best_net,
        "best_t": best_t,
        "model_skill_survivors": [f"{x.get('city')}×{x.get('type')}"
                                  for x in (skill.get("survivors") or [])],
        "model_skill_cells_tested": skill.get("n_cells_tested"),
        "model_skill_diff_oos": ((skill.get("global_test") or {}).get("mean_diff")),
        "arb_capturable": arb.get("capturable"),
        "arb_net_per_set": arb.get("avg_net_per_set"),
        "arb_partition_in_universe": arbpart.get("partitions_in_universe"),
        "arb_partition_complete": arbpart.get("complete_partitions"),
        "arb_partition_cov_median": arbpart.get("price_coverage_median"),
        "arb_partition_cov_max": arbpart.get("price_coverage_max"),
        "regime_auto_pause": gap.get("auto_pause"),
        "regime_gap_14d": ((gap.get("trailing") or {}).get("d14") or {}).get("gap"),
        "cohort_n": cohort.get("n"),
        "cohort_net_real": cohort.get("net_real"),
        "forward_resolved": fwd.get("n_forward_resolved"),
        "half_spread_realistic": (cost.get("half_spread_levels") or {}).get("realistic"),
        "errors": scans.get("_errors", []),
    }


def _diff(prev: Optional[Dict[str, Any]], cur: Dict[str, Any]) -> List[str]:
    """Only report transitions that would change what we do next."""
    if not prev:
        return ["Erster Routine-Lauf — Referenzstand aufgenommen."]

    out: List[str] = []

    new_surv = set(cur.get("survivors") or []) - set(prev.get("survivors") or [])
    lost_surv = set(prev.get("survivors") or []) - set(cur.get("survivors") or [])
    if new_surv:
        out.append(f"🟢 **NEUER ÜBERLEBENDER im Walk-Forward: {', '.join(sorted(new_surv))}** "
                   "— BH-korrigiert signifikant bei realen Kosten. Prüfen und als "
                   "Forward-Kohorte aufnehmen.")
    if lost_surv:
        out.append(f"🔻 Überlebende verloren: {', '.join(sorted(lost_surv))}.")

    if prev.get("regime_auto_pause") and cur.get("regime_auto_pause") is False:
        out.append("🟢 **Regime-Guard hat DEPAUSIERT** — die Longshot-Verzerrung ist zurück. "
                   "NO-Fade-Lane nimmt wieder Entries auf; Kandidaten-Kohorte beobachten.")
    if prev.get("regime_auto_pause") is False and cur.get("regime_auto_pause"):
        out.append("🛑 Regime-Guard hat PAUSIERT — Verzerrung verschwunden, keine neuen Entries.")

    pn, cn = prev.get("cohort_net_real"), cur.get("cohort_net_real")
    if pn is not None and cn is not None:
        if pn <= 0 < cn:
            out.append(f"🟢 Kandidaten-Kohorte ist über Break-even ({cn*100:+.2f}%, "
                       f"n={cur.get('cohort_n')}) — bei kleinem n noch Rauschen, weiter sammeln.")
        elif cn <= 0 < pn:
            out.append(f"🔻 Kandidaten-Kohorte wieder unter Break-even ({cn*100:+.2f}%).")

    new_skill = set(cur.get("model_skill_survivors") or []) - set(prev.get("model_skill_survivors") or [])
    if new_skill:
        out.append(f"🟢 **NEUE Modell-Skill-Nische: {', '.join(sorted(new_skill))}** "
                   "— Modell-Brier < Markt-Brier OOS, BH-korrigiert. Unabhängig nachrechnen, "
                   "Regime-Stabilität prüfen, dann Forward-Shadow. KEIN Kapital.")

    if not prev.get("arb_capturable") and cur.get("arb_capturable"):
        out.append("🟢 **Arbitrage ist nach realen Kosten erntbar geworden** — vor jeder "
                   "Schlussfolgerung Vollständigkeit der Bucket-Mengen und Order-Book-Tiefe prüfen.")

    pf, cf = prev.get("forward_resolved") or 0, cur.get("forward_resolved") or 0
    if cf >= 150 > pf:
        out.append(f"🟢 Gate-1-Stichprobe erreicht: {cf} aufgelöste Forward-Positionen (Ziel 150).")

    if cur.get("errors"):
        out.append(f"⚠️ Fehler in Scans: {'; '.join(cur['errors'])}")

    if not out:
        out.append("Keine entscheidungsrelevante Änderung seit dem letzten Lauf.")
    return out


def _worklist(cur: Dict[str, Any]) -> List[str]:
    """Prioritised open work — what the next agent session should pick up."""
    items: List[str] = []

    if cur.get("survivors"):
        items.append("**Priorität 1:** Überlebende Hypothese verifizieren (unabhängig "
                     "nachrechnen, Regime-Stabilität prüfen) und als Forward-Shadow-Kohorte "
                     "in `forward_reconciliation.py` aufnehmen. KEIN Kapital vor Gate 1/2/3.")
    else:
        items.append("**B2-Fortsetzung (aussichtsreichster Pfad):** Pro Event die vollständige "
                     "Bucket-Marktliste aus der Gamma-API persistieren "
                     "(`/events?tag_slug=weather` nutzt der Collector bereits), damit "
                     "Vollständigkeit VOR dem Handel prüfbar ist statt aus dem Ausgang. "
                     "Erst dann ist der Arbitrage-Test valide wiederholbar — und es wäre die "
                     "einzige modell- UND regime-unabhängige Edge-Klasse.")
        if cur.get("model_skill_survivors"):
            items.append("**B4-Folge:** Modell-Skill-Nische(n) "
                         f"{', '.join(cur['model_skill_survivors'])} verifizieren "
                         "und in Forward-Shadow überführen.")
        else:
            items.append("**B4 erledigt (negativ):** Konditionaler Modell-Skill-Scan "
                         "(`analytics/model_skill_scan.py`) findet KEINE Stadt×Typ-Nische mit "
                         "Modell-Brier < Markt-Brier OOS (BH-korrigiert). Forecaster ist auch "
                         "konditional nicht überlegen — nicht erneut aufrollen ohne neues "
                         "Modell-/Datenmaterial.")
        items.append("**B5:** Preis-Momentum — zuerst verifizieren, ob "
                     "`logs/weather_observations*.jsonl` mehrere Snapshots je Markt enthält.")
        items.append("**Neue Hypothesen** sind billig: ein Eintrag in `HYPOTHESES` in "
                     "`analytics/edge_scanner.py` genügt, das Harness erledigt Walk-Forward, "
                     "reale Kosten und BH-Korrektur.")

    if cur.get("regime_auto_pause"):
        items.append("NO-Fade bleibt regime-pausiert — nicht daran weiterarbeiten, solange "
                     "der Gap negativ ist.")
    return items


def _render_md(cur: Dict[str, Any], changes: List[str], work: List[str]) -> str:
    def pct(x):
        return "—" if x is None else f"{x*100:+.2f}%"

    def _cov(x):  # unsigned percentage for coverage fractions
        return "—" if x is None else f"{x*100:.1f}%"

    lines = [
        "# Edge-Routine — Digest",
        "",
        f"**Lauf:** {cur['ts']}  ",
        f"**Status:** {'⚠️ mit Fehlern' if cur.get('errors') else 'OK'}",
        "",
        "## Was hat sich geändert",
        "",
    ]
    lines += [f"- {c}" for c in changes]

    lines += [
        "",
        "## Aktueller Stand",
        "",
        "| Kennzahl | Wert |",
        "|---|---|",
        f"| Überlebende Hypothesen | **{', '.join(cur.get('survivors') or []) or 'KEINE'}** |",
        f"| Hypothesen getestet / OOS n | {cur.get('n_hypotheses')} / {cur.get('oos_n')} |",
        f"| Bester Kandidat | `{cur.get('best_rule')}` · net {pct(cur.get('best_net'))} "
        f"· t={cur.get('best_t')} · q={cur.get('best_q')} |",
        f"| Regime-Guard | {'🛑 PAUSIERT' if cur.get('regime_auto_pause') else '✅ aktiv'} |",
        f"| Forward aufgelöst (Gate 1: 150) | {cur.get('forward_resolved')} |",
        f"| Kandidaten-Kohorte (exact+eng) | n={cur.get('cohort_n')} · "
        f"net real {pct(cur.get('cohort_net_real'))} |",
        f"| Modell-Skill-Nische (B4) | {', '.join(cur.get('model_skill_survivors') or []) or 'KEINE'} "
        f"(getestet {cur.get('model_skill_cells_tested')} Zellen · Δ OOS {pct(cur.get('model_skill_diff_oos'))}) |",
        f"| Arbitrage erntbar | {'JA' if cur.get('arb_capturable') else 'nein'} "
        f"({pct(cur.get('arb_net_per_set'))}/Set) |",
        f"| Arb-Partitionen (negRisk) | {cur.get('arb_partition_complete')}/"
        f"{cur.get('arb_partition_in_universe')} vollständig · Preis-Coverage "
        f"median {_cov(cur.get('arb_partition_cov_median'))} / max {_cov(cur.get('arb_partition_cov_max'))} |",
        f"| Half-Spread (kalibriert) | {cur.get('half_spread_realistic')} |",
        "",
        "## Nächste Arbeit",
        "",
    ]
    lines += [f"{i}. {w}" for i, w in enumerate(work, 1)]

    lines += [
        "",
        "---",
        f"*Läuft 3x täglich lokal (Task `WeatherObserver-EdgeRoutine`). "
        f"Plan + Methoden-Guardrails: `{PLAN_MD}` · Historie: `data/edge_routine_history.jsonl`*",
        "",
    ]
    return "\n".join(lines)


def run() -> Dict[str, Any]:
    prev = _read_json(STATE_PATH) or None
    scans = _run_scans()
    cur = _snapshot(scans)
    changes = _diff(prev, cur)
    work = _worklist(cur)

    try:
        _atomic_write(DIGEST_MD, _render_md(cur, changes, work))
        _atomic_write(STATE_PATH, json.dumps(cur, indent=2, ensure_ascii=False))
        HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(HISTORY_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps({**cur, "changes": changes}, ensure_ascii=False) + "\n")
    except Exception as e:
        logger.warning("edge_routine write failed: %s", e)

    return {"snapshot": cur, "changes": changes, "worklist": work}


def main() -> None:
    out = run()
    cur = out["snapshot"]
    print("=" * 60)
    print(f"EDGE ROUTINE  {cur['ts']}")
    print("=" * 60)
    for c in out["changes"]:
        print(f"  {c}")
    print()
    print(f"  Survivors : {cur.get('survivors') or 'KEINE'}")
    print(f"  Best      : {cur.get('best_rule')} net={cur.get('best_net')} q={cur.get('best_q')}")
    print(f"  Regime    : {'PAUSED' if cur.get('regime_auto_pause') else 'active'}")
    print(f"  Forward   : {cur.get('forward_resolved')} resolved")
    print(f"  Arb       : capturable={cur.get('arb_capturable')} ({cur.get('arb_net_per_set')})")
    if cur.get("errors"):
        print(f"  ERRORS    : {cur['errors']}")
    print()
    print(f"  Digest -> {DIGEST_MD}")


if __name__ == "__main__":
    main()
