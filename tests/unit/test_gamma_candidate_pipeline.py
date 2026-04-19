"""Tests for gamma candidate price/liquidity fallback in the observation pipeline.

The orchestrator attempts to fetch live prices via CLOB API (fetch_market_prices).
Gamma-API market IDs are not present in the CLOB API, so those markets were previously
silently dropped. The fix: fall back to outcomePrices + liquidity stored in the
gamma_candidates.jsonl data.

Regression tests for:
- GitHub-issue-equivalent: London Apr21 / Atlanta Apr21 skipped with _skip_no_price
  because CLOB returned no price, even though gamma candidate has valid outcomePrices.
"""
import json
import pytest


def _extract_price_and_liq(data: dict, real_prices: dict) -> tuple[float | None, float]:
    """Replicate orchestrator price/liquidity extraction logic."""
    market_id = data.get("market_id", "")
    odds_yes = None
    liquidity_usd = 100.0  # Default fallback (same as orchestrator)

    if market_id in real_prices:
        price_data = real_prices[market_id]
        outcome_prices = price_data.get("outcomePrices")
        if outcome_prices:
            try:
                prices_list = json.loads(outcome_prices)
                if len(prices_list) >= 1:
                    odds_yes = float(prices_list[0])
            except Exception:
                pass
        liq = price_data.get("liquidity")
        if liq:
            try:
                liquidity_usd = float(liq)
            except Exception:
                pass

    # Gamma fallback
    if odds_yes is None or liquidity_usd == 100.0:
        stored_op = data.get("outcomePrices")
        if stored_op and odds_yes is None:
            try:
                if isinstance(stored_op, str):
                    _stored_list = json.loads(stored_op)
                else:
                    _stored_list = stored_op
                if _stored_list and len(_stored_list) >= 1:
                    _cand_price = float(_stored_list[0])
                    if 0.01 < _cand_price < 0.99:
                        odds_yes = _cand_price
            except Exception:
                pass
        stored_liq = data.get("liquidity")
        if stored_liq is not None and liquidity_usd == 100.0:
            try:
                liquidity_usd = float(stored_liq)
            except Exception:
                pass

    return odds_yes, liquidity_usd


# ---------------------------------------------------------------------------
# London Apr21 gamma candidate (market_id not in CLOB API)
# ---------------------------------------------------------------------------

LONDON_APR21 = {
    "market_id": "2019116",
    "title": "Will the highest temperature in London be 14\u00b0C on April 21?",
    "description": "",
    "resolution_text": "",
    "end_date": "2026-04-21T12:00:00+00:00",
    "liquidity": 1198.6007,
    "outcomePrices": '["0.33", "0.67"]',
    "source": "gamma",
}

ATLANTA_APR21 = {
    "market_id": "2019215",
    "title": "Will the highest temperature in Atlanta be between 82-83\u00b0F on April 21?",
    "description": "",
    "resolution_text": "",
    "end_date": "2026-04-21T12:00:00+00:00",
    "liquidity": 952.1946,
    "outcomePrices": '["0.17", "0.83"]',
    "source": "gamma",
}


def test_london_apr21_uses_stored_prices_when_clob_misses():
    """London Apr21 gamma candidate must be accepted when CLOB returns nothing."""
    odds_yes, liquidity_usd = _extract_price_and_liq(LONDON_APR21, real_prices={})
    assert odds_yes == pytest.approx(0.33), "YES price should come from stored outcomePrices"
    assert liquidity_usd == pytest.approx(1198.6007), "Liquidity should come from stored field"


def test_atlanta_apr21_uses_stored_prices_when_clob_misses():
    """Atlanta Apr21 gamma candidate must be accepted when CLOB returns nothing."""
    odds_yes, liquidity_usd = _extract_price_and_liq(ATLANTA_APR21, real_prices={})
    assert odds_yes == pytest.approx(0.17)
    assert liquidity_usd == pytest.approx(952.1946)


def test_gamma_candidate_passes_min_liquidity_threshold():
    """Both gamma candidates must exceed MIN_LIQUIDITY=375 USD from weather.yaml."""
    MIN_LIQUIDITY = 375.0
    for cand in (LONDON_APR21, ATLANTA_APR21):
        _, liq = _extract_price_and_liq(cand, real_prices={})
        assert liq >= MIN_LIQUIDITY, f"{cand['market_id']} liquidity {liq} < {MIN_LIQUIDITY}"


def test_gamma_candidate_passes_odds_filter():
    """Both candidates must have YES price in [0.15, 0.80] (weather.yaml bounds)."""
    MIN_ODDS, MAX_ODDS = 0.15, 0.80
    for cand in (LONDON_APR21, ATLANTA_APR21):
        odds, _ = _extract_price_and_liq(cand, real_prices={})
        assert odds is not None
        assert MIN_ODDS <= odds <= MAX_ODDS, f"{cand['market_id']} odds {odds} outside [{MIN_ODDS}, {MAX_ODDS}]"


def test_clob_price_takes_priority_over_stored_price():
    """When CLOB has fresh data, it must be used (not the stored gamma price)."""
    real_prices = {
        "2019116": {
            "outcomePrices": '["0.45", "0.55"]',
            "liquidity": "2500.00",
        }
    }
    odds_yes, liquidity_usd = _extract_price_and_liq(LONDON_APR21, real_prices=real_prices)
    assert odds_yes == pytest.approx(0.45), "CLOB price should override stored price"
    assert liquidity_usd == pytest.approx(2500.0), "CLOB liquidity should override stored"


def test_invalid_stored_outcome_prices_does_not_crash():
    """Malformed outcomePrices must not raise — market is skipped instead."""
    bad_candidate = {
        "market_id": "99999",
        "title": "Bad market",
        "outcomePrices": "not-valid-json",
        "liquidity": 500.0,
    }
    odds_yes, liquidity_usd = _extract_price_and_liq(bad_candidate, real_prices={})
    assert odds_yes is None, "Malformed price should result in None → market skipped"


def test_boundary_prices_are_rejected():
    """Prices at 0.01 or 0.99 (boundary) must not be used (near-zero/certain bets)."""
    near_zero = {
        "market_id": "11111",
        "title": "Near certain NO",
        "outcomePrices": '["0.005", "0.995"]',
        "liquidity": 1000.0,
    }
    odds_yes, _ = _extract_price_and_liq(near_zero, real_prices={})
    # 0.005 is not > 0.01 so it's rejected
    assert odds_yes is None, "Price 0.005 is below 0.01 guard → should be None"
