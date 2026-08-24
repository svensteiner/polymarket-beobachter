# =============================================================================
# POLYMARKET BEOBACHTER - STRUCTURAL ARBITRAGE MATH (pure, no I/O)
# =============================================================================
#
# Model-free complete-set / binary-lock edge after Polymarket taker fees.
# Trade only when net >= MIN_NET on REAL CLOB asks — never on Gamma mids alone.
# =============================================================================

from __future__ import annotations

import json
import re
from typing import Any, Mapping, Optional, Sequence

MIN_NET: float = 0.01
MIN_ASK_COVERAGE: float = 0.92
MIN_ASK_DEPTH: float = 5.0
MIN_LEGS: int = 2
MAX_LEGS: int = 12
GAMMA_PREFILTER_PER_LEG: float = 0.003


def taker_fee(price: float) -> float:
    """Polymarket non-linear taker fee: 0.02 * p * (1-p) / 0.25."""
    p = max(0.001, min(0.999, float(price)))
    return 0.02 * p * (1.0 - p) / 0.25


def completeset_yes_net(asks: Sequence[float]) -> float:
    """Buy every YES in a complete partition; payoff exactly 1."""
    if not asks:
        return 0.0
    cost = sum(float(a) + taker_fee(a) for a in asks)
    return 1.0 - cost


def completeset_no_net(no_asks: Sequence[float]) -> float:
    """Buy every NO in a complete partition; payoff n-1."""
    n = len(no_asks)
    if n < 2:
        return 0.0
    cost = sum(float(a) + taker_fee(a) for a in no_asks)
    return float(n - 1) - cost


def binary_lock_net(yes_ask: float, no_ask: float) -> float:
    """Buy YES+NO on a binary market; payoff exactly 1."""
    return 1.0 - (
        float(yes_ask) + taker_fee(yes_ask) + float(no_ask) + taker_fee(no_ask)
    )


def tradeable_net(net: float, min_net: float = MIN_NET) -> bool:
    return float(net) >= float(min_net)


def gamma_prefilter_ok(
    S: float,
    n: int,
    per_leg: float = GAMMA_PREFILTER_PER_LEG,
) -> bool:
    """Only probe CLOB when |1-S| exceeds n * per_leg."""
    if n < MIN_LEGS:
        return False
    return abs(1.0 - float(S)) > float(n) * float(per_leg)


def _member_yes_price(member: Mapping[str, Any]) -> Optional[float]:
    if "yes_price" in member and member.get("yes_price") is not None:
        try:
            return float(member["yes_price"])
        except (TypeError, ValueError):
            return None
    raw = member.get("outcomePrices")
    if raw is None:
        return None
    try:
        if isinstance(raw, str):
            prices = json.loads(raw)
        else:
            prices = raw
        if isinstance(prices, (list, tuple)) and prices:
            return float(prices[0])
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    return None


def _member_float(member: Mapping[str, Any], *keys: str) -> Optional[float]:
    for key in keys:
        if key not in member or member.get(key) is None:
            continue
        try:
            return float(member[key])
        except (TypeError, ValueError):
            continue
    return None


def member_is_live(member: Mapping[str, Any]) -> bool:
    """True for open legs that look tradeable (not inactive placeholders).

    Placeholders (Person/Option A–J) are typically active=false, liquidity=0,
    no outcomePrices, and produce CLOB HTTPError — they must not inflate n.
    Residual Other / catch-all is NOT a harmless placeholder (see skipped_inactive_ok).
    """
    if member.get("closed"):
        return False
    if member.get("active") is True:
        return True
    liq = _member_float(member, "liquidity", "liquidityNum")
    if liq is not None and liq > 0.0:
        return True
    yes_price = _member_yes_price(member)
    if yes_price is not None and 0.0 < yes_price < 1.0:
        return True
    best_bid = _member_float(member, "bestBid")
    if best_bid is not None and best_bid > 0.0:
        return True
    return False


# Template unused slots only. Does not match Other / catch-all / Person K+.
PLACEHOLDER_TITLE_RE = re.compile(r"(?:person|option)\s+[a-j]\b", re.IGNORECASE)


def skipped_inactive_ok(skipped_members: Optional[Sequence[Mapping[str, Any]]]) -> bool:
    """True iff every skipped non-closed non-live member is a Person/Option A-J placeholder.

    Residual Other / Other-candidate / catch-all / unmatched titles can still resolve YES
    and wipe the remaining D+R (or similar) legs -- not a clean complete set.
    Empty skip list is vacuously OK (residual_risk none).
    """
    for m in skipped_members or []:
        if not isinstance(m, Mapping):
            return False
        if m.get("closed") or member_is_live(m):
            continue
        title = str(m.get("groupItemTitle") or m.get("question") or "").strip()
        if not PLACEHOLDER_TITLE_RE.search(title):
            return False
    return True


def member_gamma_ask(member: Mapping[str, Any]) -> Optional[float]:
    """Gamma-side ask proxy: bestAsk if present, else yes_price."""
    best_ask = _member_float(member, "bestAsk")
    if best_ask is not None and 0.0 < best_ask < 1.0:
        return best_ask
    yes_price = _member_yes_price(member)
    if yes_price is not None and 0.0 < yes_price < 1.0:
        return yes_price
    return None


def ask_coverage_ok(
    asks: Sequence[float],
    min_coverage: float = MIN_ASK_COVERAGE,
) -> bool:
    """Reject fake incompletes (e.g. Nobel sum_ask≈0.36) via coverage floor."""
    if not asks:
        return False
    try:
        return sum(float(a) for a in asks) >= float(min_coverage)
    except (TypeError, ValueError):
        return False


def partition_is_complete(members: Sequence[Mapping[str, Any]]) -> bool:
    """True only if remaining open legs still form an unresolved complete set.

    A closed YES-winner (price >= 0.95) means the leftover legs pay 0 — not tradable.
    Closed NO legs (price near 0) can be skipped; missing closed prices are unknown
    and therefore incomplete.
    """
    if not members:
        return False
    open_n = 0
    for m in members:
        price = _member_yes_price(m)
        if m.get("closed"):
            if price is None:
                return False
            try:
                p = float(price)
            except (TypeError, ValueError):
                return False
            if p >= 0.95:
                return False
            continue
        open_n += 1
        if price is None:
            return False
        try:
            p = float(price)
        except (TypeError, ValueError):
            return False
        if not (0.0 < p < 1.0):
            return False
    return open_n >= MIN_LEGS


def legs_in_range(n: int) -> bool:
    return MIN_LEGS <= int(n) <= MAX_LEGS


def depth_ok(ask_depth_shares: Optional[float], min_depth: float = MIN_ASK_DEPTH) -> bool:
    if ask_depth_shares is None:
        return False
    try:
        return float(ask_depth_shares) >= float(min_depth)
    except (TypeError, ValueError):
        return False


def set_pnl_eur(
    notional_eur: float,
    cost_per_set: float,
    side: str,
    n_legs: int = 2,
) -> float:
    """Paper PnL when a complete set resolves.

    BUY_YES_SET: shares = notional/cost, payoff 1 per set → shares*1 - notional
    BUY_NO_SET:  payoff (n-1) per set → shares*(n-1) - notional
    BINARY_LOCK: same as BUY_YES_SET (payoff 1)
    """
    cost = float(cost_per_set)
    notional = float(notional_eur)
    if cost <= 0.0 or notional <= 0.0:
        return 0.0
    shares = notional / cost
    side_u = str(side).upper()
    if side_u == "BUY_NO_SET":
        payoff = float(max(int(n_legs) - 1, 0))
    else:
        payoff = 1.0
    return round(shares * payoff - notional, 6)


def cost_per_set_from_asks(asks: Sequence[float]) -> float:
    """Total fill cost including taker fees."""
    return sum(float(a) + taker_fee(a) for a in asks)
