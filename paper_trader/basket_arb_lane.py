# =============================================================================
# POLYMARKET BEOBACHTER - BASKET ARBITRAGE PAPER EXECUTION LANE
# =============================================================================
#
# WHY:
#   analytics/basket_arbitrage.py detects fill-aware, risk-free dutch books:
#   a city/date family of mutually exclusive exact temperature buckets whose
#   YES prices sum to > 1 AND whose whole NO basket is actually fillable on the
#   live CLOB at a net-positive worst case. That is the ONE edge the bot may
#   act on without a forecast and without violating the forward-validation gate
#   (it is model-free and risk-free).
#
#   This lane turns an ACTIONABLE opportunity into a real multi-leg PAPER
#   position and holds it to resolution:
#     entry:  buy NO on every bucket at its real ask (cost = sum(no_ask+fee))
#     payoff: exactly one bucket resolves YES -> its NO leg pays 0, the other
#             (n-1) NO legs pay 1 each; if the temperature lands OUTSIDE every
#             listed bucket, all n NO legs pay (that only helps). Worst case n-1.
#     pnl:    realized_payoff - cost
#
#   Fully SELF-CONTAINED: own ledger (data/basket_arb_ledger.jsonl), own
#   resolution close-out against official resolutions. It NEVER touches the
#   production simulator, guardrails, or capital. PAPER ONLY. No real money.
# =============================================================================

from __future__ import annotations

import json
import logging
import os
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LEDGER_PATH = PROJECT_ROOT / "data" / "basket_arb_ledger.jsonl"
RESOLUTIONS_PATH = PROJECT_ROOT / "data" / "outcomes" / "resolutions.jsonl"
OUT_MD = PROJECT_ROOT / "analytics" / "basket_arb_ledger.md"


# --------------------------------------------------------------------------- #
# Ledger IO
# --------------------------------------------------------------------------- #
def _load_ledger(path: Optional[Path] = None) -> List[Dict[str, Any]]:
    path = path or LEDGER_PATH
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


def _append_ledger(record: Dict[str, Any], path: Optional[Path] = None) -> None:
    path = path or LEDGER_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _rewrite_ledger(records: List[Dict[str, Any]], path: Optional[Path] = None) -> None:
    path = path or LEDGER_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            for rec in records:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        os.replace(tmp, str(path))
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _load_resolutions(path: Optional[Path] = None) -> Dict[str, str]:
    path = path or RESOLUTIONS_PATH
    out: Dict[str, str] = {}
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
            out[str(r.get("market_id"))] = r["resolution"]
    return out


# --------------------------------------------------------------------------- #
# Pure entry/close logic (unit-testable)
# --------------------------------------------------------------------------- #
def build_entry_record(opp: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Turn an ACTIONABLE basket opportunity dict into a paper position record.

    Returns None if the opportunity is not actionable or has no legs.
    """
    if not opp.get("actionable"):
        return None
    legs = opp.get("legs") or []
    if len(legs) < 3:
        return None
    cost = 0.0
    norm_legs = []
    for l in legs:
        ask = l.get("no_ask")
        if ask is None:
            return None  # cannot execute an unfillable leg
        fee = l.get("fee") or 0.0
        cost += float(ask) + float(fee)
        norm_legs.append({
            "market_id": str(l.get("market_id")),
            "no_ask": float(ask),
            "fee": float(fee),
            "resolution": None,
        })
    n = len(norm_legs)
    return {
        "basket_id": f"BARB-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}",
        "entry_time": datetime.now(timezone.utc).isoformat(),
        "family_key": opp.get("family_key"),
        "city": opp.get("city"),
        "metric": opp.get("metric"),
        "date": opp.get("date"),
        "n_buckets": n,
        "side": "NO_BASKET",
        "legs": norm_legs,
        "total_cost": round(cost, 4),
        "worst_case_payoff": n - 1,
        "expected_net": round((n - 1) - cost, 4),
        "status": "OPEN",
        "realized_payoff": None,
        "realized_pnl": None,
        "resolved_at": None,
    }


def compute_basket_pnl(legs: List[Dict[str, Any]], resolutions: Dict[str, str],
                       total_cost: float) -> Optional[Dict[str, Any]]:
    """If every leg is resolved, compute realized NO-basket payoff and pnl.

    Payoff = number of legs that resolved NO (each NO leg pays 1). Returns None
    while any leg is still unresolved.
    """
    resolved = []
    for l in legs:
        res = resolutions.get(str(l.get("market_id")))
        if res not in ("YES", "NO"):
            return None  # not all legs resolved yet
        resolved.append(res)
    no_count = sum(1 for r in resolved if r == "NO")
    payoff = float(no_count)  # each NO leg pays 1
    return {
        "realized_payoff": payoff,
        "realized_pnl": round(payoff - total_cost, 4),
        "yes_legs": sum(1 for r in resolved if r == "YES"),
    }


# --------------------------------------------------------------------------- #
# Entry / close
# --------------------------------------------------------------------------- #
def record_entries(opportunities: List[Dict[str, Any]]) -> int:
    """Record actionable baskets as paper positions (dedup by family_key)."""
    existing = {str(r.get("family_key")) for r in _load_ledger()}
    entered = 0
    for opp in opportunities or []:
        if not opp.get("actionable"):
            continue
        fkey = str(opp.get("family_key"))
        if fkey in existing:
            continue
        record = build_entry_record(opp)
        if record is None:
            continue
        _append_ledger(record)
        existing.add(fkey)
        entered += 1
        logger.info(
            "BASKET-ARB ENTER: %s | %s | n=%d cost=%.3f expected_net=%+.3f",
            record["basket_id"], fkey, record["n_buckets"],
            record["total_cost"], record["expected_net"],
        )
    return entered


def close_resolved() -> int:
    records = _load_ledger()
    if not records:
        return 0
    resolutions = _load_resolutions()
    now_iso = datetime.now(timezone.utc).isoformat()
    closed = 0
    changed = False
    for r in records:
        if r.get("status") != "OPEN":
            continue
        pnl = compute_basket_pnl(r.get("legs", []), resolutions, float(r.get("total_cost") or 0.0))
        if pnl is None:
            continue
        r["status"] = "RESOLVED"
        r["realized_payoff"] = pnl["realized_payoff"]
        r["realized_pnl"] = pnl["realized_pnl"]
        r["resolved_at"] = now_iso
        closed += 1
        changed = True
        logger.info(
            "BASKET-ARB CLOSE: %s | %s | realized_pnl=%+.3f (yes_legs=%d)",
            r.get("basket_id"), r.get("family_key"), pnl["realized_pnl"], pnl["yes_legs"],
        )
    if changed:
        _rewrite_ledger(records)
    return closed


# --------------------------------------------------------------------------- #
# Summary + report
# --------------------------------------------------------------------------- #
def summary() -> Dict[str, Any]:
    records = _load_ledger()
    open_recs = [r for r in records if r.get("status") == "OPEN"]
    resolved = [r for r in records if r.get("status") == "RESOLVED"]
    realized = [float(r["realized_pnl"]) for r in resolved if r.get("realized_pnl") is not None]
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total": len(records),
        "open": len(open_recs),
        "resolved": len(resolved),
        "total_realized_pnl": round(sum(realized), 4) if realized else 0.0,
        "wins": sum(1 for p in realized if p > 0),
        "losses": sum(1 for p in realized if p < 0),
    }


def _render_md(s: Dict[str, Any]) -> str:
    return "\n".join([
        "# Basket-Arbitrage Paper-Ledger (risk-free NO-baskets)",
        "",
        f"**Generiert:** {s['generated_at']}  ",
        f"- Körbe gesamt: **{s['total']}** (offen {s['open']}, aufgelöst {s['resolved']})",
        f"- Realisierter PnL: **{s['total_realized_pnl']:+.3f}** (Gewinne {s['wins']}, Verluste {s['losses']})",
        "",
        "> PAPER ONLY. Nur ausführbare, risikofreie Dutch-Books werden aufgenommen "
        "(gesamte Familie füllbar, Netto>0 nach echten Asks+Fees), bis Resolution gehalten.",
        "",
    ])


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)


def run(opportunities: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """One cycle: enter new actionable baskets, close resolved ones, report."""
    entered = closed = 0
    try:
        if opportunities:
            entered = record_entries(opportunities)
    except Exception as e:  # fail-open
        logger.debug("basket_arb_lane.record_entries failed: %s", e)
    try:
        closed = close_resolved()
    except Exception as e:
        logger.debug("basket_arb_lane.close_resolved failed: %s", e)
    s = summary()
    s["entered_this_cycle"] = entered
    s["closed_this_cycle"] = closed
    try:
        _atomic_write(OUT_MD, _render_md(s))
    except Exception as e:
        logger.debug("basket_arb_lane report write failed: %s", e)
    return s
