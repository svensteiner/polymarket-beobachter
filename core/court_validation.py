# =============================================================================
# POLYMARKET BEOBACHTER - COURT RULING VALIDATION
# =============================================================================
#
# GOVERNANCE INTENT:
# This module validates COURT_RULING markets for STRUCTURAL TRADEABILITY.
# It does NOT predict legal outcomes.
# It does NOT provide legal advice.
#
# CORE PRINCIPLE:
# We do NOT ask: "Will the court rule in favor of X?"
# We ask: "Is the ruling date OBJECTIVELY VERIFIABLE from official sources?"
#
# VALIDATION CHECKLIST (ALL MUST PASS):
# 1. COURT_IDENTIFIED - Specific court named (Supreme Court, SDNY, ECJ, etc.)
# 2. CASE_IDENTIFIED - Case number, name, or docket reference
# 3. OFFICIAL_SOURCE - Court website, PACER, official gazette
# 4. DATE_TYPE_CLEAR - Ruling date, filing deadline, or hearing date
# 5. RESOLUTION_BINARY - Yes/No outcome (ruling for/against, dismissed, etc.)
# 6. TIMING_FEASIBLE - Allows for official publication
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
class CourtValidationChecklist:
    """
    Result of the 6-point court ruling validation checklist.

    GOVERNANCE:
    All fields must be True for market to be VALID.
    Any False field results in INSUFFICIENT_DATA decision.
    """
    court_identified_ok: bool
    case_identified_ok: bool
    official_source_ok: bool
    date_type_ok: bool
    resolution_binary_ok: bool
    timing_feasible_ok: bool

    # Details for audit trail
    court_identified: Optional[str] = None
    court_level: Optional[str] = None  # SUPREME, APPELLATE, DISTRICT, etc.
    case_identifier: Optional[str] = None
    source_identified: Optional[str] = None
    date_type: Optional[str] = None  # RULING, HEARING, FILING_DEADLINE
    expected_date: Optional[str] = None

    # Blocking reasons
    blocking_reasons: tuple = field(default_factory=tuple)

    @property
    def is_valid(self) -> bool:
        """Check if all 6 criteria passed."""
        return all([
            self.court_identified_ok,
            self.case_identified_ok,
            self.official_source_ok,
            self.date_type_ok,
            self.resolution_binary_ok,
            self.timing_feasible_ok,
        ])

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for logging."""
        return {
            "court_identified_ok": self.court_identified_ok,
            "case_identified_ok": self.case_identified_ok,
            "official_source_ok": self.official_source_ok,
            "date_type_ok": self.date_type_ok,
            "resolution_binary_ok": self.resolution_binary_ok,
            "timing_feasible_ok": self.timing_feasible_ok,
            "court_identified": self.court_identified,
            "court_level": self.court_level,
            "case_identifier": self.case_identifier,
            "source_identified": self.source_identified,
            "date_type": self.date_type,
            "expected_date": self.expected_date,
            "blocking_reasons": list(self.blocking_reasons),
            "is_valid": self.is_valid,
        }


# =============================================================================
# COURT RULING VALIDATOR
# =============================================================================


class CourtRulingValidator:
    """
    Validates COURT_RULING markets against the 6-point checklist.

    STRICT PRINCIPLE:
    This class does NOT:
    - Predict legal outcomes
    - Provide legal advice
    - Assess case merits
    - Estimate ruling probabilities

    It ONLY validates:
    - Court identification
    - Case specificity
    - Source verification
    - Timeline feasibility
    """

    # =========================================================================
    # COURTS DATABASE
    # =========================================================================

    # US Federal Courts
    US_FEDERAL_COURTS = {
        # Supreme Court
        "supreme court": ("SCOTUS", "SUPREME"),
        "scotus": ("SCOTUS", "SUPREME"),
        "us supreme court": ("SCOTUS", "SUPREME"),
        "united states supreme court": ("SCOTUS", "SUPREME"),

        # Circuit Courts (Appellate)
        "first circuit": ("1st Cir.", "APPELLATE"),
        "second circuit": ("2nd Cir.", "APPELLATE"),
        "third circuit": ("3rd Cir.", "APPELLATE"),
        "fourth circuit": ("4th Cir.", "APPELLATE"),
        "fifth circuit": ("5th Cir.", "APPELLATE"),
        "sixth circuit": ("6th Cir.", "APPELLATE"),
        "seventh circuit": ("7th Cir.", "APPELLATE"),
        "eighth circuit": ("8th Cir.", "APPELLATE"),
        "ninth circuit": ("9th Cir.", "APPELLATE"),
        "tenth circuit": ("10th Cir.", "APPELLATE"),
        "eleventh circuit": ("11th Cir.", "APPELLATE"),
        "dc circuit": ("D.C. Cir.", "APPELLATE"),
        "federal circuit": ("Fed. Cir.", "APPELLATE"),

        # District Courts
        "sdny": ("S.D.N.Y.", "DISTRICT"),
        "southern district of new york": ("S.D.N.Y.", "DISTRICT"),
        "edny": ("E.D.N.Y.", "DISTRICT"),
        "ndca": ("N.D. Cal.", "DISTRICT"),
        "cdca": ("C.D. Cal.", "DISTRICT"),
        "ddc": ("D.D.C.", "DISTRICT"),
        "district of columbia": ("D.D.C.", "DISTRICT"),
        "district court": (None, "DISTRICT"),
    }

    # International Courts
    INTERNATIONAL_COURTS = {
        # EU Courts
        "ecj": ("ECJ", "SUPREME"),
        "european court of justice": ("ECJ", "SUPREME"),
        "cjeu": ("CJEU", "SUPREME"),
        "court of justice of the european union": ("CJEU", "SUPREME"),
        "general court": ("General Court", "APPELLATE"),
        "eu general court": ("General Court", "APPELLATE"),

        # European Human Rights
        "echr": ("ECtHR", "INTERNATIONAL"),
        "european court of human rights": ("ECtHR", "INTERNATIONAL"),

        # International
        "icj": ("ICJ", "INTERNATIONAL"),
        "international court of justice": ("ICJ", "INTERNATIONAL"),
        "icc": ("ICC", "INTERNATIONAL"),
        "international criminal court": ("ICC", "INTERNATIONAL"),

        # UK Courts
        "uk supreme court": ("UKSC", "SUPREME"),
        "high court": ("High Court", "DISTRICT"),
        "court of appeal": ("CoA", "APPELLATE"),

        # German Courts
        "bundesverfassungsgericht": ("BVerfG", "SUPREME"),
        "bverfg": ("BVerfG", "SUPREME"),
        "bundesgerichtshof": ("BGH", "SUPREME"),
        "bgh": ("BGH", "SUPREME"),
    }

    # Combine all courts
    ALL_COURTS = {**US_FEDERAL_COURTS, **INTERNATIONAL_COURTS}

    # =========================================================================
    # OFFICIAL SOURCES
    # =========================================================================
    VALID_SOURCES = {
        # US
        "pacer", "uscourts.gov", "supremecourt.gov",
        "courtlistener", "justia", "law.cornell.edu",
        "scotusblog", "federal register",
        # EU
        "curia.europa.eu", "eur-lex", "europa.eu",
        "official journal",
        # UK
        "judiciary.uk", "bailii",
        # General
        "court website", "official court", "court filing",
        "docket", "case filing",
    }

    # =========================================================================
    # CASE IDENTIFIER PATTERNS
    # =========================================================================
    CASE_PATTERNS = [
        # US Supreme Court: 21-1484
        re.compile(r'\b(\d{2}-\d{1,5})\b'),
        # US District: 1:21-cv-01234
        re.compile(r'\b(\d:\d{2}-cv-\d{4,6})\b', re.I),
        # US Criminal: 1:21-cr-00123
        re.compile(r'\b(\d:\d{2}-cr-\d{4,6})\b', re.I),
        # General docket number
        re.compile(r'\b(case\s*(?:no\.?|number|#)\s*[\w\-\/]+)\b', re.I),
        # v. pattern: Smith v. Jones
        re.compile(r'\b([A-Z][a-z]+\s+v\.?\s+[A-Z][a-z]+)\b'),
        # EU Case: C-123/45
        re.compile(r'\b([CT]-\d{1,4}/\d{2})\b'),
    ]

    # =========================================================================
    # DATE TYPE KEYWORDS
    # =========================================================================
    DATE_TYPE_KEYWORDS = {
        # Ruling dates
        "ruling": "RULING",
        "decision": "RULING",
        "judgment": "RULING",
        "verdict": "RULING",
        "opinion": "RULING",
        "order": "RULING",

        # Hearing dates
        "hearing": "HEARING",
        "oral argument": "HEARING",
        "argument": "HEARING",
        "trial": "HEARING",

        # Filing deadlines
        "filing deadline": "FILING_DEADLINE",
        "brief due": "FILING_DEADLINE",
        "response due": "FILING_DEADLINE",
        "deadline": "FILING_DEADLINE",

        # Certiorari
        "certiorari": "CERT_DECISION",
        "cert": "CERT_DECISION",
    }

    # =========================================================================
    # BINARY OUTCOME PATTERNS
    # =========================================================================
    BINARY_OUTCOMES = {
        # Favorable/Unfavorable
        "rule in favor": True,
        "rule against": True,
        "ruling for": True,
        "ruling against": True,
        "find for": True,
        "find against": True,

        # Affirm/Reverse
        "affirm": True,
        "reverse": True,
        "overturn": True,
        "uphold": True,

        # Grant/Deny
        "grant": True,
        "deny": True,
        "dismiss": True,
        "reject": True,

        # Certiorari
        "grant cert": True,
        "deny cert": True,

        # Conviction
        "convict": True,
        "acquit": True,
        "guilty": True,
        "not guilty": True,
    }

    # =========================================================================
    # VAGUE TERMS (invalidate)
    # =========================================================================
    VAGUE_TERMS = {
        "might rule", "could decide", "expected to",
        "likely", "probably", "possibly",
        "rumored", "speculation", "sources say",
        "legal experts believe", "analysts expect",
    }

    def __init__(self):
        """Initialize the court ruling validator."""
        pass

    def validate(
        self,
        market_question: str,
        resolution_text: str,
        description: str = "",
        target_date: Optional[str] = None,
    ) -> CourtValidationChecklist:
        """
        Validate a court ruling market against the 6-point checklist.

        GOVERNANCE:
        This method ONLY checks structural validity.
        It does NOT assess the likelihood of legal outcomes.

        Args:
            market_question: The market's main question
            resolution_text: The resolution criteria text
            description: Additional market description
            target_date: Optional target date string

        Returns:
            CourtValidationChecklist with all 6 criteria results
        """
        full_text = f"{market_question} {resolution_text} {description}".lower()
        blocking_reasons: List[str] = []

        # ---------------------------------------------------------------------
        # CHECK 1: COURT IDENTIFIED
        # ---------------------------------------------------------------------
        court_ok, court_name, court_level = self._check_court_identified(full_text)
        if not court_ok:
            blocking_reasons.append(
                "COURT_IDENTIFIED: No specific court identified. "
                "Must reference a specific court (e.g., Supreme Court, SDNY, ECJ)."
            )

        # ---------------------------------------------------------------------
        # CHECK 2: CASE IDENTIFIED
        # ---------------------------------------------------------------------
        case_ok, case_id = self._check_case_identified(full_text)
        if not case_ok:
            blocking_reasons.append(
                "CASE_IDENTIFIED: No specific case identified. "
                "Must reference case number, docket, or party names (X v. Y)."
            )

        # ---------------------------------------------------------------------
        # CHECK 3: OFFICIAL SOURCE
        # ---------------------------------------------------------------------
        source_ok, source_id = self._check_official_source(full_text)
        if not source_ok:
            blocking_reasons.append(
                "OFFICIAL_SOURCE: No official source referenced. "
                "Must reference court website, PACER, or official gazette."
            )

        # ---------------------------------------------------------------------
        # CHECK 4: DATE TYPE CLEAR
        # ---------------------------------------------------------------------
        date_type_ok, date_type, expected_date = self._check_date_type(
            full_text, target_date
        )
        if not date_type_ok:
            blocking_reasons.append(
                "DATE_TYPE: Date type unclear. "
                "Must specify if date is for ruling, hearing, or filing deadline."
            )

        # ---------------------------------------------------------------------
        # CHECK 5: RESOLUTION BINARY
        # ---------------------------------------------------------------------
        binary_ok = self._check_resolution_binary(full_text)
        if not binary_ok:
            blocking_reasons.append(
                "RESOLUTION_BINARY: Resolution is not binary. "
                "Must be Yes/No outcome (e.g., affirm/reverse, grant/deny)."
            )

        # ---------------------------------------------------------------------
        # CHECK 6: TIMING FEASIBLE
        # ---------------------------------------------------------------------
        timing_ok = self._check_timing_feasible(target_date, court_level)
        if not timing_ok:
            blocking_reasons.append(
                "TIMING_FEASIBLE: Timeline not feasible. "
                "Court rulings may take weeks/months to publish officially."
            )

        return CourtValidationChecklist(
            court_identified_ok=court_ok,
            case_identified_ok=case_ok,
            official_source_ok=source_ok,
            date_type_ok=date_type_ok,
            resolution_binary_ok=binary_ok,
            timing_feasible_ok=timing_ok,
            court_identified=court_name,
            court_level=court_level,
            case_identifier=case_id,
            source_identified=source_id,
            date_type=date_type,
            expected_date=expected_date,
            blocking_reasons=tuple(blocking_reasons),
        )

    def _check_court_identified(
        self, text: str
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Check if a specific court is identified.

        Returns:
            (is_valid, court_name, court_level)
        """
        for court_keyword, (court_name, court_level) in self.ALL_COURTS.items():
            if court_keyword in text:
                return True, court_name or court_keyword.upper(), court_level

        # Check for generic "court" without specifics
        if "court" in text:
            # Need more specific identification
            return False, "GENERIC_COURT", None

        return False, None, None

    def _check_case_identified(
        self, text: str
    ) -> Tuple[bool, Optional[str]]:
        """
        Check if a specific case is identified.

        Returns:
            (is_valid, case_identifier)
        """
        # Check all case patterns
        for pattern in self.CASE_PATTERNS:
            match = pattern.search(text)
            if match:
                return True, match.group(1)

        # Check for party names (X v. Y pattern in original case)
        # This is already covered in CASE_PATTERNS

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

    def _check_date_type(
        self, text: str, target_date: Optional[str]
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Check if date type is clear.

        Returns:
            (is_valid, date_type, expected_date)
        """
        # Check for vague terms first
        for vague in self.VAGUE_TERMS:
            if vague in text:
                return False, f"VAGUE:{vague}", None

        # Check for date type keywords
        for keyword, date_type in self.DATE_TYPE_KEYWORDS.items():
            if keyword in text:
                return True, date_type, target_date

        # If we have a target date but no clear type, assume ruling
        if target_date:
            return True, "RULING", target_date

        return False, None, None

    def _check_resolution_binary(
        self, text: str
    ) -> bool:
        """
        Check if resolution is binary (Yes/No outcome).

        Returns:
            is_valid
        """
        # Check for binary outcome keywords
        for outcome in self.BINARY_OUTCOMES:
            if outcome in text:
                return True

        # Check for "will X" pattern with court action
        will_pattern = re.compile(
            r'will\s+(the\s+)?(court|judge|justices?)\s+'
            r'(rule|decide|affirm|reverse|grant|deny|dismiss|uphold|overturn)',
            re.I
        )
        if will_pattern.search(text):
            return True

        # Check for "by [date]" patterns suggesting deadline-based resolution
        by_date_pattern = re.compile(
            r'(rule|decision|ruling|judgment)\s+(by|before|on)\s+',
            re.I
        )
        if by_date_pattern.search(text):
            return True

        return False

    def _check_timing_feasible(
        self, target_date: Optional[str], court_level: Optional[str]
    ) -> bool:
        """
        Check if timing allows for official verification.

        Different courts have different publication timelines:
        - Supreme Court: Opinions published same day
        - Appellate: Days to weeks
        - District: Varies widely

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

            # Minimum buffer based on court level
            min_buffer = {
                "SUPREME": 0,  # Published immediately
                "APPELLATE": 1,
                "DISTRICT": 1,
                "INTERNATIONAL": 2,
            }.get(court_level, 1)

            return days_until >= min_buffer

        except (ValueError, TypeError):
            return True  # Can't parse, let other checks handle


# =============================================================================
# MODULE-LEVEL FUNCTIONS
# =============================================================================


def validate_court_ruling(
    market_question: str,
    resolution_text: str,
    description: str = "",
    target_date: Optional[str] = None,
) -> CourtValidationChecklist:
    """
    Convenience function to validate a court ruling market.

    Args:
        market_question: The market's main question
        resolution_text: The resolution criteria text
        description: Additional market description
        target_date: Optional target date

    Returns:
        CourtValidationChecklist with validation results
    """
    validator = CourtRulingValidator()
    return validator.validate(market_question, resolution_text, description, target_date)


def is_court_ruling_market(text: str) -> bool:
    """
    Detect if a market is likely a COURT_RULING category.

    Simple keyword detection - does NOT validate the market.

    Args:
        text: Market question or description

    Returns:
        True if likely a court ruling market
    """
    court_keywords = {
        "court", "ruling", "judge", "justice",
        "supreme court", "circuit", "district court",
        "lawsuit", "case", "verdict", "judgment",
        "appeal", "affirm", "reverse", "overturn",
        "certiorari", "oral argument", "docket",
        "plaintiff", "defendant", "prosecution",
        "ecj", "cjeu", "legal", "trial",
    }

    text_lower = text.lower()
    return any(kw in text_lower for kw in court_keywords)
