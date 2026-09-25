from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from proposals.storage import get_storage
from proposals.review_gate import ReviewGate
from proposals.models import ReviewOutcome

from paper_trader.entry_guardrails import evaluate_entry_guardrails
from paper_trader.logger import get_paper_logger

logger = logging.getLogger(__name__)


PROJECT_ROOT = Path(__file__).parent.parent
OUTPUT_FILE = PROJECT_ROOT / "output" / "edge_hunter.json"


@dataclass(frozen=True)
class EdgeCandidate:
    proposal_id: str
    timestamp: str
    market_id: str
    market_question: str
    implied_probability: float
    model_probability: float
    edge: float
    confidence_level: str
    hours_to_resolution: float | None = None
    ensemble_variance: float | None = None
    actionability: str = "unknown"  # actionable | blocked | shadow_only
    block_reason: str | None = None


def _utc_iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except Exception:
        return None


def build_edge_hunter_snapshot(*, max_candidates: int = 50) -> dict[str, Any]:
    """
    Build a compact "edge hunter" snapshot for production readiness.

    Governance:
    - Read-only with regard to trading execution.
    - Does not change any thresholds/guardrails.
    - Re-uses existing review gate + guardrails to classify candidates.
    """
    storage = get_storage()
    review_gate = ReviewGate()
    paper_logger = get_paper_logger()
    open_positions_count = len(paper_logger.get_open_positions())

    proposals = storage.load_proposals(limit=800)
    trade_proposals = [p for p in proposals if p.decision == "TRADE"]

    actionable: list[EdgeCandidate] = []
    blocked: list[EdgeCandidate] = []
    shadow_only: list[EdgeCandidate] = []

    for proposal in trade_proposals:
        try:
            review = review_gate.review(proposal)
            if review.outcome != ReviewOutcome.REVIEW_PASS:
                continue

            allowed, reason = evaluate_entry_guardrails(proposal, open_positions_count=open_positions_count)
            shadow_allowed, shadow_reason = evaluate_entry_guardrails(
                proposal,
                open_positions_count=0,
                ignore_inventory_limit=True,
            )

            edge_value = float(proposal.edge)
            edge_is_relative = abs(edge_value) > 1.0

            candidate = EdgeCandidate(
                proposal_id=proposal.proposal_id,
                timestamp=proposal.timestamp,
                market_id=proposal.market_id,
                market_question=proposal.market_question,
                implied_probability=float(proposal.implied_probability),
                model_probability=float(proposal.model_probability),
                edge=edge_value,
                confidence_level=str(proposal.confidence_level),
                hours_to_resolution=_safe_float(getattr(proposal, "hours_to_resolution", None)),
                ensemble_variance=_safe_float(getattr(proposal, "ensemble_variance", None)),
            )

            if allowed:
                actionable.append(EdgeCandidate(**{**asdict(candidate), "actionability": "actionable"}))
            elif shadow_allowed:
                shadow_only.append(
                    EdgeCandidate(
                        **{
                            **asdict(candidate),
                            "actionability": "shadow_only",
                            "block_reason": str(reason),
                        }
                    )
                )
            else:
                blocked.append(
                    EdgeCandidate(
                        **{
                            **asdict(candidate),
                            "actionability": "blocked",
                            "block_reason": str(reason),
                        }
                    )
                )
        except Exception:
            continue

    def _sort_key(item: EdgeCandidate) -> float:
        # Prefer large absolute edges; tie-break on confidence
        conf_bonus = {"HIGH": 0.02, "MEDIUM": 0.01, "LOW": 0.0}.get(str(item.confidence_level).upper(), 0.0)
        return abs(float(item.edge)) + conf_bonus

    actionable.sort(key=_sort_key, reverse=True)
    shadow_only.sort(key=_sort_key, reverse=True)
    blocked.sort(key=_sort_key, reverse=True)

    return {
        "generated_at": _utc_iso_now(),
        "proposal_scan_limit": 800,
        "trade_proposals_found": len(trade_proposals),
        "open_positions_count": open_positions_count,
        "actionable_count": len(actionable),
        "shadow_only_count": len(shadow_only),
        "blocked_count": len(blocked),
        "top_actionable": [asdict(item) for item in actionable[:max_candidates]],
        "top_shadow_only": [asdict(item) for item in shadow_only[:max_candidates]],
        "top_blocked": [asdict(item) for item in blocked[:max_candidates]],
        "notes": [
            "actionable = review_pass + entry_guardrails_pass with current open position count",
            "shadow_only = blocked by inventory/limits but would pass if inventory limit ignored",
            "edge may be relative for legacy proposals (abs(edge) > 1)",
        ],
    }


def write_edge_hunter_snapshot(snapshot: dict[str, Any]) -> None:
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUTPUT_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(OUTPUT_FILE)


def run_edge_hunter(*, max_candidates: int = 50) -> dict[str, Any]:
    snapshot = build_edge_hunter_snapshot(max_candidates=max_candidates)
    write_edge_hunter_snapshot(snapshot)
    logger.info(
        "EdgeHunter: actionable=%d shadow_only=%d blocked=%d",
        snapshot.get("actionable_count", 0),
        snapshot.get("shadow_only_count", 0),
        snapshot.get("blocked_count", 0),
    )
    return snapshot
