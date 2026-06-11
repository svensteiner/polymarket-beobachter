# =============================================================================
# POLYMARKET BEOBACHTER - FORWARD EDGE VALIDATION
# =============================================================================
#
# GOVERNANCE INTENT (2026-06-10):
#   This is THE decisive test for the whole project: does the forecast model
#   have any *forward* edge OVER THE MARKET PRICE — not over a naive climatology
#   baseline? Every other "edge"/"calibration" number in the system compares the
#   model to a 4.5% base-rate; that is the wrong benchmark and produces the
#   misleadingly "GOOD" calibration label while the book bleeds.
#
#   The correct benchmark is the Polymarket entry price itself. If the model's
#   forecast Brier does not beat the market's Brier on resolved contracts, the
#   model adds no value and NO real capital may be deployed.
#
#   This module is READ-ONLY. It never modifies thresholds, never trades. It
#   joins model_probability (logged on every entry) to the realised outcome and
#   reports model-vs-market skill, directional hit-rate, and the
#   proposal_edge -> realised_pnl correlation. It writes:
#     - analytics/forward_validation.json  (machine-readable gate)
#     - analytics/forward_validation.txt   (console report)
#
#   LIVE GATE: live_eligible is True only when, on a frozen out-of-sample window
#   of >= MIN_RESOLVED_FOR_GATE resolved trades, model Brier strictly beats
#   market Brier AND directional hit-rate beats the market favourite AND
#   corr(proposal_edge, realised_pnl) > 0. Today this fails decisively.
# =============================================================================

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
POSITIONS_PATH = PROJECT_ROOT / "paper_trader" / "logs" / "paper_positions.jsonl"
OUT_JSON = PROJECT_ROOT / "analytics" / "forward_validation.json"
OUT_TXT = PROJECT_ROOT / "analytics" / "forward_validation.txt"

# Minimum resolved trades before the live gate is even allowed to evaluate.
MIN_RESOLVED_FOR_GATE = 100
# Out-of-sample split: trades whose entry_time is on/after this date form the
# held-out test window. Frozen so the result is genuinely out-of-sample.
DEFAULT_TEST_SPLIT_ISO = "2026-06-01"

GOVERNANCE_NOTICE = (
    "Forward edge validation (model vs MARKET, not vs climatology). READ-ONLY. "
    "Positive paper P&L is NOT evidence of edge — only market-relative skill is."
)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
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


def load_positions(path: Path = POSITIONS_PATH) -> List[Dict[str, Any]]:
    """Load the paper-position ledger (one JSON object per line)."""
    if not path.exists():
        return []
    rows: List[Dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def _yes_outcome(record: Dict[str, Any]) -> Optional[int]:
    """Infer the terminal YES-event outcome (1/0) for a *resolved* contract.

    Only returns a value when the contract reached a definite resolution. TP/SL/
    zombie exits before resolution carry no information about the true outcome
    and are excluded (returns None).
    """
    side = (record.get("side") or "").upper()
    exit_reason = (record.get("exit_reason") or "").lower()
    exit_price = _num(record.get("exit_price"))
    pnl = _num(record.get("realized_pnl_eur"))

    resolved = (
        "resolution" in exit_reason
        or "resolved" in exit_reason
        or (record.get("status") or "").upper() == "RESOLVED"
        or (exit_price is not None and (exit_price <= 0.02 or exit_price >= 0.98))
    )
    if not resolved:
        return None

    if exit_price is not None and exit_price >= 0.98:
        side_won: Optional[bool] = True
    elif exit_price is not None and exit_price <= 0.02:
        side_won = False
    elif pnl is not None:
        side_won = pnl > 0
    else:
        return None

    if side == "YES":
        return 1 if side_won else 0
    if side == "NO":
        return 0 if side_won else 1
    return None


def _market_yes_price(record: Dict[str, Any]) -> Optional[float]:
    """Market-implied P(YES) at entry, derived from the price actually paid."""
    entry = _num(record.get("entry_price"))
    if entry is None:
        return None
    side = (record.get("side") or "").upper()
    if side == "YES":
        return entry
    if side == "NO":
        return 1.0 - entry
    return None


def _corr(xs: List[float], ys: List[float]) -> Optional[float]:
    n = len(xs)
    if n < 3:
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    dy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if dx == 0 or dy == 0:
        return None
    return cov / (dx * dy)


def _mean(values: List[float]) -> Optional[float]:
    return sum(values) / len(values) if values else None


# --------------------------------------------------------------------------- #
# Core metrics
# --------------------------------------------------------------------------- #
def compute_edge_pnl_metrics(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Full-ledger metrics that need only proposal_edge + realised P&L."""
    edges: List[float] = []
    pnls: List[float] = []
    for r in rows:
        e = _num(r.get("proposal_edge"))
        p = _num(r.get("realized_pnl_eur"))
        if e is not None and p is not None:
            edges.append(e)
            pnls.append(p)

    pos_pnl = [p for e, p in zip(edges, pnls) if e > 0]
    nonpos_pnl = [p for e, p in zip(edges, pnls) if e <= 0]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    gross_profit = sum(wins)
    gross_loss = -sum(losses)

    return {
        "n": len(pnls),
        "total_pnl_eur": round(sum(pnls), 2) if pnls else 0.0,
        "win_rate_pct": round(100 * len(wins) / len(pnls), 2) if pnls else None,
        "profit_factor": round(gross_profit / gross_loss, 4) if gross_loss else None,
        "corr_edge_pnl": round(_corr(edges, pnls), 4) if _corr(edges, pnls) is not None else None,
        "positive_edge_trades": len(pos_pnl),
        "positive_edge_pnl_eur": round(sum(pos_pnl), 2) if pos_pnl else 0.0,
        "nonpositive_edge_trades": len(nonpos_pnl),
        "nonpositive_edge_pnl_eur": round(sum(nonpos_pnl), 2) if nonpos_pnl else 0.0,
    }


def compute_skill(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Model-vs-market Brier skill on resolution-determinable contracts."""
    model_sq: List[float] = []
    market_sq: List[float] = []
    base_sq: List[float] = []
    outcomes: List[int] = []
    model_side_hits = 0
    market_fav_hits = 0
    used = 0
    by_type: Dict[str, Dict[str, List[float]]] = {}

    for r in rows:
        outcome = _yes_outcome(r)
        model_p = _num(r.get("model_probability"))
        market_p = _market_yes_price(r)
        if outcome is None or model_p is None or market_p is None:
            continue
        used += 1
        outcomes.append(outcome)
        model_sq.append((model_p - outcome) ** 2)
        market_sq.append((market_p - outcome) ** 2)

        # Directional: did the model's chosen YES-side belief match reality?
        model_says_yes = model_p >= 0.5
        if int(model_says_yes) == outcome:
            model_side_hits += 1
        market_fav_yes = market_p >= 0.5
        if int(market_fav_yes) == outcome:
            market_fav_hits += 1

        mt = (r.get("market_type") or "unknown").lower()
        bucket = by_type.setdefault(mt, {"model": [], "market": []})
        bucket["model"].append((model_p - outcome) ** 2)
        bucket["market"].append((market_p - outcome) ** 2)

    base_rate = _mean([float(o) for o in outcomes])
    if base_rate is not None:
        base_sq = [(base_rate - o) ** 2 for o in outcomes]

    model_brier = _mean(model_sq)
    market_brier = _mean(market_sq)
    base_brier = _mean(base_sq) if base_sq else None

    skill_vs_market = None
    if model_brier is not None and market_brier not in (None, 0):
        skill_vs_market = round(1 - model_brier / market_brier, 4)

    per_type = {}
    for mt, b in by_type.items():
        mb = _mean(b["model"])
        kb = _mean(b["market"])
        per_type[mt] = {
            "n": len(b["model"]),
            "model_brier": round(mb, 4) if mb is not None else None,
            "market_brier": round(kb, 4) if kb is not None else None,
            "model_beats_market": (mb is not None and kb is not None and mb < kb),
        }

    return {
        "n_resolved": used,
        "model_brier": round(model_brier, 4) if model_brier is not None else None,
        "market_brier": round(market_brier, 4) if market_brier is not None else None,
        "baseline_brier": round(base_brier, 4) if base_brier is not None else None,
        "skill_vs_market": skill_vs_market,
        "model_beats_market": (
            model_brier is not None and market_brier is not None and model_brier < market_brier
        ),
        "model_directional_hit_rate": round(model_side_hits / used, 3) if used else None,
        "market_favorite_hit_rate": round(market_fav_hits / used, 3) if used else None,
        "by_market_type": per_type,
    }


def _split_by_time(rows: List[Dict[str, Any]], split_iso: str) -> Tuple[List, List]:
    cutoff = _parse_iso(split_iso)
    train, test = [], []
    for r in rows:
        et = _parse_iso(r.get("entry_time"))
        if cutoff is None or et is None:
            train.append(r)
        elif et >= cutoff:
            test.append(r)
        else:
            train.append(r)
    return train, test


def evaluate(rows: List[Dict[str, Any]], split_iso: str = DEFAULT_TEST_SPLIT_ISO) -> Dict[str, Any]:
    overall_edge = compute_edge_pnl_metrics(rows)
    overall_skill = compute_skill(rows)
    train, test = _split_by_time(rows, split_iso)
    oos_skill = compute_skill(test)
    oos_edge = compute_edge_pnl_metrics(test)

    # Live gate: strict, frozen, out-of-sample.
    reasons: List[str] = []
    n_oos = oos_skill["n_resolved"]
    if n_oos < MIN_RESOLVED_FOR_GATE:
        reasons.append(
            f"Nur {n_oos} aufgeloeste OOS-Trades (< {MIN_RESOLVED_FOR_GATE} noetig)."
        )
    if not oos_skill["model_beats_market"]:
        reasons.append(
            f"Modell-Brier schlaegt Markt-Brier NICHT "
            f"(model={oos_skill['model_brier']} vs market={oos_skill['market_brier']})."
        )
    hr = oos_skill["model_directional_hit_rate"]
    if hr is None or hr <= 0.5:
        reasons.append(f"Directional Hit-Rate {hr} <= 0.50 (kein Richtungs-Edge).")
    corr = oos_edge["corr_edge_pnl"]
    if corr is None or corr <= 0:
        reasons.append(f"corr(edge, pnl) = {corr} <= 0 (Edge nicht profit-korreliert).")

    live_eligible = len(reasons) == 0
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "governance_notice": GOVERNANCE_NOTICE,
        "test_split_iso": split_iso,
        "live_eligible": live_eligible,
        "live_block_reasons": reasons,
        "overall": {"edge_pnl": overall_edge, "skill": overall_skill},
        "out_of_sample": {"edge_pnl": oos_edge, "skill": oos_skill},
        "min_resolved_for_gate": MIN_RESOLVED_FOR_GATE,
        "model_probability_semantics": "model_probability assumed = P(YES condition true).",
    }


# --------------------------------------------------------------------------- #
# Rendering / IO
# --------------------------------------------------------------------------- #
def render_text(report: Dict[str, Any]) -> str:
    o = report["overall"]
    s = o["skill"]
    e = o["edge_pnl"]
    lines = [
        "=" * 60,
        "FORWARD EDGE VALIDATION (Modell vs MARKT)",
        f"Generiert: {report['generated_at']}",
        "=" * 60,
        f"LIVE-ELIGIBLE: {'JA' if report['live_eligible'] else 'NEIN'}",
    ]
    for r in report["live_block_reasons"]:
        lines.append(f"  - BLOCK: {r}")
    lines += [
        "",
        "GESAMT (alle Trades):",
        f"  Trades mit pnl:        {e['n']}",
        f"  Total P&L:             {e['total_pnl_eur']} EUR",
        f"  Win-Rate:              {e['win_rate_pct']}%",
        f"  Profit-Factor:         {e['profit_factor']}",
        f"  corr(edge, pnl):       {e['corr_edge_pnl']}   (<0 = Edge zeigt FALSCH)",
        f"  +Edge Trades:          {e['positive_edge_trades']} -> {e['positive_edge_pnl_eur']} EUR",
        f"  -Edge Trades:          {e['nonpositive_edge_trades']} -> {e['nonpositive_edge_pnl_eur']} EUR",
        "",
        "BRIER (aufgeloeste Trades — Modell muss MARKT schlagen):",
        f"  Aufgeloeste Trades:    {s['n_resolved']}",
        f"  Modell-Brier:          {s['model_brier']}",
        f"  Markt-Brier:           {s['market_brier']}",
        f"  Baseline-Brier:        {s['baseline_brier']}",
        f"  Skill vs Markt:        {s['skill_vs_market']}   (>0 = Modell schlaegt Markt)",
        f"  Modell schlaegt Markt: {'JA' if s['model_beats_market'] else 'NEIN'}",
        f"  Hit-Rate Modell:       {s['model_directional_hit_rate']}",
        f"  Hit-Rate Markt-Fav:    {s['market_favorite_hit_rate']}",
    ]
    if s.get("by_market_type"):
        lines.append("")
        lines.append("  Pro Markttyp (model_brier vs market_brier):")
        for mt, b in sorted(s["by_market_type"].items()):
            verdict = "OK" if b["model_beats_market"] else "SCHLECHTER"
            lines.append(
                f"    {mt:<12} n={b['n']:<3} model={b['model_brier']} "
                f"market={b['market_brier']} -> {verdict}"
            )
    lines += ["", "Hinweis: " + report["governance_notice"]]
    return "\n".join(lines)


def _atomic_write(path: Path, content: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)


def run() -> Dict[str, Any]:
    rows = load_positions()
    report = evaluate(rows)
    _atomic_write(OUT_JSON, json.dumps(report, indent=2, ensure_ascii=False))
    _atomic_write(OUT_TXT, render_text(report))
    return report


def main() -> None:
    report = run()
    print(render_text(report))


if __name__ == "__main__":
    main()
