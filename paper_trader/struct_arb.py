# =============================================================================
# POLYMARKET BEOBACHTER - STRUCTURAL ARBITRAGE PAPER LANE
# =============================================================================
#
# Model-free complete-set / binary-lock paper trading on REAL CLOB asks + fees.
# Sits in cash when no net >= MIN_NET opportunity exists. PAPER ONLY — never
# places live orders. Fail-open: run() never raises into the pipeline.
# =============================================================================

from __future__ import annotations

import json
import logging
import os
import tempfile
import time
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from paper_trader.struct_arb_math import (
    MIN_NET,
    ask_coverage_ok,
    binary_lock_net,
    completeset_no_net,
    completeset_yes_net,
    cost_per_set_from_asks,
    depth_ok,
    gamma_prefilter_ok,
    legs_in_range,
    member_gamma_ask,
    member_is_live,
    partition_is_complete,
    set_pnl_eur,
    skipped_inactive_ok,
    tradeable_net,
)

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LEDGER_PATH = PROJECT_ROOT / "data" / "struct_arb.jsonl"
OUT_MD = PROJECT_ROOT / "analytics" / "struct_arb.md"
OUT_JSON = PROJECT_ROOT / "analytics" / "struct_arb.json"

NOTIONAL_EUR = 5.0
MAX_OPEN = 6
MAX_EVENTS = 300
MAX_BOOK_FETCHES = 45
BOOK_DEADLINE_SECONDS = 25.0
BINARY_MAX_PROBES = 8
GOVERNANCE_NOTICE = "PAPER ONLY — no live order"

# Last scan counters (module state for reports after fail-open).
_LAST_SCAN: Dict[str, Any] = {
    "scanned": 0,
    "complete": 0,
    "rejected_cost": 0,
    "skip_counts": {},
    "candidates": 0,
    "near_miss_nets": [],
    "legs_out_of_range_hist": {},
}


def _make_client():
    from collector.client import PolymarketClient

    return PolymarketClient()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_jsonish(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (json.JSONDecodeError, ValueError):
            return None
    return value


def _yes_price(market: Dict[str, Any]) -> Optional[float]:
    prices = _parse_jsonish(market.get("outcomePrices"))
    if isinstance(prices, list) and prices:
        try:
            return float(prices[0])
        except (TypeError, ValueError):
            return None
    return None


def _no_price(market: Dict[str, Any]) -> Optional[float]:
    prices = _parse_jsonish(market.get("outcomePrices"))
    if isinstance(prices, list) and len(prices) >= 2:
        try:
            return float(prices[1])
        except (TypeError, ValueError):
            return None
    yp = _yes_price(market)
    if yp is None:
        return None
    return 1.0 - yp


def _clob_tokens(market: Dict[str, Any]) -> List[str]:
    tokens = _parse_jsonish(market.get("clobTokenIds"))
    if isinstance(tokens, list):
        return [str(t) for t in tokens]
    return []


def _yes_no_tokens(market: Dict[str, Any]) -> tuple:
    """Return (yes_token, no_token) using outcomes labels when present."""
    tokens = _clob_tokens(market)
    outcomes = _parse_jsonish(market.get("outcomes"))
    yes_idx, no_idx = 0, 1
    if isinstance(outcomes, list):
        for i, o in enumerate(outcomes):
            name = str(o).strip().lower()
            if name in ("yes", "true"):
                yes_idx = i
            elif name in ("no", "false"):
                no_idx = i
    yes_t = tokens[yes_idx] if yes_idx < len(tokens) else (tokens[0] if tokens else None)
    no_t = tokens[no_idx] if no_idx < len(tokens) else (tokens[1] if len(tokens) > 1 else None)
    return yes_t, no_t


def _load_jsonl(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    rows: List[Dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def _load_ledger() -> List[Dict[str, Any]]:
    return _load_jsonl(LEDGER_PATH)


def _append_ledger(record: Dict[str, Any]) -> None:
    LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(LEDGER_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _rewrite_ledger(records: List[Dict[str, Any]]) -> None:
    LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(LEDGER_PATH.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            for rec in records:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        os.replace(tmp, str(LEDGER_PATH))
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _open_count(records: List[Dict[str, Any]]) -> int:
    return sum(1 for r in records if r.get("status") == "OPEN")


def _existing_partition_ids(records: List[Dict[str, Any]]) -> set:
    return {str(r.get("partition_id")) for r in records if r.get("partition_id")}


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)


def fetch_open_events(client: Any = None, max_events: int = MAX_EVENTS) -> List[Dict[str, Any]]:
    """Paginate Gamma /events?closed=false. No weather tag filter. Fail-open."""
    client = client or _make_client()
    from collector.client import PolymarketClient

    max_offset = getattr(client, "MAX_EVENT_OFFSET", PolymarketClient.MAX_EVENT_OFFSET)
    page_size = 100
    offset = 0
    out: List[Dict[str, Any]] = []
    while len(out) < max_events and offset < max_offset:
        try:
            batch = client.fetch_events(
                limit=min(page_size, max_events - len(out)),
                offset=offset,
                closed=False,
            )
        except Exception as e:
            logger.warning("struct_arb event fetch aborted at offset=%s: %s", offset, e)
            break
        if not batch:
            break
        out.extend(batch)
        offset += len(batch)
        if len(batch) < page_size:
            break
        try:
            time.sleep(getattr(client, "API_DELAY_SECONDS", 0.1))
        except Exception:
            pass
    return out[:max_events]


def _build_partitions(
    events: List[Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    """partition_id -> {title, members: [market dicts enriched]}."""
    parts: Dict[str, Dict[str, Any]] = {}
    for ev in events:
        title = ev.get("title") or ""
        event_id = str(ev.get("id") or "")
        event_neg = bool(ev.get("negRisk"))
        markets = ev.get("markets") or []
        if not isinstance(markets, list):
            continue
        for m in markets:
            if not isinstance(m, dict):
                continue
            mid = str(m.get("id") or m.get("conditionId") or "")
            if not mid:
                continue
            nrid = m.get("negRiskMarketID") or None
            if nrid:
                pid = str(nrid)
            elif event_neg and event_id:
                pid = f"event:{event_id}"
            else:
                continue  # standalone binary handled separately
            bucket = parts.setdefault(pid, {"title": title, "members": [], "event_id": event_id})
            if not bucket["title"] and title:
                bucket["title"] = title
            member = dict(m)
            member["_market_id"] = mid
            member["yes_price"] = _yes_price(m)
            yes_t, no_t = _yes_no_tokens(m)
            member["yes_token"] = yes_t
            member["no_token"] = no_t
            bucket["members"].append(member)
    return parts


def _iter_binary_markets(events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for ev in events:
        markets = ev.get("markets") or []
        if not isinstance(markets, list):
            continue
        for m in markets:
            if not isinstance(m, dict) or m.get("closed"):
                continue
            # Partition members are complete-set only — do not also binary-lock them.
            if m.get("negRiskMarketID") or (bool(ev.get("negRisk")) and len(markets) >= 2):
                continue
            yes_t, no_t = _yes_no_tokens(m)
            if not yes_t or not no_t:
                continue
            mid = str(m.get("id") or m.get("conditionId") or "")
            if not mid:
                continue
            yp = _yes_price(m)
            np_ = _no_price(m)
            if yp is None or np_ is None:
                continue
            vol = m.get("volume24hr") or m.get("volume") or ev.get("volume24hr") or 0
            try:
                vol_f = float(vol)
            except (TypeError, ValueError):
                vol_f = 0.0
            out.append({
                "market_id": mid,
                "title": ev.get("title") or m.get("question") or "",
                "question": m.get("question") or "",
                "yes_price": yp,
                "no_price": np_,
                "yes_token": yes_t,
                "no_token": no_t,
                "volume": vol_f,
                "market": m,
            })
    return out


class _BookBudget:
    def __init__(self, max_fetches: int = MAX_BOOK_FETCHES, deadline_s: float = BOOK_DEADLINE_SECONDS):
        self.max_fetches = max_fetches
        self.deadline_s = deadline_s
        self.t0 = time.monotonic()
        self.fetches = 0

    def allow(self) -> bool:
        if self.fetches >= self.max_fetches:
            return False
        if (time.monotonic() - self.t0) >= self.deadline_s:
            return False
        return True

    def mark(self) -> None:
        self.fetches += 1


def _fetch_token(token_id: str, budget: _BookBudget) -> Dict[str, Any]:
    if not budget.allow():
        return {"ok": False, "reason": "budget"}
    try:
        from paper_trader.clob_book import fetch_token_book

        book = fetch_token_book(token_id).to_dict()
    except Exception as e:
        book = {"ok": False, "reason": type(e).__name__}
    budget.mark()
    return book


def _live_gamma_asks(members: List[Dict[str, Any]]) -> List[float]:
    """Gamma ask proxies for live members (bestAsk / yes_price); no CLOB I/O."""
    asks: List[float] = []
    for m in members:
        if not member_is_live(m):
            continue
        ga = member_gamma_ask(m)
        if ga is None and m.get("yes_price") is not None:
            try:
                ga = float(m["yes_price"])
            except (TypeError, ValueError):
                ga = None
        if ga is None:
            continue
        try:
            asks.append(float(ga))
        except (TypeError, ValueError):
            continue
    return asks


def _partition_probe_sort_key(item: Any) -> tuple:
    """Tight book-budget probe order: fewer live legs first (2-leg preferred), then highest gamma est_net.

    est_net = completeset_yes_net(gamma asks) = 1 - sum(ask + fee(ask)) for BUY_YES_SET.
    """
    _pid, part = item
    members = part.get("members") or []
    live = [m for m in members if member_is_live(m)]
    n_live = len(live)
    n_rank = n_live if n_live >= 2 else 999
    gamma = _live_gamma_asks(members)
    est_net = completeset_yes_net(gamma) if len(gamma) >= 2 else -1e9
    return (n_rank, -float(est_net))


def _binary_probe_sort_key(bm: Dict[str, Any]) -> tuple:
    """Prefer higher gamma-estimated binary lock net, then volume."""
    try:
        est = binary_lock_net(float(bm["yes_price"]), float(bm["no_price"]))
    except (TypeError, ValueError, KeyError):
        est = -1e9
    try:
        vol = float(bm.get("volume") or 0)
    except (TypeError, ValueError):
        vol = 0.0
    return (-float(est), -vol)


def _book_entry(
    *,
    partition_id: str,
    side: str,
    title: str,
    n_legs: int,
    asks: List[float],
    market_ids: List[str],
    net: float,
    min_depth: float,
    skipped_inactive: int = 0,
    coverage: Optional[float] = None,
    residual_risk: str = "none",
) -> bool:
    existing = _existing_partition_ids(_load_ledger())
    if partition_id in existing:
        return False
    if _open_count(_load_ledger()) >= MAX_OPEN:
        logger.info("STRUCT_ARB_SKIP: inventory_full partition=%s", partition_id)
        return False
    cost = cost_per_set_from_asks(asks)
    cov = float(coverage) if coverage is not None else sum(float(a) for a in asks)
    record = {
        "arb_id": f"SA-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}",
        "entry_time": _now_iso(),
        "partition_id": partition_id,
        "side": side,
        "title": str(title or "")[:140],
        "n_legs": int(n_legs),
        "market_ids": list(market_ids),
        "asks": [round(float(a), 4) for a in asks],
        "cost_per_set": round(cost, 6),
        "net_edge": round(float(net), 6),
        "min_ask_depth": min_depth,
        "notional_eur": float(NOTIONAL_EUR),
        "skipped_inactive": int(skipped_inactive),
        "coverage": round(cov, 6),
        "residual_risk": "placeholders_only" if str(residual_risk) == "placeholders_only" else "none",
        "status": "OPEN",
        "resolution": None,
        "winner_market_id": None,
        "pnl_eur": None,
        "resolved_at": None,
        "governance_notice": GOVERNANCE_NOTICE,
    }
    _append_ledger(record)
    logger.info(
        "STRUCT_ARB_ENTER: %s | %s %s n=%d net=%.4f cost=%.4f",
        record["arb_id"], side, partition_id[:16], n_legs, net, cost,
    )
    return True


def _record_near_miss(
    near_miss: List[Dict[str, Any]],
    *,
    title: str,
    partition_id: str,
    side: str,
    net: float,
    asks: List[float],
    n_legs: int,
) -> None:
    """Keep top near-miss nets closest to MIN_NET (max 8)."""
    near_miss.append({
        "title": str(title or "")[:140],
        "partition_id": str(partition_id),
        "side": side,
        "net": round(float(net), 6),
        "asks": [round(float(a), 4) for a in asks],
        "n_legs": int(n_legs),
        "gap_to_min_net": round(float(MIN_NET) - float(net), 6),
    })
    near_miss.sort(key=lambda x: abs(float(x.get("gap_to_min_net") or 0.0)))
    del near_miss[8:]


def record_entries() -> int:
    """Scan Gamma events, verify CLOB books, paper-enter complete-set / binary locks."""
    skips: Counter = Counter()
    scanned = 0
    complete = 0
    rejected_cost = 0
    candidates = 0
    entered = 0
    near_miss: List[Dict[str, Any]] = []
    legs_oor_hist: Counter = Counter()

    if _open_count(_load_ledger()) >= MAX_OPEN:
        skips["inventory_full"] += 1
        logger.info("STRUCT_ARB_SKIP_COUNTS: %s", dict(skips))
        _LAST_SCAN.update({
            "scanned": 0,
            "complete": 0,
            "rejected_cost": 0,
            "skip_counts": dict(skips),
            "candidates": 0,
            "near_miss_nets": [],
            "legs_out_of_range_hist": {},
        })
        return 0

    try:
        events = fetch_open_events()
    except Exception as e:
        logger.warning("struct_arb.fetch_open_events failed: %s", e)
        events = []

    existing = _existing_partition_ids(_load_ledger())
    budget = _BookBudget()
    partitions = _build_partitions(events)

    for pid, part in sorted(partitions.items(), key=_partition_probe_sort_key):
        members = part["members"]
        scanned += 1
        members_live = [m for m in members if member_is_live(m)]
        # Drop inactive placeholders; keep closed winners/losers for completeness.
        closed_members = [m for m in members if m.get("closed")]
        scan_members = closed_members + members_live
        skipped_members = [
            m for m in members
            if not m.get("closed") and not member_is_live(m)
        ]
        skipped_inactive = len(skipped_members)
        if skipped_members and not skipped_inactive_ok(skipped_members):
            skips["residual_other"] += 1
            continue
        # Fill yes_price from bestAsk when Gamma mid is missing (prefilter + complete).
        for m in scan_members:
            if m.get("yes_price") is None:
                ga = member_gamma_ask(m)
                if ga is not None:
                    m["yes_price"] = ga
        open_members = [m for m in scan_members if not m.get("closed")]
        n = len(open_members)
        if not legs_in_range(n):
            skips["legs_out_of_range"] += 1
            legs_oor_hist[n] += 1
            continue
        if not partition_is_complete(scan_members):
            skips["incomplete"] += 1
            continue
        complete += 1
        if pid in existing:
            skips["duplicate"] += 1
            continue

        gamma_asks: List[float] = []
        for m in open_members:
            yp = m.get("yes_price")
            if yp is None:
                yp = member_gamma_ask(m)
            if yp is not None:
                try:
                    gamma_asks.append(float(yp))
                except (TypeError, ValueError):
                    pass
        if len(gamma_asks) != n:
            skips["incomplete"] += 1
            continue
        S = sum(gamma_asks)
        if not gamma_prefilter_ok(S, n):
            skips["prefilter"] += 1
            continue
        candidates += 1
        if not budget.allow():
            skips["budget"] += 1
            continue

        side = "BUY_YES_SET" if S < 1.0 else "BUY_NO_SET"
        market_ids = [str(m["_market_id"]) for m in open_members]
        asks: List[float] = []
        depths: List[float] = []
        book_ok = True
        for m in open_members:
            token = m.get("yes_token") if side == "BUY_YES_SET" else m.get("no_token")
            if not token:
                book_ok = False
                skips["no_real_book"] += 1
                break
            book = _fetch_token(str(token), budget)
            ask = book.get("best_ask")
            if not book.get("ok") or ask is None:
                book_ok = False
                skips["thin_book" if book.get("reason") == "empty_ask_book" else "no_real_book"] += 1
                break
            if not depth_ok(book.get("ask_depth_shares")):
                book_ok = False
                skips["thin_book"] += 1
                break
            asks.append(float(ask))
            depths.append(float(book.get("ask_depth_shares") or 0.0))
        if not book_ok or len(asks) != n:
            continue

        coverage = sum(asks)
        if not ask_coverage_ok(asks):
            skips["low_coverage"] += 1
            continue

        cost_est = cost_per_set_from_asks(asks)
        need_shares = NOTIONAL_EUR / max(cost_est, 1e-9)
        if any(d < need_shares for d in depths):
            skips["thin_book"] += 1
            continue

        net = completeset_yes_net(asks) if side == "BUY_YES_SET" else completeset_no_net(asks)
        if not tradeable_net(net):
            rejected_cost += 1
            skips["cost_negative"] += 1
            _record_near_miss(
                near_miss,
                title=str(part.get("title") or ""),
                partition_id=pid,
                side=side,
                net=net,
                asks=asks,
                n_legs=n,
            )
            continue

        if _open_count(_load_ledger()) >= MAX_OPEN:
            skips["inventory_full"] += 1
            break
        if _book_entry(
            partition_id=pid,
            side=side,
            title=str(part.get("title") or ""),
            n_legs=n,
            asks=asks,
            market_ids=market_ids,
            net=net,
            min_depth=min(depths) if depths else 0.0,
            skipped_inactive=skipped_inactive,
            coverage=coverage,
            residual_risk="placeholders_only" if skipped_inactive else "none",
        ):
            existing.add(pid)
            entered += 1

    # Binary YES+NO lock. Gamma mids ALWAYS sum to ~1, so the mid prefilter
    # would skip every binary. Probe a small liquid sample on REAL asks instead.
    binaries = sorted(_iter_binary_markets(events), key=_binary_probe_sort_key)
    binary_probes = 0
    for bm in binaries:
        if not budget.allow():
            skips["budget"] += 1
            break
        if binary_probes >= BINARY_MAX_PROBES:
            skips["binary_cap"] += 1
            break
        scanned += 1
        pid = f"binary:{bm['market_id']}"
        if pid in existing:
            skips["duplicate"] += 1
            continue
        if not partition_is_complete([
            {"closed": False, "yes_price": bm["yes_price"]},
            {"closed": False, "yes_price": bm["no_price"]},
        ]):
            skips["incomplete"] += 1
            continue
        complete += 1
        candidates += 1
        binary_probes += 1

        yes_book = _fetch_token(bm["yes_token"], budget)
        no_book = _fetch_token(bm["no_token"], budget)
        if not yes_book.get("ok") or not no_book.get("ok"):
            skips["no_real_book"] += 1
            continue
        if not depth_ok(yes_book.get("ask_depth_shares")) or not depth_ok(no_book.get("ask_depth_shares")):
            skips["thin_book"] += 1
            continue
        yes_ask = float(yes_book["best_ask"])
        no_ask = float(no_book["best_ask"])
        cost_est = cost_per_set_from_asks([yes_ask, no_ask])
        need_shares = NOTIONAL_EUR / max(cost_est, 1e-9)
        yes_depth = float(yes_book.get("ask_depth_shares") or 0)
        no_depth = float(no_book.get("ask_depth_shares") or 0)
        if yes_depth < need_shares or no_depth < need_shares:
            skips["thin_book"] += 1
            continue
        net = binary_lock_net(yes_ask, no_ask)
        if not tradeable_net(net):
            rejected_cost += 1
            skips["cost_negative"] += 1
            _record_near_miss(
                near_miss,
                title=str(bm.get("title") or bm.get("question") or ""),
                partition_id=pid,
                side="BINARY_LOCK",
                net=net,
                asks=[yes_ask, no_ask],
                n_legs=2,
            )
            continue
        if _open_count(_load_ledger()) >= MAX_OPEN:
            skips["inventory_full"] += 1
            break
        if _book_entry(
            partition_id=pid,
            side="BINARY_LOCK",
            title=str(bm.get("title") or bm.get("question") or ""),
            n_legs=2,
            asks=[yes_ask, no_ask],
            market_ids=[bm["market_id"]],
            net=net,
            min_depth=min(
                float(yes_book.get("ask_depth_shares") or 0),
                float(no_book.get("ask_depth_shares") or 0),
            ),
        ):
            existing.add(pid)
            entered += 1

    logger.info(
        "STRUCT_ARB_SKIP_COUNTS: %s | scanned=%d complete=%d rejected_cost=%d entered=%d fetches=%d",
        dict(skips), scanned, complete, rejected_cost, entered, budget.fetches,
    )
    _LAST_SCAN.update({
        "scanned": scanned,
        "complete": complete,
        "rejected_cost": rejected_cost,
        "skip_counts": dict(skips),
        "candidates": candidates,
        "book_fetches": budget.fetches,
        "near_miss_nets": list(near_miss),
        "legs_out_of_range_hist": {str(k): int(v) for k, v in sorted(legs_oor_hist.items())},
    })
    return entered


def _fetch_gamma_market(market_id: str) -> Optional[Dict[str, Any]]:
    """Fetch a single Gamma market by id. Fail-open, never raises."""
    try:
        client = _make_client()
        result = client._request(f"/markets/{market_id}")
        if isinstance(result, list) and result:
            market = result[0]
        elif isinstance(result, dict):
            market = result
        else:
            return None
        if isinstance(market, dict):
            return market
    except Exception as e:
        logger.debug("struct_arb._fetch_gamma_market %s failed: %s", market_id, e)
    return None


def _infer_winner(markets: List[Dict[str, Any]]) -> Optional[str]:
    """Return market_id whose YES outcomePrice is near 1.0."""
    best_id = None
    best_p = -1.0
    for m in markets:
        p = _yes_price(m)
        if p is None:
            continue
        if p > best_p:
            best_p = p
            best_id = str(m.get("id") or m.get("_market_id") or "")
    if best_p >= 0.95:
        return best_id
    return None


def close_resolved() -> int:
    """Close OPEN sets when all legs are Gamma-closed; compute paper PnL."""
    records = _load_ledger()
    if not records:
        return 0
    open_recs = [r for r in records if r.get("status") == "OPEN"]
    if not open_recs:
        return 0

    needed: List[str] = []
    for r in open_recs:
        for mid in r.get("market_ids") or []:
            mid_s = str(mid)
            if mid_s and mid_s not in needed:
                needed.append(mid_s)

    idx: Dict[str, Dict[str, Any]] = {}
    for mid in needed:
        market = _fetch_gamma_market(mid)
        if market:
            idx[mid] = market

    now_iso = _now_iso()
    closed_n = 0
    changed = False

    for r in records:
        if r.get("status") != "OPEN":
            continue
        mids = [str(x) for x in (r.get("market_ids") or [])]
        if not mids:
            continue
        legs = [idx[m] for m in mids if m in idx]
        if len(legs) < len(mids):
            continue  # incomplete view — wait
        if not all(bool(m.get("closed")) for m in legs):
            continue

        side = str(r.get("side") or "BUY_YES_SET")
        cost = float(r.get("cost_per_set") or 0.0)
        notional = float(r.get("notional_eur") or NOTIONAL_EUR)
        n_legs = int(r.get("n_legs") or len(mids))
        pnl = set_pnl_eur(notional, cost, side, n_legs=n_legs)
        winner = _infer_winner(legs)

        r["status"] = "RESOLVED"
        r["resolution"] = "COMPLETE_SET"
        r["winner_market_id"] = winner
        r["pnl_eur"] = pnl
        r["resolved_at"] = now_iso
        r["governance_notice"] = GOVERNANCE_NOTICE
        closed_n += 1
        changed = True
        logger.info(
            "STRUCT_ARB_CLOSE: %s pnl=%+.4f winner=%s",
            r.get("arb_id"), pnl, winner,
        )

    if changed:
        _rewrite_ledger(records)
    return closed_n


def summary() -> Dict[str, Any]:
    records = _load_ledger()
    open_recs = [r for r in records if r.get("status") == "OPEN"]
    resolved = [r for r in records if r.get("status") == "RESOLVED"]
    pnls = [float(r["pnl_eur"]) for r in resolved if r.get("pnl_eur") is not None]
    return {
        "generated_at": _now_iso(),
        "scanned": int(_LAST_SCAN.get("scanned") or 0),
        "complete": int(_LAST_SCAN.get("complete") or 0),
        "rejected_cost": int(_LAST_SCAN.get("rejected_cost") or 0),
        "candidates": int(_LAST_SCAN.get("candidates") or 0),
        "skip_counts": dict(_LAST_SCAN.get("skip_counts") or {}),
        "book_fetches": int(_LAST_SCAN.get("book_fetches") or 0),
        "near_miss_nets": list(_LAST_SCAN.get("near_miss_nets") or []),
        "legs_out_of_range_hist": dict(_LAST_SCAN.get("legs_out_of_range_hist") or {}),
        "total": len(records),
        "open": len(open_recs),
        "resolved": len(resolved),
        "realized_pnl_eur": round(sum(pnls), 4) if pnls else 0.0,
        "open_notional_eur": round(
            sum(float(r.get("notional_eur") or 0) for r in open_recs), 2
        ),
        "min_net": MIN_NET,
        "max_open": MAX_OPEN,
        "notional_eur": NOTIONAL_EUR,
        "governance_notice": GOVERNANCE_NOTICE,
    }


def _render_md(s: Dict[str, Any]) -> str:
    skips = s.get("skip_counts") or {}
    skip_line = ", ".join(f"{k}={v}" for k, v in sorted(skips.items())) or "none"
    hist = s.get("legs_out_of_range_hist") or {}
    hist_line = ", ".join(f"n={k}:{v}" for k, v in sorted(hist.items(), key=lambda kv: int(kv[0]))) or "none"
    near = s.get("near_miss_nets") or []
    near_lines = []
    for nm in near[:8]:
        near_lines.append(
            f"  - {nm.get('side')} | net={nm.get('net')} gap={nm.get('gap_to_min_net')} | "
            f"{str(nm.get('title') or '')[:80]}"
        )
    near_block = "\n".join(near_lines) if near_lines else "  - none"
    return "\n".join([
        "# Structural Arbitrage — Paper Trading",
        "",
        f"**Generiert:** {s['generated_at']}  ",
        "",
        "> PAPER ONLY — model-free complete-set / binary-lock after real CLOB asks + taker fees. "
        "Cash if no net edge. Kein Live-Order. Active-leg filter + ask coverage >= 0.92.",
        "",
        "## Scan",
        "",
        f"- Scanned partitions/markets: **{s.get('scanned', 0)}**",
        f"- Complete partitions: **{s.get('complete', 0)}**",
        f"- Candidates (prefilter): **{s.get('candidates', 0)}**",
        f"- Rejected (cost/net < MIN_NET): **{s.get('rejected_cost', 0)}**",
        f"- Book fetches: **{s.get('book_fetches', 0)}**",
        f"- Skip counts: `{skip_line}`",
        f"- Legs out-of-range hist: `{hist_line}`",
        "",
        "## Near-miss nets (closest to MIN_NET)",
        "",
        near_block,
        "",
        "## Ledger",
        "",
        f"- Positionen: **{s['total']}** (offen {s['open']}, aufgelöst {s['resolved']})",
        f"- Offenes Notional: **{s['open_notional_eur']:.2f} EUR**",
        f"- Realisiertes Paper-P&L: **{s['realized_pnl_eur']:+.2f} EUR**",
        f"- Entered this cycle: **{s.get('entered_this_cycle', 0)}**",
        f"- Closed this cycle: **{s.get('closed_this_cycle', 0)}**",
        "",
        "---",
        f"*{GOVERNANCE_NOTICE}*",
        "",
    ])


def _empty_summary() -> Dict[str, Any]:
    return {
        "generated_at": _now_iso(),
        "scanned": 0,
        "complete": 0,
        "rejected_cost": 0,
        "candidates": 0,
        "skip_counts": {},
        "book_fetches": 0,
        "near_miss_nets": [],
        "legs_out_of_range_hist": {},
        "total": 0,
        "open": 0,
        "resolved": 0,
        "realized_pnl_eur": 0.0,
        "open_notional_eur": 0.0,
        "entered_this_cycle": 0,
        "closed_this_cycle": 0,
        "min_net": MIN_NET,
        "max_open": MAX_OPEN,
        "notional_eur": NOTIONAL_EUR,
        "governance_notice": GOVERNANCE_NOTICE,
    }


def run() -> Dict[str, Any]:
    entered = 0
    closed = 0
    try:
        entered = record_entries()
    except Exception as e:
        logger.warning("struct_arb.record_entries failed: %s", e)
    try:
        closed = close_resolved()
    except Exception as e:
        logger.warning("struct_arb.close_resolved failed: %s", e)

    try:
        s = summary()
        s["entered_this_cycle"] = entered
        s["closed_this_cycle"] = closed
        try:
            _atomic_write(OUT_MD, _render_md(s))
            _atomic_write(OUT_JSON, json.dumps(s, indent=2, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.warning("struct_arb report write failed: %s", e)
        return s
    except Exception as e:
        logger.warning("struct_arb.run summary failed: %s", e)
        s = _empty_summary()
        s["entered_this_cycle"] = entered
        s["closed_this_cycle"] = closed
        try:
            _atomic_write(OUT_MD, _render_md(s))
            _atomic_write(OUT_JSON, json.dumps(s, indent=2, ensure_ascii=False) + "\n")
        except Exception:
            pass
        return s


def main() -> None:
    print(json.dumps(run(), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
