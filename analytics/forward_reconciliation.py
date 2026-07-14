# =============================================================================
# POLYMARKET BEOBACHTER - FORWARD vs BACKTEST RECONCILIATION (read-only)
# =============================================================================
#
# WHY (2026-07-14):
#   The NO-fade edge shows +2.87%/share in the backtest (edge_research.json,
#   n=1142, cluster-t=3.19) but the live forward shadow lane
#   (data/no_fade_shadow.jsonl) runs at -5.04% modeled / -5.42% real per share
#   (n=93). That ~8pp gap is THE open question for Gate 1. If it persists at
#   n>=150 the edge is honestly dead.
#
#   This module decomposes the gap into its three candidate causes so the answer
#   is quantitative, not hand-wavy:
#     - COST:      real fills vs the modeled +/-0.5c spread (execution slippage)
#     - REGIME:    which calendar months the forward window covers vs backtest
#                  (the backtest's edge lives in May; is May even in the forward
#                  window?)
#     - SELECTION: does the lane pick a systematically different / worse market
#                  mix (city, type, entry price) than the backtest universe?
#
#   Identity used (NO held to resolution): pnl_per_share = payoff - cost, where
#   payoff = 1 if the market resolves NO else 0. Averaged:
#       net = win_rate - avg_cost
#   so any gap in net splits exactly into a win-rate part and a cost part:
#       net_fwd - net_bt = (win_rate_fwd - win_rate_bt) - (cost_fwd - cost_bt)
#
#   READ-ONLY. Never trades, never mutates thresholds. Writes
#   analytics/forward_reconciliation.md + .json, refreshed every cycle.
# =============================================================================

from __future__ import annotations

import json
import logging
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LEDGER_PATH = PROJECT_ROOT / "data" / "no_fade_shadow.jsonl"
EDGE_RESEARCH_JSON = PROJECT_ROOT / "analytics" / "edge_research.json"
OUT_MD = PROJECT_ROOT / "analytics" / "forward_reconciliation.md"
OUT_JSON = PROJECT_ROOT / "analytics" / "forward_reconciliation.json"


def _mean(xs: List[float]) -> Optional[float]:
    return sum(xs) / len(xs) if xs else None


def _load_ledger() -> List[Dict[str, Any]]:
    if not LEDGER_PATH.exists():
        return []
    rows: List[Dict[str, Any]] = []
    for line in LEDGER_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def _load_backtest() -> Dict[str, Any]:
    if not EDGE_RESEARCH_JSON.exists():
        return {}
    try:
        return json.loads(EDGE_RESEARCH_JSON.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _month(ts: Optional[str]) -> str:
    if not ts:
        return "?"
    return str(ts)[:7]


def _bucketize(records: List[Dict[str, Any]], key) -> Dict[str, Dict[str, Any]]:
    """Aggregate resolved rows by a key function into win-rate / net stats."""
    groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in records:
        groups[str(key(r))].append(r)
    out: Dict[str, Dict[str, Any]] = {}
    for name, rows in groups.items():
        wins = sum(1 for r in rows if r.get("resolution") == "NO")
        mod = [r["pnl_modeled_per_share"] for r in rows if r.get("pnl_modeled_per_share") is not None]
        real = [r["pnl_real_per_share"] for r in rows if r.get("pnl_real_per_share") is not None]
        out[name] = {
            "n": len(rows),
            "win_rate": round(wins / len(rows), 4) if rows else None,
            "net_modeled": round(_mean(mod), 5) if mod else None,
            "net_real": round(_mean(real), 5) if real else None,
        }
    return out


def reconcile() -> Dict[str, Any]:
    records = _load_ledger()
    resolved = [r for r in records if r.get("status") == "RESOLVED"]
    backtest = _load_backtest()
    bt_head = backtest.get("headline", {}) if backtest else {}

    wins = sum(1 for r in resolved if r.get("resolution") == "NO")
    win_rate_fwd = (wins / len(resolved)) if resolved else None

    mod = [r["pnl_modeled_per_share"] for r in resolved if r.get("pnl_modeled_per_share") is not None]
    real = [r["pnl_real_per_share"] for r in resolved if r.get("pnl_real_per_share") is not None]
    net_modeled_fwd = _mean(mod)
    net_real_fwd = _mean(real)

    modeled_costs = [r["modeled_no_cost"] for r in resolved if r.get("modeled_no_cost") is not None]
    real_costs = [r["real_no_cost"] for r in resolved if r.get("real_no_cost") is not None]
    spreads = [r["real_spread"] for r in resolved if r.get("real_spread") is not None]
    avg_p_yes = _mean([r["market_p_yes"] for r in resolved if r.get("market_p_yes") is not None])

    win_rate_bt = bt_head.get("win_rate")
    net_bt = bt_head.get("avg_pnl_per_share_net")
    # Backtest avg cost is implied by the identity net = win_rate - cost.
    cost_bt = (win_rate_bt - net_bt) if (win_rate_bt is not None and net_bt is not None) else None
    cost_fwd_modeled = _mean(modeled_costs)

    # Gap decomposition on the MODELED leg (isolates regime+selection from real
    # execution cost, which is measured separately below).
    gap_total = (net_modeled_fwd - net_bt) if (net_modeled_fwd is not None and net_bt is not None) else None
    winrate_component = (win_rate_fwd - win_rate_bt) if (win_rate_fwd is not None and win_rate_bt is not None) else None
    cost_component = (
        -(cost_fwd_modeled - cost_bt)
        if (cost_fwd_modeled is not None and cost_bt is not None)
        else None
    )
    # Real execution slippage: modeled leg vs real leg on the same positions.
    exec_slippage = (
        (net_real_fwd - net_modeled_fwd)
        if (net_real_fwd is not None and net_modeled_fwd is not None)
        else None
    )

    by_month = _bucketize(resolved, lambda r: _month(r.get("entry_time")))
    by_type = _bucketize(resolved, lambda r: r.get("market_type") or "?")
    by_city = _bucketize(resolved, lambda r: r.get("city") or "?")

    # Backtest month coverage (which regimes the backtest edge relies on).
    bt_months = {m["month"]: m for m in backtest.get("monthly", [])} if backtest else {}
    fwd_months = set(by_month.keys())
    missing_regimes = sorted(m for m in bt_months if m not in fwd_months)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "n_forward_resolved": len(resolved),
        "forward": {
            "win_rate": round(win_rate_fwd, 4) if win_rate_fwd is not None else None,
            "net_modeled": round(net_modeled_fwd, 5) if net_modeled_fwd is not None else None,
            "net_real": round(net_real_fwd, 5) if net_real_fwd is not None else None,
            "avg_modeled_cost": round(cost_fwd_modeled, 5) if cost_fwd_modeled is not None else None,
            "avg_real_cost": round(_mean(real_costs), 5) if real_costs else None,
            "avg_real_spread": round(_mean(spreads), 4) if spreads else None,
            "avg_entry_p_yes": round(avg_p_yes, 4) if avg_p_yes is not None else None,
        },
        "backtest": {
            "win_rate": win_rate_bt,
            "net": net_bt,
            "implied_avg_cost": round(cost_bt, 5) if cost_bt is not None else None,
            "n": bt_head.get("n"),
        },
        "decomposition": {
            "gap_modeled_total": round(gap_total, 5) if gap_total is not None else None,
            "from_win_rate": round(winrate_component, 5) if winrate_component is not None else None,
            "from_entry_cost": round(cost_component, 5) if cost_component is not None else None,
            "real_execution_slippage": round(exec_slippage, 5) if exec_slippage is not None else None,
        },
        "by_month": by_month,
        "by_type": by_type,
        "by_city": by_city,
        "backtest_months": bt_months,
        "missing_regimes": missing_regimes,
    }


def _pct(x: Any) -> str:
    if x is None:
        return "—"
    return f"{x*100:+.2f}%"


def _render_md(s: Dict[str, Any]) -> str:
    fwd = s["forward"]
    bt = s["backtest"]
    dec = s["decomposition"]

    lines = [
        "# Forward vs Backtest — Reconciliation der NO-Fade-Edge",
        "",
        f"**Generiert:** {s['generated_at']}  ",
        f"**Forward aufgelöst:** {s['n_forward_resolved']}  ",
        "",
        "> Warum liefert der Backtest **+2,87 %/Share**, die Live-Forward-Lane aber "
        "**negativ**? Diese Seite zerlegt die Lücke in Kosten, Regime und Selektion. "
        "Identität (NO bis Resolution): `net = Win-Rate − Ø-Kosten`. READ-ONLY.",
        "",
        "## Kopf-an-Kopf",
        "",
        "| Kennzahl | Forward (live) | Backtest | Δ |",
        "|---|---:|---:|---:|",
        f"| n | {s['n_forward_resolved']} | {bt.get('n') or '—'} | |",
        f"| NO-Win-Rate | {_pct(fwd['win_rate'])} | {_pct(bt['win_rate'])} | "
        f"{_pct((fwd['win_rate'] - bt['win_rate']) if fwd['win_rate'] is not None and bt['win_rate'] is not None else None)} |",
        f"| Netto/Share (modelliert) | {_pct(fwd['net_modeled'])} | {_pct(bt['net'])} | "
        f"{_pct(dec['gap_modeled_total'])} |",
        f"| Netto/Share (real) | {_pct(fwd['net_real'])} | — | |",
        f"| Ø Einstiegskosten | {fwd['avg_modeled_cost']} | {bt['implied_avg_cost']} | |",
        f"| Ø Einstiegs-P(YES) | {fwd['avg_entry_p_yes']} | ~0.142 | |",
        f"| Ø realer Spread | {fwd['avg_real_spread']} | 0.005 (synthetisch) | |",
        "",
        "## Zerlegung der modellierten Lücke",
        "",
        f"Gesamt-Lücke (Forward − Backtest, modelliert): **{_pct(dec['gap_modeled_total'])}**",
        "",
        "| Ursache | Beitrag | Lesart |",
        "|---|---:|---|",
        f"| **Win-Rate / Regime+Selektion** | {_pct(dec['from_win_rate'])} | "
        "Forward-Märkte lösen häufiger YES auf als der Backtest — Kern des Problems. |",
        f"| **Einstiegskosten (Selektion Preisband)** | {_pct(dec['from_entry_cost'])} | "
        "Kauft die Lane teurere/billigere NO-Kontrakte als der Backtest? |",
        f"| **Reale Ausführung (Slippage)** | {_pct(dec['real_execution_slippage'])} | "
        "Echte CLOB-Fills vs. modellierter 0,5c-Spread. |",
        "",
        "> **Merksatz:** Ist der Win-Rate-Beitrag der dominante negative Posten und die "
        "Ausführungs-Slippage klein, liegt es **nicht** an den Fill-Kosten, sondern an "
        "Regime/Selektion — die Edge trifft out-of-sample schlechtere Märkte.",
        "",
        "## Regime-Abdeckung",
        "",
    ]

    missing = s.get("missing_regimes") or []
    if missing:
        details = []
        for m in missing:
            bm = s["backtest_months"].get(m, {})
            details.append(f"`{m}` (Backtest: net {_pct(bm.get('net'))}, gap {_pct(bm.get('gap'))}, n={bm.get('n')})")
        lines.append(
            "Backtest-Monate, die die Forward-Lane **gar nicht abdeckt**: "
            + ", ".join(details)
            + ". Fehlt der stärkste Backtest-Monat hier, hängt der +2,87 %-Befund an einem "
            "Regime, das die Lane nie gesehen hat."
        )
    else:
        lines.append("Forward-Lane deckt alle Backtest-Monate ab — kein reiner Regime-Blindspot.")

    lines += [
        "",
        "## Forward nach Monat",
        "",
        "| Monat | n | Win-Rate | Netto modelliert | Netto real |",
        "|---|---:|---:|---:|---:|",
    ]
    for m in sorted(s["by_month"].keys()):
        g = s["by_month"][m]
        lines.append(
            f"| {m} | {g['n']} | {_pct(g['win_rate'])} | {_pct(g['net_modeled'])} | {_pct(g['net_real'])} |"
        )

    lines += [
        "",
        "## Forward nach Markttyp",
        "",
        "| Typ | n | Win-Rate | Netto modelliert |",
        "|---|---:|---:|---:|",
    ]
    for t in sorted(s["by_type"].keys()):
        g = s["by_type"][t]
        lines.append(f"| {t} | {g['n']} | {_pct(g['win_rate'])} | {_pct(g['net_modeled'])} |")

    lines += [
        "",
        "---",
        "*READ-ONLY. PAPER ONLY. Kein Live-Trade-Signal — nur Diagnose der Forward-vs-Backtest-Lücke.*",
        "",
    ]
    return "\n".join(lines)


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)


def run() -> Dict[str, Any]:
    """One cycle: recompute reconciliation, refresh md + json. Fail-open."""
    s = reconcile()
    try:
        _atomic_write(OUT_MD, _render_md(s))
        _atomic_write(OUT_JSON, json.dumps(s, indent=2, ensure_ascii=False))
    except Exception as e:
        logger.debug("forward_reconciliation write failed: %s", e)
    return s


def main() -> None:
    print(json.dumps(run(), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
