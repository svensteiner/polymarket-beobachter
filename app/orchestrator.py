# =============================================================================
# WEATHER OBSERVER - PIPELINE ORCHESTRATOR
# =============================================================================
#
# WEATHER-ONLY OBSERVATION + PAPER TRADING SYSTEM
#
# This module orchestrates the weather observation pipeline:
# 1. Collector: Fetch weather markets from Polymarket
# 2. Weather Observer: Analyze markets and detect edge
# 3. Proposal Generator: Convert edge to trading proposals
# 4. Paper Trader: Simulate trades (PAPER ONLY)
# 5. Outcome Tracker: Record observations for calibration
# 6. Status: Write summary
#
# PAPER TRADING ONLY:
# NO real orders are placed. NO real money is at risk.
#
# =============================================================================

import json
import logging
import os
import shutil
import time
import uuid
from datetime import datetime, date, timedelta, timezone
from pathlib import Path
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
from enum import Enum

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
    Weather Observer Pipeline Orchestrator.

    OBSERVER + PAPER TRADING:
    - Read-only observation and analysis
    - Paper trading simulation (no real execution)
    - Append-only logging for calibration
    """

    def __init__(self, base_dir: Optional[Path] = None):
        self.base_dir = base_dir or Path(__file__).parent.parent
        self.output_dir = self.base_dir / "output"
        self.logs_dir = self.base_dir / "logs"
        self.data_dir = self.base_dir / "data"

        # Ensure directories exist
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        (self.data_dir / "forecasts").mkdir(parents=True, exist_ok=True)
        (self.data_dir / "resolutions").mkdir(parents=True, exist_ok=True)

    def run_pipeline(self) -> PipelineResult:
        """
        Execute the weather observer pipeline.

        Steps:
        1. Collector: Fetch weather markets
        2. Weather Observer: Analyze and detect edge
        3. Proposal Generator: Convert edge to proposals
        4. Paper Trader: Simulate trades
        5. Outcome Tracker: Record for calibration
        6. Write status summary

        Returns:
            PipelineResult with state and step details
        """
        # Track pipeline duration
        pipeline_start = time.perf_counter()

        # Generate correlation ID for this pipeline run
        run_id = f"RUN-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
        logger.info(f"=== Pipeline START === run_id={run_id}")

        result = PipelineResult(
            state=RunState.OK,
            timestamp=datetime.now().isoformat()
        )

        # Step 1: Collector
        print("[1/6] Collector: Maerkte abrufen ...", end="", flush=True)
        collector_result = self._run_collector()
        result.add_step(collector_result)
        print(f" {'OK' if collector_result.success else 'FAIL'} ({collector_result.message})")

        # Step 1b: Cleanup alte Collector-Daten (>7 Tage)
        try:
            cleaned = self._cleanup_old_collector_data(max_age_days=7)
            if cleaned:
                logger.info(f"Collector cleanup: {cleaned} alte Verzeichnisse geloescht")
        except Exception as e:
            logger.warning(f"Collector cleanup fehlgeschlagen: {e}")

        # Step 2: Weather Observer
        print("[2/6] Weather Observer: Analyse + Edge ...", end="", flush=True)
        weather_result = self._run_weather_observer()
        result.add_step(weather_result)
        print(f" {'OK' if weather_result.success else 'FAIL'} ({weather_result.message})")

        # Step 2b: Market Condition Assessment (READ-ONLY)
        edge_obs_count = weather_result.data.get("edge_observations", 0)
        market_condition = self._assess_market_condition(edge_obs_count)

        # Step 3: Proposal Generator
        print("[3/6] Proposals: Edge -> Signale ...", end="", flush=True)
        proposal_result = self._run_proposal_generator(weather_result.data)
        result.add_step(proposal_result)
        print(f" {'OK' if proposal_result.success else 'FAIL'} ({proposal_result.message})")

        # Step 4: Paper Trader (mit DrawdownProtector-Snapshot)
        print("[4/6] Paper Trader: Trades simulieren ...", end="", flush=True)
        self._record_equity_snapshot("pre_paper_trader")
        paper_result = self._run_paper_trader()
        result.add_step(paper_result)
        print(f" {'OK' if paper_result.success else 'FAIL'} ({paper_result.message})")

        # Step 5: Outcome Tracker
        print("[5/6] Outcome Tracker: Kalibrierung ...", end="", flush=True)
        outcome_result = self._run_outcome_tracker(weather_result.data)
        result.add_step(outcome_result)
        print(f" {'OK' if outcome_result.success else 'FAIL'} ({outcome_result.message})")

        # Step 5b: Outcome Analyser (nach jedem Run aktualisieren)
        self._run_outcome_analyser()

        # Build summary with pipeline duration
        duration_seconds = round(time.perf_counter() - pipeline_start, 2)
        result.summary = self._build_summary(result)
        result.summary["run_id"] = run_id
        result.summary["duration_seconds"] = duration_seconds

        # Step 6: Write status
        print("[6/6] Status schreiben ...", end="", flush=True)
        status_result = self._write_status_summary(result)
        result.add_step(status_result)
        print(f" {'OK' if status_result.success else 'FAIL'}")

        # Log to audit (includes run_id via summary)
        self._log_to_audit(result)

        # Cleanup old audit logs (>90 days)
        try:
            self._cleanup_old_audit_logs(max_age_days=90)
        except Exception as e:
            logger.warning(f"Audit-Log cleanup fehlgeschlagen: {e}")

        logger.info(f"=== Pipeline END === run_id={run_id} state={result.state.value}")

        return result

    def _record_equity_snapshot(self, reason: str = "pipeline_run") -> None:
        """Speichere aktuellen Equity-Wert fuer DrawdownProtector."""
        try:
            from paper_trader.capital_manager import get_capital_manager
            from paper_trader.drawdown_protector import record_equity_snapshot
            state = get_capital_manager().get_state()
            equity = state.available_capital_eur + state.allocated_capital_eur
            record_equity_snapshot(equity, reason)
        except Exception as e:
            logger.debug(f"Equity-Snapshot fehlgeschlagen: {e}")

    def _run_collector(self) -> StepResult:
        """Fetch weather markets from Polymarket."""
        try:
            from collector.collector import Collector

            collector = Collector(
                output_dir=str(self.data_dir / "collector"),
                max_markets=500
            )
            stats = collector.run(dry_run=False)

            return StepResult(
                name="collector",
                success=True,
                message=f"Fetched {stats.total_fetched} markets, {stats.total_candidates} weather candidates",
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

    def _cleanup_old_collector_data(self, max_age_days: int = 7) -> int:
        """Loesche Collector-Rohdaten die aelter als max_age_days sind.

        Bereinigt raw/, normalized/ und candidates/ Unterverzeichnisse.
        Gibt die Anzahl geloeschter Verzeichnisse zurueck.
        """
        collector_dir = self.data_dir / "collector"
        cutoff = datetime.now() - timedelta(days=max_age_days)
        deleted = 0

        for subdir_name in ("raw", "normalized", "candidates"):
            subdir = collector_dir / subdir_name
            if not subdir.is_dir():
                continue

            for dirname in os.listdir(subdir):
                try:
                    dir_date = datetime.strptime(dirname, "%Y-%m-%d")
                    if dir_date < cutoff:
                        dir_path = subdir / dirname
                        shutil.rmtree(str(dir_path))
                        deleted += 1
                        logger.info("Collector-Daten geloescht: %s/%s", subdir_name, dirname)
                except (ValueError, OSError):
                    continue

        return deleted

    def _run_weather_observer(self) -> StepResult:
        """Run the weather observation engine."""
        try:
            from core.weather_engine import create_engine
            from core.weather_market_filter import WeatherMarket, WeatherMarketFilter
            from collector.client import PolymarketClient
            import json
            import yaml
            from datetime import datetime

            # Load config and create filter
            config_path = self.data_dir.parent / "config" / "weather.yaml"
            with open(config_path) as f:
                weather_config = yaml.safe_load(f)
            weather_filter = WeatherMarketFilter(weather_config)

            # Load collected weather candidates (stored in date-based path)
            from datetime import date
            today = date.today().isoformat()
            candidates_root = self.data_dir / "collector" / "candidates"
            candidates_file = candidates_root / today / "candidates.jsonl"
            raw_candidates = []

            # Fallback to most recent non-empty candidates file if today's is missing/empty
            if not candidates_file.exists() or candidates_file.stat().st_size == 0:
                if candidates_root.exists():
                    for day_dir in sorted(candidates_root.iterdir(), reverse=True):
                        fallback = day_dir / "candidates.jsonl"
                        if fallback.exists() and fallback.stat().st_size > 0:
                            candidates_file = fallback
                            logger.info(f"Using fallback candidates file: {fallback}")
                            break

            # Step 1: Load raw candidate data
            if candidates_file.exists() and candidates_file.stat().st_size > 0:
                with open(candidates_file, 'r', encoding='utf-8') as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            try:
                                data = json.loads(line)
                                raw_candidates.append(data)
                            except Exception as e:
                                logger.debug(f"Skipping invalid candidate: {e}")

            # Step 2: Fetch real market odds from Polymarket API
            market_ids = [c.get("market_id", "") for c in raw_candidates if c.get("market_id")]
            real_prices = {}
            if market_ids:
                try:
                    client = PolymarketClient(timeout=15)
                    real_prices = client.fetch_market_prices(market_ids)
                    logger.info(f"Fetched real odds for {len(real_prices)}/{len(market_ids)} markets")
                except Exception as e:
                    logger.warning(f"Failed to fetch real market prices: {e}")

            # Step 3: Convert to WeatherMarket with real odds
            weather_markets = []
            for data in raw_candidates:
                try:
                    market_id = data.get("market_id", "")

                    # Get real odds and liquidity if available
                    odds_yes = 0.05  # Default fallback
                    liquidity_usd = 100.0  # Default fallback

                    if market_id in real_prices:
                        price_data = real_prices[market_id]
                        # Parse outcomePrices (format: '["0.95", "0.05"]' - [YES, NO])
                        outcome_prices = price_data.get("outcomePrices")
                        if outcome_prices:
                            try:
                                prices_list = json.loads(outcome_prices)
                                if len(prices_list) >= 1:
                                    odds_yes = float(prices_list[0])
                            except Exception:
                                pass
                        # Get liquidity
                        liq = price_data.get("liquidity")
                        if liq:
                            try:
                                liquidity_usd = float(liq)
                            except Exception:
                                pass

                    market = WeatherMarket(
                        market_id=market_id,
                        question=data.get("title", ""),
                        resolution_text=data.get("resolution_text", ""),
                        description=data.get("description", ""),
                        category="WEATHER",
                        is_binary=True,
                        liquidity_usd=liquidity_usd,
                        odds_yes=odds_yes,
                        resolution_time=datetime.fromisoformat(data["end_date"]) if data.get("end_date") else datetime.now(),
                    )

                    # Run through filter to populate detected_city and detected_threshold
                    filter_result = weather_filter.filter_market(market)
                    if filter_result.passed and filter_result.market:
                        weather_markets.append(filter_result.market)
                    else:
                        logger.debug(f"Market {market.market_id} filtered out: {filter_result.rejection_reasons}")
                except Exception as e:
                    logger.debug(f"Skipping invalid candidate: {e}")

            logger.info(f"Loaded {len(weather_markets)} weather candidates for observation")

            # Create market fetcher from loaded candidates
            def market_fetcher():
                return weather_markets

            engine = create_engine(market_fetcher=market_fetcher)
            result = engine.run()

            return StepResult(
                name="weather_observer",
                success=True,
                message=f"Observed {result.markets_processed} markets, {len(result.edge_observations)} with edge",
                data={
                    "observations_total": len(result.observations),
                    "edge_observations": len(result.edge_observations),
                    "edge_observations_list": result.edge_observations,
                    "markets_processed": result.markets_processed,
                    "markets_filtered": result.markets_filtered,
                }
            )
        except Exception as e:
            logger.error(f"Weather observer failed: {e}")
            return StepResult(
                name="weather_observer",
                success=False,
                message="Weather observer failed",
                error=str(e)
            )

    def _run_proposal_generator(self, weather_data: Dict[str, Any]) -> StepResult:
        """Convert weather observations with edge to proposals.

        Uses edge_observations_list from the weather observer step directly,
        avoiding a redundant second engine run.
        """
        try:
            from proposals.signal_adapter import weather_observation_to_proposal
            from proposals.storage import get_storage

            # Use edge observations passed from weather observer step
            edge_observations = weather_data.get("edge_observations_list", [])
            if not edge_observations:
                return StepResult(
                    name="proposal_generator",
                    success=True,
                    message="No edge observations to convert",
                    data={"proposals_generated": 0}
                )

            # Convert edge observations to proposals
            proposals_generated = 0
            storage = get_storage()

            for observation in edge_observations:
                proposal = weather_observation_to_proposal(observation)
                if proposal is not None:
                    storage.save_proposal(proposal)
                    proposals_generated += 1
                    logger.info(f"Generated proposal for market {observation.market_id}")

            return StepResult(
                name="proposal_generator",
                success=True,
                message=f"Generated {proposals_generated} proposals",
                data={
                    "proposals_generated": proposals_generated,
                    "edge_observations_processed": len(edge_observations)
                }
            )

        except Exception as e:
            logger.error(f"Proposal generator failed: {e}")
            return StepResult(
                name="proposal_generator",
                success=False,
                message="Proposal generator failed",
                error=str(e)
            )

    def _run_paper_trader(self) -> StepResult:
        """
        Run paper trading cycle.

        PAPER TRADING ONLY:
        - NO real orders are placed
        - NO real money is at risk
        """
        try:
            from paper_trader.intake import get_eligible_proposals
            from paper_trader.simulator import simulate_entry
            from paper_trader.position_manager import check_and_close_resolved, check_mid_trade_exits
            from paper_trader.averaging_down import check_averaging_down
            from paper_trader.edge_reversal import check_edge_reversal_exits

            # Step 1: Check mid-trade exits FIRST (take-profit / stop-loss)
            mid_trade = check_mid_trade_exits()
            if mid_trade["take_profit"] or mid_trade["stop_loss"]:
                logger.info(
                    f"Mid-trade exits: {mid_trade['take_profit']} TP, "
                    f"{mid_trade['stop_loss']} SL, P&L: {mid_trade['pnl_eur']:+.2f} EUR"
                )

            # Step 2: Check edge reversal exits (forecast turned against us)
            edge_reversal = check_edge_reversal_exits()
            if edge_reversal["exited"]:
                logger.info(
                    f"Edge reversal exits: {edge_reversal['exited']} positions, "
                    f"P&L: {edge_reversal['pnl_eur']:+.2f} EUR"
                )

            # Step 3: Check averaging-down opportunities
            avg_down = check_averaging_down()
            if avg_down["addons"]:
                logger.info(
                    f"Averaging down: {avg_down['addons']} add-ons, "
                    f"cost: {avg_down['cost_eur']:.2f} EUR"
                )

            # Step 4: Get eligible proposals for new entries
            eligible = get_eligible_proposals()
            logger.info(f"Found {len(eligible)} eligible proposals for paper trading")

            # Simulate entries
            entered = 0
            skipped = 0

            for proposal in eligible:
                position, record = simulate_entry(proposal)
                if position is not None:
                    entered += 1
                    logger.info(f"Paper ENTRY: {proposal.market_id[:30]}... | {position.side} @ {position.entry_price:.4f}")
                else:
                    skipped += 1

            # Step 5: Check and close resolved positions
            close_summary = check_and_close_resolved()

            return StepResult(
                name="paper_trader",
                success=True,
                message=(
                    f"Entered: {entered} | Addons: {avg_down['addons']} | "
                    f"Edge-Rev: {edge_reversal['exited']} | "
                    f"Closed: {close_summary['closed']} | P&L: {close_summary['total_pnl_eur']:+.2f} EUR"
                ),
                data={
                    "proposals_eligible": len(eligible),
                    "positions_entered": entered,
                    "positions_skipped": skipped,
                    "addon_entries": avg_down["addons"],
                    "addon_cost_eur": avg_down["cost_eur"],
                    "mid_trade_tp": mid_trade["take_profit"],
                    "mid_trade_sl": mid_trade["stop_loss"],
                    "mid_trade_pnl": mid_trade["pnl_eur"],
                    "edge_reversal_exited": edge_reversal["exited"],
                    "edge_reversal_pnl": edge_reversal["pnl_eur"],
                    "positions_checked": close_summary['checked'],
                    "positions_closed": close_summary['closed'],
                    "positions_still_open": close_summary['still_open'],
                    "total_pnl_eur": close_summary['total_pnl_eur'],
                }
            )

        except Exception as e:
            logger.error(f"Paper trader failed: {e}")
            return StepResult(
                name="paper_trader",
                success=False,
                message="Paper trader failed",
                error=str(e)
            )

    def _run_outcome_tracker(self, weather_data: Dict[str, Any]) -> StepResult:
        """Record observations for calibration tracking."""
        try:
            from core.outcome_tracker import (
                OutcomeStorage,
                ResolutionChecker,
                PredictionSnapshot,
                EngineContext,
            )
            import uuid

            storage = OutcomeStorage(self.base_dir)

            # Record edge observations as predictions for calibration
            predictions_recorded = 0
            edge_observations = weather_data.get("edge_observations_list", [])
            run_id = uuid.uuid4().hex[:12]

            for obs in edge_observations:
                try:
                    snapshot = PredictionSnapshot(
                        schema_version=1,
                        event_id=f"EVT-{obs.market_id}-{datetime.now().strftime('%Y%m%d%H%M')}",
                        timestamp_utc=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S") + "Z",
                        market_id=obs.market_id,
                        question=obs.market_question,
                        outcomes=["YES", "NO"],
                        market_price_yes=obs.implied_probability,
                        market_price_no=1.0 - obs.implied_probability if obs.implied_probability else None,
                        our_estimate_yes=obs.model_probability,
                        estimate_confidence=obs.confidence_level if hasattr(obs, 'confidence_level') else None,
                        decision="TRADE" if obs.edge and abs(obs.edge) >= 0.12 else "NO_TRADE",
                        decision_reasons=[f"Edge: {obs.edge:+.2%}" if obs.edge else "No edge"],
                        engine_context=EngineContext(
                            engine="weather_observer",
                            mode="PAPER",
                            run_id=run_id,
                        ),
                        source="scheduler",
                    )
                    success, _ = storage.write_prediction(snapshot)
                    if success:
                        predictions_recorded += 1
                except Exception as e:
                    logger.debug(f"Could not record prediction for {obs.market_id}: {e}")

            # Update resolutions for past observations
            checker = ResolutionChecker(storage)
            resolution_result = checker.update_resolutions(max_checks=50)

            return StepResult(
                name="outcome_tracker",
                success=True,
                message=f"{predictions_recorded} predictions recorded, {resolution_result.get('new_resolutions', 0)} resolutions updated",
                data={
                    "observations_recorded": predictions_recorded,
                    "resolutions_updated": resolution_result.get("new_resolutions", 0),
                    "unresolved_remaining": resolution_result.get("remaining_unresolved", 0),
                }
            )
        except Exception as e:
            logger.warning(f"Outcome tracker failed: {e}")
            return StepResult(
                name="outcome_tracker",
                success=True,  # Non-critical
                message=f"Tracking skipped: {str(e)[:40]}",
                data={"observations_recorded": 0, "resolutions_updated": 0}
            )

    def _assess_market_condition(self, edge_observations_count: int = 0) -> dict:
        """Bewerte Marktbedingungen (READ-ONLY). Gibt Condition-Dict zurueck."""
        try:
            from core.market_condition import assess_market_condition
            state = assess_market_condition(edge_observations_count)
            condition = state.get("condition", "WATCH")
            logger.info(f"Market Condition: {condition} ({edge_observations_count} edge obs)")
            return state
        except Exception as e:
            logger.debug(f"Market Condition Assessment fehlgeschlagen: {e}")
            return {"condition": "WATCH"}

    def _run_outcome_analyser(self) -> None:
        """Aktualisiere Performance-Report nach jedem Pipeline-Run (non-blocking)."""
        try:
            from analytics.outcome_analyser import run_analysis
            run_analysis()
            logger.info("Outcome-Analyser: Performance-Report aktualisiert")
        except Exception as e:
            logger.debug(f"Outcome-Analyser fehlgeschlagen (unkritisch): {e}")

    def _get_drawdown_summary(self) -> Dict[str, Any]:
        """Hole aktuellen Drawdown-Status fuer Summary."""
        try:
            from paper_trader.drawdown_protector import get_drawdown_status
            return get_drawdown_status()
        except Exception as e:
            logger.debug(f"Drawdown-Status nicht verfuegbar: {e}")
            return {}

    def _build_summary(self, result: PipelineResult) -> Dict[str, Any]:
        """Build the pipeline summary."""
        collector_step = next((s for s in result.steps if s.name == "collector"), None)
        weather_step = next((s for s in result.steps if s.name == "weather_observer"), None)
        proposal_step = next((s for s in result.steps if s.name == "proposal_generator"), None)
        paper_step = next((s for s in result.steps if s.name == "paper_trader"), None)
        outcome_step = next((s for s in result.steps if s.name == "outcome_tracker"), None)

        dd = self._get_drawdown_summary()
        from core.market_condition import load_last_condition
        mc = load_last_condition()
        return {
            "run_date": date.today().isoformat(),
            "run_time": result.timestamp,
            "state": result.state.value,
            "markets_fetched": collector_step.data.get("total_fetched", 0) if collector_step else 0,
            "weather_candidates": collector_step.data.get("total_candidates", 0) if collector_step else 0,
            "observations_total": weather_step.data.get("observations_total", 0) if weather_step else 0,
            "edge_observations": weather_step.data.get("edge_observations", 0) if weather_step else 0,
            "proposals_generated": proposal_step.data.get("proposals_generated", 0) if proposal_step else 0,
            "paper_positions_entered": paper_step.data.get("positions_entered", 0) if paper_step else 0,
            "paper_positions_closed": paper_step.data.get("positions_closed", 0) if paper_step else 0,
            "paper_pnl_eur": paper_step.data.get("total_pnl_eur", 0) if paper_step else 0,
            "resolutions_updated": outcome_step.data.get("resolutions_updated", 0) if outcome_step else 0,
            "drawdown_pct": dd.get("current_dd_pct", 0.0),
            "drawdown_recovery_mode": dd.get("is_recovery_mode", False),
            "drawdown_size_factor": dd.get("size_factor", 1.0),
            "market_condition": mc.get("condition", "WATCH"),
        }

    @staticmethod
    def _rotate_if_needed(filepath, max_size_mb=5):
        """Rotate log file if it exceeds max_size_mb."""
        try:
            filepath = str(filepath)
            if os.path.exists(filepath) and os.path.getsize(filepath) > max_size_mb * 1024 * 1024:
                date_str = datetime.now().strftime("%Y%m%d_%H%M%S")
                base, ext = os.path.splitext(filepath)
                rotated = f"{base}_{date_str}{ext}"
                os.rename(filepath, rotated)
                logger.info(f"Log rotiert: {filepath} -> {rotated}")
        except OSError as e:
            logger.warning(f"Log-Rotation fehlgeschlagen fuer {filepath}: {e}")

    def _write_status_summary(self, result: PipelineResult) -> StepResult:
        """Write status summary to file."""
        try:
            summary_file = self.output_dir / "status_summary.txt"

            # Rotate if file exceeds 5 MB
            self._rotate_if_needed(summary_file, max_size_mb=5)

            entry_lines = [
                f"\n{'='*50}",
                f"Run: {result.timestamp}",
                f"Run-ID: {result.summary.get('run_id', 'N/A')}",
                f"State: {result.state.value}",
                f"{'='*50}",
                f"Markets fetched:      {result.summary.get('markets_fetched', 0)}",
                f"Weather candidates:   {result.summary.get('weather_candidates', 0)}",
                f"Observations:         {result.summary.get('observations_total', 0)}",
                f"Edge detected:        {result.summary.get('edge_observations', 0)}",
                f"Proposals generated:  {result.summary.get('proposals_generated', 0)}",
                f"Paper positions:      {result.summary.get('paper_positions_entered', 0)} entered, {result.summary.get('paper_positions_closed', 0)} closed",
                f"Paper P&L (EUR):      {result.summary.get('paper_pnl_eur', 0):+.2f}",
                f"Resolutions updated:  {result.summary.get('resolutions_updated', 0)}",
                f"Drawdown:             {result.summary.get('drawdown_pct', 0.0):.1f}% "
                f"{'[RECOVERY MODE]' if result.summary.get('drawdown_recovery_mode') else '[OK]'}",
                f"Market Condition:     {result.summary.get('market_condition', 'WATCH')}",
            ]

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
            audit_dir = self.logs_dir / "audit"
            audit_dir.mkdir(parents=True, exist_ok=True)
            audit_file = audit_dir / f"observer_{date.today().isoformat()}.jsonl"

            entry = {
                "timestamp": result.timestamp,
                "event": "OBSERVER_RUN",
                "run_id": result.summary.get("run_id"),
                "state": result.state.value,
                "summary": result.summary,
                "steps": [
                    {
                        "name": s.name,
                        "success": s.success,
                        "message": s.message,
                        "error": s.error,
                    }
                    for s in result.steps
                ]
            }

            with open(audit_file, 'a', encoding='utf-8') as f:
                f.write(json.dumps(entry) + '\n')

        except Exception as e:
            logger.error(f"Audit log failed: {e}")

    def _cleanup_old_audit_logs(self, max_age_days=90):
        """Loesche Audit-Logs aelter als max_age_days."""
        audit_dir = self.logs_dir / "audit"
        if not audit_dir.is_dir():
            return
        cutoff = datetime.now() - timedelta(days=max_age_days)
        for filename in os.listdir(audit_dir):
            if filename.startswith("observer_") and filename.endswith(".jsonl"):
                try:
                    date_str = filename.replace("observer_", "").replace(".jsonl", "")
                    file_date = datetime.strptime(date_str, "%Y-%m-%d")
                    if file_date < cutoff:
                        os.unlink(os.path.join(str(audit_dir), filename))
                        logger.info("Altes Audit-Log geloescht: %s", filename)
                except (ValueError, OSError):
                    continue

    def get_status(self) -> Dict[str, Any]:
        """Get current system status without running pipeline."""
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

        return {
            "last_run": last_run,
            "last_state": last_state,
            "logs_path": str(self.logs_dir)
        }


# Module-level convenience functions
_orchestrator: Optional[Orchestrator] = None


def get_orchestrator() -> Orchestrator:
    """Get the global orchestrator instance."""
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = Orchestrator()
    return _orchestrator


def run_pipeline() -> PipelineResult:
    """Run the weather observer pipeline."""
    return get_orchestrator().run_pipeline()


def get_status() -> Dict[str, Any]:
    """Get current status."""
    return get_orchestrator().get_status()
