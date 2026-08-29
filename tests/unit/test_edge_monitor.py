"""Tests for analytics.edge_monitor multi-day aggregation (pure logic)."""

from analytics import edge_monitor as em


def test_summarize_history_empty():
    s = em.summarize_history([])
    assert s["scans"] == 0
    assert s["ever_actionable"] == 0
    assert s["best_fillable_net_ever"] is None


def test_summarize_history_no_actionable():
    hist = [
        {"ts": "t1", "overpriced_families": 3, "actionable_families": 0,
         "best_fillable_net": -0.35, "max_deviation": 0.42},
        {"ts": "t2", "overpriced_families": 4, "actionable_families": 0,
         "best_fillable_net": -0.34, "max_deviation": 0.40},
    ]
    s = em.summarize_history(hist)
    assert s["scans"] == 2
    assert s["ever_actionable"] == 0
    assert s["first_ts"] == "t1" and s["last_ts"] == "t2"
    assert s["best_fillable_net_ever"] == -0.34   # least-negative (max)
    assert s["max_overpriced_families"] == 4
    assert s["max_deviation_ever"] == 0.42


def test_summarize_history_detects_actionable():
    hist = [
        {"ts": "t1", "overpriced_families": 2, "actionable_families": 0, "best_fillable_net": -0.1},
        {"ts": "t2", "overpriced_families": 3, "actionable_families": 1,
         "best_fillable_net": 0.05, "best_fillable_family": "arctic|range|", "max_deviation": 0.2},
    ]
    s = em.summarize_history(hist)
    assert s["ever_actionable"] == 1
    assert s["total_actionable_scans"] == 1
    assert s["best_fillable_net_ever"] == 0.05
    assert s["best_fillable_family_ever"] == "arctic|range|"


def test_summarize_ledger_counts_and_pnl():
    rows = [
        {"status": "OPEN"},
        {"status": "RESOLVED", "realized_pnl": 0.2},
        {"status": "RESOLVED", "realized_pnl": -0.1},
    ]
    s = em.summarize_ledger(rows, "realized_pnl")
    assert s["total"] == 3 and s["open"] == 1 and s["resolved"] == 2
    assert abs(s["realized_pnl"] - 0.1) < 1e-9
    assert s["wins"] == 1 and s["losses"] == 1


def test_build_report_verdict_no_edge(monkeypatch, tmp_path):
    monkeypatch.setattr(em, "HISTORY_PATH", tmp_path / "h.jsonl")
    monkeypatch.setattr(em, "BASKET_LEDGER", tmp_path / "b.jsonl")
    monkeypatch.setattr(em, "NOFADE_LEDGER", tmp_path / "n.jsonl")
    r = em.build_report()
    assert "no fill-survivable edge yet" in r["verdict"]


def test_build_report_verdict_edge_when_basket_traded(monkeypatch, tmp_path):
    h = tmp_path / "h.jsonl"; b = tmp_path / "b.jsonl"; n = tmp_path / "n.jsonl"
    h.write_text("", encoding="utf-8")
    b.write_text('{"status": "OPEN"}\n', encoding="utf-8")
    n.write_text("", encoding="utf-8")
    monkeypatch.setattr(em, "HISTORY_PATH", h)
    monkeypatch.setattr(em, "BASKET_LEDGER", b)
    monkeypatch.setattr(em, "NOFADE_LEDGER", n)
    r = em.build_report()
    assert "FILLABLE EDGE APPEARED" in r["verdict"]
