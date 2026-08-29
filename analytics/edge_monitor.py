# =============================================================================
# POLYMARKET BEOBACHTER - EDGE OPPORTUNITY MONITOR (mehrtägige Auswertung)
# =============================================================================
#
# WHY:
#   Der Bot läuft im Dauerlauf (cockpit.py --scheduler) alle 15 Min. Jeder Zyklus
#   scannt das volle Kandidaten-Universum auf fill-überlebende Edge und hängt eine
#   Zeile an analytics/basket_arb_history.jsonl. Sobald eine FÜLLBARE, risikofreie
#   Chance auftritt, eröffnet die Basket-Arb-Lane automatisch eine Paper-Position.
#
#   Dieses Modul aggregiert die Zeitreihe + die Lane-/NO-Fade-Ledger zu EINEM
#   review-freundlichen Report, der die zentrale Frage über Tage beantwortet:
#   "Ist je eine fill-überlebende Edge aufgetreten — und hat der Bot sie gehandelt?"
#
#   READ-ONLY. Schreibt analytics/edge_monitor.md + .json.
# =============================================================================

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
HISTORY_PATH = PROJECT_ROOT / "analytics" / "basket_arb_history.jsonl"
BASKET_LEDGER = PROJECT_ROOT / "data" / "basket_arb_ledger.jsonl"
NOFADE_LEDGER = PROJECT_ROOT / "data" / "no_fade_shadow.jsonl"
OUT_MD = PROJECT_ROOT / "analytics" / "edge_monitor.md"
OUT_JSON = PROJECT_ROOT / "analytics" / "edge_monitor.json"


def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    rows: List[Dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def summarize_history(history: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Aggregate the per-scan opportunity time series (pure)."""
    if not history:
        return {
            "scans": 0, "first_ts": None, "last_ts": None,
            "ever_actionable": 0, "total_actionable_scans": 0,
            "best_fillable_net_ever": None, "best_fillable_family_ever": None,
            "max_overpriced_families": 0, "max_deviation_ever": None,
        }
    actionable_scans = [h for h in history if (h.get("actionable_families") or 0) > 0]
    nets = [h["best_fillable_net"] for h in history if h.get("best_fillable_net") is not None]
    best_net = max(nets) if nets else None
    best_fam = None
    if best_net is not None:
        for h in history:
            if h.get("best_fillable_net") == best_net:
                best_fam = h.get("best_fillable_family")
                break
    return {
        "scans": len(history),
        "first_ts": history[0].get("ts"),
        "last_ts": history[-1].get("ts"),
        "ever_actionable": 1 if actionable_scans else 0,
        "total_actionable_scans": len(actionable_scans),
        "best_fillable_net_ever": best_net,
        "best_fillable_family_ever": best_fam,
        "max_overpriced_families": max((h.get("overpriced_families") or 0) for h in history),
        "max_deviation_ever": max((h.get("max_deviation") or 0.0) for h in history),
    }


def summarize_ledger(rows: List[Dict[str, Any]], pnl_key: str) -> Dict[str, Any]:
    """Aggregate a paper-position ledger (basket-arb or no-fade). Pure."""
    open_n = sum(1 for r in rows if r.get("status") == "OPEN")
    resolved = [r for r in rows if r.get("status") == "RESOLVED"]
    pnls = [float(r[pnl_key]) for r in resolved if r.get(pnl_key) is not None]
    return {
        "total": len(rows),
        "open": open_n,
        "resolved": len(resolved),
        "realized_pnl": round(sum(pnls), 4) if pnls else 0.0,
        "wins": sum(1 for p in pnls if p > 0),
        "losses": sum(1 for p in pnls if p < 0),
    }


def build_report() -> Dict[str, Any]:
    hist = summarize_history(_read_jsonl(HISTORY_PATH))
    basket = summarize_ledger(_read_jsonl(BASKET_LEDGER), "realized_pnl")
    nofade = summarize_ledger(_read_jsonl(NOFADE_LEDGER), "pnl_real_per_share")
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "opportunity_history": hist,
        "basket_arb_lane": basket,
        "no_fade_lane": nofade,
        "verdict": (
            "FILLABLE EDGE APPEARED — check lanes"
            if hist["ever_actionable"] or basket["total"] > 0
            else "no fill-survivable edge yet (market efficient net of costs)"
        ),
    }


def _render_md(r: Dict[str, Any]) -> str:
    h = r["opportunity_history"]; b = r["basket_arb_lane"]; nf = r["no_fade_lane"]
    return "\n".join([
        "# Edge-Monitor — mehrtägige Auswertung",
        "",
        f"**Generiert:** {r['generated_at']}  ",
        f"**Verdikt:** {r['verdict']}",
        "",
        "## Chancen-Verlauf (basket_arb_history.jsonl)",
        f"- Scans: **{h['scans']}** ({h['first_ts']} → {h['last_ts']})",
        f"- Je eine ausführbare (fill-überlebende) Chance? **{'JA' if h['ever_actionable'] else 'nein'}** "
        f"(actionable Scans: {h['total_actionable_scans']})",
        f"- Beste füllbare Netto-Chance je: **{h['best_fillable_net_ever']}** "
        f"({h['best_fillable_family_ever'] or '—'})",
        f"- Max. überpreiste Familien / max. Abweichung: {h['max_overpriced_families']} / {h['max_deviation_ever']}",
        "",
        "## Basket-Arb-Lane (risikofreie Körbe)",
        f"- Positionen: **{b['total']}** (offen {b['open']}, aufgelöst {b['resolved']}), "
        f"realized PnL {b['realized_pnl']:+.4f} (W{b['wins']}/L{b['losses']})",
        "",
        "## NO-Fade-Lane (fill-aware Forward-Shadow)",
        f"- Positionen: **{nf['total']}** (offen {nf['open']}, aufgelöst {nf['resolved']}), "
        f"realized PnL/Share {nf['realized_pnl']:+.4f} (W{nf['wins']}/L{nf['losses']})",
        "",
        "> Läuft im 15-Min-Scheduler. Sobald `ever_actionable=JA` oder die Basket-Lane "
        "Positionen zeigt, hat der Bot eine echte fill-überlebende Edge gehandelt.",
        "",
    ])


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)


def run() -> Dict[str, Any]:
    report = build_report()
    try:
        _atomic_write(OUT_JSON, json.dumps(report, indent=2, ensure_ascii=False))
        _atomic_write(OUT_MD, _render_md(report))
    except Exception:
        pass
    return report


def main() -> None:
    print(json.dumps(run(), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
