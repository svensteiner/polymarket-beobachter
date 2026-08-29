# =============================================================================
# POLYMARKET BEOBACHTER - CLOB ORDER-BOOK NO-FILL COST PROBE
# =============================================================================
#
# WHY:
#   The NO-Fade Forward Shadow Lane (paper_trader/no_fade_lane.py) needs the
#   REAL cost of buying the NO side at entry to close its Gate-2 question:
#   "does the modeled +3.3%/share edge survive real CLOB fills?".
#
#   The lane imports ``fetch_no_book_cost`` from THIS module. Until now the
#   module was missing, so every probe failed with ModuleNotFoundError and the
#   lane recorded ``real_no_cost = None`` — silently disabling Gate-2 forever.
#
# WHAT IT DOES (READ-ONLY, PAPER):
#   1. Resolve market_id -> CLOB token ids via the Gamma /markets/{id} endpoint.
#   2. Read the live CLOB order book for the NO token (clob.polymarket.com/book).
#   3. Compute the real NO buy cost:
#        - primary:   best (lowest) NO ask,
#        - synthetic: 1 - best YES bid  (buying NO == selling YES on a binary
#                     market) when the NO book has no asks.
#   4. Report spread and available ask depth so the lane can judge fillability.
#
#   NO orders are ever placed. This only reads public order-book data.
# =============================================================================

from __future__ import annotations

import json
import logging
import ssl
from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

GAMMA_BASE = "https://gamma-api.polymarket.com"
CLOB_BASE = "https://clob.polymarket.com"
DEFAULT_TIMEOUT = 8.0
_UA = "PolymarketBeobachter-CLOBBook/1.0"
_SSL = ssl.create_default_context()


@dataclass
class NoBookCost:
    """Result of a NO-side order-book cost probe."""
    ok: bool
    reason: str
    market_id: str
    no_best_ask: Optional[float] = None      # real cost per share to BUY NO
    no_best_bid: Optional[float] = None
    real_spread: Optional[float] = None
    ask_depth_shares: Optional[float] = None  # shares available on the NO ask side
    cost_source: Optional[str] = None         # "no_book" | "synthetic_yes"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# --------------------------------------------------------------------------- #
# HTTP helpers (urllib only — no extra deps, mirrors collector/client.py)
# --------------------------------------------------------------------------- #
def _get_json(url: str, timeout: float) -> Any:
    req = Request(url, headers={"User-Agent": _UA, "Accept": "application/json"})
    with urlopen(req, timeout=timeout, context=_SSL) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _resolve_no_token(market_id: str, timeout: float) -> Tuple[Optional[str], Optional[str], str]:
    """Return (no_token_id, yes_token_id, reason). tokens are None on failure."""
    try:
        data = _get_json(f"{GAMMA_BASE}/markets/{market_id}", timeout)
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, OSError) as e:
        return None, None, f"gamma_{type(e).__name__}"

    market = data[0] if isinstance(data, list) and data else data
    if not isinstance(market, dict):
        return None, None, "gamma_bad_shape"

    raw_tokens = market.get("clobTokenIds")
    raw_outcomes = market.get("outcomes")
    try:
        tokens: List[str] = json.loads(raw_tokens) if isinstance(raw_tokens, str) else (raw_tokens or [])
        outcomes: List[str] = json.loads(raw_outcomes) if isinstance(raw_outcomes, str) else (raw_outcomes or [])
    except json.JSONDecodeError:
        return None, None, "token_parse_error"

    if len(tokens) < 2 or len(outcomes) < 2:
        return None, None, "no_clob_tokens"

    # Map by outcome label; default to [YES, NO] ordering when labels are absent.
    no_idx, yes_idx = 1, 0
    lowered = [str(o).strip().lower() for o in outcomes]
    if "no" in lowered:
        no_idx = lowered.index("no")
        yes_idx = 1 - no_idx if len(tokens) == 2 else (lowered.index("yes") if "yes" in lowered else 0)
    return str(tokens[no_idx]), str(tokens[yes_idx]), "ok"


def _fetch_book(token_id: str, timeout: float) -> Optional[Dict[str, Any]]:
    try:
        return _get_json(f"{CLOB_BASE}/book?token_id={token_id}", timeout)
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, OSError):
        return None


# --------------------------------------------------------------------------- #
# Pure cost logic (unit-testable, no network)
# --------------------------------------------------------------------------- #
def _levels(book: Optional[Dict[str, Any]], side: str) -> List[Tuple[float, float]]:
    """Parse [(price, size), ...] for 'bids' or 'asks' from a CLOB book dict."""
    out: List[Tuple[float, float]] = []
    if not book:
        return out
    for lvl in book.get(side, []) or []:
        try:
            out.append((float(lvl["price"]), float(lvl["size"])))
        except (KeyError, TypeError, ValueError):
            continue
    return out


def compute_no_cost(no_book: Optional[Dict[str, Any]],
                    yes_book: Optional[Dict[str, Any]] = None,
                    market_id: str = "") -> NoBookCost:
    """
    Compute the real NO buy cost from raw order books. Pure function.

    Primary source: the NO token's best ask (what you actually pay to buy NO).
    Synthetic fallback: 1 - YES best bid (buying NO == selling YES on a binary
    market) — used only when the NO book has no asks but YES has bids.
    """
    no_asks = _levels(no_book, "asks")
    no_bids = _levels(no_book, "bids")

    if no_asks:
        no_asks.sort(key=lambda x: x[0])
        best_ask = no_asks[0][0]
        depth = sum(sz for pr, sz in no_asks if pr <= best_ask + 0.02)
        best_bid = max((p for p, _ in no_bids), default=None)
        spread = round(best_ask - best_bid, 4) if best_bid is not None else None
        return NoBookCost(
            ok=True, reason="ok", market_id=market_id,
            no_best_ask=round(best_ask, 4), no_best_bid=best_bid,
            real_spread=spread, ask_depth_shares=round(depth, 2),
            cost_source="no_book",
        )

    # Synthetic: buying NO == selling YES → cost = 1 - YES_best_bid
    yes_bids = _levels(yes_book, "bids")
    if yes_bids:
        yes_best_bid = max(p for p, _ in yes_bids)
        synth = round(1.0 - yes_best_bid, 4)
        depth = sum(sz for pr, sz in yes_bids if pr >= yes_best_bid - 0.02)
        yes_asks = _levels(yes_book, "asks")
        yes_best_ask = min((p for p, _ in yes_asks), default=None)
        # NO spread mirrors the YES spread: (1-yes_bid) - (1-yes_ask) = yes_ask - yes_bid
        spread = round(yes_best_ask - yes_best_bid, 4) if yes_best_ask is not None else None
        return NoBookCost(
            ok=True, reason="ok_synthetic", market_id=market_id,
            no_best_ask=synth, no_best_bid=None,
            real_spread=spread, ask_depth_shares=round(depth, 2),
            cost_source="synthetic_yes",
        )

    return NoBookCost(ok=False, reason="no_liquidity", market_id=market_id)


# --------------------------------------------------------------------------- #
# Public entry point (network)
# --------------------------------------------------------------------------- #
def fetch_no_book_cost(market_id: str, timeout: float = DEFAULT_TIMEOUT) -> NoBookCost:
    """
    Probe the live CLOB book and return the real NO-side buy cost for market_id.

    Fail-open: any network/parse error yields ok=False with a reason string;
    it never raises, so the caller (no_fade_lane) can record a modeled-only row.
    """
    mid = str(market_id)
    no_token, yes_token, reason = _resolve_no_token(mid, timeout)
    if not no_token:
        return NoBookCost(ok=False, reason=reason, market_id=mid)

    no_book = _fetch_book(no_token, timeout)
    yes_book = None
    # Only pay for the YES book when the NO book can't price the fill directly.
    if not _levels(no_book, "asks") and yes_token:
        yes_book = _fetch_book(yes_token, timeout)

    if no_book is None and yes_book is None:
        return NoBookCost(ok=False, reason="clob_unreachable", market_id=mid)

    result = compute_no_cost(no_book, yes_book, market_id=mid)
    logger.debug(
        "CLOB NO-book probe %s: ok=%s src=%s no_ask=%s depth=%s reason=%s",
        mid, result.ok, result.cost_source, result.no_best_ask,
        result.ask_depth_shares, result.reason,
    )
    return result
