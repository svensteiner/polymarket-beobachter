# =============================================================================
# POLYMARKET BEOBACHTER - FILL-AWARE BASKET (DUTCH-BOOK) ARBITRAGE DETECTOR
# =============================================================================
#
# WHY:
#   Polymarket lists each city's daily temperature as a FAMILY of mutually
#   exclusive, collectively (near-)exhaustive "exact bucket" markets, e.g.
#   "lowest temperature in Ankara be 10°C / 11°C / ... / 18°C on August 29".
#   Exactly one bucket resolves YES. Therefore the YES prices of one family
#   MUST sum to ~1.0. When they sum to >1 the family is collectively
#   OVERPRICED — buying NO on every bucket is a risk-free dutch book:
#
#       cost      = sum(NO_ask_i)
#       payoff    = n-1   (exactly one bucket resolves YES -> its NO pays 0,
#                          the other n-1 NO legs pay 1 each; if the temperature
#                          lands OUTSIDE every listed bucket, all n NO legs pay,
#                          which only helps — so n-1 is the worst case)
#       net       = (n-1) - sum(NO_ask_i) - fees
#
#   This edge is MODEL-FREE (no forecast needed) and RISK-FREE when fully
#   fillable, so — unlike a forecast bet — it does NOT conflict with the
#   forward-validation live-gate. The catch is EXECUTION: most illiquid buckets
#   have empty NO books or huge spreads, which turns the mid-price edge into a
#   mirage. This module therefore probes the REAL CLOB book for every leg
#   (via paper_trader.clob_book) and only reports an opportunity as ACTIONABLE
#   when the whole basket is fillable AND net-positive after real asks + fees.
#
#   READ-ONLY / OBSERVE. Writes analytics/basket_arbitrage.json + .md.
# =============================================================================

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUT_JSON = PROJECT_ROOT / "analytics" / "basket_arbitrage.json"
OUT_MD = PROJECT_ROOT / "analytics" / "basket_arbitrage.md"

# Minimum mid-price deviation from 1.0 to bother probing the live book.
MIN_DEVIATION = 0.04
# Dead-market guard: families where every bucket is <= this are unpriced stubs.
DEAD_PRICE = 0.005
# Minimum real risk-free net (after asks+fees) to call a basket ACTIONABLE.
MIN_NET_PROFIT = 0.01

_FAMILY_RE = re.compile(
    r"(?:the\s+)?(lowest|highest)\s+temperature\s+in\s+(.+?)\s+be\s+"
    r"(\d+(?:\.\d+)?)\s*°?\s*([cf])\b",
    re.I,
)
# "be 24°C or below/above/higher/lower" is a boundary bucket, not a single point,
# so it does not belong to the exclusive point-partition.
_BOUNDARY_RE = re.compile(r"be\s+\d+(?:\.\d+)?\s*°?\s*[cf]\s*or\s+(?:below|above|higher|lower)", re.I)
_DATE_RE = re.compile(r"on\s+([A-Za-z]+\s+\d{1,2})", re.I)


@dataclass
class BasketLeg:
    market_id: str
    question: str
    yes_price: float
    real_no_ask: Optional[float] = None
    real_depth: Optional[float] = None
    fee: Optional[float] = None


@dataclass
class BasketArbOpportunity:
    family_key: str
    city: str
    metric: str
    date: str
    n_buckets: int
    yes_sum: float
    deviation: float                 # yes_sum - 1
    legs_fillable: int
    fully_fillable: bool
    real_basket_cost: Optional[float]        # sum(real NO ask) when fully fillable
    worst_case_payoff: Optional[int]         # n-1
    real_net_profit: Optional[float]         # payoff - cost - fees
    actionable: bool
    reason: str
    legs: List[Dict[str, Any]] = field(default_factory=list)
    detected_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": "BASKET_ARBITRAGE",
            "family_key": self.family_key,
            "city": self.city,
            "metric": self.metric,
            "date": self.date,
            "n_buckets": self.n_buckets,
            "yes_sum": round(self.yes_sum, 4),
            "deviation": round(self.deviation, 4),
            "legs_fillable": self.legs_fillable,
            "fully_fillable": self.fully_fillable,
            "real_basket_cost": round(self.real_basket_cost, 4) if self.real_basket_cost is not None else None,
            "worst_case_payoff": self.worst_case_payoff,
            "real_net_profit": round(self.real_net_profit, 4) if self.real_net_profit is not None else None,
            "actionable": self.actionable,
            "reason": self.reason,
            # Per-leg execution detail is only needed for actionable baskets (the
            # ones the paper lane will actually enter); keep the report lean otherwise.
            "legs": self.legs if self.actionable else [],
            "detected_at": self.detected_at,
        }


# --------------------------------------------------------------------------- #
# Pure parsing / grouping (unit-testable, no network)
# --------------------------------------------------------------------------- #
def parse_family_key(question: str) -> Optional[Tuple[str, str, str]]:
    """Return (city, metric, date) for an exact point-bucket question, else None.

    Boundary buckets ("... or below/above") are excluded because they are not a
    single point in the exclusive partition.
    """
    if not question or _BOUNDARY_RE.search(question):
        return None
    m = _FAMILY_RE.search(question)
    if not m:
        return None
    metric = m.group(1).lower()
    city = m.group(2).strip().lower()
    dm = _DATE_RE.search(question)
    date = dm.group(1).lower() if dm else "?"
    return city, metric, date


def group_families(
    markets: List[Dict[str, Any]],
    price_fn: Callable[[Dict[str, Any]], Optional[float]],
) -> Dict[Tuple[str, str, str], List[BasketLeg]]:
    """Group candidate markets into exclusive bucket families with YES prices."""
    families: Dict[Tuple[str, str, str], List[BasketLeg]] = {}
    for c in markets:
        q = c.get("title") or c.get("question") or ""
        key = parse_family_key(q)
        if key is None:
            continue
        yp = price_fn(c)
        if yp is None:
            continue
        mid = str(c.get("market_id") or c.get("id") or "")
        if not mid:
            continue
        families.setdefault(key, []).append(BasketLeg(market_id=mid, question=q, yes_price=float(yp)))
    return families


def evaluate_fill_aware(
    legs: List[BasketLeg],
    fee_fn: Optional[Callable[[float], float]] = None,
) -> Tuple[Optional[float], Optional[int], Optional[float], bool, str]:
    """
    Compute the real, fill-aware risk-free net for a NO-basket (sum(YES)>1).

    Returns (real_basket_cost, worst_case_payoff, real_net, fully_fillable, reason).
    Pure: expects legs already annotated with real_no_ask (+ optional fee).
    """
    n = len(legs)
    priced = [l for l in legs if l.real_no_ask is not None]
    if len(priced) < n:
        return None, None, None, False, f"not_fully_fillable ({len(priced)}/{n} legs have a live NO ask)"
    cost = 0.0
    for l in legs:
        ask = float(l.real_no_ask)  # type: ignore[arg-type]
        fee = l.fee if l.fee is not None else (fee_fn(ask) if fee_fn else 0.0)
        cost += ask + fee
    worst_payoff = n - 1
    net = worst_payoff - cost
    return cost, worst_payoff, net, True, "fully_fillable"


# --------------------------------------------------------------------------- #
# Scan (network via injected book_fn / price_fn)
# --------------------------------------------------------------------------- #
def scan(
    markets: List[Dict[str, Any]],
    price_fn: Callable[[Dict[str, Any]], Optional[float]],
    book_fn: Optional[Callable[[str], Any]] = None,
    fee_fn: Optional[Callable[[float], float]] = None,
    min_deviation: float = MIN_DEVIATION,
) -> List[BasketArbOpportunity]:
    """
    Detect overpriced bucket families (sum(YES) > 1 + min_deviation) and, when a
    live book probe is provided, measure real fill-aware risk-free net.
    """
    if fee_fn is None:
        try:
            from core.fee_model import polymarket_taker_fee
            fee_fn = polymarket_taker_fee
        except Exception:
            fee_fn = lambda _p: 0.0

    families = group_families(markets, price_fn)
    opps: List[BasketArbOpportunity] = []

    for key, legs in sorted(families.items()):
        n = len(legs)
        if n < 3:
            continue
        yes_sum = sum(l.yes_price for l in legs)
        # Dead/unpriced family (all near-zero placeholders): skip.
        if all(l.yes_price <= DEAD_PRICE for l in legs):
            continue
        deviation = yes_sum - 1.0
        # Only the overpriced (sum>1) case is a *risk-free* NO-basket dutch book.
        if deviation <= min_deviation:
            continue

        city, metric, date = key
        fkey = f"{city}|{metric}|{date}"

        real_cost = payoff = real_net = None
        fully = False
        reason = "detected_mid_only (no live book probe)"
        fillable = 0

        if book_fn is not None:
            for l in legs:
                try:
                    r = book_fn(l.market_id)
                    ask = getattr(r, "no_best_ask", None)
                    if ask is not None:
                        l.real_no_ask = float(ask)
                        l.real_depth = getattr(r, "ask_depth_shares", None)
                        l.fee = fee_fn(float(ask))
                        fillable += 1
                except Exception as e:  # fail-open per leg
                    logger.debug("basket_arb book probe failed %s: %s", l.market_id, e)
            real_cost, payoff, real_net, fully, reason = evaluate_fill_aware(legs, fee_fn)
        else:
            fillable = 0

        actionable = bool(fully and real_net is not None and real_net >= MIN_NET_PROFIT)
        leg_details = [
            {
                "market_id": l.market_id,
                "question": l.question[:120],
                "yes_price": round(l.yes_price, 4),
                "no_ask": round(l.real_no_ask, 4) if l.real_no_ask is not None else None,
                "fee": round(l.fee, 4) if l.fee is not None else None,
                "depth": l.real_depth,
            }
            for l in legs
        ] if actionable else []
        opps.append(BasketArbOpportunity(
            family_key=fkey, city=city, metric=metric, date=date,
            n_buckets=n, yes_sum=yes_sum, deviation=deviation,
            legs_fillable=fillable, fully_fillable=fully,
            real_basket_cost=real_cost, worst_case_payoff=payoff,
            real_net_profit=real_net, actionable=actionable, reason=reason,
            legs=leg_details,
        ))
        logger.info(
            "BASKET-ARB %s | n=%d sum(YES)=%.3f dev=%+.3f | fillable=%d/%d net=%s actionable=%s",
            fkey, n, yes_sum, deviation, fillable, n,
            f"{real_net:+.3f}" if real_net is not None else "n/a", actionable,
        )
    return opps


# --------------------------------------------------------------------------- #
# Report + pipeline entry
# --------------------------------------------------------------------------- #
def _render_md(opps: List[BasketArbOpportunity], scanned: int) -> str:
    actionable = [o for o in opps if o.actionable]
    lines = [
        "# Basket-Arbitrage (Dutch-Book) — modell-frei, fill-aware",
        "",
        f"**Generiert:** {datetime.now(timezone.utc).isoformat()}  ",
        f"**Familien geprüft:** {scanned} · **überpreist (sum>1):** {len(opps)} · "
        f"**real ausführbar (risk-free net>0):** {len(actionable)}",
        "",
        "> Exklusive Tages-Buckets einer Stadt müssen zu ~1.0 summieren. sum(YES)>1 ⇒ "
        "NO auf alle Buckets kaufen ist ein risikofreier Dutch-Book — WENN jede Leg "
        "real füllbar ist. Kosten/Netto aus echtem CLOB-Orderbuch (paper_trader.clob_book).",
        "",
        "| Familie | n | sum(YES) | dev | fillable | real_net | actionable |",
        "|---|---:|---:|---:|---:|---:|:--:|",
    ]
    for o in sorted(opps, key=lambda x: (x.real_net_profit if x.real_net_profit is not None else -9)):
        net = f"{o.real_net_profit:+.3f}" if o.real_net_profit is not None else "—"
        lines.append(
            f"| {o.family_key} | {o.n_buckets} | {o.yes_sum:.3f} | {o.deviation:+.3f} | "
            f"{o.legs_fillable}/{o.n_buckets} | {net} | {'✅' if o.actionable else '·'} |"
        )
    if not opps:
        lines.append("| _keine überpreiste Familie_ | | | | | | |")
    lines += [
        "",
        "**Lesart:** `actionable=✅` heißt: gesamte Familie füllbar UND risikofreier Netto-"
        "Profit > 0 nach echten Asks+Fees → der Paper-Trader darf diesen Korb ohne Forecast-"
        "Risiko und ohne Verletzung des Forward-Gates handeln. Sonst ist der Mid-Preis-Edge ein "
        "Illiquiditäts-Mirage.",
        "",
    ]
    return "\n".join(lines)


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)


def _default_price_fn(c: Dict[str, Any]) -> Optional[float]:
    op = c.get("outcomePrices")
    if op:
        try:
            pl = json.loads(op) if isinstance(op, str) else op
            if pl:
                return float(pl[0])
        except Exception:
            return None
    return None


def run(
    candidates: List[Dict[str, Any]],
    probe_books: bool = True,
    price_fn: Optional[Callable[[Dict[str, Any]], Optional[float]]] = None,
) -> Dict[str, Any]:
    """Pipeline entry: scan candidates, probe live books, write report."""
    price_fn = price_fn or _default_price_fn
    book_fn = None
    if probe_books:
        try:
            from paper_trader.clob_book import fetch_no_book_cost
            book_fn = fetch_no_book_cost
        except Exception as e:
            logger.debug("basket_arb: clob_book unavailable: %s", e)

    families = group_families(candidates, price_fn)
    opps = scan(candidates, price_fn, book_fn=book_fn)
    actionable = [o for o in opps if o.actionable]

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "families_scanned": len(families),
        "overpriced_families": len(opps),
        "actionable_families": len(actionable),
        "opportunities": [o.to_dict() for o in opps],
    }
    try:
        _atomic_write(OUT_JSON, json.dumps(summary, indent=2, ensure_ascii=False))
        _atomic_write(OUT_MD, _render_md(opps, len(families)))
    except Exception as e:
        logger.debug("basket_arb report write failed: %s", e)

    if actionable:
        logger.info("BASKET-ARB: %d ACTIONABLE risk-free basket(s) found!", len(actionable))
    return summary


def main() -> None:
    import sys
    # Load today's candidates for a manual run.
    from datetime import date
    root = PROJECT_ROOT / "data" / "collector"
    cands: List[Dict[str, Any]] = []
    for sub in ("candidates", "gamma"):
        base = root / sub
        if not base.exists():
            continue
        for day in sorted(base.iterdir(), reverse=True):
            f = day / ("candidates.jsonl" if sub == "candidates" else "gamma_candidates.jsonl")
            if f.exists():
                for line in f.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if line:
                        try:
                            cands.append(json.loads(line))
                        except json.JSONDecodeError:
                            pass
                break
    probe = "--no-probe" not in sys.argv
    # Use LIVE prices for a faithful manual demonstration (stored outcomePrices
    # are often absent/stale). The pipeline passes gamma candidates that already
    # carry outcomePrices, so run() keeps working without this in production.
    price_fn = None
    if "--stored" not in sys.argv:
        try:
            from collector.client import PolymarketClient
            ids = [str(c.get("market_id") or c.get("id") or "") for c in cands]
            ids = [i for i in ids if i]
            live = PolymarketClient(timeout=20).fetch_market_prices(ids)

            def _live_price(c, _live=live):
                mid = str(c.get("market_id") or c.get("id") or "")
                op = (_live.get(mid) or {}).get("outcomePrices")
                if op:
                    try:
                        pl = json.loads(op) if isinstance(op, str) else op
                        if pl:
                            return float(pl[0])
                    except Exception:
                        return None
                return _default_price_fn(c)

            price_fn = _live_price
        except Exception:
            price_fn = None
    print(json.dumps(run(cands, probe_books=probe, price_fn=price_fn), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
