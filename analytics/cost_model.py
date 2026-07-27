# =============================================================================
# POLYMARKET BEOBACHTER - EMPIRICAL COST MODEL (read-only)
# =============================================================================
#
# WHY (2026-07-27, plan F1):
#   Every backtest number this project produced used a SYNTHETIC 0.5c half-spread.
#   That number was never measured — it was a placeholder. Edges that look good at
#   0.5c can be worthless at real fill prices, and we nearly believed one.
#
#   Meanwhile the NO-fade forward lane has been recording REAL CLOB fills
#   (data/no_fade_shadow.jsonl: real_no_cost = actual best ask on the NO token,
#   real_spread, real_ask_depth_shares). That is ground truth. This module turns
#   it into a calibrated cost model that the backtests can use instead of a guess.
#
# THE IDENTITY THE BACKTEST USES:
#   cost = raw_price + half_spread + taker_fee(p)      [raw_price = 1-p for NO]
#   so the "premium" a real fill pays over the raw price is:
#   premium = real_ask - raw_price   ==>   half_spread_equivalent = premium - fee
#
#   We measure that premium distribution and expose:
#     - realistic  : the empirical median premium (what we actually paid)
#     - stress     : the p90 premium (bad-fill days)
#     - optimistic : the legacy 0.5c placeholder, kept only for comparison
#
# IMPORTANT CAVEAT (do not lose this):
#   real_no_cost is the BEST ASK — the price for a SMALL fill. Depth at that ask
#   is reported too. Trading size larger than `ask_depth_shares` walks the book
#   and costs more. These numbers are valid for small (paper-sized) positions.
#
#   READ-ONLY. Never trades, never mutates thresholds. Fail-open everywhere.
# =============================================================================

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LEDGER_PATH = PROJECT_ROOT / "data" / "no_fade_shadow.jsonl"
OUT_JSON = PROJECT_ROOT / "analytics" / "cost_model.json"

# Legacy placeholder — kept ONLY as the "optimistic" comparison point.
OPTIMISTIC_HALF_SPREAD = 0.005
# Fallback when no real fills are available yet: assume half of a 3c book spread.
FALLBACK_HALF_SPREAD = 0.015
# Minimum real fills before we trust the empirical calibration.
MIN_FILLS_FOR_CALIBRATION = 30


def _taker_fee(price: float) -> float:
    """Polymarket non-linear taker fee, mirrors core.fee_model."""
    p = max(0.001, min(0.999, price))
    return 0.02 * p * (1.0 - p) / 0.25


def _quantile(sorted_vals: List[float], q: float) -> Optional[float]:
    if not sorted_vals:
        return None
    idx = min(len(sorted_vals) - 1, max(0, int(round(q * (len(sorted_vals) - 1)))))
    return sorted_vals[idx]


def _load_real_fills() -> List[Dict[str, Any]]:
    if not LEDGER_PATH.exists():
        return []
    out = []
    for line in LEDGER_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        if r.get("real_book_ok") and r.get("real_no_cost") is not None \
                and r.get("market_p_yes") is not None:
            out.append(r)
    return out


def measure() -> Dict[str, Any]:
    """Measure the real fill-cost premium from the forward lane's CLOB captures."""
    fills = _load_real_fills()
    premiums: List[float] = []
    fees: List[float] = []
    spreads: List[float] = []
    depths: List[float] = []

    for r in fills:
        kp = float(r["market_p_yes"])
        raw_price = 1.0 - kp                      # raw NO price before costs
        premiums.append(float(r["real_no_cost"]) - raw_price)
        fees.append(_taker_fee(kp))
        if r.get("real_spread") is not None:
            spreads.append(float(r["real_spread"]))
        if r.get("real_ask_depth_shares") is not None:
            depths.append(float(r["real_ask_depth_shares"]))

    premiums.sort()
    spreads.sort()
    depths.sort()
    n = len(premiums)
    mean_fee = (sum(fees) / len(fees)) if fees else 0.0

    med_prem = _quantile(premiums, 0.50)
    p90_prem = _quantile(premiums, 0.90)

    # half_spread equivalent = premium - fee (the fee is modeled separately)
    def _hs(prem: Optional[float]) -> Optional[float]:
        return None if prem is None else max(0.0, prem - mean_fee)

    calibrated = n >= MIN_FILLS_FOR_CALIBRATION
    realistic = _hs(med_prem) if calibrated else None
    stress = _hs(p90_prem) if calibrated else None

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "n_real_fills": n,
        "calibrated": calibrated,
        "mean_taker_fee": round(mean_fee, 5),
        "premium_over_raw_price": {
            "mean": round(sum(premiums) / n, 5) if n else None,
            "median": round(med_prem, 5) if med_prem is not None else None,
            "p75": round(_quantile(premiums, 0.75), 5) if n else None,
            "p90": round(p90_prem, 5) if p90_prem is not None else None,
            "max": round(premiums[-1], 5) if n else None,
        },
        "book_spread_no_token": {
            "median": round(_quantile(spreads, 0.50), 5) if spreads else None,
            "mean": round(sum(spreads) / len(spreads), 5) if spreads else None,
            "p90": round(_quantile(spreads, 0.90), 5) if spreads else None,
        },
        "ask_depth_shares": {
            "median": _quantile(depths, 0.50),
            "p25": _quantile(depths, 0.25),
            "min": depths[0] if depths else None,
        },
        "half_spread_levels": {
            "optimistic": OPTIMISTIC_HALF_SPREAD,
            "realistic": round(realistic, 5) if realistic is not None else FALLBACK_HALF_SPREAD,
            "stress": round(stress, 5) if stress is not None else 0.03,
        },
        "caveat": (
            "real_no_cost is the BEST ASK (small-fill price). Sizes above "
            "ask_depth_shares walk the book and cost more."
        ),
    }


_cache: Optional[Dict[str, Any]] = None


def levels() -> Dict[str, float]:
    """Half-spread levels for cost-stressing a backtest. Cached per process."""
    global _cache
    if _cache is None:
        try:
            _cache = measure()
        except Exception as e:  # fail-open
            logger.debug("cost_model.measure failed: %s", e)
            _cache = {"half_spread_levels": {
                "optimistic": OPTIMISTIC_HALF_SPREAD,
                "realistic": FALLBACK_HALF_SPREAD,
                "stress": 0.03,
            }}
    return _cache["half_spread_levels"]


def realistic_half_spread() -> float:
    """The empirically calibrated half-spread — the honest default for backtests."""
    return float(levels().get("realistic", FALLBACK_HALF_SPREAD))


def stress_half_spread() -> float:
    return float(levels().get("stress", 0.03))


def cost_floor(half_spread: Optional[float] = None, ref_price: float = 0.14) -> float:
    """Break-even cost per share at a reference longshot price.

    An edge must clear this to be worth trading at all.
    """
    hs = realistic_half_spread() if half_spread is None else half_spread
    return hs + _taker_fee(ref_price)


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)


def run() -> Dict[str, Any]:
    s = measure()
    try:
        _atomic_write(OUT_JSON, json.dumps(s, indent=2, ensure_ascii=False))
    except Exception as e:
        logger.debug("cost_model write failed: %s", e)
    return s


def main() -> None:
    s = run()
    lv = s["half_spread_levels"]
    print(f"Real fills: {s['n_real_fills']}  calibrated={s['calibrated']}")
    print(f"Premium over raw price: {s['premium_over_raw_price']}")
    print(f"Book spread (NO token): {s['book_spread_no_token']}")
    print(f"Ask depth shares:       {s['ask_depth_shares']}")
    print(f"HALF-SPREAD LEVELS -> optimistic={lv['optimistic']} "
          f"realistic={lv['realistic']} stress={lv['stress']}")
    print(f"cost floor @realistic (p=0.14): {cost_floor():.5f}")


if __name__ == "__main__":
    main()
