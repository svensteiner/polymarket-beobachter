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

# Import performance optimizers
try:
    from shared.memory_optimizer import get_memory_monitor
    from shared.cpu_optimizer import get_performance_report
    from shared.control_events import append_control_event
    HAS_OPTIMIZERS = True
except ImportError:
    HAS_OPTIMIZERS = False
    from shared.control_events import append_control_event

logger = logging.getLogger(__name__)

LIVE_READINESS_REPORT_INTERVAL_HOURS = float(os.getenv("LIVE_READINESS_REPORT_INTERVAL_HOURS", "12"))
STATUS_SUMMARY_MAX_RUNS = int(os.getenv("STATUS_SUMMARY_MAX_RUNS", "120"))
STATUS_SUMMARY_ROTATE_MB = float(os.getenv("STATUS_SUMMARY_ROTATE_MB", "1"))


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
        Execute the weather observer pipeline with performance optimization.

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

        # Initialize performance monitoring for this run
        if HAS_OPTIMIZERS:
            memory_monitor = get_memory_monitor()
            memory_before = memory_monitor.get_memory_stats()

        result = PipelineResult(
            state=RunState.OK,
            timestamp=datetime.now().isoformat()
        )

        # Step 1: Collector (mit Resilience)
        print("[1/6] Collector: Maerkte abrufen ...", end="", flush=True)
        try:
            collector_result = self._run_collector()
        except Exception as e:
            logger.error(f"CRITICAL: Collector crashed: {e}")
            collector_result = StepResult(
                name="collector", success=False,
                message=f"Crash: {str(e)[:100]}", error=str(e)
            )
        result.add_step(collector_result)
        print(f" {'OK' if collector_result.success else 'FAIL'} ({collector_result.message})")

        # Step 1b: Cleanup alte Collector-Daten (>7 Tage)
        try:
            cleaned = self._cleanup_old_collector_data(max_age_days=7)
            if cleaned:
                logger.info(f"Collector cleanup: {cleaned} alte Verzeichnisse geloescht")
        except Exception as e:
            logger.warning(f"Collector cleanup fehlgeschlagen: {e}")

        # Step 2: Weather Observer (mit Resilience)
        print("[2/6] Weather Observer: Analyse + Edge ...", end="", flush=True)
        try:
            weather_result = self._run_weather_observer()
        except Exception as e:
            logger.error(f"CRITICAL: Weather Observer crashed: {e}")
            weather_result = StepResult(
                name="weather_observer", success=False,
                message=f"Crash: {str(e)[:100]}", error=str(e),
                data={"observations": [], "edge_observations": 0}
            )
        result.add_step(weather_result)
        print(f" {'OK' if weather_result.success else 'FAIL'} ({weather_result.message})")

        # Step 2b: Market Condition Assessment (READ-ONLY)
        edge_obs_count = weather_result.data.get("edge_observations", 0)
        self._assess_market_condition(edge_obs_count)

        # Step 3: Proposal Generator
        print("[3/6] Proposals: Edge -> Signale ...", end="", flush=True)
        proposal_result = self._run_proposal_generator(weather_result.data)
        result.add_step(proposal_result)
        print(f" {'OK' if proposal_result.success else 'FAIL'} ({proposal_result.message})")

        # Pre-fetch eligible proposals ONCE here so the adversarial check runs only
        # once per pipeline run (not once more inside simulate_agents_entry below).
        _eligible_proposals = None
        try:
            from paper_trader.intake import get_eligible_proposals as _get_proposals
            _eligible_proposals = _get_proposals(run_id=run_id)
        except Exception as _e:
            logger.debug(f"Pre-fetch eligible proposals fehlgeschlagen (unkritisch): {_e}")

        # Step 3b: Evolution Agent Simulator - Entries (non-blocking)
        # Jeder Agent bewertet Proposals nach seinen eigenen Parametern
        try:
            from evolution.agent_simulator import simulate_agents_entry
            agent_entries = simulate_agents_entry(proposals=_eligible_proposals or [])
            total_agent_entries = sum(agent_entries.values())
            if total_agent_entries > 0:
                logger.info(f"[EVOLUTION] Agent-Entries: {agent_entries}")
        except Exception as e:
            logger.debug(f"Evolution Agent Entry fehlgeschlagen (unkritisch): {e}")

        # Step 4: Paper Trader (mit DrawdownProtector-Snapshot + Resilience)
        print("[4/6] Paper Trader: Trades simulieren ...", end="", flush=True)
        try:
            self._record_equity_snapshot("pre_paper_trader")
            paper_result = self._run_paper_trader(run_id=run_id, eligible=_eligible_proposals)
        except Exception as e:
            logger.error(f"CRITICAL: Paper Trader crashed: {e}")
            paper_result = StepResult(
                name="paper_trader", success=False,
                message=f"Crash: {str(e)[:100]}", error=str(e),
                data={"entries": 0, "closes": 0, "pnl": 0.0}
            )
        result.add_step(paper_result)
        print(f" {'OK' if paper_result.success else 'FAIL'} ({paper_result.message})")

        # Step 4b: Live Trader (nur wenn LIVE_TRADING_ENABLED=true)
        live_enabled = os.getenv("LIVE_TRADING_ENABLED", "false").lower() == "true"
        if live_enabled:
            print("[4b] Live Trader: Echte Orders ...", end="", flush=True)
            try:
                live_result = self._run_live_trader(paper_result.data)
            except Exception as e:
                logger.error("CRITICAL: Live Trader crashed: %s", e)
                live_result = StepResult(
                    name="live_trader", success=False,
                    message=f"Crash: {str(e)[:100]}", error=str(e),
                    data={"live_entries": 0, "live_skipped": 0},
                )
            result.add_step(live_result)
            print(f" {'OK' if live_result.success else 'FAIL'} ({live_result.message})")

        # Step 5: Outcome Tracker
        print("[5/6] Outcome Tracker: Kalibrierung ...", end="", flush=True)
        outcome_result = self._run_outcome_tracker(weather_result.data)
        result.add_step(outcome_result)
        print(f" {'OK' if outcome_result.success else 'FAIL'} ({outcome_result.message})")

        # Step 5b: Evolution Agent Simulator - Closes (non-blocking)
        # Schliesst Agenten-Positionen fuer aufgeloeste Maerkte
        try:
            from evolution.agent_simulator import simulate_agents_close
            agent_closes = simulate_agents_close()
            total_agent_closes = sum(agent_closes.values())
            if total_agent_closes > 0:
                logger.info(f"[EVOLUTION] Agent-Closes: {agent_closes}")
        except Exception as e:
            logger.debug(f"Evolution Agent Close fehlgeschlagen (unkritisch): {e}")

        # Step 5b2: Shadow Trade Tracker — offene Schatten-Trades aktualisieren
        try:
            from paper_trader.shadow_tracker import update_open_shadow_trades
            _st_updated, _st_resolved = update_open_shadow_trades()
            if _st_resolved > 0:
                logger.info("ShadowTracker: %d updated, %d resolved", _st_updated, _st_resolved)
        except Exception as _st_exc:
            logger.debug("ShadowTracker update skipped: %s", _st_exc)

        # Step 5c: Outcome Analyser (nach jedem Run aktualisieren)
        self._run_outcome_analyser()

        # Step 5d: Segmentanalyse fuer Entry-Qualitaet aktualisieren
        self._run_segment_analysis()

        # Step 5e: Strategy Advisor (persistente Empfehlungen, read-only)
        self._run_strategy_advisor()

        # Step 5f: Arbitrage Scan (READ-ONLY, non-blocking)
        self._run_arbitrage_scan(weather_result.data)

        # Step 5g: Gamma Discovery (suche neue Maerkte, non-blocking)
        self._run_gamma_discovery()

        # Step 5h: General Market Observer (non-weather edge scan, OBSERVE-ONLY)
        self._run_general_market_observer(weather_result.data)

        # Build summary with pipeline duration
        duration_seconds = round(time.perf_counter() - pipeline_start, 2)
        result.summary = self._build_summary(result)
        bot_health = self._run_bot_health_monitor(result.summary)
        result.summary["bot_health_status"] = bot_health.get("status", "HEALTHY")
        result.summary["bot_health_summary"] = bot_health.get("summary", "")
        result.summary["bot_health_guardrails_active"] = bot_health.get("guardrails_active", False)
        result.summary["run_id"] = run_id
        result.summary["duration_seconds"] = duration_seconds

        # Add performance metrics if optimizers available
        if HAS_OPTIMIZERS:
            memory_after = memory_monitor.get_memory_stats()
            performance_report = get_performance_report()

            result.summary["performance"] = {
                "memory_before_mb": memory_before["current_mb"],
                "memory_after_mb": memory_after["current_mb"],
                "memory_peak_mb": memory_after["peak_mb"],
                "memory_pressure": memory_after["pressure_level"],
                "cpu_utilization": performance_report["system"]["cpu_percent"],
                "thread_pool_stats": performance_report.get("thread_pool", {}),
                "gc_collections": memory_after.get("gc_stats", {}).get("forced_collections", 0)
            }

        policy = self._refresh_agent_policy(result.summary)
        result.summary["agent_policy_mode"] = policy.get("mode", "UNKNOWN")
        result.summary["agent_policy_city_cooldowns"] = len(policy.get("cooldown_cities", []))
        result.summary["agent_policy_max_entry_price"] = policy.get("max_entry_price", 1.0)

        # Agent Core (Sprint 1): read-only Diagnose, Gedächtnis und Action-Proposals
        agent_result = self._run_agent_loop(result.summary)
        result.summary["agent_mode"] = agent_result.get("mode", "UNKNOWN")
        result.summary["agent_summary"] = agent_result.get("summary", "")
        result.summary["agent_hypothesis"] = agent_result.get("hypothesis", "")
        result.summary["agent_proposed_actions"] = len(agent_result.get("proposed_actions", []))

        edge_hunter = self._run_edge_hunter(result.summary)
        result.summary["edge_hunter_posture"] = edge_hunter.get("posture", "UNKNOWN")
        result.summary["edge_hunter_live_gate"] = edge_hunter.get("live_gate", "WAIT")
        result.summary["edge_hunter_score"] = edge_hunter.get("score", 0)
        result.summary["edge_hunter_next_action"] = edge_hunter.get("next_action", "")
        result.summary["edge_hunter_scout_targets"] = edge_hunter.get("scout", {}).get("targets", [])

        # Step 6: Write status
        print("[6/6] Status schreiben ...", end="", flush=True)
        status_result = self._write_status_summary(result)
        result.add_step(status_result)
        print(f" {'OK' if status_result.success else 'FAIL'}")

        # Log to audit (includes run_id via summary)
        self._log_to_audit(result)

        # Telegram Pipeline Summary (nur bei interessanten Events)
        try:
            from notifications.telegram import send_pipeline_summary, is_configured
            if is_configured():
                send_pipeline_summary(result.summary)
        except Exception as e:
            logger.debug(f"Telegram Pipeline Summary fehlgeschlagen: {e}")

        # Telegram Live-Readiness Report (alle 12h, auch wenn kein Trade passiert)
        self._maybe_send_live_readiness_report(result.summary)

        # Feedback-Loop: Rule-Based Check nach jeder neuen geschlossenen Position
        # Reagiert schneller als der Evolution-Tick (der alle 10 Runs laeuft)
        paper_closes = result.summary.get("paper_closes", 0) if result.summary else 0
        if paper_closes > 0:
            try:
                from evolution.strategy_agent import _run_rule_based_checks
                rule_actions = _run_rule_based_checks()
                if rule_actions:
                    logger.info(f"[FEEDBACK-LOOP] {paper_closes} Positionen geschlossen → Regel-Aktionen: {rule_actions}")
            except Exception as e:
                logger.debug(f"Feedback-Loop Rule-Check fehlgeschlagen (unkritisch): {e}")

        # Evolution Tick (non-blocking, triggert alle 10 Runs automatisch)
        try:
            from evolution.tournament import cmd_tick
            import types
            tick_args = types.SimpleNamespace(force=False)
            cmd_tick(tick_args)
        except Exception as e:
            logger.debug(f"Evolution Tick fehlgeschlagen (unkritisch): {e}")

        # Cleanup old audit logs (>90 days)
        try:
            self._cleanup_old_audit_logs(max_age_days=90)
        except Exception as e:
            logger.warning(f"Audit-Log cleanup fehlgeschlagen: {e}")

        # LLM Strategy Analyst: GPT-5.4 mini Analyse alle 10 Runs
        try:
            from core.llm_strategy_analyst import should_run_analysis, run_strategy_analysis
            if should_run_analysis(run_count=getattr(self, '_run_count', 0)):
                analysis = run_strategy_analysis(
                    self.base_dir, result.summary,
                    run_count=getattr(self, '_run_count', 0)
                )
                if analysis:
                    result.summary["llm_assessment"] = analysis.get("overall_assessment", "?")
                    result.summary["llm_live_readiness"] = analysis.get("live_readiness_pct", 0)
                    if analysis.get("action_items"):
                        logger.info(f"[LLM ANALYST] Actions: {analysis['action_items'][:3]}")
        except Exception as e:
            logger.debug(f"LLM Strategy Analyst uebersprungen: {e}")

        # Self-Improvement-Cycle: kontinuierliche Parameter-Optimierung
        self._run_improvement_cycle()

        # Notify Self-Healing System about run result
        try:
            from analytics.improvement_agent import notify_pipeline_success, notify_pipeline_failure
            if result.state == RunState.OK:
                notify_pipeline_success()
            elif result.state == RunState.FAIL:
                notify_pipeline_failure("UNKNOWN")
        except Exception as e:
            logger.debug(f"Self-Healing Notification fehlgeschlagen: {e}")

        # Self-Heal: Kapital-Reconciliation, Zombie-Detection, Error-Patterns
        try:
            from core.self_healer import run_self_heal
            heal_report = run_self_heal(
                self.base_dir,
                run_result={"state": result.state.value, "summary": result.summary}
            )
            if heal_report.get("actions"):
                result.summary["self_heal_actions"] = heal_report["actions"]
                logger.info(f"Self-Heal: {len(heal_report['actions'])} Aktionen ausgefuehrt")
        except Exception as e:
            logger.debug(f"Self-Heal fehlgeschlagen (unkritisch): {e}")

        logger.info(f"=== Pipeline END === run_id={run_id} state={result.state.value}")

        return result

    def _run_arbitrage_scan(self, weather_data: dict) -> None:
        """Scanne Wetter-Maerkte auf Arbitrage-Moeglichkeiten (non-blocking)."""
        try:
            from analytics.arbitrage_detector import run_arbitrage_scan
            import json
            from datetime import date

            # Lade aktuelle Kandidaten - Gamma bevorzugen (enthaelt outcomePrices)
            today = date.today().isoformat()
            gamma_root = self.data_dir / "collector" / "gamma"
            candidates_root = self.data_dir / "collector" / "candidates"

            candidates_file = None
            use_gamma = False

            # Gamma-Datei hat Preisdaten → fuer Arbitrage bevorzugen
            gamma_today = gamma_root / today / "gamma_candidates.jsonl"
            if gamma_today.exists() and gamma_today.stat().st_size > 0:
                candidates_file = gamma_today
                use_gamma = True
            elif gamma_root.exists():
                for day_dir in sorted(gamma_root.iterdir(), reverse=True):
                    f = day_dir / "gamma_candidates.jsonl"
                    if f.exists() and f.stat().st_size > 0:
                        candidates_file = f
                        use_gamma = True
                        break

            # Fallback auf sanitierte Kandidaten
            if not candidates_file:
                sanitized_today = candidates_root / today / "candidates.jsonl"
                if sanitized_today.exists():
                    candidates_file = sanitized_today
                elif candidates_root.exists():
                    for day_dir in sorted(candidates_root.iterdir(), reverse=True):
                        f = day_dir / "candidates.jsonl"
                        if f.exists() and f.stat().st_size > 0:
                            candidates_file = f
                            break

            candidates = []
            if candidates_file and candidates_file.exists():
                logger.debug(f"Arbitrage Quelle: {'Gamma' if use_gamma else 'Sanitiert'} ({candidates_file.name})")
                with open(candidates_file, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            try:
                                candidates.append(json.loads(line))
                            except Exception:
                                pass

            if candidates:
                output_file = str(self.output_dir / "arbitrage_opportunities.json")
                opportunities = run_arbitrage_scan(candidates, output_file=output_file)
                if opportunities:
                    logger.info(f"Arbitrage: {len(opportunities)} Moeglichkeiten gefunden")
                    # Telegram Alert fuer grosse Arbitrage-Chancen
                    try:
                        from notifications.telegram import send_message
                        for opp in opportunities[:3]:  # Max 3 Alerts
                            if opp.inconsistency_magnitude >= 0.05:
                                text = (
                                    f"💰 <b>ARBITRAGE CHANCE</b>\n"
                                    f"📍 Stadt: {opp.city}\n"
                                    f"📊 Delta: {opp.inconsistency_magnitude:.1%}\n"
                                    f"❓ {opp._describe()[:100]}"
                                )
                                send_message(text, disable_notification=True)
                    except Exception:
                        pass
        except Exception as e:
            logger.debug(f"Arbitrage Scan fehlgeschlagen (unkritisch): {e}")

    def _maybe_send_live_readiness_report(self, summary: Dict[str, Any]) -> None:
        """Sende Live-Readiness-Bericht hoechstens alle N Stunden via Telegram."""
        state_file = self.logs_dir / "live_readiness_report_state.json"
        now = datetime.now()
        interval_seconds = max(1.0, LIVE_READINESS_REPORT_INTERVAL_HOURS) * 3600

        try:
            if state_file.exists():
                state = json.loads(state_file.read_text(encoding="utf-8"))
                last_sent_raw = state.get("last_sent_at")
                if last_sent_raw:
                    last_sent = datetime.fromisoformat(last_sent_raw)
                    if (now - last_sent).total_seconds() < interval_seconds:
                        return

            from notifications.telegram import is_configured, send_live_readiness_report

            if not is_configured():
                logger.debug("Live-Readiness Telegram Report uebersprungen: Telegram nicht konfiguriert")
                return

            sent = send_live_readiness_report(summary)
            if sent:
                payload = {
                    "last_sent_at": now.isoformat(),
                    "interval_hours": LIVE_READINESS_REPORT_INTERVAL_HOURS,
                    "run_id": summary.get("run_id"),
                    "actionable_edge_count": summary.get("actionable_edge_count", 0),
                    "state": summary.get("state", "UNKNOWN"),
                }
                tmp = state_file.with_suffix(".tmp")
                tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
                tmp.replace(state_file)
                logger.info("Live-Readiness Telegram Report gesendet")
        except Exception as e:
            logger.debug("Live-Readiness Telegram Report fehlgeschlagen (unkritisch): %s", e)

    def _run_gamma_discovery(self) -> None:
        """Suche neue Wetter-Maerkte via Gamma API (non-blocking, max 1x pro Stunde)."""
        try:
            import time

            # Rate-Limit: max 1x pro Stunde
            marker_file = self.data_dir / ".gamma_last_run"
            if marker_file.exists():
                last_run = marker_file.stat().st_mtime
                if time.time() - last_run < 3600:
                    return  # Noch nicht eine Stunde vergangen

            from collector.gamma_discovery import run_discovery_and_save
            output_dir = str(self.data_dir / "collector" / "gamma")
            count = run_discovery_and_save(output_dir=output_dir, limit=300, min_liquidity=50.0)

            if count > 0:
                logger.info(f"Gamma Discovery: {count} neue Wetter-Maerkte gefunden")

            # Marker aktualisieren
            marker_file.touch()

        except Exception as e:
            logger.debug(f"Gamma Discovery fehlgeschlagen (unkritisch): {e}")

    def _run_general_market_observer(self, weather_data: dict) -> None:
        """Scan non-weather markets for LLM-computed edge. OBSERVE-ONLY, non-blocking."""
        try:
            # Rate-limit: max once per hour
            import time
            marker_file = self.data_dir / ".general_market_last_run"
            if marker_file.exists() and time.time() - marker_file.stat().st_mtime < 3600:
                return

            # Pass markets collected this run if available
            markets = weather_data.get("all_markets_raw") or []

            from core.general_market_observer import run_general_market_observation
            summary = run_general_market_observation(self.base_dir, markets or None)

            high_edge = summary.get("high_edge_count", 0)
            obs = summary.get("observations_with_edge", 0)
            if obs > 0:
                logger.info(
                    "[GeneralMarket] %d observations, %d high-edge (>= 20%%)",
                    obs, high_edge,
                )

            marker_file.touch()

        except Exception as e:
            logger.debug("General market observer failed (non-critical): %s", e)

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

            # Step 1b: Merge gamma-discovered candidates (dedup by market_id)
            # Gamma API finds daily city temperature markets not always present in CLOB events.
            gamma_root = self.data_dir / "collector" / "gamma"
            gamma_candidate_file = None
            if gamma_root.exists():
                for day_dir in sorted(gamma_root.iterdir(), reverse=True):
                    gf = day_dir / "gamma_candidates.jsonl"
                    if gf.exists() and gf.stat().st_size > 0:
                        gamma_candidate_file = gf
                        break
            if gamma_candidate_file:
                existing_ids = {c.get("market_id") for c in raw_candidates}
                gamma_added = 0
                with open(gamma_candidate_file, 'r', encoding='utf-8') as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            gdata = json.loads(line)
                            mid = gdata.get("market_id")
                            if mid and mid not in existing_ids:
                                raw_candidates.append(gdata)
                                existing_ids.add(mid)
                                gamma_added += 1
                        except Exception as e:
                            logger.debug(f"Skipping invalid gamma candidate: {e}")
                if gamma_added:
                    logger.info(f"Merged {gamma_added} gamma candidates into observation pipeline")

            # Pre-filter: only fetch prices for markets with future resolution (saves API calls)
            from datetime import timezone as _tz
            _now_utc = datetime.now(_tz.utc)
            _min_hours = weather_config.get("MIN_TIME_TO_RESOLUTION_HOURS", 24)
            def _parse_end_date(raw: str) -> Optional[datetime]:
                if not raw:
                    return None
                try:
                    # Date-only format (e.g. "2026-03-21") → treat as end-of-day 23:59 UTC
                    if len(raw) <= 10:
                        raw = raw + "T23:59:00+00:00"
                    dt = datetime.fromisoformat(raw)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=_tz.utc)
                    return dt
                except Exception:
                    return None

            pre_filtered = []
            skipped_stale = 0
            for c in raw_candidates:
                res_dt = _parse_end_date(c.get("end_date", ""))
                if res_dt is None:
                    pre_filtered.append(c)
                    continue
                hours_away = (res_dt - _now_utc).total_seconds() / 3600
                if hours_away >= _min_hours:
                    pre_filtered.append(c)
                else:
                    skipped_stale += 1
            if skipped_stale:
                logger.info(f"Pre-filtered {skipped_stale} stale candidates (resolution < {_min_hours}h away), {len(pre_filtered)} remain")

            # Step 2: Fetch real market odds from Polymarket API
            market_ids = [c.get("market_id", "") for c in pre_filtered if c.get("market_id")]
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
            _skip_no_price = 0
            _skip_filter: dict = {}  # reason -> count
            for data in pre_filtered:
                try:
                    market_id = data.get("market_id", "")

                    # Get real odds and liquidity - SKIP if price unavailable
                    odds_yes = None
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

                    # Fallback: use outcomePrices/liquidity stored in the candidate data itself
                    # (Gamma-discovered markets carry these fields; CLOB API won't find them)
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
                                        logger.debug(
                                            f"Using stored outcomePrices for {market_id}: "
                                            f"yes={odds_yes:.3f}"
                                        )
                            except Exception:
                                pass
                        stored_liq = data.get("liquidity")
                        if stored_liq is not None and liquidity_usd == 100.0:
                            try:
                                liquidity_usd = float(stored_liq)
                            except Exception:
                                pass

                    # Skip markets without live price - can't compute edge without it
                    if odds_yes is None:
                        _skip_no_price += 1
                        logger.debug(f"Skipping {market_id}: no live price available")
                        continue

                    market = WeatherMarket(
                        market_id=market_id,
                        question=data.get("title", ""),
                        resolution_text=data.get("resolution_text", ""),
                        description=data.get("description", ""),
                        category="WEATHER",
                        is_binary=True,
                        liquidity_usd=liquidity_usd,
                        odds_yes=odds_yes,
                        resolution_time=_parse_end_date(data.get("end_date", "")) or datetime.now(_tz.utc),
                    )

                    # Run through filter to populate detected_city and detected_threshold
                    filter_result = weather_filter.filter_market(market)
                    if filter_result.passed and filter_result.market:
                        weather_markets.append(filter_result.market)
                    else:
                        reasons = filter_result.rejection_reasons or ["unknown"]
                        for r in (reasons if isinstance(reasons, list) else [str(reasons)]):
                            key = str(r).split(":")[0][:40]
                            _skip_filter[key] = _skip_filter.get(key, 0) + 1
                        logger.debug(f"Market {market.market_id} filtered out: {filter_result.rejection_reasons}")
                except Exception as e:
                    logger.warning(f"Skipping candidate due to exception: {type(e).__name__}: {e}")

            logger.info(
                f"Loaded {len(weather_markets)} weather candidates for observation "
                f"(skipped: {_skip_no_price} no-price, {sum(_skip_filter.values())} filter "
                f"[{', '.join(f'{k}:{v}' for k,v in sorted(_skip_filter.items(), key=lambda x:-x[1])[:5])}])"
            )

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

    def _run_paper_trader(self, run_id: str | None = None, eligible=None) -> StepResult:
        """
        Run paper trading cycle.

        PAPER TRADING ONLY:
        - NO real orders are placed
        - NO real money is at risk

        Args:
            eligible: Optional pre-fetched list of eligible proposals. If None,
                      they are fetched from intake (triggers adversarial check).
        """
        try:
            from paper_trader.intake import get_eligible_proposals
            from paper_trader.simulator import simulate_entry
            from paper_trader.position_manager import check_and_close_resolved, check_mid_trade_exits, check_guardrail_violations
            from paper_trader.averaging_down import check_averaging_down
            from paper_trader.edge_reversal import check_edge_reversal_exits
            from paper_trader.drawdown_protector import get_drawdown_status
            from paper_trader.guardrail_audit import build_guardrail_summary
            from paper_trader.logger import get_paper_logger

            # Step 0: Force-close any positions that violate the current entry
            # guardrail (e.g. legacy NO-between/exact positions entered before the
            # guardrail rule was added). Run before SL/TP so we don't pay a -70% SL.
            gv = check_guardrail_violations()
            if gv["force_closed"]:
                logger.info(
                    f"Guardrail violations: {gv['force_closed']} positions force-closed, "
                    f"P&L: {gv['pnl_eur']:+.2f} EUR"
                )

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

            # Step 3.5: Refresh active entry policy before proposal intake.
            # Uses latest persisted advisor/segment data plus current drawdown state.
            try:
                from agentic.policy import AgentPolicyEngine

                dd = get_drawdown_status()
                pre_trade_summary = {
                    "drawdown_recovery_mode": dd.get("is_recovery_mode", False),
                    "drawdown_pct": dd.get("current_dd_pct", 0.0),
                    "bot_health_guardrails_active": False,
                    "bot_health_status": "UNKNOWN",
                }
                AgentPolicyEngine(self.base_dir).build_and_save(pre_trade_summary)
            except Exception as e:
                logger.debug(f"Pre-trade policy refresh fehlgeschlagen (unkritisch): {e}")

            # Step 4: Get eligible proposals for new entries
            # Use pre-fetched proposals if available (avoids duplicate adversarial check)
            if eligible is None:
                eligible = get_eligible_proposals(run_id=run_id)
            guardrail_summary = build_guardrail_summary(run_id=run_id)
            logger.info(f"Found {len(eligible)} eligible proposals for paper trading")
            blocked_by_reason = guardrail_summary.get("blocked_by_reason", {}) or {}
            top_block_reason = ""
            if blocked_by_reason:
                top_block_reason = max(
                    blocked_by_reason.items(),
                    key=lambda item: int(item[1] or 0),
                )[0]

            # Simulate entries
            entered = 0
            skipped = 0
            accepted_proposals = []

            for proposal in eligible:
                position, record = simulate_entry(proposal)
                if position is not None:
                    entered += 1
                    accepted_proposals.append(proposal)
                    logger.info(f"Paper ENTRY: {proposal.market_id[:30]}... | {position.side} @ {position.entry_price:.4f}")
                else:
                    skipped += 1

            # Step 5: Check and close resolved positions
            close_summary = check_and_close_resolved()
            open_positions = get_paper_logger().get_open_positions()
            high_price_open_positions = sum(1 for pos in open_positions if (pos.entry_price or 0.0) >= 0.85)

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
                    "actionable_edge_count": len(eligible),
                    "guardrail_allowed_count": guardrail_summary.get("allowed_count", 0),
                    "guardrail_blocked_count": guardrail_summary.get("blocked_count", 0),
                    "guardrail_blocked_ratio": guardrail_summary.get("blocked_ratio", 0.0),
                    "top_guardrail_block_reason": top_block_reason,
                    "shadow_eligible_without_inventory": guardrail_summary.get("shadow_allowed_without_inventory", 0),
                    "shadow_eligible_ratio_without_inventory": guardrail_summary.get("shadow_allowed_ratio_without_inventory", 0.0),
                    "positions_entered": entered,
                    "positions_skipped": skipped,
                    "accepted_proposals": accepted_proposals,
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
                    "high_price_open_positions": high_price_open_positions,
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

    def _run_live_trader(self, paper_data: Dict[str, Any]) -> StepResult:
        """
        Execute live trades for proposals that passed paper trading guardrails.

        SAFETY:
        - Only executes if LIVE_TRADING_ENABLED=true in environment
        - Every trade requires Telegram approval (require_telegram_approval=true)
        - Uses strategy parameters from config/live_trading.yaml
        """
        accepted = paper_data.get("accepted_proposals", [])
        if not accepted:
            return StepResult(
                name="live_trader",
                success=True,
                message="No paper entries — nothing to execute live",
                data={"live_entries": 0, "live_skipped": 0},
            )

        live_enabled = os.getenv("LIVE_TRADING_ENABLED", "false").lower() == "true"
        if not live_enabled:
            return StepResult(
                name="live_trader",
                success=True,
                message=f"Live trading disabled — {len(accepted)} proposal(s) skipped",
                data={"live_entries": 0, "live_skipped": len(accepted)},
            )

        try:
            from trading.live_trader import LiveTrader
            trader = LiveTrader()

            live_entries = 0
            live_skipped = 0
            live_errors = 0

            for proposal in accepted:
                try:
                    trade = trader.execute_proposal(proposal)
                    if trade:
                        live_entries += 1
                        logger.info(
                            "LIVE ENTRY: %s | %s @ %.4f | Trade ID: %s",
                            getattr(proposal, "market_id", "?")[:30],
                            trade.side,
                            trade.price,
                            trade.trade_id[:12],
                        )
                    else:
                        live_skipped += 1
                except Exception as e:
                    live_errors += 1
                    logger.error("Live trade failed for %s: %s", getattr(proposal, "market_id", "?"), e)

            return StepResult(
                name="live_trader",
                success=True,
                message=(
                    f"Live entries: {live_entries} | "
                    f"Skipped: {live_skipped} | "
                    f"Errors: {live_errors}"
                ),
                data={
                    "live_entries": live_entries,
                    "live_skipped": live_skipped,
                    "live_errors": live_errors,
                },
            )

        except Exception as e:
            logger.error("Live trader crashed: %s", e)
            return StepResult(
                name="live_trader",
                success=False,
                message=f"Live trader error: {str(e)[:100]}",
                error=str(e),
                data={"live_entries": 0, "live_skipped": len(accepted)},
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
                        question=obs.event_description,
                        outcomes=["YES", "NO"],
                        market_price_yes=obs.market_probability,
                        market_price_no=1.0 - obs.market_probability if obs.market_probability is not None else None,
                        our_estimate_yes=obs.model_probability,
                        estimate_confidence=obs.confidence.value if hasattr(obs.confidence, 'value') else None,
                        decision="TRADE" if obs.edge and abs(obs.edge) >= 0.12 else "NO_TRADE",
                        decision_reasons=(
                            [f"Edge: {obs.edge:+.2%}" if obs.edge else "No edge"]
                            + (
                                [
                                    "PER_SOURCE_PROBS:"
                                    + __import__("json").dumps(
                                        {
                                            str(k): round(float(v), 6)
                                            for k, v in (obs.per_source_probabilities or {}).items()
                                        },
                                        separators=(",", ":"),
                                    )
                                ]
                                if getattr(obs, "per_source_probabilities", None)
                                else []
                            )
                        ),
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
            resolution_result = checker.update_resolutions(max_checks=12, max_seconds=30)

            return StepResult(
                name="outcome_tracker",
                success=True,
                message=f"{predictions_recorded} predictions recorded, {resolution_result.get('new_resolutions', 0)} resolutions updated",
                data={
                    "observations_recorded": predictions_recorded,
                    "resolutions_updated": resolution_result.get("new_resolutions", 0),
                    "unresolved_remaining": resolution_result.get("remaining_unresolved", 0),
                    "resolution_checks": resolution_result.get("checked", 0),
                    "resolution_deadline_hit": resolution_result.get("deadline_hit", False),
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

    def _run_strategy_advisor(self) -> None:
        """Schreibe persistente Strategie-Empfehlungen auf Basis der aktuellen Daten."""
        try:
            from analytics.strategy_advisor import run_strategy_advisor
            advice = run_strategy_advisor()
            logger.info(
                "[ADVISOR] %s | %s",
                str(advice.get("mode", "observe")).upper(),
                advice.get("summary", ""),
            )
        except Exception as e:
            logger.debug(f"Strategy Advisor fehlgeschlagen (unkritisch): {e}")

    def _run_segment_analysis(self) -> None:
        """Aktualisiere Segmentanalyse fuer Entry-Qualitaet (non-blocking)."""
        try:
            from analytics.segment_analyser import run_segment_analysis
            analysis = run_segment_analysis()
            risky_cities = analysis.get("risk_flags", {}).get("suggested_city_cooldowns", [])
            logger.info(
                "[SEGMENTS] %s closed positions | risky cities: %s",
                analysis.get("positions_considered", 0),
                ", ".join(risky_cities[:3]) if risky_cities else "none",
            )
        except Exception as e:
            logger.debug(f"Segmentanalyse fehlgeschlagen (unkritisch): {e}")

    def _refresh_agent_policy(self, summary: Dict[str, Any]) -> Dict[str, Any]:
        """Baue aktive Entry-Policy aus Advisor + Segmentanalyse."""
        try:
            from agentic.policy import AgentPolicyEngine

            policy = AgentPolicyEngine(self.base_dir).build_and_save(summary)
            logger.info(
                "[AGENT-POLICY] %s | max_entry=%.3f | city_cooldowns=%s",
                policy.get("mode", "UNKNOWN"),
                float(policy.get("max_entry_price", 1.0)),
                len(policy.get("cooldown_cities", [])),
            )
            return policy
        except Exception as e:
            logger.debug(f"Agent Policy Refresh fehlgeschlagen (unkritisch): {e}")
            return {}

    def _run_bot_health_monitor(self, summary: Dict[str, Any]) -> Dict[str, Any]:
        """Aktualisiere temporäre Guardrails auf Basis der aktuellen Bot-Gesundheit."""
        try:
            from paper_trader.bot_health_monitor import update_bot_health
            health = update_bot_health(summary)
            logger.info(
                "[BOT-HEALTH] %s | %s",
                health.get("status", "HEALTHY"),
                health.get("summary", ""),
            )
            return health
        except Exception as e:
            logger.debug(f"Bot Health Monitor fehlgeschlagen (unkritisch): {e}")
            return {"status": "UNKNOWN", "summary": "", "guardrails_active": False}

    def _run_edge_hunter(self, summary: Dict[str, Any]) -> Dict[str, Any]:
        """Aktualisiere Edge-Hunter-Report fuer Actionable-Edge-Fokus."""
        try:
            from analytics.edge_hunter import run_edge_hunter

            report = run_edge_hunter(summary)
            logger.info(
                "[EDGE-HUNTER] %s | %s | score=%s",
                report.get("posture", "UNKNOWN"),
                report.get("live_gate", "WAIT"),
                report.get("score", 0),
            )
            return report
        except Exception as e:
            logger.debug("Edge Hunter fehlgeschlagen (unkritisch): %s", e)
            return {
                "posture": "UNAVAILABLE",
                "live_gate": "WAIT",
                "score": 0,
                "next_action": "",
            }

    def _load_strategy_advice_summary(self) -> Dict[str, Any]:
        """Lade die letzte Strategy-Advisor-Zusammenfassung fuer Status-Ausgaben."""
        try:
            from analytics.strategy_advisor import load_latest_advice
            advice = load_latest_advice()
            recommendations = advice.get("recommendations", [])
            top_action = ""
            if recommendations:
                top_action = str(recommendations[0].get("action", ""))
            return {
                "mode": str(advice.get("mode", "observe")).upper(),
                "summary": str(advice.get("summary", "")),
                "top_action": top_action,
            }
        except Exception as e:
            logger.debug(f"Strategy-Advice Summary nicht verfuegbar: {e}")
            return {"mode": "N/A", "summary": "", "top_action": ""}

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
        advisor = self._load_strategy_advice_summary()
        return {
            "run_date": date.today().isoformat(),
            "run_time": result.timestamp,
            "state": result.state.value,
            "markets_fetched": collector_step.data.get("total_fetched", 0) if collector_step else 0,
            "weather_candidates": collector_step.data.get("total_candidates", 0) if collector_step else 0,
            "observations_total": weather_step.data.get("observations_total", 0) if weather_step else 0,
            "edge_observations": weather_step.data.get("edge_observations", 0) if weather_step else 0,
            "proposals_generated": proposal_step.data.get("proposals_generated", 0) if proposal_step else 0,
            "actionable_edge_count": paper_step.data.get("actionable_edge_count", 0) if paper_step else 0,
            "paper_positions_entered": paper_step.data.get("positions_entered", 0) if paper_step else 0,
            "paper_positions_closed": paper_step.data.get("positions_closed", 0) if paper_step else 0,
            "paper_pnl_eur": paper_step.data.get("total_pnl_eur", 0) if paper_step else 0,
            "high_price_open_positions": paper_step.data.get("high_price_open_positions", 0) if paper_step else 0,
            "guardrail_allowed_count": paper_step.data.get("guardrail_allowed_count", 0) if paper_step else 0,
            "guardrail_blocked_count": paper_step.data.get("guardrail_blocked_count", 0) if paper_step else 0,
            "guardrail_blocked_ratio": paper_step.data.get("guardrail_blocked_ratio", 0.0) if paper_step else 0.0,
            "top_guardrail_block_reason": paper_step.data.get("top_guardrail_block_reason", "") if paper_step else "",
            "shadow_eligible_without_inventory": paper_step.data.get("shadow_eligible_without_inventory", 0) if paper_step else 0,
            "shadow_eligible_ratio_without_inventory": paper_step.data.get("shadow_eligible_ratio_without_inventory", 0.0) if paper_step else 0.0,
            "resolutions_updated": outcome_step.data.get("resolutions_updated", 0) if outcome_step else 0,
            "drawdown_pct": dd.get("current_dd_pct", 0.0),
            "drawdown_recovery_mode": dd.get("is_recovery_mode", False),
            "drawdown_size_factor": dd.get("size_factor", 1.0),
            "market_condition": mc.get("condition", "WATCH"),
            "strategy_advisor_mode": advisor.get("mode", "N/A"),
            "strategy_advisor_summary": advisor.get("summary", ""),
            "strategy_advisor_top_action": advisor.get("top_action", ""),
        }

    def _run_agent_loop(self, summary: Dict[str, Any]) -> Dict[str, Any]:
        """Execute agent loop: diagnostics, memory, and approved action effects."""
        try:
            from agentic.agent_loop import AgentLoop
            from agentic.action_executor import execute_approved_actions
            from agentic.state import ActionProposal

            agent = AgentLoop(self.base_dir)
            result = agent.run(summary)

            # Execute non-read-only approved actions (pause_city, tighten_risk)
            approved_raw = result.get("proposed_actions", [])
            approved_proposals = []
            for raw in approved_raw:
                if isinstance(raw, dict) and raw.get("status") not in ("APPROVED_READ_ONLY",):
                    approved_proposals.append(ActionProposal(
                        action_type=raw.get("action_type", ""),
                        title=raw.get("title", ""),
                        rationale=raw.get("rationale", ""),
                        evidence=raw.get("evidence", []),
                        priority=raw.get("priority", "MEDIUM"),
                        params=raw.get("params", {}),
                        status=raw.get("status", "APPROVED"),
                    ))
            if approved_proposals:
                exec_result = execute_approved_actions(approved_proposals, self.base_dir)
                if exec_result["executed"]:
                    logger.info("[AGENT-EXEC] ausgefuehrt: %s", exec_result["executed"])
                result["executed_actions"] = exec_result["executed"]

            # Feedback-Loop: Städte mit guter Performance wieder freigeben
            from agentic.action_executor import check_and_lift_cooldowns
            lifted = check_and_lift_cooldowns(root=self.base_dir)
            if lifted:
                logger.info("[AGENT-COOLDOWN] Städte freigegeben: %s", lifted)
            result["lifted_cooldowns"] = lifted

            logger.info(
                "[AGENT] %s | %s",
                result.get("mode", "UNKNOWN"),
                result.get("summary", ""),
            )
            return result
        except Exception as e:
            logger.debug(f"Agent Loop fehlgeschlagen (unkritisch): {e}")
            return {
                "mode": "UNAVAILABLE",
                "summary": "",
                "hypothesis": "",
                "proposed_actions": [],
                "blocked_actions": [],
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

    @staticmethod
    def _trim_status_summary(filepath: Path, max_runs: int = STATUS_SUMMARY_MAX_RUNS) -> None:
        """Keep status_summary.txt small by retaining only the newest run blocks."""
        if max_runs <= 0 or not filepath.exists():
            return

        marker = "\n" + "=" * 50 + "\nRun:"
        content = filepath.read_text(encoding="utf-8")
        parts = content.split(marker)
        if len(parts) <= max_runs + 1:
            return

        retained = parts[-max_runs:]
        filepath.write_text("".join(f"{marker}{part}" for part in retained), encoding="utf-8")
        logger.info("Status-Summary gekuerzt: %s auf die letzten %d Runs", filepath.name, max_runs)

    def _write_status_summary(self, result: PipelineResult) -> StepResult:
        """Write status summary to file."""
        try:
            summary_file = self.output_dir / "status_summary.txt"

            self._rotate_if_needed(summary_file, max_size_mb=STATUS_SUMMARY_ROTATE_MB)

            # Forward-Edge Validation: ZUERST aktualisieren (model vs MARKET Brier,
            # corr(edge,pnl), OOS-Skill), damit der Live-Readiness-Freeze unten den
            # frischen live_eligible-Status liest. READ-ONLY, fail-open.
            try:
                from analytics.forward_validation import run as _fwd_run
                _fwd_run()
            except Exception as _fwd_err:  # fail-open: gate stays blocked on stale data
                logger.debug("Forward-Validation fehlgeschlagen: %s", _fwd_err)

            # Edge Research: direktionale NO-Fade-PnL gegen offizielle Resolutions
            # (Favorite-Longshot-Bias). Schreibt analytics/edge_research.json|md und
            # haelt die md-Datei bei JEDEM Lauf aktuell. READ-ONLY, fail-open.
            try:
                from analytics.edge_research import run as _edge_run
                _edge_run()
            except Exception as _edge_err:  # fail-open: research only, never blocks
                logger.debug("Edge-Research fehlgeschlagen: %s", _edge_err)

            # Gate-3 Regime-Gap-Monitor: VOR der Lane, damit sie ein frisches
            # auto_pause-Flag liest. Pausiert NO-Fade-Entries wenn die Longshot-
            # Verzerrung wegarbitriert ist. READ-ONLY, fail-open.
            try:
                from analytics.gap_monitor import run as _gap_run
                _gap_run()
            except Exception as _gap_err:  # fail-open
                logger.debug("Gap-Monitor fehlgeschlagen: %s", _gap_err)

            # NO-Fade Forward Shadow Lane: nimmt qualifizierende 10-20% exact/between
            # Maerkte als NO-Paper-Position auf (held-to-resolution), misst echte CLOB-
            # Fill-Kosten am Entry. Eigenes Ledger, kein Eingriff in den Live-Simulator.
            # Forward-Evidenz fuer Gate 1 + Gate 2. PAPER ONLY, fail-open.
            try:
                from paper_trader.no_fade_lane import run as _nofade_run
                _nofade_run()
            except Exception as _nf_err:  # fail-open: shadow lane never blocks pipeline
                logger.debug("NO-Fade Lane fehlgeschlagen: %s", _nf_err)

            # Forward-vs-Backtest Reconciliation: zerlegt die Luecke zwischen
            # Backtest-Edge (+2,87%) und Forward-Lane (negativ) in Kosten / Regime /
            # Selektion. Nach der Lane, damit sie das frische Ledger liest.
            # READ-ONLY, fail-open.
            try:
                from analytics.forward_reconciliation import run as _recon_run
                _recon_run()
            except Exception as _recon_err:  # fail-open
                logger.debug("Forward-Reconciliation fehlgeschlagen: %s", _recon_err)

            # Edge-Status: EINE Uebersichtsseite "wo stehen wir" (aggregiert
            # edge_research + gap_monitor + Lane + Bot-Health). Zuletzt, damit sie
            # die frischesten Zahlen sieht. READ-ONLY, fail-open.
            try:
                from analytics.edge_status import run as _status_run
                _status_run()
            except Exception as _st_err:  # fail-open
                logger.debug("Edge-Status fehlgeschlagen: %s", _st_err)

            # Live-Readiness Tracker: nach jedem Run aktualisieren, damit wir
            # kontinuierlich sehen wie weit wir von den 6 Live-Go-Meilensteinen
            # entfernt sind (analytics/live_readiness.json|txt).
            readiness_info: Dict[str, Any] = {}
            try:
                from analytics.live_readiness_tracker import update_live_readiness
                readiness_info = update_live_readiness()
            except Exception as _rdy_err:  # fail-open
                logger.debug("Live-Readiness Tracker fehlgeschlagen: %s", _rdy_err)

            # AUTONOMOUS LAYER: alle drei Selbst-Steuerungs-Module nach jedem Run.
            # Jedes Modul schreibt eigene State-Dateien + Audit-Trail in
            # logs/autonomous_decisions.jsonl. Vollstaendig fail-open, damit ein
            # bug in einem Modul nie die Pipeline kippen kann.
            autonomous_status: Dict[str, Any] = {}
            try:
                from analytics.auto_city_blacklist import evaluate_and_persist as _city_eval
                autonomous_status["auto_city_blacklist"] = _city_eval()
            except Exception as _city_err:
                logger.debug("Auto-City-Blacklist fehlgeschlagen: %s", _city_err)
            try:
                from analytics.auto_parameter_tuner import evaluate_and_persist as _param_eval
                autonomous_status["auto_parameter_tuner"] = _param_eval()
            except Exception as _param_err:
                logger.debug("Auto-Parameter-Tuner fehlgeschlagen: %s", _param_err)
            try:
                from analytics.self_diagnostic_loop import run_diagnostics as _diag
                autonomous_status["self_diagnostic"] = _diag()
            except Exception as _diag_err:
                logger.debug("Self-Diagnostic fehlgeschlagen: %s", _diag_err)
            try:
                from analytics.hypothesis_sandbox import evaluate_and_persist as _hyp
                autonomous_status["hypothesis_sandbox"] = _hyp()
            except Exception as _hyp_err:
                logger.debug("Hypothesis-Sandbox fehlgeschlagen: %s", _hyp_err)
            try:
                from analytics.agentic_self_score import evaluate_and_persist as _score
                autonomous_status["agentic_score"] = _score()
            except Exception as _score_err:
                logger.debug("Agentic-Score fehlgeschlagen: %s", _score_err)

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
                f"Actionable Edge:      {result.summary.get('actionable_edge_count', 0)} eligible proposal(s)",
                f"Paper positions:      {result.summary.get('paper_positions_entered', 0)} entered, {result.summary.get('paper_positions_closed', 0)} closed",
                f"Guardrails:           {result.summary.get('guardrail_allowed_count', 0)} pass, "
                f"{result.summary.get('guardrail_blocked_count', 0)} blocked "
                f"({result.summary.get('guardrail_blocked_ratio', 0.0):.0%})",
                f"Top Block Reason:     {result.summary.get('top_guardrail_block_reason', '') or 'n/a'}",
                f"Shadow Eligible:      {result.summary.get('shadow_eligible_without_inventory', 0)} "
                f"without inventory ({result.summary.get('shadow_eligible_ratio_without_inventory', 0.0):.0%})",
                f"Paper P&L (EUR):      {result.summary.get('paper_pnl_eur', 0):+.2f}",
                f"Resolutions updated:  {result.summary.get('resolutions_updated', 0)}",
                f"Drawdown:             {result.summary.get('drawdown_pct', 0.0):.1f}% "
                f"{'[RECOVERY MODE]' if result.summary.get('drawdown_recovery_mode') else '[OK]'}",
                f"Market Condition:     {result.summary.get('market_condition', 'WATCH')}",
                f"Strategy Advisor:     {result.summary.get('strategy_advisor_mode', 'N/A')} | "
                f"{result.summary.get('strategy_advisor_top_action', 'keine Empfehlung')}",
                f"Agent Policy:         {result.summary.get('agent_policy_mode', 'N/A')} | "
                f"max entry {result.summary.get('agent_policy_max_entry_price', 1.0):.2f} | "
                f"{result.summary.get('agent_policy_city_cooldowns', 0)} city cooldown(s)",
                f"Agent Mode:           {result.summary.get('agent_mode', 'N/A')} | "
                f"{result.summary.get('agent_proposed_actions', 0)} Proposal(s)",
                f"Edge Hunter:          {result.summary.get('edge_hunter_posture', 'N/A')} | "
                f"{result.summary.get('edge_hunter_live_gate', 'WAIT')} | "
                f"{result.summary.get('edge_hunter_score', 0)}/10",
                f"Bot Health:           {result.summary.get('bot_health_status', 'N/A')} | "
                f"{'Guardrails aktiv' if result.summary.get('bot_health_guardrails_active') else 'keine Guardrails'}",
            ]

            if readiness_info:
                blockers = readiness_info.get("blocking_issues") or []
                blocker_label = f" | Blocker: {blockers[0][:50]}" if blockers else ""
                entry_lines.append(
                    f"Live-Readiness:       "
                    f"{readiness_info.get('overall_progress_pct', 0.0):.1f}% | "
                    f"{readiness_info.get('milestones_done', 0)}/"
                    f"{readiness_info.get('milestones_total', 6)} Meilensteine | "
                    f"YES-Trades {readiness_info.get('closed_yes_trades', 0)} | "
                    f"P&L {readiness_info.get('total_paper_pnl_eur', 0.0):+.2f} EUR | "
                    f"ETA {readiness_info.get('estimated_go_live_date') or 'n/a'}"
                    f"{blocker_label}"
                )

            if autonomous_status:
                city = autonomous_status.get("auto_city_blacklist") or {}
                tuner = autonomous_status.get("auto_parameter_tuner") or {}
                diag = autonomous_status.get("self_diagnostic") or {}
                tune_dec = (tuner.get("decision") or {}) if isinstance(tuner, dict) else {}
                tune_dir = tune_dec.get("direction", "hold")
                blocked = city.get("blocked_cities") or []
                blocked_str = ",".join(blocked[:3]) if blocked else "none"
                if len(blocked) > 3:
                    blocked_str += f"+{len(blocked)-3}"
                alerts = diag.get("alerts") or []
                alert_codes = [a.get("code") for a in alerts] if alerts else []
                entry_lines.append(
                    f"Autonomy:             "
                    f"city-block=[{blocked_str}] | "
                    f"param-tuner={tune_dir} | "
                    f"diag={','.join(alert_codes) if alert_codes else 'ok'}"
                )
                score = autonomous_status.get("agentic_score") or {}
                if score:
                    entry_lines.append(
                        f"Agentic-Score:        "
                        f"{score.get('score', 0.0):.1f}/10 | "
                        f"{score.get('fresh_components', 0)}/"
                        f"{score.get('total_components', 10)} Module aktiv"
                    )

            errors = [s for s in result.steps if not s.success]
            if errors:
                entry_lines.append(f"Errors: {len(errors)} step(s) failed")
                for e in errors:
                    entry_lines.append(f"  - {e.name}: {e.error[:50] if e.error else 'Unknown'}")

            entry_lines.append("")

            with open(summary_file, 'a', encoding='utf-8') as f:
                f.write('\n'.join(entry_lines))
            self._trim_status_summary(summary_file)

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
            append_control_event(
                "pipeline_run",
                component="orchestrator",
                status=result.state.value,
                level="INFO" if result.state == RunState.OK else "WARNING",
                message=f"run_id={result.summary.get('run_id', '')}",
                metrics={
                    "markets_fetched": result.summary.get("markets_fetched", 0),
                    "edge_observations": result.summary.get("edge_observations", 0),
                    "proposals_generated": result.summary.get("proposals_generated", 0),
                    "paper_positions_entered": result.summary.get("paper_positions_entered", 0),
                    "paper_positions_closed": result.summary.get("paper_positions_closed", 0),
                    "paper_pnl_eur": result.summary.get("paper_pnl_eur", 0),
                    "duration_seconds": result.summary.get("duration_seconds", 0),
                },
                context={
                    "run_id": result.summary.get("run_id", ""),
                    "market_condition": result.summary.get("market_condition", ""),
                    "bot_health_status": result.summary.get("bot_health_status", ""),
                },
            )

        except Exception as e:
            logger.error(f"Audit log failed: {e}")

    def _run_improvement_cycle(self) -> None:
        """Self-Improvement + Self-Healing: Parameter-Optimierung (non-blocking)."""
        try:
            from analytics.improvement_agent import run_improvement_cycle
            result = run_improvement_cycle()

            # Log health status
            health_status = result.get("health_status", "UNKNOWN")
            health_issues = result.get("health_issues", [])
            health_actions = result.get("health_actions", [])

            if health_issues:
                logger.info(f"[SELF-HEALING] Status={health_status} | Issues={health_issues} | Actions={len(health_actions)}")

            # Log improvement action
            action = result.get("action", "none")
            if action not in ("none", "waiting_for_data", "waiting", "experiment_running"):
                logger.info(f"[AUTO-IMPROVE] {action}: {result.get('param', '')} "
                            f"{result.get('old', '')} → {result.get('new', '')} "
                            f"| {result.get('reasoning', result.get('reason', ''))}")
        except Exception as e:
            logger.debug(f"Improvement Cycle fehlgeschlagen (unkritisch): {e}")

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
                with open(summary_file, "rb") as f:
                    f.seek(0, os.SEEK_END)
                    size = f.tell()
                    f.seek(max(0, size - 64 * 1024), os.SEEK_SET)
                    content = f.read().decode("utf-8", errors="ignore")
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
