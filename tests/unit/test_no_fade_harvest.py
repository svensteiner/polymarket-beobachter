"""Tests for the NO-fade paper harvest lane (exact + tight spread)."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from paper_trader.no_fade_harvest import (
    MAX_REAL_SPREAD,
    classify_event,
    harvest_pnl_eur,
    qualifies,
)


def test_classify_exact_highest_temp():
    assert classify_event("Will the highest temperature in London be 22°C on August 19?") == "exact"


def test_classify_between():
    assert classify_event(
        "Will the highest temperature in New York City be between 84-85°F on August 19?"
    ) == "between"


def test_classify_at_or_above():
    assert classify_event("Will the highest temperature in Denver be 91°F or above?") == "at_or_above"


def test_classify_at_or_below():
    assert classify_event("Will the lowest temperature in Seoul be 16°C or below?") == "at_or_below"


@pytest.mark.parametrize(
    "kwargs,ok,reason",
    [
        (
            dict(
                market_type="exact",
                market_p_yes=0.15,
                hours_to_resolution=24.0,
                real_spread=0.01,
                book_ok=True,
                real_no_cost=0.86,
                ask_depth_shares=20.0,
            ),
            True,
            "ok",
        ),
        (
            dict(
                market_type="between",
                market_p_yes=0.15,
                hours_to_resolution=24.0,
                real_spread=0.01,
                book_ok=True,
                real_no_cost=0.86,
                ask_depth_shares=20.0,
            ),
            False,
            "not_exact",
        ),
        (
            dict(
                market_type="exact",
                market_p_yes=0.25,
                hours_to_resolution=24.0,
                real_spread=0.01,
                book_ok=True,
                real_no_cost=0.76,
                ask_depth_shares=20.0,
            ),
            False,
            "out_of_band",
        ),
        (
            dict(
                market_type="exact",
                market_p_yes=0.09,
                hours_to_resolution=24.0,
                real_spread=0.01,
                book_ok=True,
                real_no_cost=0.92,
                ask_depth_shares=20.0,
            ),
            False,
            "out_of_band",
        ),
        (
            dict(
                market_type="exact",
                market_p_yes=0.15,
                hours_to_resolution=5.0,
                real_spread=0.01,
                book_ok=True,
                real_no_cost=0.86,
                ask_depth_shares=20.0,
            ),
            False,
            "lead_too_short",
        ),
        (
            dict(
                market_type="exact",
                market_p_yes=0.15,
                hours_to_resolution=24.0,
                real_spread=0.02,
                book_ok=True,
                real_no_cost=0.86,
                ask_depth_shares=20.0,
            ),
            False,
            "spread_too_wide",
        ),
        (
            dict(
                market_type="exact",
                market_p_yes=0.15,
                hours_to_resolution=24.0,
                real_spread=0.03,
                book_ok=True,
                real_no_cost=0.86,
                ask_depth_shares=20.0,
            ),
            False,
            "spread_too_wide",
        ),
        (
            dict(
                market_type="exact",
                market_p_yes=0.15,
                hours_to_resolution=24.0,
                real_spread=0.01,
                book_ok=False,
                real_no_cost=0.86,
                ask_depth_shares=20.0,
            ),
            False,
            "no_real_book",
        ),
        (
            dict(
                market_type="exact",
                market_p_yes=0.15,
                hours_to_resolution=24.0,
                real_spread=None,
                book_ok=True,
                real_no_cost=0.86,
                ask_depth_shares=20.0,
            ),
            False,
            "spread_too_wide",
        ),
        (
            dict(
                market_type="exact",
                market_p_yes=0.15,
                hours_to_resolution=24.0,
                real_spread=0.01,
                book_ok=True,
                real_no_cost=None,
                ask_depth_shares=20.0,
            ),
            False,
            "bad_no_cost",
        ),
        (
            dict(
                market_type="exact",
                market_p_yes=0.15,
                hours_to_resolution=24.0,
                real_spread=0.01,
                book_ok=True,
                real_no_cost=0.86,
                ask_depth_shares=1.0,
            ),
            False,
            "thin_book",
        ),
    ],
)
def test_qualifies_matrix(kwargs, ok, reason):
    got_ok, got_reason = qualifies(**kwargs)
    assert got_ok is ok
    assert got_reason == reason


def test_spread_threshold_is_strictly_under_two_cents():
    assert MAX_REAL_SPREAD == 0.02
    ok, _ = qualifies(
        market_type="exact",
        market_p_yes=0.115,
        hours_to_resolution=16.0,
        real_spread=0.0199,
        book_ok=True,
        real_no_cost=0.89,
        ask_depth_shares=10.0,
    )
    assert ok is True


def test_pnl_no_win():
    # 5 EUR at 0.85 NO → 5/0.85 shares, each pays 1.0 → +0.882 EUR
    pnl = harvest_pnl_eur(notional_eur=5.0, no_cost=0.85, resolution="NO")
    assert pnl == pytest.approx(5.0 * (1.0 - 0.85) / 0.85)


def test_pnl_yes_loss():
    pnl = harvest_pnl_eur(notional_eur=5.0, no_cost=0.85, resolution="YES")
    assert pnl == pytest.approx(-5.0)


def test_record_entries_and_close(monkeypatch, tmp_path):
    ledger = tmp_path / "harvest.jsonl"
    obs = tmp_path / "obs.jsonl"
    res_path = tmp_path / "resolutions.jsonl"
    gap = tmp_path / "gap.json"

    gap.write_text(json.dumps({"auto_pause": False}), encoding="utf-8")
    obs.write_text(json.dumps({
        "timestamp_utc": "2099-01-01T00:00:00+00:00",
        "market_id": "m-harvest-1",
        "city": "London",
        "event_description": "Will the highest temperature in London be 22°C on August 19?",
        "market_probability": 0.115,
        "hours_to_resolution": 16.0,
        "action": "OBSERVE",
    }) + "\n", encoding="utf-8")

    import paper_trader.no_fade_harvest as harvest
    monkeypatch.setattr(harvest, "LEDGER_PATH", ledger)
    monkeypatch.setattr(harvest, "OBS_LOG", obs)
    monkeypatch.setattr(harvest, "RESOLUTIONS_PATH", res_path)
    monkeypatch.setattr(harvest, "GAP_MONITOR_JSON", gap)
    monkeypatch.setattr(harvest, "ENTRY_RECENCY_MIN", 10**9)
    monkeypatch.setattr(harvest, "_position_size_eur", lambda: 5.0)

    class FakeBook:
        def to_dict(self):
            return {
                "ok": True,
                "no_best_ask": 0.89,
                "real_spread": 0.01,
                "ask_depth_shares": 50.0,
                "reason": "ok",
            }

    monkeypatch.setattr(
        "paper_trader.clob_book.fetch_no_book_cost",
        lambda _mid: FakeBook(),
    )

    entered = harvest.record_entries()
    assert entered == 1
    rows = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 1
    assert rows[0]["side"] == "NO"
    assert rows[0]["market_type"] == "exact"
    assert rows[0]["status"] == "OPEN"
    assert rows[0]["notional_eur"] == 5.0
    assert rows[0]["real_spread"] == 0.01
    assert rows[0]["source"] == "live_obs"

    # Duplicate market must not re-enter.
    assert harvest.record_entries() == 0

    res_path.write_text(json.dumps({
        "market_id": "m-harvest-1",
        "resolved": True,
        "resolution": "NO",
    }) + "\n", encoding="utf-8")
    closed = harvest.close_resolved()
    assert closed == 1
    rows = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()]
    assert rows[0]["status"] == "RESOLVED"
    assert rows[0]["resolution"] == "NO"
    assert rows[0]["pnl_eur"] > 0


def test_auto_pause_blocks_new_entries(monkeypatch, tmp_path):
    import paper_trader.no_fade_harvest as harvest
    gap = tmp_path / "gap.json"
    gap.write_text(json.dumps({"auto_pause": True}), encoding="utf-8")
    monkeypatch.setattr(harvest, "GAP_MONITOR_JSON", gap)
    monkeypatch.setattr(harvest, "LEDGER_PATH", tmp_path / "h.jsonl")
    assert harvest.record_entries() == 0


def test_seed_from_open_shadow(monkeypatch, tmp_path):
    import paper_trader.no_fade_harvest as harvest
    ledger = tmp_path / "harvest.jsonl"
    shadow = tmp_path / "shadow.jsonl"
    gap = tmp_path / "gap.json"
    gap.write_text(json.dumps({"auto_pause": False}), encoding="utf-8")
    now = datetime.now(timezone.utc)
    shadow.write_text("\n".join([
        json.dumps({
            "market_id": "3655213",
            "status": "OPEN",
            "city": "London",
            "market_type": "exact",
            "question": "Will the highest temperature in London be 22°C on August 19?",
            "market_p_yes": 0.115,
            "hours_to_resolution": 15.8,
            "entry_time": now.isoformat(),
            "real_no_cost": 0.89,
            "real_spread": 0.01,
            "real_ask_depth_shares": 40.0,
            "real_book_ok": True,
        }),
        json.dumps({
            "market_id": "3687088",
            "status": "OPEN",
            "city": "New York",
            "market_type": "between",
            "question": "Will the highest temperature in New York City be between 84-85°F?",
            "market_p_yes": 0.10,
            "hours_to_resolution": 16.0,
            "entry_time": now.isoformat(),
            "real_no_cost": 0.91,
            "real_spread": 0.01,
            "real_ask_depth_shares": 40.0,
            "real_book_ok": True,
        }),
    ]), encoding="utf-8")

    monkeypatch.setattr(harvest, "LEDGER_PATH", ledger)
    monkeypatch.setattr(harvest, "SHADOW_LEDGER", shadow)
    monkeypatch.setattr(harvest, "GAP_MONITOR_JSON", gap)
    monkeypatch.setattr(harvest, "_position_size_eur", lambda: 5.0)

    seeded = harvest.seed_from_open_shadow()
    assert seeded == 1
    rows = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()]
    assert rows[0]["market_id"] == "3655213"
    assert rows[0]["source"] == "shadow_adopt"
    assert rows[0]["notional_eur"] == 5.0


def test_seed_rejects_stale_remaining_lead(monkeypatch, tmp_path):
    import paper_trader.no_fade_harvest as harvest
    ledger = tmp_path / "harvest.jsonl"
    shadow = tmp_path / "shadow.jsonl"
    gap = tmp_path / "gap.json"
    gap.write_text(json.dumps({"auto_pause": False}), encoding="utf-8")
    stale_entry = (datetime.now(timezone.utc) - timedelta(hours=20)).isoformat()
    shadow.write_text(json.dumps({
        "market_id": "stale-1",
        "status": "OPEN",
        "city": "Paris",
        "market_type": "exact",
        "question": "Will the highest temperature in Paris be 26°C on August 19?",
        "market_p_yes": 0.12,
        "hours_to_resolution": 16.0,
        "entry_time": stale_entry,
        "real_no_cost": 0.88,
        "real_spread": 0.01,
        "real_ask_depth_shares": 40.0,
        "real_book_ok": True,
    }) + "\n", encoding="utf-8")
    monkeypatch.setattr(harvest, "LEDGER_PATH", ledger)
    monkeypatch.setattr(harvest, "SHADOW_LEDGER", shadow)
    monkeypatch.setattr(harvest, "GAP_MONITOR_JSON", gap)
    assert harvest.seed_from_open_shadow() == 0
    assert not ledger.exists()


def test_record_entries_skips_when_inventory_full(monkeypatch, tmp_path):
    import paper_trader.no_fade_harvest as harvest
    ledger = tmp_path / "harvest.jsonl"
    gap = tmp_path / "gap.json"
    obs = tmp_path / "obs.jsonl"
    gap.write_text(json.dumps({"auto_pause": False}), encoding="utf-8")
    obs.write_text("{}\n", encoding="utf-8")
    full = [{"market_id": f"open-{i}", "status": "OPEN"} for i in range(harvest.MAX_OPEN)]
    ledger.write_text("\n".join(json.dumps(r) for r in full) + "\n", encoding="utf-8")
    monkeypatch.setattr(harvest, "LEDGER_PATH", ledger)
    monkeypatch.setattr(harvest, "GAP_MONITOR_JSON", gap)
    monkeypatch.setattr(harvest, "OBS_LOG", obs)
    assert harvest.record_entries() == 0


def test_run_is_forward_only_and_does_not_touch_shadow_or_capital(monkeypatch, tmp_path):
    import paper_trader.no_fade_harvest as harvest
    ledger = tmp_path / "harvest.jsonl"
    shadow = tmp_path / "shadow.jsonl"
    capital = tmp_path / "capital.json"
    gap = tmp_path / "gap.json"
    obs = tmp_path / "obs.jsonl"
    res = tmp_path / "resolutions.jsonl"
    capital_payload = {"position_size_eur": 5.0, "available_capital_eur": 100.0}
    shadow_payload = json.dumps({
        "market_id": "should-not-seed",
        "status": "OPEN",
        "city": "London",
        "market_type": "exact",
        "market_p_yes": 0.12,
        "hours_to_resolution": 20.0,
        "entry_time": datetime.now(timezone.utc).isoformat(),
        "real_no_cost": 0.88,
        "real_spread": 0.01,
        "real_ask_depth_shares": 40.0,
        "real_book_ok": True,
    }) + "\n"
    capital.write_text(json.dumps(capital_payload), encoding="utf-8")
    shadow.write_text(shadow_payload, encoding="utf-8")
    gap.write_text(json.dumps({"auto_pause": False}), encoding="utf-8")
    obs.write_text("", encoding="utf-8")
    res.write_text("", encoding="utf-8")
    monkeypatch.setattr(harvest, "LEDGER_PATH", ledger)
    monkeypatch.setattr(harvest, "SHADOW_LEDGER", shadow)
    monkeypatch.setattr(harvest, "GAP_MONITOR_JSON", gap)
    monkeypatch.setattr(harvest, "OBS_LOG", obs)
    monkeypatch.setattr(harvest, "RESOLUTIONS_PATH", res)
    monkeypatch.setattr(harvest, "OUT_MD", tmp_path / "harvest.md")
    before_cap = capital.read_bytes()
    before_shadow = shadow.read_bytes()
    result = harvest.run()
    assert result["seeded_this_cycle"] == 0
    assert capital.read_bytes() == before_cap
    assert shadow.read_bytes() == before_shadow
    assert not ledger.exists() or ledger.read_text(encoding="utf-8").strip() == ""
