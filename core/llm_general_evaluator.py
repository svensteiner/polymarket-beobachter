# =============================================================================
# LLM GENERAL MARKET EVALUATOR
# =============================================================================
#
# Evaluates non-weather Polymarket markets using LLM probability estimation.
# Computes edge = |llm_probability - market_yes_price|.
#
# OBSERVE-ONLY by default — no paper trades until edge is proven reliable.
#
# Usage:
#   from core.llm_general_evaluator import evaluate_market
#   result = evaluate_market(market_dict)
# =============================================================================

import logging
from dataclasses import dataclass
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

# Edge threshold to flag as interesting
MIN_EDGE_TO_LOG = 0.10
# Minimum liquidity (USD) to consider a market
MIN_LIQUIDITY_USD = 5000.0
# Markets to skip by category
SKIP_CATEGORIES = {"WEATHER"}
# High-confidence market types worth focusing on
HIGH_VALUE_KEYWORDS = [
    "fed", "rate", "interest", "inflation", "cpi", "gdp", "unemployment",
    "election", "president", "senate", "congress", "vote", "referendum",
    "bitcoin", "btc", "ethereum", "eth", "crypto",
    "earnings", "revenue", "ipo",
    "war", "ceasefire", "treaty",
    "will", "by end of", "before", "by "
]

SYSTEM_PROMPT = """You are a prediction market analyst. Given a Polymarket market question and context,
estimate the probability that the YES outcome resolves true.

Be calibrated: use base rates, current data, and common sense.
If you're very uncertain, estimate close to 0.5.
For questions about known facts, use your knowledge.

Reply ONLY with JSON:
{
  "yes_probability": <float 0.0 to 1.0>,
  "confidence": "high" | "medium" | "low",
  "reasoning": "<one sentence>",
  "category": "economic" | "political" | "crypto" | "sports" | "science" | "other"
}"""


@dataclass
class GeneralEvalResult:
    market_id: str
    question: str
    market_yes_price: float
    llm_yes_probability: float
    edge: float                  # llm_prob - market_price (positive = buy YES, negative = buy NO)
    abs_edge: float
    confidence: str              # "high" | "medium" | "low"
    reasoning: str
    category: str
    should_observe: bool         # True if abs_edge >= MIN_EDGE_TO_LOG
    side: str                    # "YES" or "NO"


def _is_worth_evaluating(market: Dict[str, Any]) -> bool:
    """Quick pre-filter before spending LLM tokens."""
    # Binary markets only
    if not market.get("active", True):
        return False

    # Skip weather
    category = (market.get("category") or "").upper()
    if category in SKIP_CATEGORIES:
        return False

    # Skip markets with no question
    question = market.get("question", "").strip()
    if len(question) < 10:
        return False

    # Minimum liquidity
    liquidity = float(market.get("liquidity", market.get("liquidity_usd", 0)) or 0)
    if liquidity < MIN_LIQUIDITY_USD:
        return False

    # Need a valid price
    yes_price = market.get("yes_price", market.get("best_yes_price", market.get("price")))
    if yes_price is None:
        return False
    yes_price = float(yes_price)
    if not (0.02 <= yes_price <= 0.98):  # Skip near-resolved markets
        return False

    return True


def evaluate_market(market: Dict[str, Any]) -> Optional[GeneralEvalResult]:
    """
    Evaluate a single market with LLM.
    Returns None if the market should be skipped or LLM fails.
    """
    if not _is_worth_evaluating(market):
        return None

    question = market.get("question", "").strip()
    description = (market.get("description") or market.get("resolution_text") or "")[:300]
    yes_price = float(market.get("yes_price", market.get("best_yes_price", market.get("price", 0.5))))
    market_id = str(market.get("id", market.get("market_id", "?")))

    try:
        from .llm_client import llm_json_call
    except ImportError:
        logger.debug("llm_client not available")
        return None

    prompt = f"Question: {question}"
    if description:
        prompt += f"\nContext: {description}"
    prompt += f"\nCurrent YES market price: {yes_price:.3f}"

    try:
        data = llm_json_call(prompt, system=SYSTEM_PROMPT)
    except Exception as e:
        logger.debug("LLM call failed for market %s: %s", market_id, e)
        return None

    if not data or "yes_probability" not in data:
        return None

    try:
        llm_prob = float(data["yes_probability"])
        llm_prob = max(0.01, min(0.99, llm_prob))
    except (TypeError, ValueError):
        return None

    edge = llm_prob - yes_price
    abs_edge = abs(edge)
    side = "YES" if edge > 0 else "NO"
    confidence = data.get("confidence", "low")
    reasoning = str(data.get("reasoning", ""))[:200]
    category = str(data.get("category", "other"))

    return GeneralEvalResult(
        market_id=market_id,
        question=question,
        market_yes_price=yes_price,
        llm_yes_probability=llm_prob,
        edge=round(edge, 4),
        abs_edge=round(abs_edge, 4),
        confidence=confidence,
        reasoning=reasoning,
        category=category,
        should_observe=abs_edge >= MIN_EDGE_TO_LOG,
        side=side,
    )


def evaluate_market_batch(
    markets: list[Dict[str, Any]],
    max_markets: int = 20,
) -> list[GeneralEvalResult]:
    """
    Evaluate a batch of markets. Stops at max_markets to limit LLM cost.
    Returns only markets where should_observe is True, sorted by abs_edge desc.
    """
    results = []
    evaluated = 0

    for market in markets:
        if evaluated >= max_markets:
            break
        if not _is_worth_evaluating(market):
            continue

        result = evaluate_market(market)
        evaluated += 1

        if result and result.should_observe:
            results.append(result)

    results.sort(key=lambda r: r.abs_edge, reverse=True)
    return results
