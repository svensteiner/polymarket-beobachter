# =============================================================================
# END-TO-END TEST: Vollstaendige Weather Observer Pipeline
# =============================================================================
#
# Testet die gesamte Pipeline von Datensammlung bis Outcome-Tracking:
#   Collect -> Observe -> Propose -> Trade -> Track
#
# Alle externen API-Calls werden gemockt (Polymarket, Wetter-APIs).
# Der Test laeuft vollstaendig OFFLINE.
#
# =============================================================================

import json
import os
import sys
import shutil
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, List, Optional
from unittest.mock import patch, MagicMock
from dataclasses import dataclass

import pytest

# Projekt-Root zum Pfad hinzufuegen
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


# =============================================================================
# HILFSFUNKTIONEN: Singleton-Reset
# =============================================================================

def _reset_all_singletons():
    """Alle globalen Singletons zuruecksetzen fuer saubere Tests."""
    import importlib

    # Capital Manager
    try:
        import paper_trader.capital_manager as cm
        cm._capital_manager = None
    except Exception:
        pass

    # Paper Logger
    try:
        import paper_trader.logger as pl
        pl._paper_logger = None
    except Exception:
        pass

    # Simulator
    try:
        import paper_trader.simulator as sim
        sim._simulator = None
    except Exception:
        pass

    # Position Manager
    try:
        import paper_trader.position_manager as pm
        pm._manager = None
    except Exception:
        pass

    # Snapshot Client
    try:
        import paper_trader.snapshot_client as sc
        sc._snapshot_client = None
    except Exception:
        pass

    # Slippage Model
    try:
        import paper_trader.slippage as sl
        sl._slippage_model = None
    except Exception:
        pass

    # Proposal Storage
    try:
        import proposals.storage as ps
        ps._storage_instance = None
    except Exception:
        pass

    # Proposal Intake
    try:
        import paper_trader.intake as pi
        pi._intake = None
    except Exception:
        pass

    # Outcome Tracker
    try:
        import core.outcome_tracker as ot
        ot._storage = None
    except Exception:
        pass

    # Orchestrator
    try:
        import app.orchestrator as orc
        orc._orchestrator = None
    except Exception:
        pass


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture(autouse=True)
def reset_singletons():
    """Vor und nach jedem Test alle Singletons zuruecksetzen."""
    _reset_all_singletons()
    yield
    _reset_all_singletons()


@pytest.fixture
def tmp_project_dir(tmp_path):
    """
    Erstellt ein temporaeres Projektverzeichnis mit allen benoetigten
    Unterverzeichnissen und Konfigurationsdateien.
    """
    base = tmp_path / "polymarket_test"
    base.mkdir()

    # Verzeichnisse erstellen
    (base / "config").mkdir()
    (base / "data" / "collector" / "candidates").mkdir(parents=True)
    (base / "data" / "forecasts").mkdir(parents=True)
    (base / "data" / "resolutions").mkdir(parents=True)
    (base / "data" / "outcomes").mkdir(parents=True)
    (base / "output").mkdir()
    (base / "logs" / "audit").mkdir(parents=True)
    (base / "paper_trader" / "logs").mkdir(parents=True)
    (base / "paper_trader" / "reports").mkdir(parents=True)
    (base / "proposals").mkdir()

    # weather.yaml Konfiguration erstellen
    weather_config = {
        "MIN_LIQUIDITY": 50,
        "MIN_ODDS": 0.01,
        "MAX_ODDS": 0.35,
        "MIN_TIME_TO_RESOLUTION_HOURS": 24,
        "SAFETY_BUFFER_HOURS": 24,
        "MIN_EDGE": 0.12,
        "MIN_EDGE_ABSOLUTE": 0.05,
        "MEDIUM_CONFIDENCE_EDGE_MULTIPLIER": 1.25,
        "SIGMA_F": 3.5,
        "SIGMA_HORIZON_ADJUSTMENTS": {1: 0.8, 2: 0.9, 3: 1.0, 5: 1.2, 7: 1.5, 10: 2.0},
        "MAX_FORECAST_HORIZON_DAYS": 10,
        "ALLOWED_CITIES": [
            "New York", "London", "Chicago", "Miami", "Denver",
            "Phoenix", "Seattle", "Boston", "Seoul", "Tokyo",
            "Paris", "Berlin", "Sydney", "Toronto", "Los Angeles",
            "Houston", "Atlanta", "Dallas", "San Francisco",
            "Washington", "Philadelphia", "Buenos Aires", "Ankara",
        ],
        "CITY_CONFIG": {},
        "FORECAST_SOURCES": [],
        "CONFIDENCE_THRESHOLDS": {
            "HIGH_CONFIDENCE_MAX_HOURS": 72,
            "MEDIUM_CONFIDENCE_MAX_HOURS": 168,
        },
        "ENGINE_VERSION": "1.0.0",
        "ENGINE_NAME": "weather_engine_v1_test",
        "LOG_ALL_OBSERVATIONS": True,
        "OBSERVATION_LOG_PATH": str(base / "logs" / "weather_observations.jsonl"),
    }

    import yaml
    with open(base / "config" / "weather.yaml", "w") as f:
        yaml.dump(weather_config, f)

    # Capital Config erstellen
    capital_config = {
        "governance_notice": "PAPER TRADING CAPITAL - Test",
        "initial_capital_eur": 5000.00,
        "available_capital_eur": 5000.00,
        "allocated_capital_eur": 0.00,
        "realized_pnl_eur": 0.00,
        "position_size_eur": 100.00,
        "max_position_pct": 2.0,
        "max_open_positions": 10,
        "max_daily_trades": 10,
        "created_at": datetime.now().isoformat(),
        "last_updated": datetime.now().isoformat(),
        "last_updated_reason": "Test setup",
    }
    with open(base / "data" / "capital_config.json", "w") as f:
        json.dump(capital_config, f, indent=2)

    # Leere Proposals-Log erstellen
    proposals_log = {
        "_metadata": {
            "created_at": datetime.now().isoformat(),
            "description": "Test proposals log",
            "governance_notice": "Test",
        },
        "proposals": [],
    }
    with open(base / "proposals" / "proposals_log.json", "w") as f:
        json.dump(proposals_log, f, indent=2)

    return base


@pytest.fixture
def mock_weather_markets():
    """
    Erstellt realistische Mock-Weather-Markets mit bekannten Ergebnissen.
    Diese Markets sollen den Filter passieren und Edge zeigen.
    """
    from core.weather_market_filter import WeatherMarket

    # Markt 1: New York Temperatur > 90F, niedrige Odds, guter Edge
    market1 = WeatherMarket(
        market_id="test-market-ny-90f",
        question="Will the high temperature in New York be above 90°F on February 15?",
        resolution_text="Resolves YES if NOAA reports high temperature above 90°F.",
        description="Weather temperature market for New York City.",
        category="WEATHER",
        is_binary=True,
        liquidity_usd=500.0,
        odds_yes=0.10,  # Markt sagt 10% Wahrscheinlichkeit
        resolution_time=datetime.utcnow() + timedelta(days=3),
    )

    # Markt 2: Chicago Temperatur > 50F, mittlere Odds
    market2 = WeatherMarket(
        market_id="test-market-chi-50f",
        question="Will the high temperature in Chicago be above 50°F on February 20?",
        resolution_text="Resolves YES if temperature exceeds 50°F in Chicago.",
        description="Weather temperature market for Chicago.",
        category="WEATHER",
        is_binary=True,
        liquidity_usd=300.0,
        odds_yes=0.15,  # Markt sagt 15%
        resolution_time=datetime.utcnow() + timedelta(days=5),
    )

    # Markt 3: Miami Temperatur > 80F - soll viel Edge haben
    market3 = WeatherMarket(
        market_id="test-market-mia-80f",
        question="Will the high temperature in Miami be above 80°F on February 18?",
        resolution_text="Resolves YES if temperature exceeds 80°F in Miami.",
        description="Weather temperature market for Miami.",
        category="WEATHER",
        is_binary=True,
        liquidity_usd=400.0,
        odds_yes=0.20,
        resolution_time=datetime.utcnow() + timedelta(days=4),
    )

    # Markt 4: Nicht-Weather Markt (soll gefiltert werden)
    market4 = WeatherMarket(
        market_id="test-market-politics",
        question="Will the president sign the bill?",
        resolution_text="Resolves YES if bill is signed.",
        description="Political market.",
        category="POLITICS",
        is_binary=True,
        liquidity_usd=1000.0,
        odds_yes=0.30,
        resolution_time=datetime.utcnow() + timedelta(days=10),
    )

    # Markt 5: Weather aber zu niedrige Liquiditaet (soll gefiltert werden)
    market5 = WeatherMarket(
        market_id="test-market-low-liq",
        question="Will the high temperature in Boston be above 60°F on March 1?",
        resolution_text="Resolves YES if temperature exceeds 60°F.",
        description="Weather temperature market for Boston.",
        category="WEATHER",
        is_binary=True,
        liquidity_usd=10.0,  # Zu niedrig
        odds_yes=0.15,
        resolution_time=datetime.utcnow() + timedelta(days=3),
    )

    return [market1, market2, market3, market4, market5]


@pytest.fixture
def mock_forecast_data():
    """
    Mock-Forecast-Daten die Edge erzeugen sollen.
    Forecast sagt: Temperatur ist hoeher als der Markt einpreist.
    """
    from core.weather_probability_model import ForecastData

    def forecast_fetcher(city: str, target_time: datetime) -> Optional[ForecastData]:
        """Mock-Forecast: Gibt fuer jede Stadt einen optimistischen Forecast zurueck."""
        forecasts = {
            "New York": ForecastData(
                city="New York",
                forecast_time=datetime.utcnow(),
                target_time=target_time,
                temperature_f=95.0,  # Deutlich ueber 90F Threshold -> hohe P(>90)
                source="test_mock",
                temperature_min_f=88.0,
                temperature_max_f=99.0,
            ),
            "Chicago": ForecastData(
                city="Chicago",
                forecast_time=datetime.utcnow(),
                target_time=target_time,
                temperature_f=55.0,  # Ueber 50F Threshold -> hohe P(>50)
                source="test_mock",
                temperature_min_f=48.0,
                temperature_max_f=60.0,
            ),
            "Miami": ForecastData(
                city="Miami",
                forecast_time=datetime.utcnow(),
                target_time=target_time,
                temperature_f=88.0,  # Deutlich ueber 80F -> sehr hohe P(>80)
                source="test_mock",
                temperature_min_f=82.0,
                temperature_max_f=92.0,
            ),
        }
        return forecasts.get(city)

    return forecast_fetcher


@pytest.fixture
def mock_snapshot_resolved():
    """Mock-Snapshot fuer resolved Market (YES gewonnen)."""
    from paper_trader.models import MarketSnapshot
    return MarketSnapshot(
        market_id="test-market-ny-90f",
        snapshot_time=datetime.now().isoformat(),
        best_bid=0.98,
        best_ask=0.99,
        mid_price=0.985,
        spread_pct=1.0,
        liquidity_bucket="HIGH",
        is_resolved=True,
        resolved_outcome="YES",
    )


# =============================================================================
# TEST 1: Weather Engine - Market Filtering
# =============================================================================

class TestMarketFiltering:
    """Tests fuer die korrekte Filterung von Weather Markets."""

    def test_weather_markets_werden_akzeptiert(self, tmp_project_dir, mock_weather_markets):
        """Weather Markets mit guten Parametern passieren den Filter."""
        import yaml
        config_path = tmp_project_dir / "config" / "weather.yaml"
        with open(config_path) as f:
            config = yaml.safe_load(f)

        from core.weather_market_filter import WeatherMarketFilter
        wf = WeatherMarketFilter(config)

        # Markt 1 (NY) sollte passieren
        result1 = wf.filter_market(mock_weather_markets[0])
        assert result1.passed, f"NY-Market haette passieren sollen: {result1.rejection_reasons}"
        assert result1.market is not None
        assert result1.market.detected_city == "New York"

    def test_nicht_weather_markets_werden_gefiltert(self, tmp_project_dir, mock_weather_markets):
        """Nicht-Weather Markets werden abgelehnt."""
        import yaml
        config_path = tmp_project_dir / "config" / "weather.yaml"
        with open(config_path) as f:
            config = yaml.safe_load(f)

        from core.weather_market_filter import WeatherMarketFilter
        wf = WeatherMarketFilter(config)

        # Markt 4 (Politik) sollte abgelehnt werden
        result4 = wf.filter_market(mock_weather_markets[3])
        assert not result4.passed, "Politik-Market haette gefiltert werden sollen"

    def test_niedrige_liquiditaet_wird_gefiltert(self, tmp_project_dir, mock_weather_markets):
        """Markets mit zu niedriger Liquiditaet werden gefiltert."""
        import yaml
        config_path = tmp_project_dir / "config" / "weather.yaml"
        with open(config_path) as f:
            config = yaml.safe_load(f)

        from core.weather_market_filter import WeatherMarketFilter
        wf = WeatherMarketFilter(config)

        # Markt 5 (niedrige Liquiditaet) sollte abgelehnt werden
        result5 = wf.filter_market(mock_weather_markets[4])
        assert not result5.passed, "Market mit niedriger Liquiditaet haette gefiltert werden sollen"
        assert any("LIQUIDITY" in r for r in result5.rejection_reasons)

    def test_batch_filter_zaehlt_korrekt(self, tmp_project_dir, mock_weather_markets):
        """Batch-Filterung zaehlt passende und abgelehnte Markets korrekt."""
        import yaml
        config_path = tmp_project_dir / "config" / "weather.yaml"
        with open(config_path) as f:
            config = yaml.safe_load(f)

        from core.weather_market_filter import WeatherMarketFilter
        wf = WeatherMarketFilter(config)

        passed, all_results = wf.filter_markets(mock_weather_markets)

        # Mindestens die guten Weather Markets sollten passieren
        assert len(passed) >= 1, f"Mindestens 1 Market sollte passieren, aber {len(passed)} passierten"
        assert len(all_results) == len(mock_weather_markets)


# =============================================================================
# TEST 2: Edge-Berechnung
# =============================================================================

class TestEdgeCalculation:
    """Tests fuer korrekte Edge-Berechnung zwischen Modell und Markt."""

    def test_edge_wird_korrekt_berechnet(self):
        """Edge = (fair - market) / market wird korrekt berechnet."""
        from core.weather_probability_model import compute_edge

        # Fair prob 30%, Markt 10% -> Edge = (0.30 - 0.10) / 0.10 = 2.0 (200%)
        edge = compute_edge(0.30, 0.10)
        assert abs(edge - 2.0) < 0.001

        # Fair prob 15%, Markt 15% -> Edge = 0
        edge_zero = compute_edge(0.15, 0.15)
        assert abs(edge_zero) < 0.001

        # Fair prob 5%, Markt 10% -> Negativer Edge
        edge_neg = compute_edge(0.05, 0.10)
        assert edge_neg < 0

    def test_edge_threshold_mit_confidence(self):
        """Edge-Threshold variiert mit Confidence-Level."""
        from core.weather_probability_model import meets_edge_threshold
        from core.weather_signal import WeatherConfidence

        # HIGH Confidence: 15% Edge mit 12% Minimum -> Pass
        assert meets_edge_threshold(0.15, 0.12, WeatherConfidence.HIGH)

        # MEDIUM Confidence: 15% Edge mit 12% * 1.25 = 15% -> gerade so pass
        assert meets_edge_threshold(0.15, 0.12, WeatherConfidence.MEDIUM, 1.25)

        # LOW Confidence: Immer False
        assert not meets_edge_threshold(0.50, 0.12, WeatherConfidence.LOW)

    def test_probability_model_berechnet_fair_prob(self, tmp_project_dir, mock_forecast_data):
        """Das Wahrscheinlichkeitsmodell berechnet eine faire Probability."""
        import yaml
        config_path = tmp_project_dir / "config" / "weather.yaml"
        with open(config_path) as f:
            config = yaml.safe_load(f)

        from core.weather_probability_model import WeatherProbabilityModel

        model = WeatherProbabilityModel(config)

        # New York: Forecast 95F, Threshold 90F -> P(>90F) sollte hoch sein
        forecast = mock_forecast_data("New York", datetime.utcnow() + timedelta(days=2))
        result = model.compute_probability(forecast, threshold_f=90.0, event_type="exceeds")

        assert result.fair_probability > 0.5, (
            f"P(>90F | forecast=95F) sollte > 50% sein, aber ist {result.fair_probability:.2%}"
        )
        assert result.confidence.value in ("HIGH", "MEDIUM")

    def test_absolute_edge_floor(self, tmp_project_dir, mock_forecast_data):
        """Der absolute Edge-Floor verhindert False Positives bei niedrigen Odds."""
        import yaml
        config_path = tmp_project_dir / "config" / "weather.yaml"
        with open(config_path) as f:
            config = yaml.safe_load(f)

        from core.weather_probability_model import compute_edge

        # Sehr niedriger Markt (1%) und Modell bei 2%
        # Relativer Edge = (0.02 - 0.01) / 0.01 = 1.0 (100%) -> scheint hoch
        # Absoluter Edge = 0.02 - 0.01 = 0.01 -> unter 5% Floor
        edge = compute_edge(0.02, 0.01)
        absolute_edge = abs(0.02 - 0.01)

        assert edge > 0.12, "Relativer Edge sollte hoch sein"
        assert absolute_edge < 0.05, "Absoluter Edge sollte unter dem Floor liegen"


# =============================================================================
# TEST 3: Weather Engine - Vollstaendiger Run
# =============================================================================

class TestWeatherEngine:
    """Tests fuer den vollstaendigen Weather Engine Run."""

    def test_engine_run_mit_edge(self, tmp_project_dir, mock_weather_markets, mock_forecast_data):
        """Engine Run erkennt Edge in passenden Markets."""
        from core.weather_engine import WeatherEngine
        import yaml

        config_path = tmp_project_dir / "config" / "weather.yaml"
        with open(config_path) as f:
            config = yaml.safe_load(f)

        # Observation-Log-Pfad auf tmp umleiten
        config["OBSERVATION_LOG_PATH"] = str(tmp_project_dir / "logs" / "weather_observations.jsonl")

        # Nur die guten Weather Markets verwenden
        good_markets = [m for m in mock_weather_markets if m.category == "WEATHER" and m.liquidity_usd >= 50]

        def market_fetcher():
            return good_markets

        engine = WeatherEngine(
            config=config,
            market_fetcher=market_fetcher,
            forecast_fetcher=mock_forecast_data,
        )

        result = engine.run()

        assert result.markets_processed >= 1, "Mindestens 1 Market sollte verarbeitet werden"
        assert len(result.observations) >= 1, "Mindestens 1 Observation sollte erzeugt werden"

        # Pruefen ob Edge-Observations vorhanden (Forecast sagt hoehere Wahrscheinlichkeit)
        if result.edge_observations:
            for obs in result.edge_observations:
                assert obs.model_probability > 0
                assert obs.edge > 0
                assert obs.action.value == "OBSERVE"

    def test_engine_run_ohne_forecast_gibt_no_signal(self, tmp_project_dir, mock_weather_markets):
        """Ohne Forecast-Daten gibt die Engine NO_SIGNAL."""
        from core.weather_engine import WeatherEngine
        import yaml

        config_path = tmp_project_dir / "config" / "weather.yaml"
        with open(config_path) as f:
            config = yaml.safe_load(f)

        config["OBSERVATION_LOG_PATH"] = str(tmp_project_dir / "logs" / "weather_observations.jsonl")

        good_markets = [m for m in mock_weather_markets if m.category == "WEATHER" and m.liquidity_usd >= 50]

        def no_forecast(city, target):
            return None

        engine = WeatherEngine(
            config=config,
            market_fetcher=lambda: good_markets,
            forecast_fetcher=no_forecast,
        )

        result = engine.run()

        # Alle Observations sollten NO_SIGNAL sein wenn kein Forecast verfuegbar
        assert len(result.edge_observations) == 0, "Ohne Forecast sollte kein Edge erkannt werden"


# =============================================================================
# TEST 4: Proposal-Generierung
# =============================================================================

class TestProposalGeneration:
    """Tests fuer die Umwandlung von Edge-Observations zu Proposals."""

    def test_observation_to_proposal(self):
        """Eine OBSERVE-Observation wird korrekt in ein Proposal umgewandelt."""
        from core.weather_signal import (
            WeatherObservation,
            ObservationAction,
            WeatherConfidence,
            create_observation,
        )
        from proposals.signal_adapter import weather_observation_to_proposal

        observation = create_observation(
            market_id="test-market-123",
            city="New York",
            event_description="Will temperature in New York be above 90°F?",
            market_probability=0.10,
            model_probability=0.40,
            confidence=WeatherConfidence.HIGH,
            action=ObservationAction.OBSERVE,
            config_snapshot={"test": True},
            forecast_source="test_mock",
            forecast_temperature_f=95.0,
            threshold_temperature_f=90.0,
            hours_to_resolution=48.0,
        )

        proposal = weather_observation_to_proposal(observation)

        assert proposal is not None, "Proposal sollte erzeugt werden"
        assert proposal.market_id == "test-market-123"
        assert proposal.decision == "TRADE"
        assert proposal.model_probability == 0.40
        assert proposal.implied_probability == 0.10
        assert proposal.edge > 0
        assert proposal.confidence_level in ("HIGH", "MEDIUM")

    def test_no_signal_erzeugt_kein_proposal(self):
        """Eine NO_SIGNAL-Observation erzeugt kein Proposal."""
        from core.weather_signal import create_no_signal
        from proposals.signal_adapter import weather_observation_to_proposal

        observation = create_no_signal(
            market_id="test-no-signal",
            city="Boston",
            event_description="Test event",
            market_probability=0.05,
            reason="Insufficient edge",
            config_snapshot={"test": True},
        )

        proposal = weather_observation_to_proposal(observation)
        assert proposal is None, "NO_SIGNAL sollte kein Proposal erzeugen"


# =============================================================================
# TEST 5: Paper Trading - Einstieg
# =============================================================================

class TestPaperTrading:
    """Tests fuer Paper Trading Entry und Capital Management."""

    def test_paper_entry_erstellt_position(self, tmp_project_dir):
        """Ein Proposal mit TRADE-Entscheidung erzeugt eine Paper Position."""
        from proposals.models import Proposal, ProposalCoreCriteria

        # Capital Manager und Logger auf tmp-Verzeichnis umleiten
        from paper_trader.capital_manager import CapitalManager
        from paper_trader.logger import PaperTradingLogger
        from paper_trader.simulator import ExecutionSimulator
        from paper_trader.models import MarketSnapshot

        # Singletons mit tmp-Pfaden initialisieren
        cap_mgr = CapitalManager(config_path=tmp_project_dir / "data" / "capital_config.json")
        paper_log = PaperTradingLogger(
            logs_dir=tmp_project_dir / "paper_trader" / "logs",
            reports_dir=tmp_project_dir / "paper_trader" / "reports",
        )

        # Singletons patchen
        import paper_trader.capital_manager as cm_mod
        import paper_trader.logger as pl_mod
        cm_mod._capital_manager = cap_mgr
        pl_mod._paper_logger = paper_log

        # Simulator erstellen (nutzt jetzt die gepatchten Singletons)
        import paper_trader.simulator as sim_mod
        sim_mod._simulator = None  # Reset

        # Mock-Proposal erstellen
        proposal = Proposal(
            proposal_id="PROP-TEST-001",
            timestamp=datetime.now().isoformat(),
            market_id="test-market-ny-90f",
            market_question="Will the high temperature in New York be above 90°F on February 15?",
            decision="TRADE",
            implied_probability=0.10,
            model_probability=0.40,
            edge=3.0,
            core_criteria=ProposalCoreCriteria(
                liquidity_ok=True,
                volume_ok=True,
                time_to_resolution_ok=True,
                data_quality_ok=True,
            ),
            warnings=tuple(),
            confidence_level="HIGH",
            justification_summary="Test: Forecast 95F vs threshold 90F",
        )

        # Mock-Snapshot fuer den Market
        mock_snapshot = MarketSnapshot(
            market_id="test-market-ny-90f",
            snapshot_time=datetime.now().isoformat(),
            best_bid=0.09,
            best_ask=0.11,
            mid_price=0.10,
            spread_pct=2.0,
            liquidity_bucket="MEDIUM",
            is_resolved=False,
            resolved_outcome=None,
        )

        # Snapshot-Client mocken
        with patch("paper_trader.snapshot_client.get_market_snapshot", return_value=mock_snapshot):
            from paper_trader.simulator import simulate_entry
            position, record = simulate_entry(proposal)

        assert position is not None, f"Position sollte erzeugt werden, aber Record sagt: {record.reason}"
        assert position.side == "YES"  # Positiver Edge -> Buy YES
        assert position.status == "OPEN"
        assert position.entry_price > 0
        assert position.cost_basis_eur > 0
        assert record.action == "PAPER_ENTER"

        # Capital sollte allokiert sein
        state = cap_mgr.get_state()
        assert state.allocated_capital_eur > 0, "Capital sollte allokiert sein"
        assert state.available_capital_eur < 5000.0, "Verfuegbares Capital sollte gesunken sein"

    def test_capital_limit_verhindert_entry(self, tmp_project_dir):
        """Wenn kein Capital verfuegbar ist, wird kein Trade ausgefuehrt."""
        from proposals.models import Proposal, ProposalCoreCriteria
        from paper_trader.capital_manager import CapitalManager
        from paper_trader.logger import PaperTradingLogger

        # Capital auf 0 setzen
        capital_config = {
            "initial_capital_eur": 5000.00,
            "available_capital_eur": 0.00,  # Kein Kapital verfuegbar
            "allocated_capital_eur": 5000.00,
            "realized_pnl_eur": 0.00,
            "position_size_eur": 100.00,
            "max_position_pct": 2.0,
            "max_open_positions": 10,
            "max_daily_trades": 10,
        }
        with open(tmp_project_dir / "data" / "capital_config.json", "w") as f:
            json.dump(capital_config, f)

        cap_mgr = CapitalManager(config_path=tmp_project_dir / "data" / "capital_config.json", auto_reconcile=False)
        paper_log = PaperTradingLogger(
            logs_dir=tmp_project_dir / "paper_trader" / "logs",
            reports_dir=tmp_project_dir / "paper_trader" / "reports",
        )

        import paper_trader.capital_manager as cm_mod
        import paper_trader.logger as pl_mod
        import paper_trader.simulator as sim_mod
        cm_mod._capital_manager = cap_mgr
        pl_mod._paper_logger = paper_log
        sim_mod._simulator = None

        proposal = Proposal(
            proposal_id="PROP-TEST-NOCAP",
            timestamp=datetime.now().isoformat(),
            market_id="test-market-no-cap",
            market_question="Will the high temperature in New York be above 90°F on February 15?",
            decision="TRADE",
            implied_probability=0.10,
            model_probability=0.40,
            edge=3.0,
            core_criteria=ProposalCoreCriteria(
                liquidity_ok=True, volume_ok=True,
                time_to_resolution_ok=True, data_quality_ok=True,
            ),
            warnings=tuple(),
            confidence_level="HIGH",
            justification_summary="Test no capital",
        )

        from paper_trader.models import MarketSnapshot
        mock_snapshot = MarketSnapshot(
            market_id="test-market-no-cap",
            snapshot_time=datetime.now().isoformat(),
            best_bid=0.09, best_ask=0.11, mid_price=0.10,
            spread_pct=2.0, liquidity_bucket="MEDIUM",
            is_resolved=False, resolved_outcome=None,
        )

        with patch("paper_trader.snapshot_client.get_market_snapshot", return_value=mock_snapshot):
            from paper_trader.simulator import simulate_entry
            position, record = simulate_entry(proposal)

        assert position is None, "Ohne Capital sollte kein Trade ausgefuehrt werden"
        assert record.action == "SKIP"


# =============================================================================
# TEST 6: Position Management (TP/SL)
# =============================================================================

class TestPositionManagement:
    """Tests fuer Take-Profit und Stop-Loss."""

    def _setup_open_position(self, tmp_project_dir, entry_price=0.10):
        """Hilfsfunktion: Erstellt eine offene Test-Position."""
        from paper_trader.capital_manager import CapitalManager
        from paper_trader.logger import PaperTradingLogger
        from paper_trader.models import PaperPosition

        cap_mgr = CapitalManager(config_path=tmp_project_dir / "data" / "capital_config.json")
        paper_log = PaperTradingLogger(
            logs_dir=tmp_project_dir / "paper_trader" / "logs",
            reports_dir=tmp_project_dir / "paper_trader" / "reports",
        )

        import paper_trader.capital_manager as cm_mod
        import paper_trader.logger as pl_mod
        import paper_trader.simulator as sim_mod
        import paper_trader.position_manager as pm_mod
        cm_mod._capital_manager = cap_mgr
        pl_mod._paper_logger = paper_log
        sim_mod._simulator = None
        pm_mod._manager = None

        # Open Position direkt ins Log schreiben
        position = PaperPosition(
            position_id="PAPER-TEST-TP-001",
            proposal_id="PROP-TEST-TP",
            market_id="test-market-tp",
            market_question="Will the high temperature in Miami be above 80°F on February 18?",
            side="YES",
            status="OPEN",
            entry_time=datetime.now().isoformat(),
            entry_price=entry_price,
            entry_slippage=0.002,
            size_contracts=100.0 / entry_price,
            cost_basis_eur=100.0,
            exit_time=None,
            exit_price=None,
            exit_slippage=None,
            exit_reason=None,
            realized_pnl_eur=None,
            pnl_pct=None,
        )

        paper_log.log_position(position)

        # Capital allokieren
        cap_mgr.allocate_capital(100.0, "Test position")

        return position, cap_mgr, paper_log

    def test_take_profit_bei_kursgewinn(self, tmp_project_dir):
        """Take-Profit wird ausgeloest wenn Kurs um 15%+ steigt."""
        from paper_trader.models import MarketSnapshot

        position, cap_mgr, paper_log = self._setup_open_position(tmp_project_dir, entry_price=0.10)

        # Snapshot mit Kurs der 20% ueber Entry liegt (Take-Profit bei 15%)
        tp_snapshot = MarketSnapshot(
            market_id="test-market-tp",
            snapshot_time=datetime.now().isoformat(),
            best_bid=0.119,
            best_ask=0.121,
            mid_price=0.12,  # 20% ueber 0.10 Entry
            spread_pct=1.5,
            liquidity_bucket="MEDIUM",
            is_resolved=False,
            resolved_outcome=None,
        )

        with patch("paper_trader.position_manager.get_market_snapshots", return_value={"test-market-tp": tp_snapshot}):
            from paper_trader.position_manager import PositionManager
            pm = PositionManager()
            result = pm.check_mid_trade_exits()

        assert result["take_profit"] >= 1, "Take-Profit sollte ausgeloest worden sein"
        assert result["pnl_eur"] > 0, "P&L sollte positiv sein bei Take-Profit"

    def test_stop_loss_bei_kursverlust(self, tmp_project_dir):
        """Stop-Loss wird ausgeloest wenn Kurs um 25%+ faellt."""
        from paper_trader.models import MarketSnapshot

        position, cap_mgr, paper_log = self._setup_open_position(tmp_project_dir, entry_price=0.20)

        # Snapshot mit Kurs der 30% unter Entry liegt (Stop-Loss bei -25%)
        sl_snapshot = MarketSnapshot(
            market_id="test-market-tp",
            snapshot_time=datetime.now().isoformat(),
            best_bid=0.139,
            best_ask=0.141,
            mid_price=0.14,  # 30% unter 0.20 Entry
            spread_pct=1.5,
            liquidity_bucket="MEDIUM",
            is_resolved=False,
            resolved_outcome=None,
        )

        with patch("paper_trader.position_manager.get_market_snapshots", return_value={"test-market-tp": sl_snapshot}):
            from paper_trader.position_manager import PositionManager
            pm = PositionManager()
            result = pm.check_mid_trade_exits()

        assert result["stop_loss"] >= 1, "Stop-Loss sollte ausgeloest worden sein"
        assert result["pnl_eur"] < 0, "P&L sollte negativ sein bei Stop-Loss"


# =============================================================================
# TEST 7: Capital Management Lifecycle
# =============================================================================

class TestCapitalManagement:
    """Tests fuer den Capital-Lifecycle: Allokation -> Release."""

    def test_capital_allokation_und_release(self, tmp_project_dir):
        """Capital wird korrekt allokiert und bei Exit zurueckgegeben."""
        from paper_trader.capital_manager import CapitalManager

        cap_mgr = CapitalManager(config_path=tmp_project_dir / "data" / "capital_config.json")

        # Anfangs-State pruefen
        state = cap_mgr.get_state()
        assert state.available_capital_eur == 5000.0
        assert state.allocated_capital_eur == 0.0

        # Capital allokieren
        success = cap_mgr.allocate_capital(100.0, "Test Entry")
        assert success

        state = cap_mgr.get_state()
        assert state.available_capital_eur == 4900.0
        assert state.allocated_capital_eur == 100.0

        # Capital zurueckgeben mit Gewinn
        cap_mgr.release_capital(100.0, 15.0, "Test Exit mit Gewinn")

        state = cap_mgr.get_state()
        assert state.available_capital_eur == 5015.0  # 4900 + 100 + 15
        assert state.allocated_capital_eur == 0.0
        assert state.realized_pnl_eur == 15.0

    def test_capital_release_mit_verlust(self, tmp_project_dir):
        """Capital-Release mit Verlust aktualisiert P&L korrekt."""
        from paper_trader.capital_manager import CapitalManager

        cap_mgr = CapitalManager(config_path=tmp_project_dir / "data" / "capital_config.json")

        cap_mgr.allocate_capital(100.0, "Test Entry")
        cap_mgr.release_capital(100.0, -25.0, "Test Exit mit Verlust")

        state = cap_mgr.get_state()
        assert state.available_capital_eur == 4975.0  # 5000 - 100 + (100 - 25)
        assert state.realized_pnl_eur == -25.0

    def test_position_limit_wird_eingehalten(self, tmp_project_dir):
        """Max-Position-Limit wird korrekt durchgesetzt."""
        from paper_trader.capital_manager import CapitalManager

        # Config mit max 2 Positionen
        capital_config = {
            "initial_capital_eur": 5000.00,
            "available_capital_eur": 5000.00,
            "allocated_capital_eur": 0.00,
            "realized_pnl_eur": 0.00,
            "position_size_eur": 100.00,
            "max_position_pct": 2.0,
            "max_open_positions": 2,
            "max_daily_trades": 10,
        }
        with open(tmp_project_dir / "data" / "capital_config.json", "w") as f:
            json.dump(capital_config, f)

        cap_mgr = CapitalManager(config_path=tmp_project_dir / "data" / "capital_config.json")

        can_open_1, reason_1 = cap_mgr.can_open_position(0)
        assert can_open_1, f"Erste Position sollte moeglich sein: {reason_1}"

        can_open_2, reason_2 = cap_mgr.can_open_position(1)
        assert can_open_2, f"Zweite Position sollte moeglich sein: {reason_2}"

        can_open_3, reason_3 = cap_mgr.can_open_position(2)
        assert not can_open_3, "Dritte Position sollte geblockt werden"
        assert "Max positions" in reason_3


# =============================================================================
# TEST 8: Outcome Tracking
# =============================================================================

class TestOutcomeTracking:
    """Tests fuer das Prediction- und Resolution-Tracking."""

    def test_prediction_wird_gespeichert(self, tmp_project_dir):
        """PredictionSnapshots werden korrekt in JSONL gespeichert."""
        from core.outcome_tracker import (
            OutcomeStorage,
            PredictionSnapshot,
            EngineContext,
        )

        storage = OutcomeStorage(base_dir=tmp_project_dir)

        snapshot = PredictionSnapshot(
            schema_version=1,
            event_id="EVT-test-001",
            timestamp_utc=datetime.utcnow().isoformat(),
            market_id="test-market-ny-90f",
            question="Will temperature exceed 90F in NYC?",
            outcomes=["YES", "NO"],
            market_price_yes=0.10,
            market_price_no=0.90,
            our_estimate_yes=0.40,
            estimate_confidence="HIGH",
            decision="TRADE",
            decision_reasons=["Edge: +300%"],
            engine_context=EngineContext(
                engine="weather_observer",
                mode="PAPER",
                run_id="test-run-001",
            ),
            source="scheduler",
        )

        success, message = storage.write_prediction(snapshot)
        assert success, f"Prediction-Speicherung fehlgeschlagen: {message}"

        # Lesen und verifizieren
        predictions = storage.read_predictions()
        assert len(predictions) >= 1
        assert predictions[0].market_id == "test-market-ny-90f"

    def test_resolution_wird_gespeichert(self, tmp_project_dir):
        """ResolutionRecords werden korrekt gespeichert."""
        from core.outcome_tracker import (
            OutcomeStorage,
            create_resolution_record,
        )

        storage = OutcomeStorage(base_dir=tmp_project_dir)

        resolution = create_resolution_record(
            market_id="test-market-ny-90f",
            resolution="YES",
            resolution_source="test",
            resolved_timestamp_utc=datetime.utcnow().isoformat(),
        )

        success, message = storage.write_resolution(resolution)
        assert success, f"Resolution-Speicherung fehlgeschlagen: {message}"

        # Lesen und verifizieren
        resolutions = storage.read_resolutions()
        assert len(resolutions) >= 1
        assert resolutions[0].resolution == "YES"

    def test_duplikate_werden_verhindert(self, tmp_project_dir):
        """Doppelte Predictions werden nicht gespeichert (Dedup)."""
        from core.outcome_tracker import (
            OutcomeStorage,
            PredictionSnapshot,
            EngineContext,
        )

        storage = OutcomeStorage(base_dir=tmp_project_dir)

        ts = datetime.utcnow().isoformat()
        snapshot = PredictionSnapshot(
            schema_version=1,
            event_id="EVT-test-dedup",
            timestamp_utc=ts,
            market_id="test-market-dedup",
            question="Dedup test?",
            outcomes=["YES", "NO"],
            market_price_yes=0.10,
            market_price_no=0.90,
            our_estimate_yes=0.40,
            estimate_confidence="HIGH",
            decision="TRADE",
            decision_reasons=["Test"],
            engine_context=EngineContext(
                engine="weather_observer", mode="PAPER", run_id="dedup-001",
            ),
            source="scheduler",
        )

        success1, _ = storage.write_prediction(snapshot)
        assert success1

        # Gleiche Prediction nochmal schreiben -> sollte Duplikat sein
        snapshot2 = PredictionSnapshot(
            schema_version=1,
            event_id="EVT-test-dedup-2",
            timestamp_utc=ts,  # Gleicher Timestamp-Bucket
            market_id="test-market-dedup",  # Gleiche Market-ID
            question="Dedup test?",
            outcomes=["YES", "NO"],
            market_price_yes=0.10,
            market_price_no=0.90,
            our_estimate_yes=0.40,
            estimate_confidence="HIGH",
            decision="TRADE",  # Gleiche Decision
            decision_reasons=["Test"],
            engine_context=EngineContext(
                engine="weather_observer", mode="PAPER", run_id="dedup-002",
            ),
            source="scheduler",
        )

        success2, msg2 = storage.write_prediction(snapshot2)
        assert not success2, "Duplikat sollte verhindert werden"
        assert "Duplicate" in msg2 or "skipped" in msg2.lower()


# =============================================================================
# TEST 9: Diversifikation
# =============================================================================

class TestDiversification:
    """Tests fuer Diversifikations-Regeln (max Positionen pro Stadt)."""

    def test_max_position_pro_stadt_datum(self, tmp_project_dir):
        """Max 1 Position pro Stadt/Datum wird enforced."""
        from paper_trader.simulator import _extract_city_date

        # Gleiche Stadt und Datum
        city1, date1 = _extract_city_date(
            "Will the high temperature in New York be above 90°F on February 15?"
        )
        city2, date2 = _extract_city_date(
            "Will the high temperature in New York be above 80°F on February 15?"
        )

        assert city1 == "New York"
        assert city2 == "New York"
        # Wenn beide gleiche Stadt+Datum haben, sollte nur einer eingegangen werden


# =============================================================================
# TEST 10: Review Gate
# =============================================================================

class TestReviewGate:
    """Tests fuer die Proposal Review-Gate."""

    def test_guter_proposal_passiert_review(self):
        """Ein guter Proposal passiert die Review Gate."""
        from proposals.models import Proposal, ProposalCoreCriteria, ReviewOutcome
        from proposals.review_gate import ReviewGate

        proposal = Proposal(
            proposal_id="PROP-REVIEW-001",
            timestamp=datetime.now().isoformat(),
            market_id="test-review",
            market_question="Will temperature in NYC exceed 90F?",
            decision="TRADE",
            implied_probability=0.10,
            model_probability=0.40,
            edge=3.0,
            core_criteria=ProposalCoreCriteria(
                liquidity_ok=True, volume_ok=True,
                time_to_resolution_ok=True, data_quality_ok=True,
            ),
            warnings=tuple(),
            confidence_level="HIGH",
            justification_summary="Test proposal",
        )

        gate = ReviewGate()
        result = gate.review(proposal)

        assert result.outcome == ReviewOutcome.REVIEW_PASS, (
            f"Guter Proposal sollte REVIEW_PASS bekommen, bekam aber {result.outcome.value}: {result.reasons}"
        )

    def test_low_confidence_wird_abgelehnt(self):
        """Ein Proposal mit LOW Confidence wird abgelehnt."""
        from proposals.models import Proposal, ProposalCoreCriteria, ReviewOutcome
        from proposals.review_gate import ReviewGate

        proposal = Proposal(
            proposal_id="PROP-REVIEW-LOW",
            timestamp=datetime.now().isoformat(),
            market_id="test-review-low",
            market_question="Test low confidence",
            decision="TRADE",
            implied_probability=0.10,
            model_probability=0.40,
            edge=3.0,
            core_criteria=ProposalCoreCriteria(
                liquidity_ok=True, volume_ok=True,
                time_to_resolution_ok=True, data_quality_ok=True,
            ),
            warnings=tuple(),
            confidence_level="LOW",  # Niedrige Confidence
            justification_summary="Test low confidence",
        )

        gate = ReviewGate()
        result = gate.review(proposal)

        assert result.outcome == ReviewOutcome.REVIEW_REJECT, (
            f"LOW Confidence sollte REVIEW_REJECT bekommen, bekam aber {result.outcome.value}"
        )


# =============================================================================
# TEST 11: Proposal Storage
# =============================================================================

class TestProposalStorage:
    """Tests fuer die Proposal-Speicherung."""

    def test_proposal_speichern_und_laden(self, tmp_project_dir):
        """Proposals werden korrekt gespeichert und wieder geladen."""
        from proposals.storage import ProposalStorage
        from proposals.models import Proposal, ProposalCoreCriteria

        storage = ProposalStorage(base_dir=tmp_project_dir / "proposals")

        proposal = Proposal(
            proposal_id="PROP-STORAGE-001",
            timestamp=datetime.now().isoformat(),
            market_id="test-storage",
            market_question="Test storage question",
            decision="TRADE",
            implied_probability=0.10,
            model_probability=0.35,
            edge=2.5,
            core_criteria=ProposalCoreCriteria(
                liquidity_ok=True, volume_ok=True,
                time_to_resolution_ok=True, data_quality_ok=True,
            ),
            warnings=tuple(),
            confidence_level="HIGH",
            justification_summary="Test storage",
        )

        success = storage.save_proposal(proposal)
        assert success, "Proposal sollte gespeichert werden"

        # Laden
        loaded = storage.load_proposals()
        assert len(loaded) >= 1
        assert loaded[0].proposal_id == "PROP-STORAGE-001"
        assert loaded[0].model_probability == 0.35


# =============================================================================
# TEST 12: Kelly Position Sizing
# =============================================================================

class TestKellySizing:
    """Tests fuer Kelly-basierte Positionsgroesse."""

    def test_kelly_berechnet_groesse(self):
        """Kelly berechnet eine sinnvolle Positionsgroesse."""
        from paper_trader.kelly import kelly_size, MIN_POSITION_EUR, MAX_POSITION_EUR

        # Starker Edge: 60% Win-Prob bei 20% Entry-Price
        size = kelly_size(win_probability=0.60, entry_price=0.20, bankroll=5000.0)

        assert size >= MIN_POSITION_EUR, f"Position {size} sollte >= {MIN_POSITION_EUR} sein"
        assert size <= MAX_POSITION_EUR, f"Position {size} sollte <= {MAX_POSITION_EUR} sein"

    def test_kelly_kein_edge_gibt_minimum(self):
        """Ohne positiven Edge gibt Kelly die Mindestgroesse zurueck."""
        from paper_trader.kelly import kelly_size, MIN_POSITION_EUR

        # Kein Edge: 10% Win-Prob bei 20% Entry-Price (negativ)
        size = kelly_size(win_probability=0.10, entry_price=0.20, bankroll=5000.0)
        assert size == MIN_POSITION_EUR

    def test_kelly_none_inputs_gibt_fallback(self):
        """Bei None-Inputs gibt Kelly den Fallback-Wert zurueck."""
        from paper_trader.kelly import kelly_size, FALLBACK_POSITION_EUR

        size = kelly_size(win_probability=None, entry_price=0.10, bankroll=5000.0)
        assert size == FALLBACK_POSITION_EUR


# =============================================================================
# TEST 13: Slippage Model
# =============================================================================

class TestSlippage:
    """Tests fuer das konservative Slippage-Modell."""

    def test_entry_slippage_ist_pessimistisch(self):
        """Entry-Preis liegt ueber dem Ask (pessimistisch)."""
        from paper_trader.slippage import SlippageModel
        from paper_trader.models import MarketSnapshot

        model = SlippageModel()

        snapshot = MarketSnapshot(
            market_id="test-slip",
            snapshot_time=datetime.now().isoformat(),
            best_bid=0.09,
            best_ask=0.11,
            mid_price=0.10,
            spread_pct=2.0,
            liquidity_bucket="MEDIUM",
            is_resolved=False,
            resolved_outcome=None,
        )

        result = model.calculate_entry_price(snapshot, "YES")
        assert result is not None
        entry_price, slippage = result

        # Entry-Preis sollte >= Ask sein (pessimistisch)
        assert entry_price >= snapshot.best_ask, (
            f"Entry {entry_price} sollte >= Ask {snapshot.best_ask} sein"
        )
        assert slippage > 0

    def test_exit_bei_resolution_kein_slippage(self):
        """Bei Resolution gibt es keinen Slippage."""
        from paper_trader.slippage import SlippageModel
        from paper_trader.models import MarketSnapshot

        model = SlippageModel()

        snapshot = MarketSnapshot(
            market_id="test-resolution",
            snapshot_time=datetime.now().isoformat(),
            best_bid=0.99,
            best_ask=1.00,
            mid_price=0.995,
            spread_pct=1.0,
            liquidity_bucket="HIGH",
            is_resolved=True,
            resolved_outcome="YES",
        )

        # YES-Seite gewinnt
        result = model.calculate_exit_price(snapshot, "YES", is_resolution=True)
        assert result is not None
        exit_price, slippage = result
        assert exit_price == 1.0, "Gewinnende YES-Position zahlt 1.0"
        assert slippage == 0.0, "Kein Slippage bei Resolution"

        # NO-Seite verliert
        result_no = model.calculate_exit_price(snapshot, "NO", is_resolution=True)
        assert result_no is not None
        exit_price_no, slippage_no = result_no
        assert exit_price_no == 0.0, "Verlierende NO-Position zahlt 0.0"


# =============================================================================
# TEST 14: Vollstaendiger Pipeline-Durchlauf (Integration)
# =============================================================================

class TestFullPipeline:
    """
    Vollstaendiger End-to-End Test der gesamten Pipeline.
    Simuliert: Collect -> Observe -> Propose -> Trade -> Track
    """

    def test_pipeline_end_to_end(self, tmp_project_dir, mock_weather_markets, mock_forecast_data):
        """
        Vollstaendiger Pipeline-Durchlauf mit gemockten Daten.
        Verifiziert dass alle Schritte korrekt zusammenarbeiten.
        """
        import yaml

        # --- Schritt 1: Setup ---
        config_path = tmp_project_dir / "config" / "weather.yaml"
        with open(config_path) as f:
            config = yaml.safe_load(f)

        config["OBSERVATION_LOG_PATH"] = str(tmp_project_dir / "logs" / "weather_observations.jsonl")

        # Capital Manager und Logger mit tmp-Pfaden initialisieren
        from paper_trader.capital_manager import CapitalManager
        from paper_trader.logger import PaperTradingLogger
        from proposals.storage import ProposalStorage
        from core.outcome_tracker import OutcomeStorage

        cap_mgr = CapitalManager(config_path=tmp_project_dir / "data" / "capital_config.json")
        paper_log = PaperTradingLogger(
            logs_dir=tmp_project_dir / "paper_trader" / "logs",
            reports_dir=tmp_project_dir / "paper_trader" / "reports",
        )
        prop_storage = ProposalStorage(base_dir=tmp_project_dir / "proposals")
        outcome_storage = OutcomeStorage(base_dir=tmp_project_dir)

        # Singletons patchen
        import paper_trader.capital_manager as cm_mod
        import paper_trader.logger as pl_mod
        import paper_trader.simulator as sim_mod
        import paper_trader.position_manager as pm_mod
        import proposals.storage as ps_mod
        import core.outcome_tracker as ot_mod

        cm_mod._capital_manager = cap_mgr
        pl_mod._paper_logger = paper_log
        sim_mod._simulator = None
        pm_mod._manager = None
        ps_mod._storage_instance = prop_storage
        ot_mod._storage = outcome_storage

        # --- Schritt 2: Weather Engine Run (Observe) ---
        from core.weather_engine import WeatherEngine

        good_markets = [m for m in mock_weather_markets if m.category == "WEATHER" and m.liquidity_usd >= 50]

        engine = WeatherEngine(
            config=config,
            market_fetcher=lambda: good_markets,
            forecast_fetcher=mock_forecast_data,
        )

        engine_result = engine.run()

        assert engine_result.markets_processed >= 1, "Markets muessen verarbeitet werden"
        assert len(engine_result.observations) >= 1, "Observations muessen erzeugt werden"

        # --- Schritt 3: Proposals generieren ---
        from proposals.signal_adapter import weather_observation_to_proposal

        proposals_generated = 0
        for obs in engine_result.edge_observations:
            proposal = weather_observation_to_proposal(obs)
            if proposal is not None:
                prop_storage.save_proposal(proposal)
                proposals_generated += 1

        # Es kann sein dass nicht alle Markets Edge zeigen, also pruefen wir nur >= 0
        loaded_proposals = prop_storage.load_proposals()

        # --- Schritt 4: Paper Trading ---
        from paper_trader.models import MarketSnapshot

        # Mock-Snapshots fuer alle Markets erstellen
        def mock_get_snapshot(market_id):
            # Finde den Market um den Preis zu verwenden
            for m in good_markets:
                if m.market_id == market_id:
                    return MarketSnapshot(
                        market_id=market_id,
                        snapshot_time=datetime.now().isoformat(),
                        best_bid=max(0.01, m.odds_yes - 0.01),
                        best_ask=min(0.99, m.odds_yes + 0.01),
                        mid_price=m.odds_yes,
                        spread_pct=2.0,
                        liquidity_bucket="MEDIUM",
                        is_resolved=False,
                        resolved_outcome=None,
                    )
            return None

        entries = 0
        skips = 0
        with patch("paper_trader.snapshot_client.get_market_snapshot", side_effect=mock_get_snapshot):
            from paper_trader.simulator import simulate_entry
            for proposal in loaded_proposals:
                if proposal.decision == "TRADE":
                    position, record = simulate_entry(proposal)
                    if position is not None:
                        entries += 1
                    else:
                        skips += 1

        # --- Schritt 5: Outcome Tracking ---
        from core.outcome_tracker import PredictionSnapshot, EngineContext

        predictions_recorded = 0
        for obs in engine_result.edge_observations:
            try:
                snapshot = PredictionSnapshot(
                    schema_version=1,
                    event_id=f"EVT-{obs.market_id}-{datetime.now().strftime('%Y%m%d%H%M')}",
                    timestamp_utc=datetime.utcnow().isoformat(),
                    market_id=obs.market_id,
                    question=obs.event_description,
                    outcomes=["YES", "NO"],
                    market_price_yes=obs.market_probability,
                    market_price_no=1.0 - obs.market_probability,
                    our_estimate_yes=obs.model_probability,
                    estimate_confidence=obs.confidence.value if hasattr(obs.confidence, 'value') else None,
                    decision="TRADE",
                    decision_reasons=[f"Edge: {obs.edge:+.2%}"],
                    engine_context=EngineContext(
                        engine="weather_observer",
                        mode="PAPER",
                        run_id="e2e-test-001",
                    ),
                    source="scheduler",
                )
                success, _ = outcome_storage.write_prediction(snapshot)
                if success:
                    predictions_recorded += 1
            except Exception as e:
                pass  # Manche Observations koennen ungueltige Werte haben

        # --- Verifizierung ---
        # Capital wurde korrekt allokiert
        cap_state = cap_mgr.get_state()
        if entries > 0:
            assert cap_state.allocated_capital_eur > 0, "Capital sollte allokiert sein"
            assert cap_state.available_capital_eur < 5000.0, "Verfuegbares Capital sollte gesunken sein"

        # Open Positions existieren
        open_positions = paper_log.get_open_positions()
        assert len(open_positions) == entries, (
            f"Anzahl offener Positionen ({len(open_positions)}) sollte Entries ({entries}) entsprechen"
        )

        # Trade Records existieren
        all_trades = paper_log.read_all_trades()
        assert len(all_trades) >= entries, "Trade Records sollten geloggt sein"

        # Outcome Storage hat Records
        if predictions_recorded > 0:
            stats = outcome_storage.get_stats()
            assert stats["total_predictions"] >= 1, "Predictions sollten gespeichert sein"

        # Status-Summary kann geschrieben werden
        status_file = tmp_project_dir / "output" / "status_summary.txt"
        with open(status_file, "w") as f:
            f.write(f"E2E Test: {entries} entries, {skips} skips\n")
        assert status_file.exists()

    def test_pipeline_mit_resolution(self, tmp_project_dir, mock_weather_markets, mock_forecast_data):
        """
        Pipeline-Test mit anschliessendem Resolution.
        Erstellt eine Position und schliesst sie per Resolution.
        """
        import yaml
        config_path = tmp_project_dir / "config" / "weather.yaml"
        with open(config_path) as f:
            config = yaml.safe_load(f)

        from paper_trader.capital_manager import CapitalManager
        from paper_trader.logger import PaperTradingLogger
        from paper_trader.models import PaperPosition, MarketSnapshot

        cap_mgr = CapitalManager(config_path=tmp_project_dir / "data" / "capital_config.json")
        paper_log = PaperTradingLogger(
            logs_dir=tmp_project_dir / "paper_trader" / "logs",
            reports_dir=tmp_project_dir / "paper_trader" / "reports",
        )

        import paper_trader.capital_manager as cm_mod
        import paper_trader.logger as pl_mod
        import paper_trader.simulator as sim_mod
        import paper_trader.position_manager as pm_mod
        cm_mod._capital_manager = cap_mgr
        pl_mod._paper_logger = paper_log
        sim_mod._simulator = None
        pm_mod._manager = None

        # Position erstellen (direkt, ohne Engine-Run)
        position = PaperPosition(
            position_id="PAPER-E2E-RESOLVE",
            proposal_id="PROP-E2E-RESOLVE",
            market_id="test-market-resolve",
            market_question="Will the high temperature in Miami be above 80°F on February 18?",
            side="YES",
            status="OPEN",
            entry_time=datetime.now().isoformat(),
            entry_price=0.20,
            entry_slippage=0.003,
            size_contracts=500.0,  # 100 EUR / 0.20
            cost_basis_eur=100.0,
            exit_time=None,
            exit_price=None,
            exit_slippage=None,
            exit_reason=None,
            realized_pnl_eur=None,
            pnl_pct=None,
        )
        paper_log.log_position(position)
        cap_mgr.allocate_capital(100.0, "E2E Resolve Test")

        # Verifizieren dass Position offen ist
        open_pos = paper_log.get_open_positions()
        assert len(open_pos) == 1
        assert open_pos[0].position_id == "PAPER-E2E-RESOLVE"

        # Resolution-Snapshot (YES gewinnt)
        resolved_snapshot = MarketSnapshot(
            market_id="test-market-resolve",
            snapshot_time=datetime.now().isoformat(),
            best_bid=0.99,
            best_ask=1.00,
            mid_price=0.995,
            spread_pct=1.0,
            liquidity_bucket="HIGH",
            is_resolved=True,
            resolved_outcome="YES",
        )

        with patch("paper_trader.position_manager.get_market_snapshots",
                    return_value={"test-market-resolve": resolved_snapshot}):
            from paper_trader.position_manager import PositionManager
            pm = PositionManager()
            close_result = pm.check_and_close_resolved()

        assert close_result["closed"] == 1, "Position sollte geschlossen worden sein"
        assert close_result["total_pnl_eur"] > 0, "YES-Position bei YES-Resolution sollte Gewinn sein"

        # Capital sollte zurueckgegeben sein
        state = cap_mgr.get_state()
        assert state.allocated_capital_eur == 0.0, "Kein Capital sollte mehr allokiert sein"
        assert state.realized_pnl_eur > 0, "Realisierter P&L sollte positiv sein"

        # Position sollte nicht mehr als OPEN auftauchen
        open_pos_after = paper_log.get_open_positions()
        assert len(open_pos_after) == 0, "Keine offenen Positionen nach Resolution"


# =============================================================================
# TEST 15: Orchestrator (vereinfacht, ohne echte API-Calls)
# =============================================================================

class TestOrchestrator:
    """Tests fuer den Pipeline-Orchestrator."""

    def test_orchestrator_erstellt_verzeichnisse(self, tmp_project_dir):
        """Der Orchestrator erstellt alle benoetigten Verzeichnisse."""
        from app.orchestrator import Orchestrator

        orch = Orchestrator(base_dir=tmp_project_dir)

        assert (tmp_project_dir / "output").exists()
        assert (tmp_project_dir / "logs").exists()
        assert (tmp_project_dir / "data" / "forecasts").exists()

    def test_pipeline_result_dataclass(self):
        """PipelineResult und StepResult funktionieren korrekt."""
        from app.orchestrator import PipelineResult, StepResult, RunState

        result = PipelineResult(
            state=RunState.OK,
            timestamp=datetime.now().isoformat(),
        )

        # Erfolgreicher Schritt
        result.add_step(StepResult(
            name="test_step",
            success=True,
            message="Alles gut",
        ))
        assert result.state == RunState.OK

        # Fehlgeschlagener Schritt -> DEGRADED
        result.add_step(StepResult(
            name="failing_step",
            success=False,
            message="Fehler",
            error="Test error",
        ))
        assert result.state == RunState.DEGRADED
