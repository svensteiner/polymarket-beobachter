# =============================================================================
# POLYMARKET BEOBACHTER - MOCK DATA GENERATORS
# =============================================================================
#
# PURPOSE:
# Generate realistic mock data for all market categories to enable
# comprehensive end-to-end testing without network dependencies.
#
# CATEGORIES COVERED:
# - EU_REGULATION
# - WEATHER_EVENT
# - CORPORATE_EVENT
# - COURT_RULING
#
# =============================================================================

import uuid
from datetime import date, datetime, timedelta
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field


# =============================================================================
# MOCK MARKET TEMPLATES
# =============================================================================


@dataclass
class MockMarket:
    """Mock market data structure."""
    market_id: str
    title: str
    description: str
    resolution_text: str
    category: str
    end_date: str
    expected_decision: str  # TRADE, NO_TRADE, INSUFFICIENT_DATA
    expected_reason: str
    market_price: float = 0.5

    def to_dict(self) -> Dict[str, Any]:
        return {
            "market_id": self.market_id,
            "question": self.title,
            "title": self.title,
            "description": self.description,
            "resolutionSource": self.resolution_text,
            "resolution": self.resolution_text,
            "category": self.category,
            "endDate": self.end_date,
            "end_date": self.end_date,
            "market_price": self.market_price,
        }


# =============================================================================
# EU REGULATION MOCKS
# =============================================================================


def create_eu_regulation_valid() -> MockMarket:
    """Create a valid EU regulation market that should pass."""
    future_date = (date.today() + timedelta(days=180)).isoformat()
    return MockMarket(
        market_id=f"EU-VALID-{uuid.uuid4().hex[:8]}",
        title="Will the EU AI Act implementing acts be published in the Official Journal by June 2026?",
        description=(
            "This market resolves to YES if the European Commission publishes "
            "the implementing acts for the AI Act in the Official Journal of the "
            "European Union (EUR-Lex) before June 30, 2026."
        ),
        resolution_text=(
            "Resolution source: Official Journal of the European Union (EUR-Lex). "
            "The market resolves YES if implementing acts reference AI Act Article 6 "
            "are published. Resolution is binary: YES if published, NO otherwise."
        ),
        category="EU_REGULATION",
        end_date=future_date,
        expected_decision="TRADE",
        expected_reason="All criteria met for EU regulatory market",
        market_price=0.35,
    )


def create_eu_regulation_invalid_vague() -> MockMarket:
    """Create an invalid EU market with vague resolution."""
    future_date = (date.today() + timedelta(days=90)).isoformat()
    return MockMarket(
        market_id=f"EU-INVALID-VAGUE-{uuid.uuid4().hex[:8]}",
        title="Will the EU do something about AI regulation?",
        description="General question about EU AI policy.",
        resolution_text="We will decide based on news reports and expert opinions.",
        category="EU_REGULATION",
        end_date=future_date,
        expected_decision="NO_TRADE",
        expected_reason="Resolution is vague and subjective",
        market_price=0.5,
    )


def create_eu_regulation_invalid_past() -> MockMarket:
    """Create an invalid EU market with past date."""
    past_date = (date.today() - timedelta(days=30)).isoformat()
    return MockMarket(
        market_id=f"EU-INVALID-PAST-{uuid.uuid4().hex[:8]}",
        title="Will GDPR fines exceed 1B EUR in 2024?",
        description="EU GDPR enforcement market.",
        resolution_text="Based on official EDPB annual report.",
        category="EU_REGULATION",
        end_date=past_date,
        expected_decision="NO_TRADE",
        expected_reason="Target date is in the past",
        market_price=0.7,
    )


# =============================================================================
# WEATHER EVENT MOCKS
# =============================================================================


def create_weather_valid() -> MockMarket:
    """Create a valid weather market that should pass."""
    future_date = (date.today() + timedelta(days=30)).isoformat()
    return MockMarket(
        market_id=f"WEATHER-VALID-{uuid.uuid4().hex[:8]}",
        title="Will temperature at JFK Airport (KJFK) exceed 40°C by July 31, 2026?",
        description=(
            "This market tracks whether the official temperature reading at "
            "John F. Kennedy International Airport exceeds 40 degrees Celsius."
        ),
        resolution_text=(
            "Resolution source: NOAA METAR data for station KJFK. "
            "Market resolves YES if any official reading shows temperature >= 40°C "
            "before 11:59 PM EST on July 31, 2026. Resolution is binary."
        ),
        category="WEATHER_EVENT",
        end_date=future_date,
        expected_decision="TRADE",
        expected_reason="All 6 weather criteria met",
        market_price=0.15,
    )


def create_weather_invalid_vague_metric() -> MockMarket:
    """Create invalid weather market with vague metric."""
    future_date = (date.today() + timedelta(days=60)).isoformat()
    return MockMarket(
        market_id=f"WEATHER-INVALID-VAGUE-{uuid.uuid4().hex[:8]}",
        title="Will there be significant rainfall in New York this summer?",
        description="Weather prediction for NYC area.",
        resolution_text="Based on whether it rains a lot.",
        category="WEATHER_EVENT",
        end_date=future_date,
        expected_decision="INSUFFICIENT_DATA",
        expected_reason="Vague metric (significant), no official source, ambiguous location",
        market_price=0.5,
    )


def create_weather_invalid_no_source() -> MockMarket:
    """Create invalid weather market without official source."""
    future_date = (date.today() + timedelta(days=45)).isoformat()
    return MockMarket(
        market_id=f"WEATHER-INVALID-NOSRC-{uuid.uuid4().hex[:8]}",
        title="Will it snow more than 10 inches in Boston by February 2026?",
        description="Snow accumulation prediction.",
        resolution_text="We will check local news reports for snow totals.",
        category="WEATHER_EVENT",
        end_date=future_date,
        expected_decision="INSUFFICIENT_DATA",
        expected_reason="No official measurement source specified",
        market_price=0.6,
    )


# =============================================================================
# CORPORATE EVENT MOCKS
# =============================================================================


def create_corporate_valid() -> MockMarket:
    """Create a valid corporate event market."""
    future_date = (date.today() + timedelta(days=60)).isoformat()
    return MockMarket(
        market_id=f"CORP-VALID-{uuid.uuid4().hex[:8]}",
        title="Will Apple (AAPL) file 10-K with SEC by January 31, 2026?",
        description=(
            "This market tracks whether Apple Inc. files its annual 10-K report "
            "with the Securities and Exchange Commission."
        ),
        resolution_text=(
            "Resolution source: SEC EDGAR database. Market resolves YES if "
            "Apple's 10-K filing appears on EDGAR before January 31, 2026 "
            "11:59 PM EST. Binary resolution."
        ),
        category="CORPORATE_EVENT",
        end_date=future_date,
        expected_decision="TRADE",
        expected_reason="All corporate criteria met",
        market_price=0.95,
    )


def create_corporate_invalid_subjective() -> MockMarket:
    """Create invalid corporate market with subjective resolution."""
    future_date = (date.today() + timedelta(days=30)).isoformat()
    return MockMarket(
        market_id=f"CORP-INVALID-SUBJ-{uuid.uuid4().hex[:8]}",
        title="Will Tesla beat earnings expectations in Q1 2026?",
        description="Tesla quarterly earnings prediction.",
        resolution_text="Resolves YES if Tesla beats analyst expectations.",
        category="CORPORATE_EVENT",
        end_date=future_date,
        expected_decision="INSUFFICIENT_DATA",
        expected_reason="Subjective outcome (beat expectations)",
        market_price=0.5,
    )


def create_corporate_invalid_no_company() -> MockMarket:
    """Create invalid corporate market without specific company."""
    future_date = (date.today() + timedelta(days=90)).isoformat()
    return MockMarket(
        market_id=f"CORP-INVALID-NOCOMP-{uuid.uuid4().hex[:8]}",
        title="Will a major tech company announce layoffs in Q2 2026?",
        description="Tech sector employment prediction.",
        resolution_text="Based on news reports of layoff announcements.",
        category="CORPORATE_EVENT",
        end_date=future_date,
        expected_decision="INSUFFICIENT_DATA",
        expected_reason="No specific company identified",
        market_price=0.4,
    )


# =============================================================================
# COURT RULING MOCKS
# =============================================================================


def create_court_valid() -> MockMarket:
    """Create a valid court ruling market."""
    future_date = (date.today() + timedelta(days=120)).isoformat()
    return MockMarket(
        market_id=f"COURT-VALID-{uuid.uuid4().hex[:8]}",
        title="Will SCOTUS affirm in case 23-719 by June 30, 2026?",
        description=(
            "This market tracks the Supreme Court's decision in case 23-719, "
            "a major constitutional challenge."
        ),
        resolution_text=(
            "Resolution source: supremecourt.gov official opinions. "
            "Market resolves YES if the Court affirms the lower court ruling. "
            "Resolves NO if reversed or remanded. Binary resolution."
        ),
        category="COURT_RULING",
        end_date=future_date,
        expected_decision="TRADE",
        expected_reason="All court criteria met",
        market_price=0.55,
    )


def create_court_invalid_no_case() -> MockMarket:
    """Create invalid court market without case identifier."""
    future_date = (date.today() + timedelta(days=90)).isoformat()
    return MockMarket(
        market_id=f"COURT-INVALID-NOCASE-{uuid.uuid4().hex[:8]}",
        title="Will the Supreme Court rule on immigration this term?",
        description="General SCOTUS prediction.",
        resolution_text="Based on whether any immigration case is decided.",
        category="COURT_RULING",
        end_date=future_date,
        expected_decision="INSUFFICIENT_DATA",
        expected_reason="No specific case identified",
        market_price=0.6,
    )


def create_court_invalid_vague_outcome() -> MockMarket:
    """Create invalid court market with vague outcome."""
    future_date = (date.today() + timedelta(days=60)).isoformat()
    return MockMarket(
        market_id=f"COURT-INVALID-VAGUE-{uuid.uuid4().hex[:8]}",
        title="Will legal experts expect SCOTUS to rule favorably in Smith v. Jones?",
        description="Expert opinion prediction.",
        resolution_text="Based on consensus of legal analysts.",
        category="COURT_RULING",
        end_date=future_date,
        expected_decision="INSUFFICIENT_DATA",
        expected_reason="Vague outcome based on expert opinions",
        market_price=0.5,
    )


# =============================================================================
# MOCK DATA COLLECTIONS
# =============================================================================


def get_all_valid_mocks() -> List[MockMarket]:
    """Get all mock markets expected to pass (TRADE)."""
    return [
        create_eu_regulation_valid(),
        create_weather_valid(),
        create_corporate_valid(),
        create_court_valid(),
    ]


def get_all_invalid_mocks() -> List[MockMarket]:
    """Get all mock markets expected to fail (NO_TRADE or INSUFFICIENT_DATA)."""
    return [
        create_eu_regulation_invalid_vague(),
        create_eu_regulation_invalid_past(),
        create_weather_invalid_vague_metric(),
        create_weather_invalid_no_source(),
        create_corporate_invalid_subjective(),
        create_corporate_invalid_no_company(),
        create_court_invalid_no_case(),
        create_court_invalid_vague_outcome(),
    ]


def get_all_mocks() -> List[MockMarket]:
    """Get all mock markets."""
    return get_all_valid_mocks() + get_all_invalid_mocks()


def get_mocks_by_category(category: str) -> List[MockMarket]:
    """Get mock markets by category."""
    return [m for m in get_all_mocks() if m.category == category]


# =============================================================================
# MOCK SNAPSHOT DATA (for paper trading)
# =============================================================================


@dataclass
class MockSnapshot:
    """Mock market snapshot for paper trading tests."""
    market_id: str
    current_price: float
    is_resolved: bool = False
    resolved_outcome: Optional[str] = None  # "YES" or "NO"
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "market_id": self.market_id,
            "price": self.current_price,
            "is_resolved": self.is_resolved,
            "resolved_outcome": self.resolved_outcome,
            "timestamp": self.timestamp,
        }


def create_mock_snapshots_open(market_ids: List[str]) -> Dict[str, MockSnapshot]:
    """Create mock snapshots for open (unresolved) markets."""
    return {
        mid: MockSnapshot(
            market_id=mid,
            current_price=0.5 + (hash(mid) % 40) / 100,  # 0.50 - 0.90 range
            is_resolved=False,
        )
        for mid in market_ids
    }


def create_mock_snapshots_resolved(
    market_ids: List[str], outcomes: Dict[str, str]
) -> Dict[str, MockSnapshot]:
    """Create mock snapshots for resolved markets."""
    return {
        mid: MockSnapshot(
            market_id=mid,
            current_price=1.0 if outcomes.get(mid) == "YES" else 0.0,
            is_resolved=True,
            resolved_outcome=outcomes.get(mid, "NO"),
        )
        for mid in market_ids
    }
