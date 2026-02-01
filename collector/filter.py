# =============================================================================
# POLYMARKET EU REGULATORY COLLECTOR
# Module: collector/filter.py
# Purpose: Filter markets by EU regulatory relevance
# =============================================================================
#
# FILTERING LOGIC:
# Include if matches:
#   ("EU" OR "European Union" OR "Commission" OR regulatory bodies) AND
#   (regulatory keywords: implementing act, delegated act, guidelines, etc.)
#
# Additionally require:
#   - Clear date/deadline in metadata OR extractable from resolution text
#
# Exclude:
#   - Markets about "price/market performance"
#   - Vague opinion questions
#
# =============================================================================

import re
import logging
from typing import Dict, Any, List, Tuple, Optional, Set
from datetime import date, datetime
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class FilterResult(Enum):
    """Result of filtering a market."""
    INCLUDED = "included"
    INCLUDED_CORPORATE = "included_corporate"
    INCLUDED_COURT = "included_court"
    INCLUDED_WEATHER = "included_weather"
    INCLUDED_POLITICAL = "included_political"
    INCLUDED_CRYPTO = "included_crypto"
    INCLUDED_FINANCE = "included_finance"      # NEW: Finance/stocks/fed
    INCLUDED_GENERAL = "included_general"
    EXCLUDED_NO_EU_MATCH = "excluded_no_eu_match"
    EXCLUDED_NO_AI_MATCH = "excluded_no_ai_match"
    EXCLUDED_NO_DEADLINE = "excluded_no_deadline"
    EXCLUDED_PRICE_MARKET = "excluded_price_market"
    EXCLUDED_OPINION_MARKET = "excluded_opinion_market"
    EXCLUDED_INCOMPLETE = "excluded_incomplete"


@dataclass
class FilteredMarket:
    """Result of filtering a single market."""
    market: Dict[str, Any]
    result: FilterResult
    matched_eu_keywords: List[str]
    matched_ai_keywords: List[str]
    extracted_deadline: Optional[date]
    notes: List[str]


class MarketFilter:
    """
    Filters markets for EU + AI/Tech regulation relevance.

    Implements fail-closed behavior: if data is missing or ambiguous,
    the market is marked as incomplete and excluded from candidates.
    """

    # =========================================================================
    # EU-RELATED KEYWORDS (includes regulatory bodies)
    # =========================================================================
    EU_KEYWORDS: Set[str] = {
        "eu",
        "european union",
        "european commission",
        "commission",
        "european parliament",
        "parliament",
        "brussels",
        "eu regulation",
        "eu directive",
        "eu law",
        "member state",
        "member states",
        "council of the eu",
        "eur-lex",
        "official journal",
        # EU Regulatory Bodies
        "esma",  # European Securities and Markets Authority
        "eba",   # European Banking Authority
        "edpb",  # European Data Protection Board
        "eiopa", # European Insurance and Occupational Pensions Authority
        "enisa", # EU Agency for Cybersecurity
        "ecb",   # European Central Bank
    }

    # Regex patterns for EU matching (case-insensitive)
    EU_PATTERNS: List[str] = [
        r"\beu\b",
        r"\beuropean\s+union\b",
        r"\beuropean\s+commission\b",
        r"\beuropean\s+parliament\b",
        r"\beu\s+regulation\b",
        r"\beu\s+directive\b",
        r"\beu\s+law\b",
        r"\bmember\s+states?\b",
        r"\bbrussels\b",
        r"\bcouncil\s+of\s+the\s+eu\b",
        # EU Regulatory Bodies
        r"\besma\b",
        r"\beba\b",
        r"\bedpb\b",
        r"\beiopa\b",
        r"\benisa\b",
        r"\becb\b",
    ]

    # =========================================================================
    # REGULATORY KEYWORDS (implementing acts, enforcement, etc.)
    # =========================================================================
    AI_KEYWORDS: Set[str] = {
        # Original AI/Tech keywords
        "ai",
        "artificial intelligence",
        "ai act",
        "ai regulation",
        "tech regulation",
        "technology regulation",
        "digital services act",
        "dsa",
        "digital markets act",
        "dma",
        "gdpr",
        "data protection",
        "platform regulation",
        "algorithmic",
        "machine learning",
        "generative ai",
        "chatgpt",
        "large language model",
        "llm",
        "foundation model",
        # NEW: EU Regulatory Process Keywords
        "implementing act",
        "implementing acts",
        "delegated act",
        "delegated acts",
        "delegated regulation",
        "guidelines",
        "guidance",
        "enforcement",
        "enforcement action",
        "codes of conduct",
        "code of conduct",
        "technical standards",
        "regulatory technical standards",
        "rts",
        "implementing technical standards",
        "its",
        "supervisory",
        "supervision",
        "compliance",
        "infringement",
        "penalty",
        "fine",
        "sanction",
    }

    # Regex patterns for regulatory matching (case-insensitive)
    AI_PATTERNS: List[str] = [
        # Original AI patterns
        r"\bai\b",
        r"\bartificial\s+intelligence\b",
        r"\bai\s+act\b",
        r"\btech\s+regulation\b",
        r"\btechnology\s+regulation\b",
        r"\bdigital\s+services\s+act\b",
        r"\bdsa\b",
        r"\bdigital\s+markets\s+act\b",
        r"\bdma\b",
        r"\bgdpr\b",
        r"\bdata\s+protection\b",
        r"\bplatform\s+regulation\b",
        r"\balgorithm\w*\b",
        r"\bmachine\s+learning\b",
        r"\bgenerative\s+ai\b",
        r"\bfoundation\s+model\b",
        r"\blarge\s+language\s+model\b",
        r"\bllm\b",
        # NEW: EU Regulatory Process Patterns
        r"\bimplementing\s+act\b",
        r"\bimplementing\s+acts\b",
        r"\bdelegated\s+act\b",
        r"\bdelegated\s+acts\b",
        r"\bdelegated\s+regulation\b",
        r"\bguidelines?\b",
        r"\bguidance\b",
        r"\benforcement\b",
        r"\bcodes?\s+of\s+conduct\b",
        r"\btechnical\s+standards?\b",
        r"\bregulatory\s+technical\s+standards?\b",
        r"\brts\b",
        r"\bimplementing\s+technical\s+standards?\b",
        r"\bits\b",
        r"\bsupervis\w+\b",
        r"\bcompliance\b",
        r"\binfringement\b",
        r"\bpenalt\w+\b",
        r"\bfines?\b",
        r"\bsanctions?\b",
    ]

    # =========================================================================
    # CORPORATE EVENT KEYWORDS
    # Requires COMPANY context - not just "annual report" alone
    # =========================================================================
    CORPORATE_KEYWORDS: Set[str] = {
        "earnings", "quarterly earnings", "annual earnings",
        "earnings report", "earnings call", "earnings release",
        "10-k", "10-q", "8-k", "sec filing",
        "ipo", "initial public offering", "direct listing",
        "dividend", "stock split", "merger", "acquisition",
        "spinoff", "spin-off", "investor day",
        "eps", "revenue guidance", "earnings guidance",
    }

    CORPORATE_PATTERNS: List[str] = [
        # Require EARNINGS context specifically (not just "annual report")
        r"\b(q[1-4]|quarterly|annual)\s*earnings",
        r"\bearnings\s*(call|release|report|announcement)",
        r"\b(10-[kq]|8-k|s-1|def\s*14a)\b",
        r"\b(ipo|initial\s+public\s+offering|direct\s+listing)",
        r"\b(dividend|stock\s+split|merger|acquisition|spinoff)",
        r"\bproduct\s+(launch|announcement|release)",
        # Require ticker + corporate action
        r"\b([A-Z]{2,5})\s*(earnings|ipo|dividend|split)",
    ]

    # Exclude these from corporate (government reports, etc.)
    CORPORATE_EXCLUSIONS: Set[str] = {
        "ice annual report", "government report", "federal report",
        "agency report", "department report", "deport", "immigration",
    }

    # =========================================================================
    # COURT RULING KEYWORDS
    # Requires LEGAL context - not random "case" or "decision"
    # =========================================================================
    COURT_KEYWORDS: Set[str] = {
        "supreme court", "scotus", "circuit court", "district court",
        "court ruling", "court decision", "verdict", "judgment",
        "appeal", "appellate", "certiorari",
        "lawsuit", "legal case", "docket", "trial court",
        "justices", "overturn", "uphold",
        "plaintiff", "defendant",
        "ecj", "cjeu", "european court of justice",
    }

    COURT_PATTERNS: List[str] = [
        r"\b(supreme\s+court|scotus|circuit\s+court|district\s+court)",
        r"\b(ecj|cjeu|european\s+court\s+of\s+justice)",
        r"\bcourt\s+(ruling|decision|rule|decide|affirm|reverse)",
        r"\b(affirm|reverse|overturn|uphold)\s+(the\s+)?(ruling|decision|verdict)",
        r"\b(\d{2}-\d{1,5})\b",  # Case numbers like 21-1484
        r"\b(\d:\d{2}-cv-\d{4,6})\b",  # District court case numbers
        r"\b([A-Z][a-z]+\s+v\.?\s+[A-Z][a-z]+)\s+(case|ruling|decision)",  # X v. Y case
    ]

    # Exclude these from court rulings (meme markets, games, etc.)
    COURT_EXCLUSIONS: Set[str] = {
        "gta", "video game", "album", "movie", "music", "before gta",
        "jesus", "return", "invade", "president out",
    }

    # =========================================================================
    # WEATHER EVENT KEYWORDS
    # =========================================================================
    WEATHER_KEYWORDS: Set[str] = {
        "temperature", "celsius", "fahrenheit", "degrees",
        "rain", "rainfall", "precipitation", "snow", "snowfall",
        "weather", "hurricane", "typhoon", "cyclone", "storm",
        "heat", "heatwave", "cold", "freeze", "frost",
        "drought", "flood", "flooding", "tornado", "wind",
        "noaa", "nws", "weather service", "meteorological",
        "climate", "el nino", "la nina",
    }

    WEATHER_PATTERNS: List[str] = [
        r"\b(temperature|temp)\s*(above|below|exceed|reach|hit)\s*\d+",
        r"\b\d+\s*(celsius|fahrenheit|°[cf]|degrees)",
        r"\b(rain|rainfall|precipitation|snow|snowfall)\s*(above|below|exceed|more|less)",
        r"\b(hurricane|typhoon|cyclone|tropical\s+storm)\s+[a-z]+",
        r"\b(noaa|nws|national\s+weather\s+service)",
        r"\b(heatwave|heat\s+wave|cold\s+snap|cold\s+wave)",
        r"\bweather\s+(event|forecast|alert|warning)",
        r"\b(flood|flooding|drought|tornado|wildfire)",
    ]

    # =========================================================================
    # EXCLUSION PATTERNS
    # =========================================================================
    # Markets matching these patterns are excluded

    PRICE_MARKET_PATTERNS: List[str] = [
        r"\bprice\s+(of|at|above|below|reach|hit)\b",
        r"\bmarket\s+(cap|capitalization)\b",
        r"\bstock\s+price\b",
        r"\btrading\s+at\b",
        r"\b(bitcoin|btc|eth|crypto)\s+(price|reach|hit)\b",
        r"\btoken\s+price\b",
        r"\bworth\s+\$",
        r"\bhit\s+\$\d+",
    ]

    OPINION_MARKET_PATTERNS: List[str] = [
        r"\bwho\s+will\s+win\b",
        r"\bwho\s+is\s+better\b",
        r"\bmost\s+popular\b",
        r"\bfavorite\b",
        r"\bpolling\b",
        r"\bapproval\s+rating\b",
        r"\bwill\s+\w+\s+be\s+president\b",
        r"\belection\s+winner\b",
    ]

    # =========================================================================
    # POLITICAL EVENT KEYWORDS (elections, legislation, government actions)
    # =========================================================================
    POLITICAL_KEYWORDS: Set[str] = {
        "election", "vote", "ballot", "referendum",
        "president", "congress", "senate", "parliament",
        "bill", "legislation", "law", "act",
        "executive order", "veto", "impeachment",
        "governor", "mayor", "minister", "chancellor",
        "democrat", "republican", "party",
        "inauguration", "term", "administration",
        "tariff", "sanction", "policy", "regulation",
        "trump", "biden", "government", "federal",
    }

    POLITICAL_PATTERNS: List[str] = [
        r"\b(election|vote|ballot|referendum)\b",
        r"\b(president|congress|senate|parliament)\s+(will|to|pass|vote|sign)",
        r"\b(bill|legislation|act)\s+(pass|fail|sign|veto)",
        r"\bexecutive\s+order\b",
        r"\b(tariff|sanction|ban|restrict)\s+on\b",
        r"\b(trump|biden|government)\s+(will|to|announce|sign|impose)",
        r"\bby\s+(january|february|march|april|may|june|july|august|september|october|november|december)\s+\d{1,2}",
        r"\bbefore\s+(january|february|march|april|may|june|july|august|september|october|november|december)",
    ]

    # =========================================================================
    # CRYPTO/BLOCKCHAIN EVENT KEYWORDS
    # =========================================================================
    CRYPTO_KEYWORDS: Set[str] = {
        "bitcoin", "btc", "ethereum", "eth", "crypto",
        "blockchain", "defi", "nft", "token",
        "halving", "etf", "sec", "cftc",
        "exchange", "coinbase", "binance",
        "stablecoin", "usdc", "usdt", "tether",
        "solana", "cardano", "polygon",
        "approval", "listing", "launch",
    }

    CRYPTO_PATTERNS: List[str] = [
        r"\b(bitcoin|btc|ethereum|eth)\s+(etf|approval|halving|upgrade)",
        r"\bspot\s+(bitcoin|btc|eth|ethereum)\s+etf",
        r"\b(sec|cftc)\s+(approve|reject|delay|decision)",
        r"\bcrypto\s+(regulation|bill|law|ban)",
        r"\b(coinbase|binance|kraken)\s+(list|delist|launch)",
        r"\bstablecoin\s+(regulation|bill|ban)",
        r"\bblockchain\s+(upgrade|fork|launch)",
    ]

    # =========================================================================
    # FINANCE EVENT KEYWORDS (Fed, stocks, indices, commodities)
    # =========================================================================
    FINANCE_KEYWORDS: Set[str] = {
        "fed", "federal reserve", "fomc", "rate cut", "rate hike",
        "interest rate", "monetary policy", "powell", "inflation",
        "s&p", "s&p 500", "spx", "dow jones", "nasdaq", "index",
        "stock", "shares", "market cap", "largest company",
        "earnings", "revenue", "quarterly", "annual report",
        "amazon", "amzn", "apple", "aapl", "tesla", "tsla",
        "nvidia", "nvda", "google", "googl", "microsoft", "msft",
        "meta", "netflix", "nflx", "berkshire",
        "gold", "silver", "oil", "commodities",
        "forex", "dollar", "euro", "yen",
        "recession", "gdp", "unemployment", "jobs report",
    }

    FINANCE_PATTERNS: List[str] = [
        r"\b(fed|fomc|federal\s+reserve)\s+(rate|cut|hike|decision|meeting)",
        r"\brate\s+(cut|hike|decision)s?\b",
        r"\b(s&p|spx|dow|nasdaq|djia)\s*(500)?\s*(up|down|above|below)",
        r"\blargest\s+company\b",
        r"\bmarket\s+cap\b",
        r"\b(amzn|aapl|tsla|nvda|googl|msft|meta|nflx)\b",
        r"\b(amazon|apple|tesla|nvidia|google|microsoft|netflix)\s+(stock|close|finish)",
        r"\b(gold|silver|oil)\s+(price|reach|hit|above|below)",
        r"\b(recession|gdp\s+growth|unemployment)\s*(in|for|by)?\s*\d{4}",
        r"\bjobs?\s+report\b",
        r"\binflation\s+(rate|above|below|reach)",
        r"\b(q[1-4]|quarterly)\s+(earnings|results|report)",
    ]

    # =========================================================================
    # GENERAL TIME-BOUND EVENTS (catch-all for interesting markets)
    # =========================================================================
    GENERAL_PATTERNS: List[str] = [
        # Markets with specific dates/deadlines
        r"\bby\s+(end\s+of\s+)?(january|february|march|april|may|june|july|august|september|october|november|december)\s+\d{4}",
        r"\bbefore\s+(january|february|march|april|may|june|july|august|september|october|november|december)\s+\d{1,2}",
        r"\bin\s+(q[1-4]|january|february|march|april|may|june|july|august|september|october|november|december)\s+\d{4}",
        # Action-oriented markets
        r"\bwill\s+\w+\s+(announce|release|launch|approve|reject|ban|pass)\b",
        r"\b(announce|release|launch|approve|reject)\s+by\b",
    ]

    # =========================================================================
    # DATE EXTRACTION PATTERNS
    # =========================================================================
    DATE_PATTERNS: List[Tuple[str, str]] = [
        # ISO format
        (r"(\d{4}-\d{2}-\d{2})", "%Y-%m-%d"),
        # Month day, year
        (r"((?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4})", "%B %d, %Y"),
        (r"((?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4})", "%B %d %Y"),
        # day Month year
        (r"(\d{1,2}\s+(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4})", "%d %B %Y"),
        # Short month
        (r"((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2},?\s+\d{4})", "%b %d, %Y"),
        (r"((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2},?\s+\d{4})", "%b %d %Y"),
        # MM/DD/YYYY
        (r"(\d{1,2}/\d{1,2}/\d{4})", "%m/%d/%Y"),
        # DD.MM.YYYY
        (r"(\d{1,2}\.\d{1,2}\.\d{4})", "%d.%m.%Y"),
        # Year only with context
        (r"by\s+(?:end\s+of\s+)?(\d{4})", None),  # Just year
        (r"before\s+(\d{4})", None),  # Just year
        (r"in\s+(\d{4})", None),  # Just year
    ]

    def __init__(
        self,
        custom_eu_keywords: Optional[List[str]] = None,
        custom_ai_keywords: Optional[List[str]] = None,
    ):
        """
        Initialize the market filter.

        Args:
            custom_eu_keywords: Additional EU keywords to match
            custom_ai_keywords: Additional AI keywords to match
        """
        self.eu_keywords = set(self.EU_KEYWORDS)
        self.ai_keywords = set(self.AI_KEYWORDS)
        self.corporate_keywords = set(self.CORPORATE_KEYWORDS)
        self.court_keywords = set(self.COURT_KEYWORDS)
        self.weather_keywords = set(self.WEATHER_KEYWORDS)
        self.political_keywords = set(self.POLITICAL_KEYWORDS)
        self.crypto_keywords = set(self.CRYPTO_KEYWORDS)
        self.finance_keywords = set(self.FINANCE_KEYWORDS)

        if custom_eu_keywords:
            self.eu_keywords.update(k.lower() for k in custom_eu_keywords)
        if custom_ai_keywords:
            self.ai_keywords.update(k.lower() for k in custom_ai_keywords)

        # Compile regex patterns
        self._eu_patterns = [re.compile(p, re.IGNORECASE) for p in self.EU_PATTERNS]
        self._ai_patterns = [re.compile(p, re.IGNORECASE) for p in self.AI_PATTERNS]
        self._corporate_patterns = [re.compile(p, re.IGNORECASE) for p in self.CORPORATE_PATTERNS]
        self._court_patterns = [re.compile(p, re.IGNORECASE) for p in self.COURT_PATTERNS]
        self._weather_patterns = [re.compile(p, re.IGNORECASE) for p in self.WEATHER_PATTERNS]
        self._political_patterns = [re.compile(p, re.IGNORECASE) for p in self.POLITICAL_PATTERNS]
        self._crypto_patterns = [re.compile(p, re.IGNORECASE) for p in self.CRYPTO_PATTERNS]
        self._finance_patterns = [re.compile(p, re.IGNORECASE) for p in self.FINANCE_PATTERNS]
        self._general_patterns = [re.compile(p, re.IGNORECASE) for p in self.GENERAL_PATTERNS]
        self._price_patterns = [re.compile(p, re.IGNORECASE) for p in self.PRICE_MARKET_PATTERNS]
        self._opinion_patterns = [re.compile(p, re.IGNORECASE) for p in self.OPINION_MARKET_PATTERNS]

    def filter_market(self, market: Dict[str, Any]) -> FilteredMarket:
        """
        Filter a single market for relevance.

        Args:
            market: Sanitized market dictionary

        Returns:
            FilteredMarket with result and metadata
        """
        notes: List[str] = []

        # Extract searchable text
        title = market.get("question") or market.get("title") or ""
        description = market.get("description") or ""
        resolution = market.get("resolutionSource") or market.get("resolution") or ""
        searchable_text = f"{title} {description} {resolution}".lower()

        # Check for incomplete data
        if not title.strip():
            notes.append("missing_title")
            return FilteredMarket(
                market=market,
                result=FilterResult.EXCLUDED_INCOMPLETE,
                matched_eu_keywords=[],
                matched_ai_keywords=[],
                extracted_deadline=None,
                notes=notes,
            )

        # Check exclusion patterns first
        if self._matches_patterns(searchable_text, self._price_patterns):
            notes.append("price_market_detected")
            return FilteredMarket(
                market=market,
                result=FilterResult.EXCLUDED_PRICE_MARKET,
                matched_eu_keywords=[],
                matched_ai_keywords=[],
                extracted_deadline=None,
                notes=notes,
            )

        if self._matches_patterns(searchable_text, self._opinion_patterns):
            notes.append("opinion_market_detected")
            return FilteredMarket(
                market=market,
                result=FilterResult.EXCLUDED_OPINION_MARKET,
                matched_eu_keywords=[],
                matched_ai_keywords=[],
                extracted_deadline=None,
                notes=notes,
            )

        # Check for CORPORATE EVENT markets first (priority check)
        # But exclude government reports, immigration, etc.
        is_corporate_excluded = any(excl in searchable_text for excl in self.CORPORATE_EXCLUSIONS)
        if not is_corporate_excluded:
            corporate_matches = self._find_keyword_matches(searchable_text, self._corporate_patterns)
            if corporate_matches:
                deadline = self._extract_deadline(market, searchable_text)
                if self._is_deadline_valid(deadline):
                    notes.append("corporate_event_market")
                    return FilteredMarket(
                        market=market,
                        result=FilterResult.INCLUDED_CORPORATE,
                        matched_eu_keywords=[],
                        matched_ai_keywords=corporate_matches,
                        extracted_deadline=deadline,
                        notes=notes,
                    )

        # Check for WEATHER EVENT markets
        weather_matches = self._find_keyword_matches(searchable_text, self._weather_patterns)
        if weather_matches:
            deadline = self._extract_deadline(market, searchable_text)
            if self._is_deadline_valid(deadline):
                notes.append("weather_event_market")
                return FilteredMarket(
                    market=market,
                    result=FilterResult.INCLUDED_WEATHER,
                    matched_eu_keywords=[],
                    matched_ai_keywords=weather_matches,
                    extracted_deadline=deadline,
                    notes=notes,
                )

        # Check for COURT RULING markets (priority check)
        # But exclude meme markets, games, etc.
        is_court_excluded = any(excl in searchable_text for excl in self.COURT_EXCLUSIONS)
        if not is_court_excluded:
            court_matches = self._find_keyword_matches(searchable_text, self._court_patterns)
            if court_matches:
                deadline = self._extract_deadline(market, searchable_text)
                if self._is_deadline_valid(deadline):
                    notes.append("court_ruling_market")
                    return FilteredMarket(
                        market=market,
                        result=FilterResult.INCLUDED_COURT,
                        matched_eu_keywords=[],
                        matched_ai_keywords=court_matches,
                        extracted_deadline=deadline,
                        notes=notes,
                    )

        # Check for POLITICAL EVENT markets
        political_matches = self._find_keyword_matches(searchable_text, self._political_patterns)
        if political_matches:
            deadline = self._extract_deadline(market, searchable_text)
            if self._is_deadline_valid(deadline):
                notes.append("political_event_market")
                return FilteredMarket(
                    market=market,
                    result=FilterResult.INCLUDED_POLITICAL,
                    matched_eu_keywords=[],
                    matched_ai_keywords=political_matches,
                    extracted_deadline=deadline,
                    notes=notes,
                )

        # Check for CRYPTO EVENT markets
        crypto_matches = self._find_keyword_matches(searchable_text, self._crypto_patterns)
        if crypto_matches:
            deadline = self._extract_deadline(market, searchable_text)
            if self._is_deadline_valid(deadline):
                notes.append("crypto_event_market")
                return FilteredMarket(
                    market=market,
                    result=FilterResult.INCLUDED_CRYPTO,
                    matched_eu_keywords=[],
                    matched_ai_keywords=crypto_matches,
                    extracted_deadline=deadline,
                    notes=notes,
                )

        # Check for FINANCE EVENT markets (Fed, stocks, indices)
        finance_matches = self._find_keyword_matches(searchable_text, self._finance_patterns)
        if finance_matches:
            deadline = self._extract_deadline(market, searchable_text)
            if self._is_deadline_valid(deadline):
                notes.append("finance_event_market")
                return FilteredMarket(
                    market=market,
                    result=FilterResult.INCLUDED_FINANCE,
                    matched_eu_keywords=[],
                    matched_ai_keywords=finance_matches,
                    extracted_deadline=deadline,
                    notes=notes,
                )

        # Check for GENERAL time-bound markets (catch-all)
        general_matches = self._find_keyword_matches(searchable_text, self._general_patterns)
        if general_matches:
            deadline = self._extract_deadline(market, searchable_text)
            if self._is_deadline_valid(deadline):
                notes.append("general_event_market")
                return FilteredMarket(
                    market=market,
                    result=FilterResult.INCLUDED_GENERAL,
                    matched_eu_keywords=[],
                    matched_ai_keywords=general_matches,
                    extracted_deadline=deadline,
                    notes=notes,
                )

        # Check EU keywords (original flow)
        eu_matches = self._find_keyword_matches(searchable_text, self._eu_patterns)
        if not eu_matches:
            notes.append("no_eu_keywords")
            return FilteredMarket(
                market=market,
                result=FilterResult.EXCLUDED_NO_EU_MATCH,
                matched_eu_keywords=[],
                matched_ai_keywords=[],
                extracted_deadline=None,
                notes=notes,
            )

        # Check AI/Tech keywords
        ai_matches = self._find_keyword_matches(searchable_text, self._ai_patterns)
        if not ai_matches:
            notes.append("no_ai_keywords")
            return FilteredMarket(
                market=market,
                result=FilterResult.EXCLUDED_NO_AI_MATCH,
                matched_eu_keywords=eu_matches,
                matched_ai_keywords=[],
                extracted_deadline=None,
                notes=notes,
            )

        # Extract deadline
        deadline = self._extract_deadline(market, searchable_text)
        if deadline is None:
            notes.append("no_deadline_found")
            return FilteredMarket(
                market=market,
                result=FilterResult.EXCLUDED_NO_DEADLINE,
                matched_eu_keywords=eu_matches,
                matched_ai_keywords=ai_matches,
                extracted_deadline=None,
                notes=notes,
            )

        # Check if deadline is in the past
        if deadline < date.today():
            notes.append("deadline_in_past")
            return FilteredMarket(
                market=market,
                result=FilterResult.EXCLUDED_NO_DEADLINE,
                matched_eu_keywords=eu_matches,
                matched_ai_keywords=ai_matches,
                extracted_deadline=deadline,
                notes=notes,
            )

        # All checks passed - include
        return FilteredMarket(
            market=market,
            result=FilterResult.INCLUDED,
            matched_eu_keywords=eu_matches,
            matched_ai_keywords=ai_matches,
            extracted_deadline=deadline,
            notes=notes,
        )

    def filter_markets(
        self, markets: List[Dict[str, Any]]
    ) -> Tuple[List[FilteredMarket], Dict[str, int]]:
        """
        Filter multiple markets.

        Args:
            markets: List of sanitized market dictionaries

        Returns:
            Tuple of (filtered_markets, stats_by_result)
        """
        filtered = []
        stats: Dict[str, int] = {}

        for market in markets:
            result = self.filter_market(market)
            filtered.append(result)

            key = result.result.value
            stats[key] = stats.get(key, 0) + 1

        return filtered, stats

    def _matches_patterns(
        self, text: str, patterns: List[re.Pattern]
    ) -> bool:
        """Check if text matches any pattern."""
        for pattern in patterns:
            if pattern.search(text):
                return True
        return False

    def _find_keyword_matches(
        self, text: str, patterns: List[re.Pattern]
    ) -> List[str]:
        """Find all matching keywords in text."""
        matches = []
        for pattern in patterns:
            found = pattern.findall(text)
            matches.extend(found)
        return list(set(matches))  # Dedupe

    def _extract_deadline(
        self, market: Dict[str, Any], searchable_text: str
    ) -> Optional[date]:
        """
        Extract deadline from market data or text.

        Args:
            market: Market dictionary
            searchable_text: Combined searchable text

        Returns:
            Extracted date or None
        """
        # Try metadata fields first
        for field in ["endDate", "endDateIso", "end_date", "closeTime", "resolutionDate"]:
            value = market.get(field)
            if value:
                parsed = self._parse_date_string(str(value))
                if parsed:
                    return parsed

        # Try to extract from text
        for pattern_str, date_format in self.DATE_PATTERNS:
            pattern = re.compile(pattern_str, re.IGNORECASE)
            match = pattern.search(searchable_text)
            if match:
                date_str = match.group(1)
                parsed = self._parse_date_string(date_str, date_format)
                if parsed:
                    return parsed

        return None

    def _is_deadline_valid(self, deadline: Optional[date]) -> bool:
        """Check if deadline is valid (not None and not in the past)."""
        if deadline is None:
            return False
        if deadline < date.today():
            return False
        return True

    def _parse_date_string(
        self, date_str: str, format_hint: Optional[str] = None
    ) -> Optional[date]:
        """
        Parse a date string into a date object.

        Args:
            date_str: String to parse
            format_hint: Optional format string

        Returns:
            Parsed date or None
        """
        # Clean the string
        date_str = date_str.strip().replace(",", "")

        # Try ISO format first
        try:
            # Handle ISO datetime
            if "T" in date_str:
                return datetime.fromisoformat(date_str.replace("Z", "+00:00")).date()
            # Handle ISO date
            if re.match(r"^\d{4}-\d{2}-\d{2}$", date_str):
                return date.fromisoformat(date_str)
        except ValueError:
            pass

        # Try format hint
        if format_hint:
            try:
                return datetime.strptime(date_str, format_hint).date()
            except ValueError:
                pass

        # Try common formats
        formats = [
            "%Y-%m-%d",
            "%B %d %Y",
            "%b %d %Y",
            "%d %B %Y",
            "%d %b %Y",
            "%m/%d/%Y",
            "%d.%m.%Y",
        ]

        for fmt in formats:
            try:
                return datetime.strptime(date_str, fmt).date()
            except ValueError:
                continue

        # Handle year-only
        if re.match(r"^\d{4}$", date_str):
            year = int(date_str)
            if 2020 <= year <= 2030:
                return date(year, 12, 31)  # End of year

        return None
