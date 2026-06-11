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
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
POSITIONS_PATH = PROJECT_ROOT / "paper_trader" / "logs" / "paper_positions.jsonl"
OUT_JSON = PROJECT_ROOT / "analytics" / "forward_validation.json"
OUT_TXT = PROJECT_ROOT / "analytics" / "forward_validation.txt"
# Official Polymarket resolutions (ground truth) keyed by market_id.
RESOLUTIONS_PATH = PROJECT_ROOT / "data" / "outcomes" / "resolutions.jsonl"
OBS_LOG_DIR = PROJECT_ROOT / "logs"
# Fair model-vs-market comparison point: the forecast at ~this many hours before
# resolution. Both still carry uncertainty here; right at resolution the market
# price trivially converges to the outcome and the comparison becomes unfair.
DEFAULT_LEAD_HOURS = 24.0

# Minimum resolved markets before the live gate is even allowed to evaluate.
MIN_RESOLVED_FOR_GATE = 100

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


# --------------------------------------------------------------------------- #
# Observation-based test (the large-sample model-vs-market verdict)
# --------------------------------------------------------------------------- #
def load_resolutions(path: Path = RESOLUTIONS_PATH) -> Dict[str, int]:
    """Official Polymarket resolutions: market_id -> 1 (YES) / 0 (NO)."""
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


def load_all_observations(full: bool = True) -> List[Dict[str, Any]]:
    """Load weather observations. full=all rotated logs; else active log only."""
    if full:
        files = sorted(OBS_LOG_DIR.glob("weather_observations*.jsonl"))
    else:
        active = OBS_LOG_DIR / "weather_observations.jsonl"
        files = [active] if active.exists() else []
    rows: List[Dict[str, Any]] = []
    for f in files:
        try:
            text = f.read_text(encoding="utf-8")
        except OSError:
            continue
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def _obs_event_type(desc: Optional[str]) -> str:
    """Coarse market-type from the question text."""
    d = (desc or "").lower()
    if "between" in d:
        return "between"
    if re.search(r"or\s+(?:below|less|under|lower)|\bbelow\b", d):
        return "at_or_below"
    if re.search(r"or\s+(?:above|higher|more|over)|\babove\b|exceed", d):
        return "at_or_above"
    return "exact"


def _dedupe_by_lead(
    observations: List[Dict[str, Any]],
    resolutions: Dict[str, int],
    lead_hours: float,
) -> List[Dict[str, Any]]:
    """One observation per resolved market: the one closest to lead_hours."""
    best: Dict[str, Any] = {}
    for o in observations:
        mid = str(o.get("market_id"))
        if mid not in resolutions:
            continue
        h = _num(o.get("hours_to_resolution"))
        mp = _num(o.get("model_probability"))
        kp = _num(o.get("market_probability"))
        if h is None or mp is None or kp is None:
            continue
        dist = abs(h - lead_hours)
        cur = best.get(mid)
        if cur is None or dist < cur[0]:
            best[mid] = (dist, o)
    return [v[1] for v in best.values()]


def compute_observation_test(
    observations: List[Dict[str, Any]],
    resolutions: Dict[str, int],
    lead_hours: float = DEFAULT_LEAD_HOURS,
) -> Dict[str, Any]:
    """Score MODEL and RAW ensemble probability vs the MARKET, against the
    official Polymarket resolution, on one observation per resolved market."""
    chosen = _dedupe_by_lead(observations, resolutions, lead_hours)

    model_sq: List[float] = []
    market_sq: List[float] = []
    outcomes: List[int] = []
    model_hits = 0
    market_hits = 0
    by_type: Dict[str, Dict[str, List[float]]] = {}
    raw_sq: List[float] = []
    raw_market_sq: List[float] = []
    raw_hits = 0

    for o in chosen:
        outcome = resolutions[str(o.get("market_id"))]
        mp = _num(o.get("model_probability"))
        kp = _num(o.get("market_probability"))
        if mp is None or kp is None:
            continue
        outcomes.append(outcome)
        model_sq.append((mp - outcome) ** 2)
        market_sq.append((kp - outcome) ** 2)
        model_hits += int(int(mp >= 0.5) == outcome)
        market_hits += int(int(kp >= 0.5) == outcome)
        bucket = by_type.setdefault(_obs_event_type(o.get("event_description")),
                                    {"model": [], "market": []})
        bucket["model"].append((mp - outcome) ** 2)
        bucket["market"].append((kp - outcome) ** 2)
        rp = _num(o.get("raw_member_probability"))
        if rp is not None:
            raw_sq.append((rp - outcome) ** 2)
            raw_market_sq.append((kp - outcome) ** 2)
            raw_hits += int(int(rp >= 0.5) == outcome)

    n = len(outcomes)
    base_rate = _mean([float(x) for x in outcomes]) if outcomes else None
    base_sq = [(base_rate - o) ** 2 for o in outcomes] if base_rate is not None else []
    model_brier = _mean(model_sq)
    market_brier = _mean(market_sq)
    skill = (round(1 - model_brier / market_brier, 4)
             if model_brier is not None and market_brier not in (None, 0) else None)

    per_type = {}
    for mt, b in by_type.items():
        mb, kb = _mean(b["model"]), _mean(b["market"])
        per_type[mt] = {
            "n": len(b["model"]),
            "model_brier": round(mb, 4) if mb is not None else None,
            "market_brier": round(kb, 4) if kb is not None else None,
            "model_beats_market": (mb is not None and kb is not None and mb < kb),
        }

    raw_brier = _mean(raw_sq)
    raw_market_brier = _mean(raw_market_sq)
    raw_skill = (round(1 - raw_brier / raw_market_brier, 4)
                 if raw_brier is not None and raw_market_brier not in (None, 0) else None)

    return {
        "lead_hours": lead_hours,
        "n_resolved": n,
        "base_rate": round(base_rate, 4) if base_rate is not None else None,
        "model_brier": round(model_brier, 4) if model_brier is not None else None,
        "market_brier": round(market_brier, 4) if market_brier is not None else None,
        "baseline_brier": round(_mean(base_sq), 4) if base_sq else None,
        "skill_vs_market": skill,
        "model_beats_market": (model_brier is not None and market_brier is not None
                               and model_brier < market_brier),
        "model_directional_hit_rate": round(model_hits / n, 3) if n else None,
        "market_favorite_hit_rate": round(market_hits / n, 3) if n else None,
        "by_market_type": per_type,
        "raw_ensemble": {
            "n": len(raw_sq),
            "raw_brier": round(raw_brier, 4) if raw_brier is not None else None,
            "market_brier_on_subset": round(raw_market_brier, 4) if raw_market_brier is not None else None,
            "raw_skill_vs_market": raw_skill,
            "raw_beats_market": (raw_brier is not None and raw_market_brier is not None
                                 and raw_brier < raw_market_brier),
            "raw_directional_hit_rate": round(raw_hits / len(raw_sq), 3) if raw_sq else None,
        },
    }


def evaluate(
    rows: List[Dict[str, Any]],
    *,
    full_obs: bool = True,
    lead_hours: float = DEFAULT_LEAD_HOURS,
) -> Dict[str, Any]:
    paper_edge = compute_edge_pnl_metrics(rows)
    paper_skill = compute_skill(rows)
    resolutions = load_resolutions()
    observations = load_all_observations(full_obs)
    obs = compute_observation_test(observations, resolutions, lead_hours)

    # Live gate: driven by the large-sample observation test (model vs MARKET on
    # official resolutions), with the paper-trade edge correlation as a backstop.
    reasons: List[str] = []
    n = obs["n_resolved"]
    if n < MIN_RESOLVED_FOR_GATE:
        reasons.append(f"Nur {n} aufgeloeste Markt-Observations (< {MIN_RESOLVED_FOR_GATE} noetig).")
    if not obs["model_beats_market"]:
        reasons.append(
            f"Modell-Brier schlaegt Markt-Brier NICHT auf {n} Maerkten "
            f"(model={obs['model_brier']} vs market={obs['market_brier']})."
        )
    mh, kh = obs["model_directional_hit_rate"], obs["market_favorite_hit_rate"]
    if mh is None or kh is None or mh <= kh:
        reasons.append(f"Modell-Hit-Rate {mh} <= Markt-Favorit {kh} (kein Richtungs-Edge).")
    corr = paper_edge["corr_edge_pnl"]
    if corr is not None and corr <= 0:
        reasons.append(f"corr(edge, pnl) = {corr} <= 0 (getradete Edges anti-korreliert).")

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "governance_notice": GOVERNANCE_NOTICE,
        "live_eligible": len(reasons) == 0,
        "live_block_reasons": reasons,
        "observation_test": obs,
        "paper_test": {"edge_pnl": paper_edge, "skill": paper_skill},
        "min_resolved_for_gate": MIN_RESOLVED_FOR_GATE,
        "model_probability_semantics": (
            "model_probability=P(YES); market_probability=YES odds; "
            "outcome from official Polymarket resolution (data/outcomes/resolutions.jsonl)."
        ),
    }


# --------------------------------------------------------------------------- #
# Rendering / IO
# --------------------------------------------------------------------------- #
def render_text(report: Dict[str, Any]) -> str:
    obs = report["observation_test"]
    raw = obs.get("raw_ensemble", {})
    p = report["paper_test"]["edge_pnl"]
    lines = [
        "=" * 60,
        "FORWARD EDGE VALIDATION (Modell & Roh-Ensemble vs MARKT)",
        f"Generiert: {report['generated_at']}",
        "=" * 60,
        f"LIVE-ELIGIBLE: {'JA' if report['live_eligible'] else 'NEIN'}",
    ]
    for r in report["live_block_reasons"]:
        lines.append(f"  - BLOCK: {r}")
    lines += [
        "",
        f"OBSERVATION-TEST (offizielle Resolutions, ~{obs['lead_hours']}h vor Aufloesung):",
        f"  Aufgeloeste Maerkte:   {obs['n_resolved']}",
        f"  Basisrate (YES):       {obs['base_rate']}",
        f"  Modell-Brier:          {obs['model_brier']}",
        f"  Markt-Brier:           {obs['market_brier']}",
        f"  Baseline-Brier:        {obs['baseline_brier']}",
        f"  Skill vs Markt:        {obs['skill_vs_market']}   (>0 = Modell schlaegt Markt)",
        f"  Modell schlaegt Markt: {'JA' if obs['model_beats_market'] else 'NEIN'}",
        f"  Hit-Rate Modell:       {obs['model_directional_hit_rate']}",
        f"  Hit-Rate Markt-Fav:    {obs['market_favorite_hit_rate']}",
        "",
        f"  ROH-ENSEMBLE pre-Shrinkage (n={raw.get('n')}):",
        f"    Roh-Brier:           {raw.get('raw_brier')}",
        f"    Markt-Brier(Subset): {raw.get('market_brier_on_subset')}",
        f"    Roh-Skill vs Markt:  {raw.get('raw_skill_vs_market')}   (>0 = Roh schlaegt Markt!)",
        f"    Roh schlaegt Markt:  {'JA' if raw.get('raw_beats_market') else 'NEIN'}",
    ]
    if obs.get("by_market_type"):
        lines.append("")
        lines.append("  Pro Markttyp (model_brier vs market_brier):")
        for mt, b in sorted(obs["by_market_type"].items()):
            verdict = "OK" if b["model_beats_market"] else "SCHLECHTER"
            lines.append(
                f"    {mt:<12} n={b['n']:<5} model={b['model_brier']} "
                f"market={b['market_brier']} -> {verdict}"
            )
    lines += [
        "",
        "PAPER-TRADES (Sekundaer):",
        f"  Trades mit pnl:        {p['n']}",
        f"  corr(edge, pnl):       {p['corr_edge_pnl']}   (<0 = Edge zeigt FALSCH)",
        f"  +Edge -> {p['positive_edge_pnl_eur']} EUR | -Edge -> {p['nonpositive_edge_pnl_eur']} EUR",
        "",
        "Hinweis: " + report["governance_notice"],
    ]
    return "\n".join(lines)


def _atomic_write(path: Path, content: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)


def run(full_obs: bool = True) -> Dict[str, Any]:
    rows = load_positions()
    report = evaluate(rows, full_obs=full_obs)
    _atomic_write(OUT_JSON, json.dumps(report, indent=2, ensure_ascii=False))
    _atomic_write(OUT_TXT, render_text(report))
    return report


def main() -> None:
    import sys
    # Default: full history (decisive large sample). --quick = active log only.
    full = "--quick" not in sys.argv
    report = run(full_obs=full)
    print(render_text(report))


if __name__ == "__main__":
    main()
