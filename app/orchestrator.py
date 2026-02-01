# =============================================================================
# POLYMARKET BEOBACHTER - PIPELINE ORCHESTRATOR
# =============================================================================
#
# GOVERNANCE:
# This module provides a SINGLE orchestration point for the entire pipeline.
# It maintains all existing governance protections:
# - Layer isolation
# - No live trading
# - Append-only logs
# - Human review requirements
#
# PIPELINE STEPS:
# 1. Collector: Fetch market metadata (no prices)
# 2. Analyzer: Determine TRADE / NO_TRADE / INSUFFICIENT_DATA
# 3. Proposals: Generate and review proposals
# 4. Paper Trader: Simulate entries (no real trades)
# 5. Cross-Market Research: Detect logical inconsistencies (ISOLATED)
# 6. Outcome Tracker: Record predictions for calibration (ISOLATED)
# 7. Status: Write summary to output/status_summary.txt
#
# =============================================================================

import json
import logging
import sys
from datetime import datetime, date
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple
from dataclasses import dataclass, field
from enum import Enum

# Setup paths
BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR))

logger = logging.getLogger(__name__)


class RunState(Enum):
    """Pipeline run state."""
    OK = "OK"
    DEGRADED = "DEGRADED"
    FAIL = "FAIL"


@dataclass
class StepResult:
    """Result of a single pipeline step."""
    name: str
    success: bool
    message: str
    data: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None


@dataclass
class PipelineResult:
    """Result of a full pipeline run."""
    state: RunState
    timestamp: str
    steps: List[StepResult] = field(default_factory=list)
    summary: Dict[str, Any] = field(default_factory=dict)

    def add_step(self, step: StepResult):
        self.steps.append(step)
        if not step.success and self.state == RunState.OK:
            self.state = RunState.DEGRADED


class Orchestrator:
    """
    Main pipeline orchestrator.

    GOVERNANCE:
    - All existing protections remain in place
    - Each step is wrapped with error handling
    - Failures in one step don't crash the pipeline
    - All errors are logged to audit
    """

    # =========================================================================
    # CONFIGURABLE LIMITS (avoid magic numbers)
    # =========================================================================
    MAX_CANDIDATES_TO_ANALYZE = 500  # Max candidates analyzed per run (was 20)
    MAX_PROPOSALS_PER_RUN = 20       # Max proposals generated per run (was 5)

    def __init__(self, base_dir: Optional[Path] = None):
        self.base_dir = base_dir or BASE_DIR
        self.output_dir = self.base_dir / "output"
        self.logs_dir = self.base_dir / "logs"
        self.audit_dir = self.logs_dir / "audit"
        self.proposals_dir = self.base_dir / "proposals"
        self.data_dir = self.base_dir / "data" / "collector"

        # Ensure directories exist
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.audit_dir.mkdir(parents=True, exist_ok=True)

        # Load module configuration
        try:
            from shared.module_loader import get_module_config
            self.module_config = get_module_config()
        except ImportError:
            self.module_config = None
            logger.warning("Module loader not available, all modules enabled by default")

    def _is_module_enabled(self, module_name: str) -> bool:
        """Check if a module is enabled in config."""
        if self.module_config is None:
            return True  # Default to enabled if no config
        return self.module_config.is_enabled(module_name)

    def run_pipeline(self) -> PipelineResult:
        """
        Execute the full pipeline.

        Steps (only if enabled in config/modules.yaml):
        1. Collector (metadata only)
        2. Core Analyzer
        3. Proposal Generator + Review Gate
        4. Paper Trader
        5. Cross-Market Research
        6. Outcome Tracker
        7. Weather Engine
        8. Write status summary

        Returns:
            PipelineResult with state and step details
        """
        result = PipelineResult(
            state=RunState.OK,
            timestamp=datetime.now().isoformat()
        )

        # Check master switch
        if self.module_config and not self.module_config.master_enabled:
            logger.warning("Master switch is OFF - pipeline disabled")
            result.state = RunState.DEGRADED
            result.summary = {"error": "Master switch is disabled"}
            return result

        # Step 1: Collector
        if self._is_module_enabled("collector"):
            collector_result = self._run_collector()
            result.add_step(collector_result)
        else:
            collector_result = StepResult(name="collector", success=True, message="DISABLED", data={})
            result.add_step(collector_result)

        # Step 2: Analyzer
        if self._is_module_enabled("analyzer"):
            analyzer_result = self._run_analyzer(collector_result.data)
            result.add_step(analyzer_result)
        else:
            analyzer_result = StepResult(name="analyzer", success=True, message="DISABLED", data={})
            result.add_step(analyzer_result)

        # Step 3: Proposals
        if self._is_module_enabled("proposals"):
            proposal_result = self._run_proposals(analyzer_result.data)
            result.add_step(proposal_result)
        else:
            proposal_result = StepResult(name="proposals", success=True, message="DISABLED", data={})
            result.add_step(proposal_result)

        # Step 4: Paper Trader
        if self._is_module_enabled("paper_trader"):
            paper_result = self._run_paper_trader(proposal_result.data)
            result.add_step(paper_result)
        else:
            result.add_step(StepResult(name="paper_trader", success=True, message="DISABLED", data={}))

        # Step 5: Cross-Market Research (ISOLATED - does not affect trading)
        if self._is_module_enabled("cross_market"):
            cross_market_result = self._run_cross_market(collector_result.data)
            result.add_step(cross_market_result)
        else:
            result.add_step(StepResult(name="cross_market", success=True, message="DISABLED", data={}))

        # Step 6: Outcome Tracker (ISOLATED - records facts only)
        if self._is_module_enabled("outcome_tracker"):
            outcome_result = self._run_outcome_tracker(
                collector_result.data,
                analyzer_result.data,
                result.timestamp
            )
            result.add_step(outcome_result)
        else:
            result.add_step(StepResult(name="outcome_tracker", success=True, message="DISABLED", data={}))

        # Step 7: Weather Engine (signal generation)
        if self._is_module_enabled("weather_engine"):
            weather_result = self._run_weather_engine()
            result.add_step(weather_result)

        # Step 8: Signal-to-Paper-Trade wiring
        # Convert weather + arbitrage signals into proposals and paper trade them
        if self._is_module_enabled("paper_trader"):
            signal_result = self._run_signal_trading()
            result.add_step(signal_result)

        # Build summary
        result.summary = self._build_summary(result)

        # Step 8: Write status
        status_result = self._write_status_summary(result)
        result.add_step(status_result)

        # Log to audit
        self._log_to_audit(result)

        return result

    def _run_weather_engine(self) -> StepResult:
        """Run the weather engine step (ISOLATED - signals only)."""
        try:
            from core.weather_engine import create_engine

            # Weather engine is READ-ONLY, does not execute trades
            engine = create_engine()
            result = engine.run()

            return StepResult(
                name="weather_engine",
                success=True,
                message=f"Generated {len(result.actionable_signals)} actionable signals",
                data={
                    "signals_total": len(result.signals),
                    "signals_actionable": len(result.actionable_signals),
                    "markets_processed": result.markets_processed,
                }
            )
        except Exception as e:
            logger.error(f"Weather engine failed: {e}")
            return StepResult(
                name="weather_engine",
                success=False,
                message="Weather engine failed",
                error=str(e)
            )

    def _run_signal_trading(self) -> StepResult:
        """
        Convert signals from specialized engines into proposals and paper trade them.

        Wires: Weather Signals + Arbitrage Signals → Proposals → Paper Trader

        This is the bridge between isolated signal engines and the paper trading system.
        All proposals still pass through ReviewGate before being paper-traded.
        """
        try:
            from proposals.signal_adapter import (
                load_recent_weather_signals,
                load_recent_arbitrage_signals,
                weather_signal_to_analysis,
                arbitrage_signal_to_analysis,
            )
            from proposals.generator import ProposalGenerator
            from proposals.review_gate import ReviewGate
            from proposals.storage import get_storage
            from paper_trader.intake import is_proposal_eligible
            from paper_trader.simulator import simulate_entry

            generator = ProposalGenerator()
            gate = ReviewGate()
            storage = get_storage()

            weather_proposals = 0
            arb_proposals = 0
            paper_traded = 0
            skipped = 0
            seen_markets = set()

            # --- Weather Signals ---
            weather_signals = load_recent_weather_signals(max_signals=10)
            for signal in weather_signals:
                try:
                    analysis = weather_signal_to_analysis(signal)
                    if not analysis:
                        continue

                    market_id = analysis["market_input"]["market_id"]
                    if market_id in seen_markets:
                        continue
                    seen_markets.add(market_id)

                    proposal = generator.generate(analysis)
                    if not proposal:
                        continue

                    storage.save_proposal(proposal)
                    review = gate.review(proposal)
                    storage.save_review(proposal, review)

                    if review.outcome.value == "REVIEW_PASS":
                        weather_proposals += 1
                        if is_proposal_eligible(proposal)[0]:
                            position, record = simulate_entry(proposal)
                            if position is not None:
                                paper_traded += 1
                            else:
                                skipped += 1
                except Exception as e:
                    logger.warning(f"Weather signal trading failed: {e}")

            # --- Arbitrage Signals ---
            arb_signals = load_recent_arbitrage_signals(max_signals=10)
            for signal in arb_signals:
                try:
                    analysis = arbitrage_signal_to_analysis(signal)
                    if not analysis:
                        continue

                    market_id = analysis["market_input"]["market_id"]
                    if market_id in seen_markets:
                        continue
                    seen_markets.add(market_id)

                    proposal = generator.generate(analysis)
                    if not proposal:
                        continue

                    storage.save_proposal(proposal)
                    review = gate.review(proposal)
                    storage.save_review(proposal, review)

                    if review.outcome.value == "REVIEW_PASS":
                        arb_proposals += 1
                        if is_proposal_eligible(proposal)[0]:
                            position, record = simulate_entry(proposal)
                            if position is not None:
                                paper_traded += 1
                            else:
                                skipped += 1
                except Exception as e:
                    logger.warning(f"Arbitrage signal trading failed: {e}")

            total = weather_proposals + arb_proposals
            return StepResult(
                name="signal_trading",
                success=True,
                message=f"{total} signal proposals ({weather_proposals} weather, {arb_proposals} arb), {paper_traded} paper traded",
                data={
                    "weather_proposals": weather_proposals,
                    "arbitrage_proposals": arb_proposals,
                    "paper_traded": paper_traded,
                    "skipped": skipped,
                }
            )

        except Exception as e:
            logger.warning(f"Signal trading step failed (non-critical): {e}")
            return StepResult(
                name="signal_trading",
                success=True,  # Non-critical
                message=f"Signal trading skipped: {str(e)[:50]}",
                data={"weather_proposals": 0, "arbitrage_proposals": 0, "paper_traded": 0}
            )

    def _run_collector(self) -> StepResult:
        """Run the collector step."""
        try:
            from collector.collector import Collector

            collector = Collector(
                output_dir=str(self.data_dir),
                max_markets=1500  # Increased from 500 for more coverage
            )
            stats = collector.run(dry_run=False)

            return StepResult(
                name="collector",
                success=True,
                message=f"Fetched {stats.total_fetched} markets, {stats.total_candidates} candidates",
                data={
                    "total_fetched": stats.total_fetched,
                    "total_candidates": stats.total_candidates,
                    "filter_results": stats.filter_results
                }
            )
        except Exception as e:
            logger.error(f"Collector failed: {e}")
            return StepResult(
                name="collector",
                success=False,
                message="Collector failed",
                error=str(e)
            )

    def _run_analyzer(self, collector_data: Dict[str, Any]) -> StepResult:
        """Run the core analyzer step with specialized analyzers per category."""
        try:
            # Load candidates from collector output
            today_str = date.today().isoformat()
            candidates_file = self.data_dir / "candidates" / today_str / "candidates.jsonl"

            if not candidates_file.exists():
                return StepResult(
                    name="analyzer",
                    success=True,
                    message="No candidates to analyze",
                    data={"analyzed": 0, "trade": 0, "no_trade": 0, "insufficient": 0}
                )

            candidates = []
            with open(candidates_file, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line:
                        candidates.append(json.loads(line))

            if not candidates:
                return StepResult(
                    name="analyzer",
                    success=True,
                    message="No candidates to analyze",
                    data={"analyzed": 0, "trade": 0, "no_trade": 0, "insufficient": 0}
                )

            # Import all analyzers
            from core.corporate_analyzer import CorporateEventAnalyzer, CorporateMarketInput
            from core.court_analyzer import CourtRulingAnalyzer, CourtMarketInput

            # Initialize specialized analyzers
            corporate_analyzer = CorporateEventAnalyzer()
            court_analyzer = CourtRulingAnalyzer()

            results = {"trade": 0, "no_trade": 0, "insufficient": 0}
            analyses = []
            latest_trade = None

            for candidate in candidates[:self.MAX_CANDIDATES_TO_ANALYZE]:
                try:
                    category = self._get_category(candidate)
                    title = candidate.get("title", "Unknown")
                    resolution = candidate.get("resolution_text", candidate.get("description", ""))
                    end_date = candidate.get("end_date", "2025-12-31")[:10]

                    # Route to specialized analyzer based on category
                    if category == "CORPORATE_EVENT":
                        result = self._analyze_corporate(corporate_analyzer, candidate)
                    elif category == "COURT_RULING":
                        result = self._analyze_court(court_analyzer, candidate)
                    else:
                        # Use simplified analysis for other categories
                        result = self._analyze_simple(candidate)

                    outcome = result["decision"]
                    if outcome == "TRADE":
                        results["trade"] += 1
                        latest_trade = {
                            "market_id": candidate.get("market_id"),
                            "title": title[:60],
                            "category": category,
                            "end_date": end_date,
                            "reason": result.get("reason", "Meets criteria")[:200],
                            "confidence": result.get("confidence", "MEDIUM"),
                        }
                    elif outcome == "NO_TRADE":
                        results["no_trade"] += 1
                    else:
                        results["insufficient"] += 1

                    analyses.append({
                        "market_id": candidate.get("market_id"),
                        "title": title,
                        "category": category,
                        "decision": outcome,
                        "confidence": result.get("confidence", "MEDIUM"),
                        "blocking_criteria": result.get("blocking", [])
                    })

                except Exception as e:
                    logger.warning(f"Analysis failed: {e}")
                    results["insufficient"] += 1

            return StepResult(
                name="analyzer",
                success=True,
                message=f"Analyzed {len(candidates[:self.MAX_CANDIDATES_TO_ANALYZE])} markets",
                data={
                    "analyzed": len(candidates[:self.MAX_CANDIDATES_TO_ANALYZE]),
                    **results,
                    "analyses": analyses,
                    "latest_trade": latest_trade
                }
            )

        except Exception as e:
            logger.error(f"Analyzer failed: {e}")
            return StepResult(
                name="analyzer",
                success=False,
                message="Analyzer failed",
                error=str(e),
                data={"analyzed": 0, "trade": 0, "no_trade": 0, "insufficient": 0}
            )

    def _get_category(self, candidate: Dict[str, Any]) -> str:
        """Extract category from candidate."""
        category = candidate.get("category", "").upper()
        if category:
            return category
        # Infer from collector_notes
        notes = candidate.get("collector_notes", [])
        if "corporate_event_market" in notes:
            return "CORPORATE_EVENT"
        elif "court_ruling_market" in notes:
            return "COURT_RULING"
        elif "weather_event_market" in notes:
            return "WEATHER_EVENT"
        elif "political_event_market" in notes:
            return "POLITICAL_EVENT"
        elif "finance_event_market" in notes:
            return "FINANCE_EVENT"
        return "GENERIC"

    def _analyze_corporate(self, analyzer, candidate: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze corporate event with specialized analyzer."""
        from core.corporate_analyzer import CorporateMarketInput
        market_input = CorporateMarketInput(
            market_question=candidate.get("title", "Unknown"),
            resolution_text=candidate.get("resolution_text", candidate.get("description", "")),
            target_date=candidate.get("end_date", "2025-12-31")[:10],
            description=candidate.get("description", ""),
        )
        report = analyzer.analyze(market_input)
        return {
            "decision": report.decision,
            "confidence": "HIGH" if report.decision == "TRADE" else "MEDIUM",
            "blocking": report.blocking_reasons,
            "reason": "; ".join(report.blocking_reasons[:3]) if report.blocking_reasons else "Passed all checks",
        }

    def _analyze_court(self, analyzer, candidate: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze court ruling with specialized analyzer."""
        from core.court_analyzer import CourtMarketInput
        market_input = CourtMarketInput(
            market_question=candidate.get("title", "Unknown"),
            resolution_text=candidate.get("resolution_text", candidate.get("description", "")),
            target_date=candidate.get("end_date", "2025-12-31")[:10],
            description=candidate.get("description", ""),
        )
        report = analyzer.analyze(market_input)
        return {
            "decision": report.decision,
            "confidence": "HIGH" if report.decision == "TRADE" else "MEDIUM",
            "blocking": report.blocking_reasons,
            "reason": "; ".join(report.blocking_reasons[:3]) if report.blocking_reasons else "Passed all checks",
        }

    def _analyze_simple(self, candidate: Dict[str, Any]) -> Dict[str, Any]:
        """
        Simplified analysis for non-specialized categories.
        Less strict - allows more TRADE decisions.
        """
        title = candidate.get("title", "").lower()
        end_date_str = candidate.get("end_date", "2025-12-31")[:10]
        blocking = []

        # Check timeline
        try:
            end_date = date.fromisoformat(end_date_str)
            days_until = (end_date - date.today()).days
            if days_until < 1:
                blocking.append("Target date too soon")
            elif days_until > 365:
                blocking.append("Target date too far")
        except ValueError:
            blocking.append("Invalid date")

        # Check for resolution text
        resolution = candidate.get("resolution_text", candidate.get("description", ""))
        if len(resolution) < 20:
            blocking.append("Resolution text too short")

        # Check for problematic keywords
        problematic = ["at our discretion", "we may", "subject to"]
        if any(p in resolution.lower() for p in problematic):
            blocking.append("Ambiguous resolution")

        # Decision based on blocking reasons
        if blocking:
            return {"decision": "NO_TRADE", "confidence": "MEDIUM", "blocking": blocking, "reason": "; ".join(blocking)}
        else:
            return {"decision": "TRADE", "confidence": "MEDIUM", "blocking": [], "reason": "All basic checks passed"}

    def _run_proposals(self, analyzer_data: Dict[str, Any]) -> StepResult:
        """Run proposal generation and review step."""
        try:
            analyses = analyzer_data.get("analyses", [])
            trade_analyses = [a for a in analyses if a.get("decision") == "TRADE"]

            if not trade_analyses:
                return StepResult(
                    name="proposals",
                    success=True,
                    message="No TRADE decisions to propose",
                    data={"generated": 0, "reviewed": 0, "passed": 0}
                )

            # Generate proposals for TRADE decisions
            from proposals.generator import ProposalGenerator
            from proposals.review_gate import ReviewGate
            from proposals.storage import get_storage
            from core.probability_models import get_honest_estimate, calculate_edge

            generator = ProposalGenerator()
            gate = ReviewGate()
            storage = get_storage()

            generated = 0
            reviewed = 0
            passed = 0
            skipped_no_signal = 0
            latest_proposal = None

            for analysis in trade_analyses[:self.MAX_PROPOSALS_PER_RUN]:
                try:
                    # =========================================================
                    # HONEST PROBABILITY ESTIMATION
                    # =========================================================
                    # Use the new honest probability model interface.
                    # If the model returns valid=False, we SKIP this market.
                    # NO fake edges. NO placeholder probabilities.
                    # =========================================================

                    # Fetch current market price via snapshot client
                    market_id = analysis.get("market_id", "unknown")
                    market_probability = None
                    try:
                        from paper_trader.snapshot_client import get_market_snapshot
                        snapshot = get_market_snapshot(market_id)
                        if snapshot and hasattr(snapshot, 'mid_price') and snapshot.mid_price:
                            market_probability = snapshot.mid_price
                    except Exception as e:
                        logger.debug(f"Could not fetch snapshot for {market_id}: {e}")

                    market_data = {
                        "market_id": market_id,
                        "title": analysis.get("title", "Unknown"),
                        "category": analysis.get("category", "Unknown"),
                        "description": analysis.get("resolution_text", ""),
                        "market_implied_probability": market_probability,
                        "yes_price": market_probability,
                        "price": market_probability,
                    }

                    # Get HONEST probability estimate
                    estimate = get_honest_estimate(market_data)

                    # If estimate is INVALID -> NO_SIGNAL -> skip proposal
                    if not estimate.valid:
                        skipped_no_signal += 1
                        logger.info(
                            f"NO_SIGNAL: Skipping market '{market_data['title'][:40]}...' - "
                            f"{estimate.reasoning}"
                        )
                        continue

                    # If we still don't have market_probability, skip
                    if market_probability is None:
                        skipped_no_signal += 1
                        logger.info(
                            f"NO_SIGNAL: No market price for '{market_data['title'][:40]}...'"
                        )
                        continue

                    # Calculate edge
                    edge_calc = calculate_edge(estimate, market_probability)

                    if not edge_calc.valid:
                        skipped_no_signal += 1
                        logger.info(
                            f"NO_SIGNAL: Cannot calculate edge for '{market_data['title'][:40]}...' - "
                            f"{edge_calc.reason}"
                        )
                        continue

                    # Build analysis dict with REAL probabilities
                    analysis_dict = {
                        "final_decision": {"outcome": "TRADE"},
                        "market_input": {
                            "market_id": market_data["market_id"],
                            "market_title": market_data["title"],
                            "market_implied_probability": market_probability or 0.0
                        },
                        "probability_estimate": {
                            "probability_midpoint": estimate.probability,
                            "probability_low": estimate.probability_low,
                            "probability_high": estimate.probability_high,
                            "confidence_level": estimate.confidence.value,
                            "model_type": estimate.model_type.value if estimate.model_type else None,
                            "assumption": estimate.assumption,
                            "data_sources": estimate.data_sources,
                        },
                        "market_sanity": {
                            "direction": edge_calc.direction
                        },
                        "edge_calculation": edge_calc.to_dict(),
                    }

                    proposal = generator.generate(analysis_dict)
                    if proposal:
                        generated += 1
                        storage.save_proposal(proposal)

                        review = gate.review(proposal)
                        reviewed += 1
                        storage.save_review(proposal, review)

                        if review.outcome.value == "REVIEW_PASS":
                            passed += 1
                            latest_proposal = {
                                "proposal_id": proposal.proposal_id,
                                "market": proposal.market_question[:50],
                                "review": "PASS"
                            }

                except Exception as e:
                    logger.warning(f"Proposal generation failed: {e}")

            return StepResult(
                name="proposals",
                success=True,
                message=f"Generated {generated} proposals, {passed} passed, {skipped_no_signal} NO_SIGNAL",
                data={
                    "generated": generated,
                    "reviewed": reviewed,
                    "passed": passed,
                    "skipped_no_signal": skipped_no_signal,
                    "latest_proposal": latest_proposal
                }
            )

        except Exception as e:
            logger.error(f"Proposals failed: {e}")
            return StepResult(
                name="proposals",
                success=False,
                message="Proposal generation failed",
                error=str(e),
                data={"generated": 0, "reviewed": 0, "passed": 0}
            )

    def _run_paper_trader(self, proposal_data: Dict[str, Any]) -> StepResult:
        """Run paper trading step."""
        try:
            from paper_trader.position_manager import get_position_summary, check_and_close_resolved
            from paper_trader.intake import get_eligible_proposals
            from paper_trader.simulator import simulate_entry

            # -----------------------------------------------------------------
            # STEP 1: Check and close any resolved positions
            # -----------------------------------------------------------------
            close_result = check_and_close_resolved()

            # -----------------------------------------------------------------
            # STEP 2: Open new paper positions for eligible proposals
            # This is the KEY step that makes paper trading automatic!
            # -----------------------------------------------------------------
            eligible_proposals = get_eligible_proposals()
            new_positions_opened = 0
            skipped = 0

            for proposal in eligible_proposals[:self.MAX_PROPOSALS_PER_RUN]:
                try:
                    position, record = simulate_entry(proposal)
                    if position is not None:
                        new_positions_opened += 1
                        logger.info(
                            f"Paper trade opened: {proposal.market_question[:40]} "
                            f"| {position.side} @ {position.entry_price:.4f}"
                        )
                    else:
                        skipped += 1
                        logger.info(f"Paper trade skipped: {record.reason}")
                except Exception as e:
                    logger.warning(f"Failed to open paper trade: {e}")
                    skipped += 1

            # -----------------------------------------------------------------
            # STEP 3: Get current position summary
            # -----------------------------------------------------------------
            summary = get_position_summary()

            return StepResult(
                name="paper_trader",
                success=True,
                message=f"{summary.get('open', 0)} open, {new_positions_opened} new",
                data={
                    "open_positions": summary.get("open", 0),
                    "closed_positions": summary.get("closed", 0) + summary.get("resolved", 0),
                    "total_pnl": summary.get("total_realized_pnl_eur", 0.0),
                    "closed_this_run": close_result.get("closed", 0),
                    "new_positions_opened": new_positions_opened,
                    "skipped": skipped,
                }
            )

        except Exception as e:
            logger.error(f"Paper trader failed: {e}")
            return StepResult(
                name="paper_trader",
                success=False,
                message="Paper trader failed",
                error=str(e),
                data={"open_positions": 0, "closed_positions": 0, "total_pnl": 0.0}
            )

    def _run_cross_market(self, collector_data: Dict[str, Any]) -> StepResult:
        """
        Run cross-market consistency research (ISOLATED).

        ISOLATION GUARANTEES:
        - This step has NO influence on trading decisions
        - It only reads market data and writes to separate log
        - Findings are informational only
        - If this step fails, trading is NOT affected
        """
        try:
            # Load candidates for research
            today_str = date.today().isoformat()
            candidates_file = self.data_dir / "candidates" / today_str / "candidates.jsonl"

            if not candidates_file.exists():
                return StepResult(
                    name="cross_market",
                    success=True,
                    message="No candidates for research",
                    data={"markets_analyzed": 0, "relations_found": 0, "inconsistencies": 0}
                )

            # Load ALL candidates (research wants many markets)
            candidates = []
            with open(candidates_file, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line:
                        candidates.append(json.loads(line))

            if len(candidates) < 2:
                return StepResult(
                    name="cross_market",
                    success=True,
                    message="Too few candidates for consistency check",
                    data={"markets_analyzed": len(candidates), "relations_found": 0, "inconsistencies": 0}
                )

            # Import cross-market engine (ISOLATED module)
            from cross_market_engine.auto_detector import detect_from_collector_output, get_detection_summary
            from cross_market_engine.consistency_check import check_all_relations
            from cross_market_engine.runner import write_summary_to_log
            from cross_market_engine.arbitrage_signals import generate_signals_from_findings, log_signals

            # Detect relations automatically
            graph, relations = detect_from_collector_output(candidates)

            if not relations:
                return StepResult(
                    name="cross_market",
                    success=True,
                    message=f"Analyzed {len(candidates)} markets, no relations detected",
                    data={"markets_analyzed": len(candidates), "relations_found": 0, "inconsistencies": 0, "arbitrage_signals": 0}
                )

            # Run consistency check
            findings_summary = check_all_relations(graph, relations)

            # Write findings to isolated log
            write_summary_to_log(findings_summary)

            # Generate arbitrage signals from inconsistencies
            arb_signals = generate_signals_from_findings(findings_summary)
            if arb_signals:
                log_signals(arb_signals)

            # Get detection summary
            detection_info = get_detection_summary(graph, relations)

            return StepResult(
                name="cross_market",
                success=True,
                message=f"{findings_summary.inconsistent_count} inconsistencies, {len(arb_signals)} arb signals",
                data={
                    "markets_analyzed": detection_info["markets_analyzed"],
                    "relations_found": len(relations),
                    "topic_groups": detection_info["topic_groups"],
                    "consistent": findings_summary.consistent_count,
                    "inconsistencies": findings_summary.inconsistent_count,
                    "unclear": findings_summary.unclear_count,
                    "run_id": findings_summary.run_id,
                    "arbitrage_signals": len(arb_signals),
                }
            )

        except Exception as e:
            # Cross-market failures should NOT fail the pipeline
            # This is research - trading must continue
            logger.warning(f"Cross-market research failed (non-critical): {e}")
            return StepResult(
                name="cross_market",
                success=True,  # Mark as success to not degrade pipeline
                message=f"Research skipped: {str(e)[:40]}",
                data={"markets_analyzed": 0, "relations_found": 0, "inconsistencies": 0}
            )

    def _run_outcome_tracker(
        self,
        collector_data: Dict[str, Any],
        analyzer_data: Dict[str, Any],
        run_timestamp: str,
    ) -> StepResult:
        """
        Run outcome tracking (ISOLATED).

        ISOLATION GUARANTEES:
        - This step has NO influence on trading decisions
        - It only records facts (predictions + resolutions)
        - If this step fails, trading is NOT affected
        - NO imports from decision_engine or panic_contrarian_engine
        """
        try:
            from core.outcome_tracker import (
                OutcomeStorage,
                ResolutionChecker,
                create_prediction_snapshot,
                generate_event_id,
            )

            storage = OutcomeStorage(self.base_dir)
            run_id = f"scheduler_{generate_event_id()[:8]}"

            # Get analyses from analyzer step
            analyses = analyzer_data.get("analyses", [])

            if not analyses:
                return StepResult(
                    name="outcome_tracker",
                    success=True,
                    message="No analyses to track",
                    data={"predictions_recorded": 0, "resolutions_updated": 0}
                )

            # Load candidate details for market questions
            today_str = date.today().isoformat()
            candidates_file = self.data_dir / "candidates" / today_str / "candidates.jsonl"
            candidates_by_id = {}

            if candidates_file.exists():
                with open(candidates_file, 'r', encoding='utf-8') as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            c = json.loads(line)
                            mid = c.get("market_id") or c.get("condition_id")
                            if mid:
                                candidates_by_id[mid] = c

            # Record predictions
            recorded = 0
            skipped = 0

            for analysis in analyses[:self.MAX_CANDIDATES_TO_ANALYZE]:
                market_id = analysis.get("market_id")
                if not market_id:
                    continue

                candidate = candidates_by_id.get(market_id, {})
                decision = analysis.get("decision", "INSUFFICIENT_DATA")
                confidence = analysis.get("confidence")
                blocking = analysis.get("blocking_criteria", [])

                # Build reasons
                reasons = []
                if blocking:
                    reasons = [f"Blocked: {c}" for c in blocking[:3]]
                elif decision == "TRADE":
                    reasons = ["All criteria passed"]
                else:
                    reasons = ["Analyzed by baseline engine"]

                try:
                    snapshot = create_prediction_snapshot(
                        market_id=market_id,
                        question=candidate.get("title", analysis.get("title", "Unknown")),
                        decision=decision,
                        decision_reasons=reasons,
                        engine="baseline",
                        mode="SHADOW",
                        run_id=run_id,
                        source="scheduler",
                        market_price_yes=candidate.get("probability"),
                        our_estimate_yes=None,
                        estimate_confidence=confidence,
                    )

                    success, _ = storage.write_prediction(snapshot)
                    if success:
                        recorded += 1
                    else:
                        skipped += 1

                except Exception as e:
                    logger.debug(f"Failed to record prediction for {market_id}: {e}")
                    skipped += 1

            # Update resolutions (check up to 10 per run to avoid slowdown)
            checker = ResolutionChecker(storage)
            resolution_result = checker.update_resolutions(max_checks=10)

            return StepResult(
                name="outcome_tracker",
                success=True,
                message=f"{recorded} predictions, {resolution_result.get('new_resolutions', 0)} resolutions",
                data={
                    "predictions_recorded": recorded,
                    "predictions_skipped": skipped,
                    "resolutions_updated": resolution_result.get("new_resolutions", 0),
                    "unresolved_remaining": resolution_result.get("remaining_unresolved", 0),
                }
            )

        except Exception as e:
            # Outcome tracker failures should NOT fail the pipeline
            logger.warning(f"Outcome tracker failed (non-critical): {e}")
            return StepResult(
                name="outcome_tracker",
                success=True,  # Mark as success to not degrade pipeline
                message=f"Tracking skipped: {str(e)[:40]}",
                data={"predictions_recorded": 0, "resolutions_updated": 0}
            )

    def _build_summary(self, result: PipelineResult) -> Dict[str, Any]:
        """Build the pipeline summary."""
        collector_step = next((s for s in result.steps if s.name == "collector"), None)
        analyzer_step = next((s for s in result.steps if s.name == "analyzer"), None)
        proposal_step = next((s for s in result.steps if s.name == "proposals"), None)
        paper_step = next((s for s in result.steps if s.name == "paper_trader"), None)
        cross_market_step = next((s for s in result.steps if s.name == "cross_market"), None)

        return {
            "run_date": date.today().isoformat(),
            "run_time": result.timestamp,
            "state": result.state.value,
            "markets_checked": collector_step.data.get("total_fetched", 0) if collector_step else 0,
            "candidates_found": collector_step.data.get("total_candidates", 0) if collector_step else 0,
            "trade_count": analyzer_step.data.get("trade", 0) if analyzer_step else 0,
            "no_trade_count": analyzer_step.data.get("no_trade", 0) if analyzer_step else 0,
            "insufficient_count": analyzer_step.data.get("insufficient", 0) if analyzer_step else 0,
            "proposals_generated": proposal_step.data.get("generated", 0) if proposal_step else 0,
            "proposals_passed": proposal_step.data.get("passed", 0) if proposal_step else 0,
            "paper_positions_open": paper_step.data.get("open_positions", 0) if paper_step else 0,
            "paper_total_pnl": paper_step.data.get("total_pnl", 0.0) if paper_step else 0.0,
            "paper_new_opened": paper_step.data.get("new_positions_opened", 0) if paper_step else 0,
            "paper_closed_this_run": paper_step.data.get("closed_this_run", 0) if paper_step else 0,
            "latest_trade": analyzer_step.data.get("latest_trade") if analyzer_step else None,
            "latest_proposal": proposal_step.data.get("latest_proposal") if proposal_step else None,
            # Cross-Market Research (ISOLATED)
            "cross_market_relations": cross_market_step.data.get("relations_found", 0) if cross_market_step else 0,
            "cross_market_inconsistencies": cross_market_step.data.get("inconsistencies", 0) if cross_market_step else 0,
            "cross_market_topics": cross_market_step.data.get("topic_groups", 0) if cross_market_step else 0,
        }

    def _write_status_summary(self, result: PipelineResult) -> StepResult:
        """Write status summary to file."""
        try:
            summary_file = self.output_dir / "status_summary.txt"

            # Append-only: add timestamp entry
            entry_lines = [
                f"\n{'='*50}",
                f"Run: {result.timestamp}",
                f"State: {result.state.value}",
                f"{'='*50}",
                f"Markets checked: {result.summary.get('markets_checked', 0)}",
                f"Candidates: {result.summary.get('candidates_found', 0)}",
                f"TRADE: {result.summary.get('trade_count', 0)}",
                f"NO_TRADE: {result.summary.get('no_trade_count', 0)}",
                f"INSUFFICIENT_DATA: {result.summary.get('insufficient_count', 0)}",
                f"Paper positions open: {result.summary.get('paper_positions_open', 0)}",
                f"Paper P&L: {result.summary.get('paper_total_pnl', 0.0):+.2f} EUR",
                f"New paper trades: {result.summary.get('paper_new_opened', 0)}",
            ]

            latest_trade = result.summary.get("latest_trade")
            if latest_trade:
                entry_lines.append("")
                entry_lines.append("=" * 40)
                entry_lines.append("TRADE SIGNAL DETECTED")
                entry_lines.append("=" * 40)
                entry_lines.append(f"Market: {latest_trade.get('title', 'N/A')[:50]}")
                entry_lines.append(f"Category: {latest_trade.get('category', 'N/A')}")
                entry_lines.append(f"End Date: {latest_trade.get('end_date', 'N/A')}")
                entry_lines.append("")
                entry_lines.append("--- Probability Analysis ---")
                entry_lines.append(f"Our Estimate: {latest_trade.get('our_estimate', 0):.1%} ({latest_trade.get('estimate_range', 'N/A')})")
                entry_lines.append(f"Market Price: {latest_trade.get('market_price', 0):.1%}")
                edge = latest_trade.get('edge', 0)
                entry_lines.append(f"Edge: {edge:+.1%}")
                entry_lines.append(f"Direction: {latest_trade.get('direction', 'N/A')}")
                entry_lines.append("")
                entry_lines.append("--- Decision Quality ---")
                entry_lines.append(f"Confidence: {latest_trade.get('confidence', 'N/A')}")
                entry_lines.append(f"Criteria: {latest_trade.get('criteria_passed', 0)}/{latest_trade.get('criteria_total', 0)} passed")
                entry_lines.append(f"Days to Target: {latest_trade.get('days_until_target', 'N/A')}")
                # Risk warnings
                warnings = latest_trade.get('risk_warnings', [])
                if warnings:
                    entry_lines.append("")
                    entry_lines.append("Risk Warnings:")
                    for w in warnings[:3]:
                        entry_lines.append(f"  ! {w[:70]}")
                # Recommendation
                action = latest_trade.get('recommended_action', '')
                if action:
                    entry_lines.append("")
                    entry_lines.append(f"Recommendation: {action[:80]}")

            # Check for errors
            errors = [s for s in result.steps if not s.success]
            if errors:
                entry_lines.append(f"Errors: {len(errors)} step(s) failed")
                for e in errors:
                    entry_lines.append(f"  - {e.name}: {e.error[:50] if e.error else 'Unknown'}")

            entry_lines.append("")

            with open(summary_file, 'a', encoding='utf-8') as f:
                f.write('\n'.join(entry_lines))

            return StepResult(
                name="status_writer",
                success=True,
                message=f"Status written to {summary_file.name}"
            )

        except Exception as e:
            logger.error(f"Status write failed: {e}")
            return StepResult(
                name="status_writer",
                success=False,
                message="Failed to write status",
                error=str(e)
            )

    def _log_to_audit(self, result: PipelineResult):
        """Log pipeline run to audit."""
        try:
            audit_file = self.audit_dir / f"pipeline_{date.today().isoformat()}.jsonl"

            entry = {
                "timestamp": result.timestamp,
                "event": "PIPELINE_RUN",
                "state": result.state.value,
                "summary": result.summary,
                "steps": [
                    {
                        "name": s.name,
                        "success": s.success,
                        "message": s.message,
                        "error": s.error,
                        "data": s.data  # Include step data for filter_results
                    }
                    for s in result.steps
                ]
            }

            with open(audit_file, 'a', encoding='utf-8') as f:
                f.write(json.dumps(entry) + '\n')

        except Exception as e:
            logger.error(f"Audit log failed: {e}")

    def get_status(self) -> Dict[str, Any]:
        """
        Get current system status without running pipeline.

        Returns:
            Status dictionary
        """
        try:
            from paper_trader.position_manager import get_position_summary
            paper_summary = get_position_summary()
        except Exception as e:
            logger.warning(f"Paper trader unavailable: {e}")
            paper_summary = {"open": 0, "total_realized_pnl_eur": 0.0}

        # Load latest from status file
        summary_file = self.output_dir / "status_summary.txt"
        last_run = "Never"
        last_state = "UNKNOWN"

        if summary_file.exists():
            try:
                content = summary_file.read_text(encoding='utf-8')
                lines = content.strip().split('\n')
                for line in reversed(lines):
                    if line.startswith("Run:"):
                        last_run = line.replace("Run:", "").strip()
                        break
                for line in reversed(lines):
                    if line.startswith("State:"):
                        last_state = line.replace("State:", "").strip()
                        break
            except Exception as e:
                logger.debug(f"Could not parse status file: {e}")

        # Count proposals
        proposals_log = self.proposals_dir / "proposals_log.json"
        proposal_count = 0
        if proposals_log.exists():
            try:
                with open(proposals_log, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    proposal_count = len(data.get("proposals", []))
            except Exception as e:
                logger.debug(f"Could not load proposals log: {e}")

        # Load audit for today's stats
        today_stats = {"trade": 0, "no_trade": 0, "insufficient": 0, "markets_checked": 0}
        audit_file = self.audit_dir / f"pipeline_{date.today().isoformat()}.jsonl"
        if audit_file.exists():
            try:
                with open(audit_file, 'r', encoding='utf-8') as f:
                    for line in f:
                        entry = json.loads(line.strip())
                        if entry.get("event") == "PIPELINE_RUN":
                            summary = entry.get("summary", {})
                            today_stats["trade"] += summary.get("trade_count", 0)
                            today_stats["no_trade"] += summary.get("no_trade_count", 0)
                            today_stats["insufficient"] += summary.get("insufficient_count", 0)
                            today_stats["markets_checked"] += summary.get("markets_checked", 0)
            except Exception as e:
                logger.debug(f"Could not load audit file: {e}")

        return {
            "last_run": last_run,
            "last_state": last_state,
            "today": today_stats,
            "paper_positions_open": paper_summary.get("open", 0),
            "paper_total_pnl": paper_summary.get("total_realized_pnl_eur", 0.0),
            "total_proposals": proposal_count,
            "logs_path": str(self.logs_dir)
        }

    def get_latest_proposal(self) -> Optional[Dict[str, Any]]:
        """
        Get the latest proposal with review result.

        Returns:
            Proposal dict or None
        """
        proposals_log = self.proposals_dir / "proposals_log.json"

        if not proposals_log.exists():
            return None

        try:
            with open(proposals_log, 'r', encoding='utf-8') as f:
                data = json.load(f)
                proposals = data.get("proposals", [])
                if not proposals:
                    return None

                # Get latest
                proposals.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
                latest = proposals[0]

                return {
                    "proposal_id": latest.get("proposal_id"),
                    "timestamp": latest.get("timestamp"),
                    "market": latest.get("market_question", "Unknown")[:60],
                    "decision": latest.get("decision"),
                    "edge": latest.get("edge", 0),
                    "confidence": latest.get("confidence_level")
                }

        except Exception as e:
            logger.debug(f"Could not load latest proposal: {e}")
            return None

    def get_paper_summary(self) -> Dict[str, Any]:
        """
        Get paper trading summary.

        Returns:
            Summary dict with positions and recent actions
        """
        try:
            from paper_trader.position_manager import get_position_summary, get_open_positions
            from paper_trader.logger import get_paper_logger

            summary = get_position_summary()
            open_positions = get_open_positions()

            # Get recent trades
            paper_logger = get_paper_logger()
            recent_trades = []
            try:
                all_trades = paper_logger.read_all_trades()
                all_trades.sort(key=lambda x: x.timestamp, reverse=True)
                recent_trades = [
                    {
                        "timestamp": t.timestamp,
                        "action": t.action,
                        "market_id": t.market_id[:20],
                        "pnl": t.pnl_eur
                    }
                    for t in all_trades[:5]
                ]
            except Exception as e:
                logger.debug(f"Could not read trade history: {e}")

            return {
                "open_positions": len(open_positions),
                "total_positions": summary.get("total_positions", 0),
                "realized_pnl": summary.get("total_realized_pnl_eur", 0.0),
                "open_cost_basis": summary.get("open_cost_basis_eur", 0.0),
                "positions": [
                    {
                        "id": p.position_id[:12],
                        "market": p.market_question[:40] if p.market_question else "Unknown",
                        "side": p.side,
                        "entry_price": p.entry_price
                    }
                    for p in open_positions[:5]
                ],
                "recent_actions": recent_trades
            }

        except Exception as e:
            logger.error(f"Paper summary failed: {e}")
            return {
                "open_positions": 0,
                "total_positions": 0,
                "realized_pnl": 0.0,
                "positions": [],
                "recent_actions": []
            }

    def get_category_stats(self) -> Dict[str, Any]:
        """
        Get market category breakdown.

        Returns:
            Stats per category (EU, Weather, Corporate, Court)
        """
        stats = {
            "eu_regulation": 0,
            "weather_event": 0,
            "corporate_event": 0,
            "court_ruling": 0,
            "political_event": 0,
            "crypto_event": 0,
            "finance_event": 0,
            "general_event": 0,
            "generic": 0,
            "total_candidates": 0,
        }

        # Load today's candidates
        today_str = date.today().isoformat()
        candidates_file = self.data_dir / "candidates" / today_str / "candidates.jsonl"

        if candidates_file.exists():
            try:
                with open(candidates_file, 'r', encoding='utf-8') as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            candidate = json.loads(line)
                            stats["total_candidates"] += 1

                            # Get category from field first, fallback to collector_notes
                            category = candidate.get("category")
                            if not category:
                                # Infer category from collector_notes
                                notes = candidate.get("collector_notes", [])
                                if "corporate_event_market" in notes:
                                    category = "CORPORATE_EVENT"
                                elif "court_ruling_market" in notes:
                                    category = "COURT_RULING"
                                elif "weather_event_market" in notes:
                                    category = "WEATHER_EVENT"
                                elif "political_event_market" in notes:
                                    category = "POLITICAL_EVENT"
                                elif "crypto_event_market" in notes:
                                    category = "CRYPTO_EVENT"
                                elif "finance_event_market" in notes:
                                    category = "FINANCE_EVENT"
                                elif "general_event_market" in notes:
                                    category = "GENERAL_EVENT"
                                else:
                                    category = "GENERIC"

                            category = category.upper()

                            if category == "EU_REGULATION":
                                stats["eu_regulation"] += 1
                            elif category == "WEATHER_EVENT":
                                stats["weather_event"] += 1
                            elif category == "CORPORATE_EVENT":
                                stats["corporate_event"] += 1
                            elif category == "COURT_RULING":
                                stats["court_ruling"] += 1
                            elif category == "POLITICAL_EVENT":
                                stats["political_event"] += 1
                            elif category == "CRYPTO_EVENT":
                                stats["crypto_event"] += 1
                            elif category == "FINANCE_EVENT":
                                stats["finance_event"] += 1
                            elif category == "GENERAL_EVENT":
                                stats["general_event"] += 1
                            else:
                                stats["generic"] += 1
            except Exception as e:
                logger.error(f"Failed to load category stats: {e}")

        return stats

    def get_filter_stats(self) -> Dict[str, Any]:
        """
        Get filter statistics from collector.

        Returns:
            Stats about why markets were included/excluded
        """
        stats = {
            "included": 0,
            "included_corporate": 0,
            "included_court": 0,
            "included_weather": 0,
            "excluded_no_eu_match": 0,
            "excluded_no_ai_match": 0,
            "excluded_no_deadline": 0,
            "excluded_price_market": 0,
            "excluded_opinion_market": 0,
            "excluded_incomplete": 0,
            "total_fetched": 0,
        }

        # Try to load from audit log - get the LATEST entry only
        audit_file = self.audit_dir / f"pipeline_{date.today().isoformat()}.jsonl"
        if audit_file.exists():
            try:
                latest_entry = None
                with open(audit_file, 'r', encoding='utf-8') as f:
                    for line in f:
                        entry = json.loads(line.strip())
                        if entry.get("event") == "PIPELINE_RUN":
                            latest_entry = entry

                if latest_entry:
                    steps = latest_entry.get("steps", [])
                    for step in steps:
                        if step.get("name") == "collector":
                            step_data = step.get("data", {})
                            stats["total_fetched"] = step_data.get("total_fetched", 0)
                            filter_results = step_data.get("filter_results", {})
                            for key, value in filter_results.items():
                                if key in stats:
                                    stats[key] = value
            except Exception as e:
                logger.error(f"Failed to load filter stats: {e}")

        return stats

    def get_candidates(self) -> List[Dict[str, Any]]:
        """
        Get current candidates list with details.

        Returns:
            List of candidate dictionaries
        """
        candidates = []

        today_str = date.today().isoformat()
        candidates_file = self.data_dir / "candidates" / today_str / "candidates.jsonl"

        if candidates_file.exists():
            try:
                with open(candidates_file, 'r', encoding='utf-8') as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            candidate = json.loads(line)

                            # Get category from field first, fallback to collector_notes
                            category = candidate.get("category")
                            if not category:
                                notes = candidate.get("collector_notes", [])
                                if "corporate_event_market" in notes:
                                    category = "CORPORATE_EVENT"
                                elif "court_ruling_market" in notes:
                                    category = "COURT_RULING"
                                elif "weather_event_market" in notes:
                                    category = "WEATHER_EVENT"
                                elif "political_event_market" in notes:
                                    category = "POLITICAL_EVENT"
                                elif "crypto_event_market" in notes:
                                    category = "CRYPTO_EVENT"
                                elif "finance_event_market" in notes:
                                    category = "FINANCE_EVENT"
                                elif "general_event_market" in notes:
                                    category = "GENERAL_EVENT"
                                else:
                                    category = "GENERIC"

                            candidates.append({
                                "market_id": candidate.get("market_id", "?")[:16],
                                "title": candidate.get("title", "Unknown")[:60],
                                "category": category,
                                "end_date": candidate.get("end_date", "N/A")[:10],
                                "matched_keywords": candidate.get("matched_keywords", [])[:3],
                            })
            except Exception as e:
                logger.error(f"Failed to load candidates: {e}")

        return candidates[:20]  # Limit to 20 for display

    def get_audit_log(self, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Get recent audit log entries.

        Args:
            limit: Maximum entries to return

        Returns:
            List of audit log entries
        """
        entries = []

        # Check last 3 days of audit files
        for days_ago in range(3):
            check_date = date.today()
            if days_ago > 0:
                from datetime import timedelta
                check_date = date.today() - timedelta(days=days_ago)

            audit_file = self.audit_dir / f"pipeline_{check_date.isoformat()}.jsonl"

            if audit_file.exists():
                try:
                    with open(audit_file, 'r', encoding='utf-8') as f:
                        for line in f:
                            entry = json.loads(line.strip())
                            if entry.get("event") == "PIPELINE_RUN":
                                summary = entry.get("summary", {})
                                entries.append({
                                    "timestamp": entry.get("timestamp", "?")[:19],
                                    "state": entry.get("state", "?"),
                                    "markets_checked": summary.get("markets_checked", 0),
                                    "candidates": summary.get("candidates_found", 0),
                                    "trade": summary.get("trade_count", 0),
                                    "no_trade": summary.get("no_trade_count", 0),
                                    "insufficient": summary.get("insufficient_count", 0),
                                })
                except Exception as e:
                    logger.error(f"Failed to load audit log: {e}")

        # Sort by timestamp descending
        entries.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        return entries[:limit]


# Module-level convenience functions
_orchestrator: Optional[Orchestrator] = None


def get_orchestrator() -> Orchestrator:
    """Get the global orchestrator instance."""
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = Orchestrator()
    return _orchestrator


def run_pipeline() -> PipelineResult:
    """Run the full pipeline."""
    return get_orchestrator().run_pipeline()


def get_status() -> Dict[str, Any]:
    """Get current status."""
    return get_orchestrator().get_status()


def get_category_stats() -> Dict[str, Any]:
    """Get category breakdown statistics."""
    return get_orchestrator().get_category_stats()


def get_filter_stats() -> Dict[str, Any]:
    """Get filter statistics."""
    return get_orchestrator().get_filter_stats()


def get_candidates() -> List[Dict[str, Any]]:
    """Get current candidates list."""
    return get_orchestrator().get_candidates()


def get_audit_log(limit: int = 10) -> List[Dict[str, Any]]:
    """Get recent audit log entries."""
    return get_orchestrator().get_audit_log(limit)


def get_latest_proposal() -> Optional[Dict[str, Any]]:
    """Get latest proposal."""
    return get_orchestrator().get_latest_proposal()


def get_paper_summary() -> Dict[str, Any]:
    """Get paper trading summary."""
    return get_orchestrator().get_paper_summary()
