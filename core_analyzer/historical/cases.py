# =============================================================================
# POLYMARKET EU AI REGULATION ANALYZER
# Module: historical/cases.py
# Purpose: Historical case dataset for counterfactual testing
# =============================================================================
#
# CASE DESIGN PRINCIPLES:
# - Use REAL EU regulatory timelines (not simplified)
# - Test COMMON institutional timing errors
# - Focus on adoption vs application confusion
# - Include delegated act delays
# - Represent realistic Polymarket-style resolution text
#
# CASE SELECTION:
# 1. EU AI Act - Prohibited practices timing (adoption vs enforcement)
# 2. GDPR - Enforcement action timing (transition period)
# 3. DMA - Gatekeeper compliance deadline (designation delays)
# 4. EU AI Act - General application date (August 2027 complexity)
# 5. DSA - VLOPs designation timing
#
# =============================================================================

from datetime import date
from typing import List

from .models import HistoricalCase, FormalTimeline, KnownOutcome


def get_all_cases() -> List[HistoricalCase]:
    """
    Get all historical cases for testing.

    Returns:
        List of HistoricalCase objects
    """
    return [
        case_ai_act_prohibited_practices_early(),
        case_gdpr_enforcement_immediate(),
        case_dma_gatekeeper_compliance(),
        case_ai_act_full_application(),
        case_ai_act_delegated_acts(),
    ]


# =============================================================================
# CASE 1: EU AI Act Prohibited Practices - Early Enforcement Expectation
# =============================================================================
# COMMON ERROR: Confusing adoption date with enforcement start
# The AI Act was adopted August 1, 2024, but Article 5 (prohibited practices)
# only applies from February 2, 2025.
# =============================================================================

def case_ai_act_prohibited_practices_early() -> HistoricalCase:
    """
    Case: Market expected enforcement action by end of 2024.

    SCENARIO:
    A hypothetical market asks whether ANY enforcement action under Article 5
    of the EU AI Act will occur by December 31, 2024.

    REALITY:
    Article 5 provisions only apply from February 2, 2025 (6 months after
    entry into force). No enforcement action was possible in 2024.

    EXPECTED ANALYZER BEHAVIOR:
    Should REJECT due to timeline impossibility - enforcement cannot
    occur before the provisions apply.
    """
    return HistoricalCase(
        case_id="CASE_001",
        title="EU AI Act Prohibited Practices Enforcement by End of 2024",
        description=(
            "Tests whether the analyzer correctly rejects a market asking about "
            "enforcement action before the relevant provisions apply. "
            "Common error: confusing adoption (Aug 2024) with enforcement start (Feb 2025)."
        ),
        synthetic_resolution_text=(
            "This market resolves to YES if the European Commission or any EU Member "
            "State authority has publicly announced enforcement action under Article 5 "
            "(Prohibited AI practices) of Regulation (EU) 2024/1689 (the EU AI Act) "
            "by 11:59 PM CET on December 31, 2024. Enforcement action includes: formal "
            "investigations, warnings, fines, or cease-and-desist orders. Resolution "
            "source: European Commission press releases or official communications from "
            "national supervisory authorities."
        ),
        hypothetical_target_date=date(2024, 12, 31),
        referenced_regulation="EU AI Act",
        authority_involved="European Commission, National Supervisory Authorities",
        analysis_as_of_date=date(2024, 9, 1),
        formal_timeline=FormalTimeline(
            proposal_date=date(2021, 4, 21),
            adoption_date=date(2024, 5, 21),  # EP adopted
            publication_date=date(2024, 7, 12),  # OJ publication
            entry_into_force=date(2024, 8, 1),
            application_date=date(2026, 8, 2),  # General application
            enforcement_start=date(2025, 2, 2),  # Article 5 applies 6 months after EIF
            additional_milestones={
                "article_5_application": date(2025, 2, 2),
                "article_111_application": date(2025, 8, 2),
                "high_risk_application": date(2027, 8, 2),
            }
        ),
        known_outcome=KnownOutcome.NO,
        notes=(
            "The EU AI Act has a staggered application timeline. Article 5 "
            "(prohibited practices) applies 6 months after entry into force "
            "(February 2, 2025). No enforcement action was legally possible in 2024."
        ),
        failure_explanation=(
            "Article 5 provisions only became applicable on February 2, 2025. "
            "No enforcement action could legally occur before that date. "
            "Common error: confusing 'adoption' or 'entry into force' with "
            "'application date' for specific provisions."
        ),
    )


# =============================================================================
# CASE 2: GDPR Enforcement - Immediate Action Expectation
# =============================================================================
# COMMON ERROR: Expecting enforcement immediately after regulation adoption
# GDPR was adopted April 2016, but only became enforceable May 25, 2018.
# =============================================================================

def case_gdpr_enforcement_immediate() -> HistoricalCase:
    """
    Case: Market expected GDPR fines by end of 2016.

    SCENARIO:
    A hypothetical market from 2016 asks whether any GDPR fine will
    be issued by December 31, 2016.

    REALITY:
    GDPR had a 2-year transition period. It only became enforceable
    on May 25, 2018. No fines were possible in 2016 or 2017.

    EXPECTED ANALYZER BEHAVIOR:
    Should REJECT due to the mandatory transition period.
    """
    return HistoricalCase(
        case_id="CASE_002",
        title="GDPR Enforcement Fine by End of 2016",
        description=(
            "Tests whether the analyzer correctly identifies the mandatory "
            "2-year transition period in GDPR. Common error: expecting immediate "
            "enforcement after adoption."
        ),
        synthetic_resolution_text=(
            "This market resolves to YES if any EU Data Protection Authority "
            "issues a fine under the General Data Protection Regulation (GDPR) "
            "(Regulation (EU) 2016/679) by 11:59 PM CET on December 31, 2016. "
            "Resolution source: Official press releases from national DPAs or "
            "the European Data Protection Board."
        ),
        hypothetical_target_date=date(2016, 12, 31),
        referenced_regulation="GDPR",
        authority_involved="European Data Protection Board, National DPAs",
        analysis_as_of_date=date(2016, 5, 1),
        formal_timeline=FormalTimeline(
            proposal_date=date(2012, 1, 25),
            adoption_date=date(2016, 4, 14),
            publication_date=date(2016, 5, 4),
            entry_into_force=date(2016, 5, 24),
            application_date=date(2018, 5, 25),  # 2 years after EIF
            enforcement_start=date(2018, 5, 25),
            additional_milestones={
                "transition_period_end": date(2018, 5, 25),
            }
        ),
        known_outcome=KnownOutcome.NO,
        notes=(
            "GDPR included a mandatory 2-year transition period. "
            "Article 99(2) states the regulation 'shall apply from 25 May 2018'. "
            "No fines could be issued before that date."
        ),
        failure_explanation=(
            "GDPR explicitly stated a 2-year transition period. "
            "Article 99(2) clearly specifies application from May 25, 2018. "
            "No enforcement was legally possible before that date."
        ),
    )


# =============================================================================
# CASE 3: DMA Gatekeeper Compliance - Underestimated Timeline
# =============================================================================
# COMMON ERROR: Underestimating time for gatekeeper designation + compliance
# DMA required Commission to designate gatekeepers, then 6-month compliance.
# =============================================================================

def case_dma_gatekeeper_compliance() -> HistoricalCase:
    """
    Case: Market expected full DMA compliance by March 2024.

    SCENARIO:
    A hypothetical market asks whether ALL designated gatekeepers
    will be fully compliant with DMA obligations by March 1, 2024.

    REALITY:
    Gatekeeper designations occurred September 6, 2023, triggering
    a 6-month compliance period ending March 6, 2024. March 1 was
    before the compliance deadline.

    EXPECTED ANALYZER BEHAVIOR:
    Should REJECT because the compliance deadline had not yet passed.
    Market resolution would be impossible before March 6, 2024.
    """
    return HistoricalCase(
        case_id="CASE_003",
        title="DMA Full Gatekeeper Compliance by March 1, 2024",
        description=(
            "Tests whether the analyzer correctly identifies the 6-month "
            "compliance window after gatekeeper designation. Common error: "
            "underestimating procedural timelines."
        ),
        synthetic_resolution_text=(
            "This market resolves to YES if ALL companies designated as "
            "gatekeepers under the Digital Markets Act (DMA) have submitted "
            "compliance reports demonstrating full compliance with all "
            "obligations by 11:59 PM CET on March 1, 2024. Resolution source: "
            "European Commission DMA implementation announcements."
        ),
        hypothetical_target_date=date(2024, 3, 1),
        referenced_regulation="Digital Markets Act",
        authority_involved="European Commission DG COMP",
        analysis_as_of_date=date(2023, 10, 1),
        formal_timeline=FormalTimeline(
            proposal_date=date(2020, 12, 15),
            adoption_date=date(2022, 7, 5),
            publication_date=date(2022, 10, 12),
            entry_into_force=date(2022, 11, 1),
            application_date=date(2023, 5, 2),  # 6 months after EIF
            enforcement_start=date(2024, 3, 7),  # After compliance deadline
            additional_milestones={
                "designation_deadline": date(2023, 9, 6),
                "compliance_deadline": date(2024, 3, 6),
            }
        ),
        known_outcome=KnownOutcome.NO,
        notes=(
            "The DMA compliance timeline: (1) DMA applicable May 2, 2023, "
            "(2) Notification period July 3, 2023, (3) Designation by Sept 6, 2023, "
            "(4) 6-month compliance period, (5) Deadline: March 6, 2024. "
            "March 1 was BEFORE the compliance deadline."
        ),
        failure_explanation=(
            "The compliance deadline was March 6, 2024, not March 1. "
            "The market target date was before the legally mandated deadline, "
            "making compliance resolution impossible."
        ),
    )


# =============================================================================
# CASE 4: EU AI Act Full Application - 2027 Complexity
# =============================================================================
# COMMON ERROR: Not accounting for the staggered application timeline
# The AI Act has multiple application dates through August 2027.
# =============================================================================

def case_ai_act_full_application() -> HistoricalCase:
    """
    Case: Market expected full AI Act application by end of 2025.

    SCENARIO:
    A hypothetical market asks whether the EU AI Act will be
    "fully applicable" by December 31, 2025.

    REALITY:
    The AI Act has a staggered timeline. High-risk AI system rules
    (Article 6) only apply from August 2, 2027. Full application
    is not until August 2027 at the earliest.

    EXPECTED ANALYZER BEHAVIOR:
    Should REJECT because the market resolution criteria are
    impossible to meet before 2027.
    """
    return HistoricalCase(
        case_id="CASE_004",
        title="EU AI Act Fully Applicable by End of 2025",
        description=(
            "Tests whether the analyzer correctly identifies the staggered "
            "application timeline of the AI Act. Common error: expecting "
            "single application date."
        ),
        synthetic_resolution_text=(
            "This market resolves to YES if ALL provisions of Regulation (EU) "
            "2024/1689 (the EU AI Act) are applicable and enforceable in all "
            "EU Member States by 11:59 PM CET on December 31, 2025. This includes "
            "all rules for high-risk AI systems, general-purpose AI, and prohibited "
            "practices. Resolution source: Official Journal of the European Union."
        ),
        hypothetical_target_date=date(2025, 12, 31),
        referenced_regulation="EU AI Act",
        authority_involved="European Commission, EU AI Office",
        analysis_as_of_date=date(2024, 9, 1),
        formal_timeline=FormalTimeline(
            proposal_date=date(2021, 4, 21),
            adoption_date=date(2024, 5, 21),
            publication_date=date(2024, 7, 12),
            entry_into_force=date(2024, 8, 1),
            application_date=date(2026, 8, 2),  # General application
            enforcement_start=date(2025, 2, 2),  # First provisions
            additional_milestones={
                "article_5_application": date(2025, 2, 2),  # 6 months
                "article_111_application": date(2025, 8, 2),  # 12 months
                "chapter_iii_section_4_application": date(2025, 8, 2),  # 12 months
                "general_application": date(2026, 8, 2),  # 24 months
                "article_6_high_risk": date(2027, 8, 2),  # 36 months
            }
        ),
        known_outcome=KnownOutcome.NO,
        notes=(
            "The AI Act has a complex staggered application timeline: "
            "6 months (prohibited AI), 12 months (governance/GPAI), "
            "24 months (general), 36 months (high-risk systems Annex I). "
            "Full application is August 2027, not 2025."
        ),
        failure_explanation=(
            "The AI Act explicitly provides for staggered application. "
            "High-risk AI system rules (Chapter III) only apply from August 2027. "
            "The market asking for 'full' application by 2025 was structurally impossible."
        ),
    )


# =============================================================================
# CASE 5: EU AI Act Delegated Acts - Dependency Underestimation
# =============================================================================
# COMMON ERROR: Not accounting for delegated act dependencies
# Many AI Act provisions require delegated acts before they can be enforced.
# =============================================================================

def case_ai_act_delegated_acts() -> HistoricalCase:
    """
    Case: Market expected high-risk classification clarity by mid-2025.

    SCENARIO:
    A hypothetical market asks whether the Commission will have
    published all delegated acts clarifying high-risk AI classification
    by June 30, 2025.

    REALITY:
    Delegated acts for high-risk classification (Article 6) have
    extended timelines and depend on AI Office capacity. The Commission
    has discretion and no hard deadline.

    EXPECTED ANALYZER BEHAVIOR:
    Should REJECT due to ambiguous resolution criteria and
    uncertainty about delegated act timelines.
    """
    return HistoricalCase(
        case_id="CASE_005",
        title="EU AI Act High-Risk Delegated Acts by June 2025",
        description=(
            "Tests whether the analyzer correctly identifies delegated act "
            "dependencies and timeline uncertainties. Common error: assuming "
            "fast delegated act adoption."
        ),
        synthetic_resolution_text=(
            "This market resolves to YES if the European Commission has adopted "
            "and published in the Official Journal ALL delegated acts required "
            "under Article 6(6) and Article 6(7) of the EU AI Act (clarifying "
            "high-risk AI system classification criteria) by 11:59 PM CET on "
            "June 30, 2025. Resolution source: EUR-Lex official publications."
        ),
        hypothetical_target_date=date(2025, 6, 30),
        referenced_regulation="EU AI Act",
        authority_involved="European Commission, EU AI Office",
        analysis_as_of_date=date(2024, 9, 1),
        formal_timeline=FormalTimeline(
            proposal_date=date(2021, 4, 21),
            adoption_date=date(2024, 5, 21),
            publication_date=date(2024, 7, 12),
            entry_into_force=date(2024, 8, 1),
            application_date=date(2026, 8, 2),
            enforcement_start=date(2025, 2, 2),
            additional_milestones={
                "ai_office_established": date(2024, 2, 21),
                # Delegated acts have no fixed deadline - Commission discretion
            }
        ),
        known_outcome=KnownOutcome.NO,
        notes=(
            "Delegated acts under EU law have no guaranteed timeline. "
            "The Commission has discretion on timing. The AI Office was "
            "only established in February 2024 and needs capacity building. "
            "As of the target date, not all delegated acts were published."
        ),
        failure_explanation=(
            "Delegated acts depend on Commission discretion and preparatory work. "
            "The AI Office capacity constraints and stakeholder consultation "
            "requirements meant delegated acts were not all ready by June 2025. "
            "Common error: assuming delegated acts follow fixed timelines."
        ),
    )
