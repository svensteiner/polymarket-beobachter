# =============================================================================
# POLYMARKET EU AI REGULATION ANALYZER
# Module: core/resolution_parser.py
# Purpose: Parse and validate market resolution criteria
# =============================================================================
#
# AUDIT PRINCIPLE:
# A market is only tradeable if its resolution is:
# 1. Binary (YES/NO outcome)
# 2. Objectively verifiable (can be checked against public record)
# 3. Unambiguous (no room for interpretation disputes)
#
# If ANY ambiguity is detected, this module flags a HARD FAIL.
# This is a FAIL CLOSED design - uncertainty defaults to NO_TRADE.
#
# METHODOLOGY:
# - Pattern matching against known ambiguous phrases
# - Keyword detection for verifiable sources
# - Structural analysis of resolution text
#
# NO NLP. NO ML. Only deterministic pattern matching.
#
# =============================================================================

import re
from typing import List, Tuple
from models.data_models import MarketInput, ResolutionAnalysis


class ResolutionParser:
    """
    Parser for Polymarket resolution criteria.

    Determines if a market has clean, tradeable resolution criteria.

    DESIGN NOTES:
    - All methods are deterministic
    - Pattern lists are explicit and auditable
    - Err on the side of flagging ambiguity (fail closed)
    """

    # =========================================================================
    # AMBIGUITY PATTERNS
    # =========================================================================
    # These phrases indicate potential interpretation disputes.
    # If found, they are flagged as ambiguity concerns.
    #
    # RATIONALE for each pattern:
    # - "may", "might", "could": Uncertainty in resolution criteria
    # - "reasonable", "substantial": Subjective judgment required
    # - "in the opinion of": Depends on whose opinion
    # - "generally", "typically": Allows for exceptions
    # - "or similar", "or equivalent": Undefined scope
    # - "discretion": Arbiter judgment required
    # - "material", "significant": Undefined threshold
    # =========================================================================

    AMBIGUITY_PATTERNS: List[Tuple[str, str]] = [
        (r"\bmay\b", "Word 'may' suggests uncertainty in resolution criteria"),
        (r"\bmight\b", "Word 'might' suggests uncertainty in resolution criteria"),
        (r"\bcould\b", "Word 'could' suggests uncertainty in resolution criteria"),
        (r"\breasonabl[ey]\b", "Word 'reasonable/reasonably' requires subjective judgment"),
        (r"\bsubstantial(ly)?\b", "Word 'substantial' is undefined and subjective"),
        (r"\bin the opinion of\b", "Resolution depends on subjective opinion"),
        (r"\bgenerally\b", "Word 'generally' allows for undefined exceptions"),
        (r"\btypically\b", "Word 'typically' allows for undefined exceptions"),
        (r"\bor similar\b", "Phrase 'or similar' has undefined scope"),
        (r"\bor equivalent\b", "Phrase 'or equivalent' has undefined scope"),
        (r"\bdiscretion\b", "Resolution involves arbiter discretion"),
        (r"\bmaterial(ly)?\b", "Word 'material' is undefined threshold"),
        (r"\bsignificant(ly)?\b", "Word 'significant' is undefined threshold"),
        (r"\bat (its|their|our) sole\b", "Sole discretion language is dangerous"),
        (r"\bbelieve[sd]?\b", "Resolution based on beliefs is subjective"),
        (r"\bappears?\b", "Word 'appears' is subjective"),
        (r"\bseem[s]?\b", "Word 'seems' is subjective"),
        (r"\blikely\b", "Word 'likely' is probabilistic, not deterministic"),
        (r"\bunlikely\b", "Word 'unlikely' is probabilistic, not deterministic"),
    ]

    # =========================================================================
    # VERIFIABLE SOURCE PATTERNS
    # =========================================================================
    # These phrases indicate the resolution references an official source.
    # The presence of these is a POSITIVE signal.
    #
    # RATIONALE:
    # - Official Journal: EU's official publication
    # - EUR-Lex: EU's legal database
    # - European Commission: Official statements
    # - Press release: Official communications
    # - CELEX number: Official EU legal document ID
    # =========================================================================

    VERIFIABLE_SOURCE_PATTERNS: List[Tuple[str, str]] = [
        (r"\bOfficial Journal\b", "References EU Official Journal"),
        (r"\bEUR-Lex\b", "References EUR-Lex database"),
        (r"\bEuropean Commission\b", "References European Commission"),
        (r"\bEuropean Parliament\b", "References European Parliament"),
        (r"\bCouncil of the (European Union|EU)\b", "References Council of the EU"),
        (r"\bpress release\b", "References official press release"),
        (r"\bCELEX\b", "References CELEX document number"),
        (r"\bpublished\b", "References publication event"),
        (r"\bofficial(ly)?\b", "References official source"),
        (r"\bRegulation \(EU\)", "References specific EU Regulation"),
        (r"\bDirective \(EU\)", "References specific EU Directive"),
    ]

    # =========================================================================
    # BINARY OUTCOME PATTERNS
    # =========================================================================
    # These patterns suggest the market is binary YES/NO.
    # =========================================================================

    BINARY_PATTERNS: List[str] = [
        r"\byes\b.*\bno\b",
        r"\bno\b.*\byes\b",
        r"\bwill\b.*\bby\b",
        r"\bwill not\b",
        r"\bbefore\b.*\d{4}",
        r"\bby\b.*\d{4}",
        r"\badopted\b",
        r"\bentered into force\b",
        r"\bpublished\b",
        r"\bin effect\b",
        r"\bapplicable\b",
    ]

    # =========================================================================
    # CRITICAL AMBIGUITY PATTERNS (HARD FAIL)
    # =========================================================================
    # These patterns are so problematic that they trigger immediate HARD FAIL.
    # =========================================================================

    CRITICAL_AMBIGUITY_PATTERNS: List[Tuple[str, str]] = [
        (r"\bno official resolution\b", "No official resolution criteria defined"),
        (r"\bto be determined\b", "Resolution criteria to be determined"),
        (r"\bTBD\b", "Resolution contains TBD"),
        (r"\bundefined\b", "Resolution explicitly undefined"),
        (r"\bsubject to change\b", "Resolution subject to change"),
        (r"\bmarket maker\b.*\bresolution\b", "Market maker determines resolution"),
    ]

    def __init__(self):
        """
        Initialize the resolution parser.

        Compiles all regex patterns for efficient repeated use.
        """
        # Pre-compile patterns for efficiency
        self._ambiguity_compiled = [
            (re.compile(pattern, re.IGNORECASE), reason)
            for pattern, reason in self.AMBIGUITY_PATTERNS
        ]

        self._source_compiled = [
            (re.compile(pattern, re.IGNORECASE), reason)
            for pattern, reason in self.VERIFIABLE_SOURCE_PATTERNS
        ]

        self._binary_compiled = [
            re.compile(pattern, re.IGNORECASE)
            for pattern in self.BINARY_PATTERNS
        ]

        self._critical_compiled = [
            (re.compile(pattern, re.IGNORECASE), reason)
            for pattern, reason in self.CRITICAL_AMBIGUITY_PATTERNS
        ]

    def analyze(self, market_input: MarketInput) -> ResolutionAnalysis:
        """
        Analyze the resolution criteria of a market.

        PROCESS:
        1. Check for critical ambiguities (immediate fail)
        2. Detect ambiguity flags
        3. Check for verifiable sources
        4. Assess binary nature
        5. Determine overall hard_fail status

        Args:
            market_input: The market to analyze

        Returns:
            ResolutionAnalysis with all findings
        """
        resolution_text = market_input.resolution_text
        ambiguity_flags: List[str] = []

        # ---------------------------------------------------------------------
        # STEP 1: Check for critical ambiguities (immediate HARD FAIL)
        # ---------------------------------------------------------------------
        for pattern, reason in self._critical_compiled:
            if pattern.search(resolution_text):
                # Critical ambiguity found - immediate hard fail
                return ResolutionAnalysis(
                    is_binary=False,
                    is_objectively_verifiable=False,
                    ambiguity_flags=[f"CRITICAL: {reason}"],
                    resolution_source_identified=False,
                    hard_fail=True,
                    reasoning=f"HARD FAIL: Critical ambiguity detected - {reason}. "
                              f"This market has fundamentally flawed resolution criteria."
                )

        # ---------------------------------------------------------------------
        # STEP 2: Detect ambiguity flags
        # ---------------------------------------------------------------------
        for pattern, reason in self._ambiguity_compiled:
            if pattern.search(resolution_text):
                ambiguity_flags.append(reason)

        # ---------------------------------------------------------------------
        # STEP 3: Check for verifiable sources
        # ---------------------------------------------------------------------
        source_indicators: List[str] = []
        for pattern, reason in self._source_compiled:
            if pattern.search(resolution_text):
                source_indicators.append(reason)

        resolution_source_identified = len(source_indicators) > 0

        # ---------------------------------------------------------------------
        # STEP 4: Assess binary nature
        # ---------------------------------------------------------------------
        binary_score = sum(
            1 for pattern in self._binary_compiled
            if pattern.search(resolution_text)
        )

        # A market is considered binary if it matches at least 2 binary patterns
        is_binary = binary_score >= 2

        # If not clearly binary, add an ambiguity flag
        if not is_binary:
            ambiguity_flags.append(
                "Resolution does not clearly indicate binary YES/NO outcome"
            )

        # ---------------------------------------------------------------------
        # STEP 5: Determine objectively verifiable
        # ---------------------------------------------------------------------
        # Objectively verifiable requires:
        # - A clear source is identified
        # - No more than 2 ambiguity flags
        is_objectively_verifiable = (
            resolution_source_identified and
            len(ambiguity_flags) <= 2
        )

        # ---------------------------------------------------------------------
        # STEP 6: Determine hard_fail status
        # ---------------------------------------------------------------------
        # Hard fail conditions:
        # - Not binary
        # - More than 3 ambiguity flags
        # - No verifiable source AND any ambiguity flags
        hard_fail = (
            not is_binary or
            len(ambiguity_flags) > 3 or
            (not resolution_source_identified and len(ambiguity_flags) > 0)
        )

        # ---------------------------------------------------------------------
        # STEP 7: Build reasoning
        # ---------------------------------------------------------------------
        reasoning_parts = []

        if is_binary:
            reasoning_parts.append(
                f"Resolution appears binary (matched {binary_score} binary patterns)."
            )
        else:
            reasoning_parts.append(
                "Resolution does NOT appear to be binary YES/NO."
            )

        if resolution_source_identified:
            reasoning_parts.append(
                f"Verifiable source(s) identified: {', '.join(source_indicators)}."
            )
        else:
            reasoning_parts.append(
                "No clear verifiable source identified in resolution text."
            )

        if ambiguity_flags:
            reasoning_parts.append(
                f"Ambiguity concerns ({len(ambiguity_flags)}): {'; '.join(ambiguity_flags)}."
            )
        else:
            reasoning_parts.append("No ambiguity concerns detected.")

        if hard_fail:
            reasoning_parts.append(
                "CONCLUSION: Resolution criteria fail quality check. HARD FAIL - NO TRADE."
            )
        else:
            reasoning_parts.append(
                "CONCLUSION: Resolution criteria pass quality check."
            )

        return ResolutionAnalysis(
            is_binary=is_binary,
            is_objectively_verifiable=is_objectively_verifiable,
            ambiguity_flags=ambiguity_flags,
            resolution_source_identified=resolution_source_identified,
            hard_fail=hard_fail,
            reasoning=" ".join(reasoning_parts)
        )
