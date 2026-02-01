# =============================================================================
# POLYMARKET BEOBACHTER - CORPORATE EVENT VALIDATION
# =============================================================================
#
# GOVERNANCE INTENT:
# This module validates CORPORATE_EVENT markets for STRUCTURAL TRADEABILITY.
# It does NOT predict corporate outcomes.
# It does NOT use insider information or forecasts.
#
# CORE PRINCIPLE:
# We do NOT ask: "Will earnings beat expectations?"
# We ask: "Is the event date OBJECTIVELY VERIFIABLE from official sources?"
#
# VALIDATION CHECKLIST (ALL MUST PASS):
# 1. COMPANY_IDENTIFIED - Specific company with ticker/identifier
# 2. EVENT_TYPE_CLEAR - Earnings, Filing, Product Launch, etc.
# 3. OFFICIAL_SOURCE - SEC, Company IR, Exchange filings
# 4. DATE_VERIFIABLE - Explicit date from official calendar
# 5. RESOLUTION_OBJECTIVE - Binary, measurable outcome
# 6. TIMING_FEASIBLE - Event date allows for verification
#
# IF ANY FAILS: Decision = INSUFFICIENT_DATA
#
# =============================================================================

import re
import logging
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any, Tuple
from datetime import date, datetime

logger = logging.getLogger(__name__)


# =============================================================================
# DATA MODELS
# =============================================================================


@dataclass(frozen=True)
class CorporateValidationChecklist:
    """
    Result of the 6-point corporate event validation checklist.

    GOVERNANCE:
    All fields must be True for market to be VALID.
    Any False field results in INSUFFICIENT_DATA decision.
    """
    company_identified_ok: bool
    event_type_ok: bool
    official_source_ok: bool
    date_verifiable_ok: bool
    resolution_objective_ok: bool
    timing_feasible_ok: bool

    # Details for audit trail
    company_identified: Optional[str] = None
    ticker_symbol: Optional[str] = None
    event_type_identified: Optional[str] = None
    source_identified: Optional[str] = None
    date_identified: Optional[str] = None
    resolution_type: Optional[str] = None

    # Blocking reasons
    blocking_reasons: tuple = field(default_factory=tuple)

    @property
    def is_valid(self) -> bool:
        """Check if all 6 criteria passed."""
        return all([
            self.company_identified_ok,
            self.event_type_ok,
            self.official_source_ok,
            self.date_verifiable_ok,
            self.resolution_objective_ok,
            self.timing_feasible_ok,
        ])

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for logging."""
        return {
            "company_identified_ok": self.company_identified_ok,
            "event_type_ok": self.event_type_ok,
            "official_source_ok": self.official_source_ok,
            "date_verifiable_ok": self.date_verifiable_ok,
            "resolution_objective_ok": self.resolution_objective_ok,
            "timing_feasible_ok": self.timing_feasible_ok,
            "company_identified": self.company_identified,
            "ticker_symbol": self.ticker_symbol,
            "event_type_identified": self.event_type_identified,
            "source_identified": self.source_identified,
            "date_identified": self.date_identified,
            "resolution_type": self.resolution_type,
            "blocking_reasons": list(self.blocking_reasons),
            "is_valid": self.is_valid,
        }


# =============================================================================
# CORPORATE EVENT VALIDATOR
# =============================================================================


class CorporateEventValidator:
    """
    Validates CORPORATE_EVENT markets against the 6-point checklist.

    STRICT PRINCIPLE:
    This class does NOT:
    - Predict earnings outcomes
    - Use analyst estimates
    - Access insider information
    - Estimate probabilities

    It ONLY validates:
    - Event identification
    - Source verification
    - Timeline feasibility
    """

    # =========================================================================
    # OFFICIAL SOURCES (explicit names required)
    # =========================================================================
    VALID_SOURCES = {
        # US Regulatory
        "sec", "securities and exchange commission",
        "edgar", "sec.gov", "sec filing",
        "10-k", "10-q", "8-k", "s-1", "def 14a",
        # Exchanges
        "nyse", "nasdaq", "new york stock exchange",
        "london stock exchange", "lse",
        "deutsche börse", "xetra",
        "euronext", "tokyo stock exchange",
        # Company Sources
        "investor relations", "ir website",
        "earnings call", "quarterly report",
        "annual report", "press release",
        "company announcement",
        # News Wire Services (for official announcements)
        "business wire", "pr newswire", "globenewswire",
    }

    # =========================================================================
    # EVENT TYPES (must be objectively verifiable)
    # =========================================================================
    VALID_EVENT_TYPES = {
        # Earnings
        "earnings": "EARNINGS",
        "quarterly earnings": "EARNINGS",
        "q1 earnings": "EARNINGS",
        "q2 earnings": "EARNINGS",
        "q3 earnings": "EARNINGS",
        "q4 earnings": "EARNINGS",
        "annual earnings": "EARNINGS",
        "earnings report": "EARNINGS",
        "earnings release": "EARNINGS",
        # Filings
        "10-k": "SEC_FILING",
        "10-q": "SEC_FILING",
        "8-k": "SEC_FILING",
        "s-1": "SEC_FILING",
        "ipo": "IPO",
        "initial public offering": "IPO",
        "direct listing": "IPO",
        # Corporate Actions
        "dividend": "DIVIDEND",
        "stock split": "STOCK_SPLIT",
        "merger": "MERGER",
        "acquisition": "ACQUISITION",
        "spinoff": "SPINOFF",
        "spin-off": "SPINOFF",
        # Product Events
        "product launch": "PRODUCT_LAUNCH",
        "product announcement": "PRODUCT_LAUNCH",
        "conference": "CONFERENCE",
        "investor day": "INVESTOR_DAY",
        # Guidance
        "guidance": "GUIDANCE",
        "outlook": "GUIDANCE",
        "forecast": "GUIDANCE",
    }

    # Patterns for event types
    EVENT_PATTERNS = [
        re.compile(r'\b(q[1-4]|quarterly|annual)\s*(earnings|results|report)', re.I),
        re.compile(r'\bearnings\s*(call|release|report|announcement)', re.I),
        re.compile(r'\b(10-[kq]|8-k|s-1|def\s*14a)\b', re.I),
        re.compile(r'\b(ipo|initial\s+public\s+offering|direct\s+listing)', re.I),
        re.compile(r'\b(dividend|stock\s+split|merger|acquisition|spinoff)', re.I),
        re.compile(r'\bproduct\s+(launch|announcement|release)', re.I),
    ]

    # =========================================================================
    # TICKER PATTERNS
    # =========================================================================
    # US tickers: 1-5 uppercase letters
    US_TICKER_PATTERN = re.compile(r'\b([A-Z]{1,5})\b')
    # With exchange prefix: NYSE:AAPL, NASDAQ:GOOGL
    EXCHANGE_TICKER_PATTERN = re.compile(
        r'\b(NYSE|NASDAQ|LSE|XETRA)[:\s]([A-Z]{1,5})\b', re.I
    )
    # Common company names with known tickers
    KNOWN_COMPANIES = {
        "apple": "AAPL",
        "microsoft": "MSFT",
        "google": "GOOGL",
        "alphabet": "GOOGL",
        "amazon": "AMZN",
        "meta": "META",
        "facebook": "META",
        "tesla": "TSLA",
        "nvidia": "NVDA",
        "netflix": "NFLX",
        "disney": "DIS",
        "walmart": "WMT",
        "jpmorgan": "JPM",
        "bank of america": "BAC",
        "goldman sachs": "GS",
        "berkshire": "BRK",
        "johnson & johnson": "JNJ",
        "pfizer": "PFE",
        "moderna": "MRNA",
        "exxon": "XOM",
        "chevron": "CVX",
    }

    # =========================================================================
    # VAGUE TERMS (invalidate the market)
    # =========================================================================
    VAGUE_TERMS = {
        "might", "could", "possibly", "probably",
        "expected to", "likely to", "rumored",
        "speculation", "insider", "leak",
        "anonymous source", "sources say",
    }

    # =========================================================================
    # SUBJECTIVE OUTCOME TERMS (invalidate resolution)
    # =========================================================================
    SUBJECTIVE_OUTCOMES = {
        "beat expectations", "miss expectations",
        "better than expected", "worse than expected",
        "surprise", "disappointing", "impressive",
        "good earnings", "bad earnings",
        "positive", "negative",
        "bullish", "bearish",
    }

    def __init__(self):
        """Initialize the corporate event validator."""
        pass

    def validate(
        self,
        market_question: str,
        resolution_text: str,
        description: str = "",
        target_date: Optional[str] = None,
    ) -> CorporateValidationChecklist:
        """
        Validate a corporate event market against the 6-point checklist.

        GOVERNANCE:
        This method ONLY checks structural validity.
        It does NOT assess the likelihood of corporate outcomes.

        Args:
            market_question: The market's main question
            resolution_text: The resolution criteria text
            description: Additional market description
            target_date: Optional target date string

        Returns:
            CorporateValidationChecklist with all 6 criteria results
        """
        full_text = f"{market_question} {resolution_text} {description}".lower()
        blocking_reasons: List[str] = []

        # ---------------------------------------------------------------------
        # CHECK 1: COMPANY IDENTIFIED
        # ---------------------------------------------------------------------
        company_ok, company_name, ticker = self._check_company_identified(full_text)
        if not company_ok:
            blocking_reasons.append(
                "COMPANY_IDENTIFIED: No specific company or ticker identified. "
                "Market must reference a specific publicly traded company."
            )

        # ---------------------------------------------------------------------
        # CHECK 2: EVENT TYPE
        # ---------------------------------------------------------------------
        event_ok, event_type = self._check_event_type(full_text)
        if not event_ok:
            blocking_reasons.append(
                "EVENT_TYPE: No verifiable corporate event type identified. "
                "Must be earnings, filing, dividend, merger, etc."
            )

        # ---------------------------------------------------------------------
        # CHECK 3: OFFICIAL SOURCE
        # ---------------------------------------------------------------------
        source_ok, source_id = self._check_official_source(full_text)
        if not source_ok:
            blocking_reasons.append(
                "OFFICIAL_SOURCE: No official source referenced. "
                "Must reference SEC, exchange, or company IR."
            )

        # ---------------------------------------------------------------------
        # CHECK 4: DATE VERIFIABLE
        # ---------------------------------------------------------------------
        date_ok, date_id = self._check_date_verifiable(full_text, target_date)
        if not date_ok:
            blocking_reasons.append(
                "DATE_VERIFIABLE: No explicit, verifiable date. "
                "Event date must be from official calendar or filing."
            )

        # ---------------------------------------------------------------------
        # CHECK 5: RESOLUTION OBJECTIVE
        # ---------------------------------------------------------------------
        resolution_ok, resolution_type = self._check_resolution_objective(full_text)
        if not resolution_ok:
            blocking_reasons.append(
                "RESOLUTION_OBJECTIVE: Resolution criteria is subjective. "
                "Cannot use 'beat expectations' or similar vague terms."
            )

        # ---------------------------------------------------------------------
        # CHECK 6: TIMING FEASIBLE
        # ---------------------------------------------------------------------
        timing_ok = self._check_timing_feasible(target_date)
        if not timing_ok:
            blocking_reasons.append(
                "TIMING_FEASIBLE: Event date is in the past or too close. "
                "Must allow time for official verification."
            )

        return CorporateValidationChecklist(
            company_identified_ok=company_ok,
            event_type_ok=event_ok,
            official_source_ok=source_ok,
            date_verifiable_ok=date_ok,
            resolution_objective_ok=resolution_ok,
            timing_feasible_ok=timing_ok,
            company_identified=company_name,
            ticker_symbol=ticker,
            event_type_identified=event_type,
            source_identified=source_id,
            date_identified=date_id,
            resolution_type=resolution_type,
            blocking_reasons=tuple(blocking_reasons),
        )

    def _check_company_identified(
        self, text: str
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Check if a specific company is identified.

        Returns:
            (is_valid, company_name, ticker_symbol)
        """
        # Check for exchange:ticker format
        exchange_match = self.EXCHANGE_TICKER_PATTERN.search(text.upper())
        if exchange_match:
            return True, None, f"{exchange_match.group(1)}:{exchange_match.group(2)}"

        # Check for known company names
        text_lower = text.lower()
        for company, ticker in self.KNOWN_COMPANIES.items():
            if company in text_lower:
                return True, company.title(), ticker

        # Check for ticker symbols (be conservative - need context)
        # Look for patterns like "AAPL earnings" or "Tesla (TSLA)"
        ticker_context = re.compile(
            r'\b([A-Z]{2,5})\s*(earnings|report|filing|dividend|split|ipo)|'
            r'\(([A-Z]{2,5})\)',
            re.I
        )
        ticker_match = ticker_context.search(text.upper())
        if ticker_match:
            ticker = ticker_match.group(1) or ticker_match.group(3)
            return True, None, ticker

        return False, None, None

    def _check_event_type(
        self, text: str
    ) -> Tuple[bool, Optional[str]]:
        """
        Check if event type is verifiable.

        Returns:
            (is_valid, event_type)
        """
        # Check patterns
        for pattern in self.EVENT_PATTERNS:
            match = pattern.search(text)
            if match:
                return True, match.group(0).upper()

        # Check keywords
        for keyword, event_type in self.VALID_EVENT_TYPES.items():
            if keyword in text:
                return True, event_type

        return False, None

    def _check_official_source(
        self, text: str
    ) -> Tuple[bool, Optional[str]]:
        """
        Check if official source is referenced.

        Returns:
            (is_valid, source_identified)
        """
        for source in self.VALID_SOURCES:
            if source in text:
                return True, source.upper()

        return False, None

    def _check_date_verifiable(
        self, text: str, target_date: Optional[str]
    ) -> Tuple[bool, Optional[str]]:
        """
        Check if date is explicit and verifiable.

        Returns:
            (is_valid, date_identified)
        """
        # If explicit target date provided
        if target_date:
            try:
                parsed = date.fromisoformat(target_date[:10])
                return True, target_date
            except (ValueError, TypeError):
                pass

        # Look for date patterns in text
        date_patterns = [
            re.compile(r'\b(\d{4}-\d{2}-\d{2})\b'),
            re.compile(r'\b(january|february|march|april|may|june|july|august|september|october|november|december)\s+\d{1,2},?\s+\d{4}\b', re.I),
            re.compile(r'\b\d{1,2}\s+(january|february|march|april|may|june|july|august|september|october|november|december)\s+\d{4}\b', re.I),
            re.compile(r'\bq[1-4]\s+\d{4}\b', re.I),  # Q1 2026
        ]

        for pattern in date_patterns:
            match = pattern.search(text)
            if match:
                return True, match.group(0)

        # Check for vague date references
        vague_dates = ["soon", "upcoming", "later this year", "sometime"]
        for vague in vague_dates:
            if vague in text:
                return False, f"VAGUE:{vague}"

        return False, None

    def _check_resolution_objective(
        self, text: str
    ) -> Tuple[bool, Optional[str]]:
        """
        Check if resolution criteria is objective.

        Returns:
            (is_valid, resolution_type)
        """
        # Check for subjective terms
        for subjective in self.SUBJECTIVE_OUTCOMES:
            if subjective in text:
                return False, f"SUBJECTIVE:{subjective}"

        # Check for vague terms
        for vague in self.VAGUE_TERMS:
            if vague in text:
                return False, f"VAGUE:{vague}"

        # Look for objective resolution patterns
        objective_patterns = [
            (re.compile(r'(file|submit|release)\s*(before|by|on)', re.I), "DATE_BASED"),
            (re.compile(r'(announce|report)\s*(revenue|eps|earnings)\s*(of|above|below|at)\s*\$?[\d.]+', re.I), "NUMERIC_THRESHOLD"),
            (re.compile(r'(ipo|go\s+public|list)\s*(before|by|on)', re.I), "DATE_BASED"),
            (re.compile(r'(dividend|split)\s*(of|at)\s*\$?[\d.]+', re.I), "NUMERIC_VALUE"),
            (re.compile(r'(merger|acquisition)\s*(complete|close|finalize)', re.I), "EVENT_COMPLETION"),
        ]

        for pattern, res_type in objective_patterns:
            if pattern.search(text):
                return True, res_type

        # If no subjective terms and has event type, assume objective
        for pattern in self.EVENT_PATTERNS:
            if pattern.search(text):
                return True, "EVENT_OCCURRENCE"

        return False, None

    def _check_timing_feasible(
        self, target_date: Optional[str]
    ) -> bool:
        """
        Check if timing allows for verification.

        Returns:
            is_valid
        """
        if not target_date:
            return True  # Can't verify, let other checks handle

        try:
            target = date.fromisoformat(target_date[:10])
            today = date.today()
            days_until = (target - today).days

            # Must be in the future
            if days_until < 0:
                return False

            # Need at least 1 day for verification
            if days_until < 1:
                return False

            return True

        except (ValueError, TypeError):
            return True  # Can't parse, let other checks handle


# =============================================================================
# MODULE-LEVEL FUNCTIONS
# =============================================================================


def validate_corporate_event(
    market_question: str,
    resolution_text: str,
    description: str = "",
    target_date: Optional[str] = None,
) -> CorporateValidationChecklist:
    """
    Convenience function to validate a corporate event market.

    Args:
        market_question: The market's main question
        resolution_text: The resolution criteria text
        description: Additional market description
        target_date: Optional target date

    Returns:
        CorporateValidationChecklist with validation results
    """
    validator = CorporateEventValidator()
    return validator.validate(market_question, resolution_text, description, target_date)


def is_corporate_event_market(text: str) -> bool:
    """
    Detect if a market is likely a CORPORATE_EVENT category.

    Simple keyword detection - does NOT validate the market.

    Args:
        text: Market question or description

    Returns:
        True if likely a corporate event market
    """
    corporate_keywords = {
        "earnings", "quarterly", "annual report",
        "10-k", "10-q", "8-k", "sec filing",
        "ipo", "dividend", "stock split",
        "merger", "acquisition", "spinoff",
        "investor day", "earnings call",
        "revenue", "eps", "guidance",
    }

    text_lower = text.lower()
    return any(kw in text_lower for kw in corporate_keywords)
