from __future__ import annotations

import json

from analytics.edge_memory import assess_proposal_edge, get_edge_summary
from proposals.models import Proposal, ProposalCoreCriteria


def _proposal(*, edge: float, confidence: str = "HIGH", market_id: str = "m1") -> Proposal:
    return Proposal(
        proposal_id=f"p-{market_id}",
        timestamp="2026-03-09T12:00:00+00:00",
        market_id=market_id,
        market_question="Will the temperature in Berlin be above 60F on March 10?",
        decision="TRADE",
        implied_probability=0.40,
        model_probability=0.65 if edge >= 0 else 0.30,
        edge=edge,
        core_criteria=ProposalCoreCriteria(True, True, True, True),
        warnings=(),
        confidence_level=confidence,
        justification_summary="test",
    )


def test_edge_summary_aggregates_closed_position_buckets(monkeypatch, tmp_path):
    positions_file = tmp_path / "paper_positions.jsonl"
    payloads = [
        {
            "position_id": "1",
            "status": "CLOSED",
            "realized_pnl_eur": 12.0,
            "confidence_level": "HIGH",
            "market_type": "at_or_above",
            "side": "YES",
            "proposal_edge": 0.18,
            "hours_to_resolution": 36.0,
            "edge_bucket": "HIGH|at_or_above|YES|edge10p|time_24_72h",
        },
        {
            "position_id": "2",
            "status": "CLOSED",
            "realized_pnl_eur": -4.0,
            "confidence_level": "HIGH",
            "market_type": "at_or_above",
            "side": "YES",
            "proposal_edge": 0.15,
            "hours_to_resolution": 40.0,
            "edge_bucket": "HIGH|at_or_above|YES|edge10p|time_24_72h",
        },
    ]
    positions_file.write_text("\n".join(json.dumps(item) for item in payloads), encoding="utf-8")

    monkeypatch.setattr("analytics.edge_memory.POSITIONS_FILE", positions_file)

    summary = get_edge_summary(min_trades=2, limit=5)

    assert len(summary) == 1
    assert summary[0]["trade_count"] == 2
    assert summary[0]["avg_pnl_eur"] == 4.0
    assert summary[0]["win_rate"] == 0.5


def test_assess_proposal_edge_blocks_negative_bucket(monkeypatch, tmp_path):
    positions_file = tmp_path / "paper_positions.jsonl"
    payloads = []
    for idx, pnl in enumerate((-10.0, -8.0, -7.0, -6.0), start=1):
        payloads.append(
            {
                "position_id": str(idx),
                "status": "CLOSED",
                "realized_pnl_eur": pnl,
                "confidence_level": "HIGH",
                "market_type": "at_or_above",
                "side": "YES",
                "proposal_edge": 0.18,
                "hours_to_resolution": 36.0,
                "edge_bucket": "HIGH|at_or_above|YES|edge10p|time_24_72h",
            }
        )
    positions_file.write_text("\n".join(json.dumps(item) for item in payloads), encoding="utf-8")

    monkeypatch.setattr("analytics.edge_memory.POSITIONS_FILE", positions_file)

    verdict = assess_proposal_edge(_proposal(edge=0.18))

    assert verdict["allowed"] is False
    assert verdict["reason"] == "negative_edge_memory"


def test_assess_proposal_edge_scales_positive_bucket(monkeypatch, tmp_path):
    positions_file = tmp_path / "paper_positions.jsonl"
    payloads = []
    for idx, pnl in enumerate((12.0, 10.0, 9.0, 8.5), start=1):
        payloads.append(
            {
                "position_id": str(idx),
                "status": "CLOSED",
                "realized_pnl_eur": pnl,
                "confidence_level": "HIGH",
                "market_type": "at_or_above",
                "side": "YES",
                "proposal_edge": 0.18,
                "hours_to_resolution": 36.0,
                "edge_bucket": "HIGH|at_or_above|YES|edge10p|time_24_72h",
            }
        )
    positions_file.write_text("\n".join(json.dumps(item) for item in payloads), encoding="utf-8")

    monkeypatch.setattr("analytics.edge_memory.POSITIONS_FILE", positions_file)

    verdict = assess_proposal_edge(_proposal(edge=0.18))

    assert verdict["allowed"] is True
    assert verdict["reason"] == "positive_edge_memory"
    assert verdict["position_scale"] > 1.0
