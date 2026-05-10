# =============================================================================
# POLYMARKET BEOBACHTER - PROPOSAL INTAKE FOR PAPER TRADING
# =============================================================================
#
# GOVERNANCE INTENT:
# This module loads and filters proposals for paper trading.
# It implements READ-ONLY access to the proposals/ storage.
#
# FILTERING CRITERIA:
# Only proposals that meet ALL of the following are selected:
# 1. decision == "TRADE"
# 2. review_result == "REVIEW_PASS" (after running review gate)
# 3. Not already paper-executed (idempotency)
#
# DATA FLOW:
#   proposals/proposals_log.json → intake.py → paper_trader
#   ❌ NO REVERSE FLOW (paper trading never modifies proposals)
#
# =============================================================================

import sys
import logging
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Optional

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from proposals.models import Proposal, ReviewOutcome
from proposals.storage import get_storage
from proposals.review_gate import ReviewGate

from paper_trader.entry_guardrails import describe_proposal, evaluate_entry_guardrails
from paper_trader.guardrail_audit import record_guardrail_decision
from paper_trader.logger import get_paper_logger
from analytics.edge_memory import assess_proposal_edge, detect_market_type

logger = logging.getLogger(__name__)

MAX_PROPOSAL_AGE_HOURS = int(os.getenv("MAX_PROPOSAL_AGE_HOURS", "4"))


# =============================================================================
# PROPOSAL INTAKE
# =============================================================================


class ProposalIntake:
    """
    Loads and filters proposals for paper trading.

    GOVERNANCE:
    - READ-ONLY access to proposals
    - Does NOT modify proposals
    - Does NOT write back to proposals/
    - Enforces idempotency (no re-execution)
    """

    def __init__(self):
        """Initialize the intake module."""
        self._storage = get_storage()
        self._review_gate = ReviewGate()
        self._paper_logger = get_paper_logger()

    def get_eligible_proposals(self, run_id: str | None = None) -> List[Proposal]:
        """
        Get proposals eligible for paper trading.

        CRITERIA:
        1. decision == "TRADE"
        2. Passes review gate (REVIEW_PASS)
        3. Not already paper-executed

        Returns:
            List of eligible Proposal objects
        """
        # Get all proposals
        all_proposals = self._storage.load_proposals()
        logger.info(f"Loaded {len(all_proposals)} total proposals")
        all_proposals = self._filter_recent_unique_proposals(all_proposals)
        # Sort: positive-edge (YES) proposals first so they are evaluated before NO-bets
        # fill up the position-count limit.  NO-bets consume eligible slots and then get
        # rejected by the YES-only simulator check — blocking valid YES opportunities.
        all_proposals.sort(key=lambda p: -(float(getattr(p, "edge", 0) or 0)))
        logger.info(
            "Using %d recent unique proposals (<= %dh, YES-first sort)",
            len(all_proposals),
            MAX_PROPOSAL_AGE_HOURS,
        )

        # Get already-executed proposal IDs
        executed_ids = self._paper_logger.get_executed_proposal_ids()
        logger.info(f"Found {len(executed_ids)} already paper-executed proposals")

        # ====================================================================
        # SPREAD PRE-FILTER (intake-level LOW-liq drop, audit 2026-04-27)
        # ====================================================================
        # The simulator blocks LOW-liq (spread >= 5%) at entry because 9/9 historical
        # LOW-liq trades lost -67% to -93% (-54.32 EUR total — essentially the entire
        # bot drawdown). However, the upstream filters use *volume*-based thresholds
        # (gamma min_liq=50 USD, MIN_LIQUIDITY=375 USD), which are uncorrelated with
        # *spread* in current weather markets. Result: 100% of proposals pass volume
        # gates but get blocked at simulator entry — wasted compute, 0 trades per cycle.
        #
        # This pre-filter fetches market snapshots ONCE per cycle (sequential per
        # market_id but only for not-yet-executed TRADE proposals) and drops markets
        # the simulator would block anyway. Fail-open on any error: if snapshot fetch
        # fails or returns None, the proposal continues normally and the simulator
        # block remains as defense-in-depth. No proposal is silently dropped.
        #
        # Rollback: delete this block (and the in-loop `if proposal.market_id in
        # spread_blocked` check below). The simulator behaviour is unchanged.
        # ====================================================================
        spread_blocked: set = set()
        spread_unknown: set = set()
        try:
            from paper_trader.snapshot_client import get_market_snapshots
            candidate_market_ids = list({
                p.market_id for p in all_proposals
                if getattr(p, "decision", None) == "TRADE"
                and p.proposal_id not in executed_ids
            })
            if candidate_market_ids:
                snapshots = get_market_snapshots(candidate_market_ids)
                for mid, snap in snapshots.items():
                    if snap is None:
                        spread_unknown.add(mid)
                        continue
                    liq = str(getattr(snap, "liquidity_bucket", "") or "").upper()
                    if liq == "LOW":
                        spread_blocked.add(mid)
                logger.info(
                    "[INTAKE-SPREAD] checked=%d low_liq_blocked=%d unknown=%d "
                    "(of %d candidate markets) — saved adversarial-check time",
                    len(snapshots),
                    len(spread_blocked),
                    len(spread_unknown),
                    len(candidate_market_ids),
                )
            else:
                logger.debug("[INTAKE-SPREAD] no candidate markets to pre-check")
        except Exception as e:
            # Fail-open: any error here MUST NOT block the pipeline. The simulator
            # LOW-liq block remains as the authoritative gate.
            logger.warning("[INTAKE-SPREAD] pre-filter failed (fail-open): %s", e)
            spread_blocked = set()

        # Filter
        eligible = []
        open_positions = self._paper_logger.get_open_positions()
        for proposal in all_proposals:
            # Check 1: Decision is TRADE
            if proposal.decision != "TRADE":
                continue

            # Check 2: Not already executed (idempotency)
            if proposal.proposal_id in executed_ids:
                continue

            # Check 2b: Spread pre-filter — drop markets the simulator would LOW-liq-block.
            # See block comment above for evidence and rollback.
            if proposal.market_id in spread_blocked:
                logger.info(
                    "[INTAKE-SPREAD] SKIP %s market=%s edge=%+.3f — LOW-liq pre-filter "
                    "(simulator would block: 9/9 historical LOW-liq lost -67%%+)",
                    proposal.proposal_id,
                    proposal.market_id,
                    float(getattr(proposal, "edge", 0) or 0),
                )
                try:
                    record_guardrail_decision(
                        {
                            "run_id": run_id,
                            "proposal_id": proposal.proposal_id,
                            "market_id": proposal.market_id,
                            "allowed": False,
                            "reason_code": "intake_spread_filter",
                            "reason_detail": "LOW-liq market dropped pre-adversarial",
                            "shadow_allowed_without_inventory": False,
                            **describe_proposal(proposal),
                        }
                    )
                except Exception as _audit_err:
                    logger.debug("[INTAKE-SPREAD] audit record failed: %s", _audit_err)
                continue

            # Check 3: Passes review gate
            review = self._review_gate.review(proposal)
            if review.outcome != ReviewOutcome.REVIEW_PASS:
                continue

            allowed, guardrail_reason = evaluate_entry_guardrails(
                proposal,
                open_positions_count=len(open_positions) + len(eligible),
            )
            shadow_allowed, shadow_reason = evaluate_entry_guardrails(
                proposal,
                open_positions_count=0,
                ignore_inventory_limit=True,
            )
            proposal_meta = describe_proposal(proposal)
            reason_code, _, reason_detail = guardrail_reason.partition("|")
            if not reason_detail:
                reason_code = "passed"
                reason_detail = guardrail_reason
            shadow_reason_code, _, shadow_reason_detail = shadow_reason.partition("|")
            if not shadow_reason_detail:
                shadow_reason_code = "passed"
                shadow_reason_detail = shadow_reason
            record_guardrail_decision(
                {
                    "run_id": run_id,
                    "proposal_id": proposal.proposal_id,
                    "market_id": proposal.market_id,
                    "allowed": allowed,
                    "reason_code": reason_code,
                    "reason_detail": reason_detail,
                    "policy_open_positions_count": len(open_positions) + len(eligible),
                    "shadow_allowed_without_inventory": shadow_allowed,
                    "shadow_reason_code": shadow_reason_code,
                    "shadow_reason_detail": shadow_reason_detail,
                    **proposal_meta,
                }
            )
            if not allowed:
                _side = getattr(proposal, "token", None) or getattr(proposal, "side", "?")
                _ep = getattr(proposal, "implied_probability", None)
                _edge = getattr(proposal, "edge", None)
                _is_yes = _edge is not None and float(_edge or 0) > 0
                logger.info(
                    "Proposal %s blocked by entry guardrail: %s [side=%s ep=%.3f edge=%+.3f %s]",
                    proposal.proposal_id,
                    reason_detail,
                    _side,
                    float(_ep or 0),
                    float(_edge or 0),
                    "YES-opportunity-missed?" if _is_yes else "NO-bet-correct-block",
                )
                # Shadow-Tracking: geblockter YES-Edge als Schatten-Trade aufzeichnen
                if _is_yes:
                    try:
                        from paper_trader.shadow_tracker import record_shadow_entry
                        record_shadow_entry(proposal, reason_code, reason_detail)
                    except Exception as _st_err:
                        logger.debug("shadow_tracker record failed (non-blocking): %s", _st_err)
                continue

            edge_memory = assess_proposal_edge(proposal, market_type=detect_market_type(proposal.market_question))
            if not edge_memory["allowed"]:
                logger.info(
                    "Proposal %s blocked by edge memory: %s | bucket=%s",
                    proposal.proposal_id,
                    edge_memory["reason"],
                    edge_memory["bucket"],
                )
                record_guardrail_decision(
                    {
                        "run_id": run_id,
                        "proposal_id": proposal.proposal_id,
                        "market_id": proposal.market_id,
                        "allowed": False,
                        "reason_code": "edge_memory",
                        "reason_detail": edge_memory["reason"],
                        "shadow_allowed_without_inventory": False,
                        **proposal_meta,
                    }
                )
                continue

            # Check 4: Adversarial Check nur fuer NEUE Proposals (<2h alt, max 5 pro Run)
            # Verhindert dass historische Proposals bei jedem Run erneut geprueft werden
            from datetime import timezone as _tz
            _now = datetime.now(_tz.utc)
            try:
                _ts = datetime.fromisoformat(proposal.timestamp.rstrip("Z")).replace(tzinfo=_tz.utc)
                _age_hours = (_now - _ts).total_seconds() / 3600
            except Exception:
                _age_hours = 999  # Unbekannt → nicht prüfen
            _is_new = _age_hours < 0.5  # Nur Proposals der letzten 30 Min (ein Pipeline-Run)

            edge_pct = abs(proposal.edge) * 100
            if _is_new and edge_pct > 10:
                try:
                    import concurrent.futures
                    from shared.adversarial_dialog import run_adversarial_check
                    _exe = concurrent.futures.ThreadPoolExecutor(max_workers=1)
                    _fut = _exe.submit(
                        run_adversarial_check,
                        market_question=proposal.market_question,
                        edge_pct=edge_pct,
                        our_probability=proposal.model_probability,
                        market_probability=proposal.implied_probability,
                        context={
                            "confidence": proposal.confidence_level,
                            "proposal_id": proposal.proposal_id,
                            "market_type": detect_market_type(proposal.market_question),
                            "side": "YES" if float(proposal.edge or 0) >= 0 else "NO",
                        },
                    )
                    try:
                        adv = _fut.result(timeout=30)
                    except concurrent.futures.TimeoutError:
                        logger.warning(
                            f"[ADVERSARIAL] Timeout (30s) fuer {proposal.proposal_id} "
                            "— Proposal wird akzeptiert (fail-open)"
                        )
                        _exe.shutdown(wait=False)
                        eligible.append(proposal)
                        continue
                    finally:
                        _exe.shutdown(wait=False)
                    if not adv.proceed:
                        logger.info(
                            f"[ADVERSARIAL] Edge abgelehnt fuer {proposal.proposal_id}: "
                            f"{adv.judge_reason}"
                        )
                        continue
                    logger.info(
                        f"[ADVERSARIAL] Edge bestaetigt ({adv.judge_verdict}) fuer "
                        f"{proposal.proposal_id}: {adv.judge_reason}"
                    )
                except Exception:
                    # Niemals crashen — bei Fehler wird Proposal trotzdem akzeptiert
                    pass

            eligible.append(proposal)

        logger.info(f"Found {len(eligible)} eligible proposals for paper trading")
        return eligible

    def _filter_recent_unique_proposals(self, proposals: List[Proposal]) -> List[Proposal]:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=MAX_PROPOSAL_AGE_HOURS)
        latest_by_market: Dict[str, Proposal] = {}

        for proposal in proposals:
            ts = self._parse_proposal_timestamp(proposal.timestamp)
            if ts is None or ts < cutoff:
                continue

            existing = latest_by_market.get(proposal.market_id)
            if existing is None:
                latest_by_market[proposal.market_id] = proposal
                continue

            existing_ts = self._parse_proposal_timestamp(existing.timestamp)
            if existing_ts is None or ts >= existing_ts:
                latest_by_market[proposal.market_id] = proposal

        filtered = list(latest_by_market.values())
        filtered.sort(key=lambda item: item.timestamp, reverse=True)
        return filtered

    @staticmethod
    def _parse_proposal_timestamp(raw_timestamp: str) -> Optional[datetime]:
        try:
            cleaned = raw_timestamp.strip()
            if cleaned.endswith("Z"):
                cleaned = cleaned[:-1] + "+00:00"
            dt = datetime.fromisoformat(cleaned)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except Exception:
            return None

    def get_proposal_by_id(self, proposal_id: str) -> Optional[Proposal]:
        """
        Get a specific proposal by ID.

        Args:
            proposal_id: The proposal ID

        Returns:
            Proposal if found, None otherwise
        """
        return self._storage.get_proposal_by_id(proposal_id)

    def is_proposal_eligible(self, proposal: Proposal) -> tuple:
        """
        Check if a specific proposal is eligible for paper trading.

        Returns:
            Tuple of (is_eligible: bool, reason: str)
        """
        # Check 1: Decision
        if proposal.decision != "TRADE":
            return (False, f"Decision is {proposal.decision}, not TRADE")

        # Check 2: Already executed
        executed_ids = self._paper_logger.get_executed_proposal_ids()
        if proposal.proposal_id in executed_ids:
            return (False, "Proposal already paper-executed (idempotency)")

        # Check 3: Review gate
        review = self._review_gate.review(proposal)
        if review.outcome != ReviewOutcome.REVIEW_PASS:
            return (False, f"Review outcome is {review.outcome.value}, not REVIEW_PASS")

        return (True, "Proposal eligible for paper trading")


# =============================================================================
# MODULE-LEVEL FUNCTIONS
# =============================================================================

_intake: Optional[ProposalIntake] = None


def get_intake() -> ProposalIntake:
    """Get the global intake instance."""
    global _intake
    if _intake is None:
        _intake = ProposalIntake()
    return _intake


def get_eligible_proposals(run_id: str | None = None) -> List[Proposal]:
    """Convenience function to get eligible proposals."""
    return get_intake().get_eligible_proposals(run_id=run_id)


