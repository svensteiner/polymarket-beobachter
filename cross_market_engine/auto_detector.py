# =============================================================================
# CROSS-MARKET CONSISTENCY ENGINE - AUTO RELATION DETECTOR
# =============================================================================
#
# Automatically detects IMPLIES relations between markets.
#
# ISOLATION: This module has NO imports from trading code.
# It only reads market data passed as input and returns detected relations.
#
# Detection Strategy:
# 1. Group markets by topic similarity (keywords, entities)
# 2. Within groups, find temporal orderings (2025 < 2026 < 2027)
# 3. Create IMPLIES relations for earlier -> later deadlines
#
# =============================================================================

import re
from typing import List, Dict, Any, Tuple, Optional
from collections import defaultdict
from datetime import datetime

from .market_graph import MarketGraph, create_market_snapshot
from .relations import create_implies_relation, Relation


# =============================================================================
# TOPIC EXTRACTION
# =============================================================================

def extract_topic_key(title: str, description: str = "") -> Optional[str]:
    """
    Extract a normalized topic key from market title/description.

    Returns None if no clear topic can be extracted.
    """
    text = f"{title} {description}".lower()

    # Remove common words and noise
    noise_words = {
        "will", "the", "be", "by", "in", "on", "at", "to", "a", "an",
        "before", "after", "end", "of", "this", "year", "month", "week",
        "january", "february", "march", "april", "may", "june",
        "july", "august", "september", "october", "november", "december",
        "2024", "2025", "2026", "2027", "2028", "2029", "2030",
        "q1", "q2", "q3", "q4"
    }

    # Extract meaningful words
    words = re.findall(r'[a-z]+', text)
    meaningful = [w for w in words if w not in noise_words and len(w) > 2]

    if len(meaningful) < 2:
        return None

    # Take first 5 meaningful words as topic key
    return " ".join(sorted(meaningful[:5]))


def extract_deadline_year(title: str, end_date: str) -> Optional[int]:
    """
    Extract the target year from market title or end date.

    Looks for patterns like:
    - "by 2025"
    - "before December 2026"
    - "by end of 2025"
    - Falls back to end_date year
    """
    text = title.lower()

    # Look for explicit year mentions
    year_patterns = [
        r'by\s+(?:end\s+of\s+)?(\d{4})',
        r'before\s+(?:\w+\s+)?(\d{4})',
        r'in\s+(\d{4})',
        r'(\d{4})',
    ]

    for pattern in year_patterns:
        match = re.search(pattern, text)
        if match:
            year = int(match.group(1))
            if 2020 <= year <= 2035:
                return year

    # Fall back to end_date
    if end_date:
        try:
            year = int(end_date[:4])
            if 2020 <= year <= 2035:
                return year
        except (ValueError, IndexError):
            pass

    return None


# =============================================================================
# RELATION DETECTION
# =============================================================================

def detect_implies_relations(
    markets: List[Dict[str, Any]],
    min_group_size: int = 2,
    tolerance: float = 0.05,
) -> Tuple[MarketGraph, List[Relation]]:
    """
    Automatically detect IMPLIES relations between markets.

    Strategy:
    1. Group markets by topic similarity
    2. Within each group, order by deadline year
    3. Create IMPLIES relations: earlier deadline -> later deadline

    Args:
        markets: List of market dicts with keys: market_id, title, end_date, probability
        min_group_size: Minimum markets in a group to consider
        tolerance: Tolerance for consistency check (default 5%)

    Returns:
        Tuple of (MarketGraph with markets and relations, list of Relations)

    ISOLATION: This function is PURE. No side effects, no I/O.
    """
    graph = MarketGraph()
    relations = []

    # Group markets by topic
    topic_groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)

    for market in markets:
        title = market.get("title", "")
        description = market.get("description", market.get("resolution_text", ""))

        topic_key = extract_topic_key(title, description)
        if topic_key:
            topic_groups[topic_key].append(market)

    # Process each topic group
    for topic_key, group_markets in topic_groups.items():
        if len(group_markets) < min_group_size:
            continue

        # Extract deadline years
        markets_with_years = []
        for m in group_markets:
            year = extract_deadline_year(m.get("title", ""), m.get("end_date", ""))
            if year:
                markets_with_years.append((m, year))

        if len(markets_with_years) < min_group_size:
            continue

        # Sort by year (earliest first)
        markets_with_years.sort(key=lambda x: x[1])

        # Add markets to graph
        for m, year in markets_with_years:
            market_id = m.get("market_id", m.get("condition_id", ""))
            if not market_id:
                continue

            # Get probability (default to 0.5 if not available)
            prob = m.get("probability", m.get("best_bid", 0.5))
            if prob is None:
                prob = 0.5

            graph.add_market(create_market_snapshot(
                market_id=market_id,
                question=m.get("title", "Unknown"),
                probability=float(prob),
                metadata={
                    "end_date": m.get("end_date", ""),
                    "deadline_year": year,
                    "topic_key": topic_key,
                }
            ))

        # Create IMPLIES relations (earlier -> later)
        for i in range(len(markets_with_years) - 1):
            earlier_market, earlier_year = markets_with_years[i]
            later_market, later_year = markets_with_years[i + 1]

            earlier_id = earlier_market.get("market_id", earlier_market.get("condition_id", ""))
            later_id = later_market.get("market_id", later_market.get("condition_id", ""))

            if not earlier_id or not later_id:
                continue

            if earlier_year < later_year:
                relation = create_implies_relation(
                    antecedent_id=earlier_id,
                    consequent_id=later_id,
                    description=f"Event by {earlier_year} implies event by {later_year} (topic: {topic_key[:30]})",
                    tolerance=tolerance,
                )
                graph.add_relation(relation)
                relations.append(relation)

    return graph, relations


def detect_from_collector_output(
    candidates: List[Dict[str, Any]],
    tolerance: float = 0.05,
) -> Tuple[MarketGraph, List[Relation]]:
    """
    Convenience function to detect relations from collector output format.

    Args:
        candidates: List of candidate dicts from collector
        tolerance: Tolerance for consistency check

    Returns:
        Tuple of (MarketGraph, Relations list)
    """
    # Normalize to standard format
    normalized = []
    for c in candidates:
        normalized.append({
            "market_id": c.get("market_id") or c.get("condition_id", ""),
            "title": c.get("title", "Unknown"),
            "description": c.get("resolution_text") or c.get("description", ""),
            "end_date": c.get("end_date", ""),
            "probability": c.get("probability", 0.5),
        })

    return detect_implies_relations(normalized, tolerance=tolerance)


# =============================================================================
# SUMMARY HELPERS
# =============================================================================

def get_detection_summary(graph: MarketGraph, relations: List[Relation]) -> Dict[str, Any]:
    """
    Get a summary of detected relations.

    Returns:
        Summary dict with counts and details
    """
    # Group relations by topic
    topics: Dict[str, int] = defaultdict(int)
    for rel in relations:
        market = graph.get_market(rel.market_a_id)
        if market and market.metadata:
            topic = market.metadata.get("topic_key", "unknown")[:30]
            topics[topic] += 1

    return {
        "markets_analyzed": graph.market_count(),
        "relations_detected": len(relations),
        "topic_groups": len(topics),
        "topics": dict(topics),
    }
