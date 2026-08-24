# =============================================================================
# POLYMARKET BEOBACHTER - REAL CLOB ORDER-BOOK PROBE (read-only)
# =============================================================================
#
# WHY (2026-06-14):
#   edge_research found a real favorite-longshot NO-fade edge, but the adversarial
#   verification's #1 kill-risk is that the project has NO real order-book depth:
#   snapshot_client synthesises a +/-1c placeholder spread from a single Gamma
#   outcomePrice. A NO-fade buys at ~0.80-0.90 on thin markets; if the true fill
#   cost is 3-5c instead of the modeled ~1.5c, the edge evaporates.
#
#   This module measures the REAL cost: it reads the Polymarket CLOB order book
#   (public, no auth needed to READ) for a market's NO outcome token and returns
#   the real best ask, spread, and fillable depth. It is READ-ONLY, fail-open, and
#   short-timeout so it can never hang or crash the live pipeline.
#
#   The book must be sampled AT ENTRY TIME (~24h lead): once a weather market nears
#   resolution the bucket collapses to ~0/1, so a retroactive read is meaningless.
# =============================================================================

from __future__ import annotations

import json
import logging
import ssl
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

GAMMA_API = "https://gamma-api.polymarket.com"
CLOB_API = "https://clob.polymarket.com"
_TIMEOUT = 4
_SSL = ssl.create_default_context()
# Depth within this many cents of best ask counts as "immediately fillable".
DEPTH_BAND = 0.02


@dataclass(frozen=True)
class NoBookCost:
    """Real NO-side execution snapshot from the live CLOB book."""

    ok: bool
    no_best_ask: Optional[float]      # price you pay per NO share at top of book
    no_best_bid: Optional[float]
    real_spread: Optional[float]      # ask - bid on the NO token
    ask_depth_shares: Optional[float] # size available within DEPTH_BAND of best ask
    n_ask_levels: Optional[int]
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "no_best_ask": self.no_best_ask,
            "no_best_bid": self.no_best_bid,
            "real_spread": self.real_spread,
            "ask_depth_shares": self.ask_depth_shares,
            "n_ask_levels": self.n_ask_levels,
            "reason": self.reason,
        }


def _get(url: str) -> Any:
    req = Request(url, headers={"User-Agent": "PolymarketBeobachter/2.0", "Accept": "application/json"})
    with urlopen(req, timeout=_TIMEOUT, context=_SSL) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _parse_jsonish(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (json.JSONDecodeError, ValueError):
            return None
    return value


def _no_token_id(market: Dict[str, Any]) -> Optional[str]:
    """Map the market's NO outcome to its CLOB token id (outcomes || clobTokenIds)."""
    outcomes = _parse_jsonish(market.get("outcomes"))
    tokens = _parse_jsonish(market.get("clobTokenIds"))
    if not tokens or not isinstance(tokens, list):
        return None
    no_idx = 1
    if isinstance(outcomes, list):
        for i, o in enumerate(outcomes):
            if str(o).strip().lower() == "no":
                no_idx = i
                break
    if no_idx < len(tokens):
        return str(tokens[no_idx])
    return None


@dataclass(frozen=True)
class TokenBookCost:
    """Real execution snapshot for an arbitrary CLOB token_id."""

    ok: bool
    best_ask: Optional[float]
    best_bid: Optional[float]
    real_spread: Optional[float]
    ask_depth_shares: Optional[float]
    n_ask_levels: Optional[int]
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "best_ask": self.best_ask,
            "best_bid": self.best_bid,
            "real_spread": self.real_spread,
            "ask_depth_shares": self.ask_depth_shares,
            "n_ask_levels": self.n_ask_levels,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class YesBookCost:
    """Real YES-side execution snapshot from the live CLOB book."""

    ok: bool
    yes_best_ask: Optional[float]
    yes_best_bid: Optional[float]
    real_spread: Optional[float]
    ask_depth_shares: Optional[float]
    n_ask_levels: Optional[int]
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "yes_best_ask": self.yes_best_ask,
            "yes_best_bid": self.yes_best_bid,
            "real_spread": self.real_spread,
            "ask_depth_shares": self.ask_depth_shares,
            "n_ask_levels": self.n_ask_levels,
            "reason": self.reason,
        }


def _yes_token_id(market: Dict[str, Any]) -> Optional[str]:
    """Map the market's YES outcome to its CLOB token id (outcomes || clobTokenIds)."""
    outcomes = _parse_jsonish(market.get("outcomes"))
    tokens = _parse_jsonish(market.get("clobTokenIds"))
    if not tokens or not isinstance(tokens, list):
        return None
    yes_idx = 0
    if isinstance(outcomes, list):
        for i, o in enumerate(outcomes):
            if str(o).strip().lower() == "yes":
                yes_idx = i
                break
    if yes_idx < len(tokens):
        return str(tokens[yes_idx])
    return None


def fetch_token_book(token_id: str) -> TokenBookCost:
    """Read the live CLOB book for an arbitrary token_id. Fail-open, never raises."""
    try:
        if not token_id:
            return TokenBookCost(False, None, None, None, None, None, "empty_token_id")
        book = _get(f"{CLOB_API}/book?token_id={token_id}")
        asks: List[Dict[str, Any]] = book.get("asks") or []
        bids: List[Dict[str, Any]] = book.get("bids") or []
        ask_prices = [float(a["price"]) for a in asks if "price" in a]
        bid_prices = [float(b["price"]) for b in bids if "price" in b]
        best_ask = min(ask_prices) if ask_prices else None
        best_bid = max(bid_prices) if bid_prices else None
        if best_ask is None:
            return TokenBookCost(False, None, best_bid, None, None, len(asks), "empty_ask_book")
        depth = sum(
            float(a["size"]) for a in asks
            if "price" in a and "size" in a and float(a["price"]) <= best_ask + DEPTH_BAND
        )
        spread = (best_ask - best_bid) if (best_bid is not None) else None
        return TokenBookCost(
            ok=True,
            best_ask=round(best_ask, 4),
            best_bid=round(best_bid, 4) if best_bid is not None else None,
            real_spread=round(spread, 4) if spread is not None else None,
            ask_depth_shares=round(depth, 1),
            n_ask_levels=len(asks),
            reason="ok",
        )
    except Exception as e:
        logger.debug("clob_book token probe failed for %s: %s", token_id, e)
        return TokenBookCost(False, None, None, None, None, None, f"{type(e).__name__}")


def fetch_yes_book_cost(market_id: str) -> YesBookCost:
    """Read the live CLOB book for `market_id`'s YES token. Fail-open, never raises."""
    try:
        gm = _get(f"{GAMMA_API}/markets?id={market_id}&limit=1")
        market = gm[0] if isinstance(gm, list) and gm else (gm if isinstance(gm, dict) else None)
        if not market:
            return YesBookCost(False, None, None, None, None, None, "gamma_market_not_found")
        if market.get("closed"):
            return YesBookCost(False, None, None, None, None, None, "market_closed")
        token = _yes_token_id(market)
        if not token:
            return YesBookCost(False, None, None, None, None, None, "no_clob_token")

        book = fetch_token_book(token)
        if not book.ok:
            return YesBookCost(
                False, None, book.best_bid, book.real_spread,
                book.ask_depth_shares, book.n_ask_levels, book.reason,
            )
        return YesBookCost(
            ok=True,
            yes_best_ask=book.best_ask,
            yes_best_bid=book.best_bid,
            real_spread=book.real_spread,
            ask_depth_shares=book.ask_depth_shares,
            n_ask_levels=book.n_ask_levels,
            reason="ok",
        )
    except Exception as e:
        logger.debug("clob_book YES probe failed for %s: %s", market_id, e)
        return YesBookCost(False, None, None, None, None, None, f"{type(e).__name__}")


def fetch_no_book_cost(market_id: str) -> NoBookCost:
    """Read the live CLOB book for `market_id`'s NO token and summarise NO-fill cost.

    Fully fail-open: any network/parse error returns ok=False with a reason; never
    raises. Designed to be called once per qualifying market per pipeline cycle.
    """
    try:
        gm = _get(f"{GAMMA_API}/markets?id={market_id}&limit=1")
        market = gm[0] if isinstance(gm, list) and gm else (gm if isinstance(gm, dict) else None)
        if not market:
            return NoBookCost(False, None, None, None, None, None, "gamma_market_not_found")
        if market.get("closed"):
            return NoBookCost(False, None, None, None, None, None, "market_closed")
        token = _no_token_id(market)
        if not token:
            return NoBookCost(False, None, None, None, None, None, "no_clob_token")

        book = _get(f"{CLOB_API}/book?token_id={token}")
        asks: List[Dict[str, Any]] = book.get("asks") or []
        bids: List[Dict[str, Any]] = book.get("bids") or []
        ask_prices = [float(a["price"]) for a in asks if "price" in a]
        bid_prices = [float(b["price"]) for b in bids if "price" in b]
        best_ask = min(ask_prices) if ask_prices else None
        best_bid = max(bid_prices) if bid_prices else None
        if best_ask is None:
            return NoBookCost(False, None, best_bid, None, None, len(asks), "empty_ask_book")
        depth = sum(
            float(a["size"]) for a in asks
            if "price" in a and "size" in a and float(a["price"]) <= best_ask + DEPTH_BAND
        )
        spread = (best_ask - best_bid) if (best_bid is not None) else None
        return NoBookCost(
            ok=True,
            no_best_ask=round(best_ask, 4),
            no_best_bid=round(best_bid, 4) if best_bid is not None else None,
            real_spread=round(spread, 4) if spread is not None else None,
            ask_depth_shares=round(depth, 1),
            n_ask_levels=len(asks),
            reason="ok",
        )
    except Exception as e:  # fail-open: research probe must never break the pipeline
        logger.debug("clob_book probe failed for %s: %s", market_id, e)
        return NoBookCost(False, None, None, None, None, None, f"{type(e).__name__}")
