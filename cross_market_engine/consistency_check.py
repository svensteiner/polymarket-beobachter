# =============================================================================
# CROSS-MARKET CONSISTENCY ENGINE - CONSISTENCY CHECKER
# =============================================================================
#
# Pure logic evaluation for market consistency.
#
# ISOLATION: This file has NO imports from trading code.
# All functions are PURE - no side effects, no I/O, no network.
#
# FAIL-CLOSED PRINCIPLE:
# If there is ANY ambiguity, return UNCLEAR (not INCONSISTENT).
# We never want false positives that might influence human decisions.
#
# =============================================================================

import uuid
from datetime import datetime
from typing import List, Optional

from .relations import Relation, RelationType
from .market_graph import MarketGraph, MarketNode
from .findings import Finding, FindingsSummary, ConsistencyStatus


def check_implies_relation(
    relation: Relation,
    p_a: float,
    p_b: float,
) -> ConsistencyStatus:
    """
    Check if an IMPLIES relation holds.

    IMPLIES semantics:
    - If A is true, then B must be true
    - Therefore: P(A) <= P(B)
    - If P(A) > P(B) + tolerance, this is INCONSISTENT

    Args:
        relation: The IMPLIES relation to check
        p_a: Probability of the antecedent market
        p_b: Probability of the consequent market

    Returns:
        ConsistencyStatus indicating the result

    FAIL-CLOSED: Returns UNCLEAR if inputs are invalid.
    """
    # Validate inputs - fail closed
    if relation.relation_type != RelationType.IMPLIES:
        return ConsistencyStatus.UNCLEAR

    if not (0.0 <= p_a <= 1.0) or not (0.0 <= p_b <= 1.0):
        return ConsistencyStatus.UNCLEAR

    # Edge cases - treat as unclear to avoid false positives
    if p_a < 0.01 or p_a > 0.99:
        # Near-certainty markets may have pricing anomalies
        # Don't flag as inconsistent
        return ConsistencyStatus.UNCLEAR

    if p_b < 0.01 or p_b > 0.99:
        return ConsistencyStatus.UNCLEAR

    # Core check: P(A) should be <= P(B) for IMPLIES
    # Inconsistent if: P(A) > P(B) + tolerance
    delta = p_a - p_b

    if delta > relation.tolerance:
        return ConsistencyStatus.INCONSISTENT

    return ConsistencyStatus.CONSISTENT


def generate_explanation(
    relation: Relation,
    p_a: float,
    p_b: float,
    status: ConsistencyStatus,
) -> str:
    """
    Generate a human-readable explanation of the consistency check.

    Args:
        relation: The relation that was checked
        p_a: Probability of market A
        p_b: Probability of market B
        status: The result of the check

    Returns:
        Plain English explanation
    """
    delta = p_a - p_b
    delta_pct = delta * 100

    if status == ConsistencyStatus.CONSISTENT:
        return (
            f"CONSISTENT: Market A ({p_a:.1%}) implies Market B ({p_b:.1%}). "
            f"The implication holds because P(A) <= P(B) + {relation.tolerance:.0%} tolerance. "
            f"Delta: {delta_pct:+.1f}%."
        )

    elif status == ConsistencyStatus.INCONSISTENT:
        return (
            f"INCONSISTENT: Market A ({p_a:.1%}) implies Market B ({p_b:.1%}), "
            f"but P(A) > P(B) by {delta_pct:.1f}% (exceeds {relation.tolerance:.0%} tolerance). "
            f"If A implies B, then P(A) should not exceed P(B). "
            f"This suggests a potential mispricing or the implication may not hold."
        )

    else:  # UNCLEAR
        return (
            f"UNCLEAR: Cannot determine consistency. "
            f"P(A)={p_a:.1%}, P(B)={p_b:.1%}. "
            f"This may be due to extreme probabilities or data issues."
        )


def check_relation(
    relation: Relation,
    graph: MarketGraph,
) -> Finding:
    """
    Check a single relation for consistency.

    Args:
        relation: The relation to check
        graph: The market graph containing market data

    Returns:
        A Finding object with the result

    FAIL-CLOSED: Returns UNCLEAR finding if markets not found.
    """
    finding_id = f"finding_{uuid.uuid4().hex[:12]}"
    timestamp = datetime.utcnow()

    # Get market data
    market_a = graph.get_market(relation.market_a_id)
    market_b = graph.get_market(relation.market_b_id)

    # Fail closed if markets not found
    if market_a is None or market_b is None:
        missing = []
        if market_a is None:
            missing.append(relation.market_a_id)
        if market_b is None:
            missing.append(relation.market_b_id)

        return Finding(
            finding_id=finding_id,
            timestamp=timestamp,
            market_a_id=relation.market_a_id,
            market_b_id=relation.market_b_id,
            relation_type=relation.relation_type.value,
            p_a=0.0,
            p_b=0.0,
            delta=0.0,
            tolerance=relation.tolerance,
            status=ConsistencyStatus.UNCLEAR,
            explanation=f"UNCLEAR: Missing market data for: {', '.join(missing)}",
            metadata={"missing_markets": missing},
        )

    p_a = market_a.probability
    p_b = market_b.probability
    delta = p_a - p_b

    # Check consistency
    status = check_implies_relation(relation, p_a, p_b)

    # Generate explanation
    explanation = generate_explanation(relation, p_a, p_b, status)

    return Finding(
        finding_id=finding_id,
        timestamp=timestamp,
        market_a_id=relation.market_a_id,
        market_b_id=relation.market_b_id,
        relation_type=relation.relation_type.value,
        p_a=p_a,
        p_b=p_b,
        delta=delta,
        tolerance=relation.tolerance,
        status=status,
        explanation=explanation,
        metadata={
            "market_a_question": market_a.question,
            "market_b_question": market_b.question,
            "relation_description": relation.description,
        },
    )


def check_all_relations(
    graph: MarketGraph,
    relations: Optional[List[Relation]] = None,
) -> FindingsSummary:
    """
    Check all relations in the graph for consistency.

    Args:
        graph: The market graph with market data
        relations: Optional list of relations to check (default: all in graph)

    Returns:
        A FindingsSummary with all results

    ISOLATION GUARANTEE:
    This function is PURE. It only reads data and produces findings.
    It has no side effects and cannot influence trading.
    """
    run_id = f"run_{uuid.uuid4().hex[:12]}"
    timestamp = datetime.utcnow()

    # Get relations to check
    if relations is None:
        relations = graph.get_all_relations()

    # Check each relation
    findings: List[Finding] = []
    for relation in relations:
        finding = check_relation(relation, graph)
        findings.append(finding)

    # Count results
    consistent_count = sum(1 for f in findings if f.status == ConsistencyStatus.CONSISTENT)
    inconsistent_count = sum(1 for f in findings if f.status == ConsistencyStatus.INCONSISTENT)
    unclear_count = sum(1 for f in findings if f.status == ConsistencyStatus.UNCLEAR)

    return FindingsSummary(
        run_id=run_id,
        timestamp=timestamp,
        total_relations_checked=len(findings),
        consistent_count=consistent_count,
        inconsistent_count=inconsistent_count,
        unclear_count=unclear_count,
        findings=findings,
    )
