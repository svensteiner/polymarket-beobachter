"""NO-fade lane must only open positions that are REALLY fillable on the CLOB
(a genuine NO best ask exists) — unfillable in-band candidates are skipped, so
the forward ledger only contains fill-survivable trades."""

import sys
import types

import paper_trader.no_fade_lane as lane


class _Book:
    def __init__(self, no_best_ask, ok=True, reason="ok", depth=100.0, spread=0.02):
        self.no_best_ask = no_best_ask
        self.real_spread = spread
        self.ask_depth_shares = depth
        self.ok = ok
        self.reason = reason

    def to_dict(self):
        return {
            "no_best_ask": self.no_best_ask, "real_spread": self.real_spread,
            "ask_depth_shares": self.ask_depth_shares, "ok": self.ok, "reason": self.reason,
        }


def _install_fake_clob(monkeypatch, mapping):
    """Install a fake paper_trader.clob_book with fetch_no_book_cost(mid)->_Book."""
    mod = types.ModuleType("paper_trader.clob_book")
    mod.fetch_no_book_cost = lambda mid, timeout=8.0: mapping[str(mid)]
    monkeypatch.setitem(sys.modules, "paper_trader.clob_book", mod)


def _cand(mid, kp):
    return {
        "market_id": mid, "market_probability": kp, "hours_to_resolution": 20.0,
        "event_description": f"Will the lowest temperature in Testville be {mid}C be 12C?",
        "action": "OBSERVE", "city": "Testville",
    }


def test_skips_unfillable_and_enters_fillable(tmp_path, monkeypatch):
    monkeypatch.setattr(lane, "LEDGER_PATH", tmp_path / "led.jsonl")
    monkeypatch.setattr(lane, "_auto_paused", lambda: False)
    # two in-band candidates: one fillable (real ask), one not (None)
    monkeypatch.setattr(lane, "_latest_in_band_candidates",
                        lambda: [_cand("A", 0.12), _cand("B", 0.15)])
    _install_fake_clob(monkeypatch, {
        "A": _Book(no_best_ask=0.90),          # fillable
        "B": _Book(no_best_ask=None, ok=False, reason="no_liquidity"),  # unfillable
    })
    entered = lane.record_entries()
    assert entered == 1
    rows = lane._load_ledger()
    assert len(rows) == 1
    assert rows[0]["market_id"] == "A"
    assert rows[0]["real_no_cost"] == 0.90
    assert rows[0]["real_book_ok"] is True


def test_enters_nothing_when_all_unfillable(tmp_path, monkeypatch):
    monkeypatch.setattr(lane, "LEDGER_PATH", tmp_path / "led.jsonl")
    monkeypatch.setattr(lane, "_auto_paused", lambda: False)
    monkeypatch.setattr(lane, "_latest_in_band_candidates",
                        lambda: [_cand("A", 0.12), _cand("B", 0.15)])
    _install_fake_clob(monkeypatch, {
        "A": _Book(no_best_ask=None, ok=False, reason="no_liquidity"),
        "B": _Book(no_best_ask=None, ok=False, reason="clob_unreachable"),
    })
    assert lane.record_entries() == 0
    assert lane._load_ledger() == []
