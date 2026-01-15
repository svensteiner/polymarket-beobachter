# =============================================================================
# MICROSTRUCTURE RESEARCH - LIQUIDITY STUDY
# =============================================================================
#
# ╔═══════════════════════════════════════════════════════════════════════════╗
# ║                    RESEARCH ONLY - NO DECISION AUTHORITY                  ║
# ╚═══════════════════════════════════════════════════════════════════════════╝
#
# PURPOSE:
# Study liquidity patterns in Polymarket markets.
# Output is purely observational - NO trade recommendations.
#
# =============================================================================

import logging
from dataclasses import dataclass
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)


@dataclass
class LiquidityObservation:
    """
    Single liquidity observation.

    RESEARCH DATA - NOT A TRADE SIGNAL.
    """
    market_id: str
    depth_bid: float
    depth_ask: float
    total_depth: float
    imbalance: float  # (ask - bid) / total


@dataclass
class LiquiditySummary:
    """
    Summary of liquidity observations.

    RESEARCH OUTPUT - NO DECISION AUTHORITY.
    """
    observation_count: int
    avg_total_depth: float
    avg_imbalance: float
    depth_distribution: Dict[str, int]  # Bucketed counts


class LiquidityAnalyzer:
    """
    Studies liquidity patterns across markets.

    ┌─────────────────────────────────────────────────────────────────┐
    │ THIS CLASS PRODUCES RESEARCH OUTPUT ONLY.                       │
    │ IT DOES NOT GENERATE TRADE RECOMMENDATIONS.                     │
    │ IT HAS NO DECISION AUTHORITY.                                   │
    └─────────────────────────────────────────────────────────────────┘

    This analyzer studies:
    - Orderbook depth distributions
    - Liquidity imbalances
    - Depth patterns by market type
    """

    def __init__(self):
        """Initialize the liquidity analyzer."""
        pass

    def analyze_liquidity(
        self,
        orderbook_data: List[Dict[str, Any]],
    ) -> Optional[LiquiditySummary]:
        """
        Analyze liquidity patterns from orderbook data.

        RESEARCH OUTPUT ONLY - NO TRADE RECOMMENDATIONS.

        Args:
            orderbook_data: List of orderbook snapshots

        Returns:
            LiquiditySummary if sufficient data, None otherwise
        """
        logger.info("Starting liquidity analysis (RESEARCH ONLY)")

        observations = []
        for ob in orderbook_data:
            depth_bid = sum(level.get("size", 0) for level in ob.get("bids", []))
            depth_ask = sum(level.get("size", 0) for level in ob.get("asks", []))
            total = depth_bid + depth_ask

            if total > 0:
                observations.append(LiquidityObservation(
                    market_id=ob.get("market_id", "unknown"),
                    depth_bid=depth_bid,
                    depth_ask=depth_ask,
                    total_depth=total,
                    imbalance=(depth_ask - depth_bid) / total,
                ))

        if len(observations) < 5:
            logger.warning("Insufficient data for liquidity analysis")
            return None

        # Calculate summary statistics
        avg_depth = sum(o.total_depth for o in observations) / len(observations)
        avg_imbalance = sum(o.imbalance for o in observations) / len(observations)

        # Bucket depth distribution
        buckets = {"low": 0, "medium": 0, "high": 0}
        for o in observations:
            if o.total_depth < avg_depth * 0.5:
                buckets["low"] += 1
            elif o.total_depth < avg_depth * 1.5:
                buckets["medium"] += 1
            else:
                buckets["high"] += 1

        return LiquiditySummary(
            observation_count=len(observations),
            avg_total_depth=avg_depth,
            avg_imbalance=avg_imbalance,
            depth_distribution=buckets,
        )

    def generate_report(self, summary: LiquiditySummary) -> str:
        """
        Generate a markdown liquidity report.

        RESEARCH REPORT - NO TRADE RECOMMENDATIONS.
        """
        lines = [
            "# Liquidity Study Report",
            "",
            "**RESEARCH OUTPUT ONLY - NO TRADE RECOMMENDATIONS**",
            "",
            "## Summary",
            "",
            f"- Observations: {summary.observation_count}",
            f"- Average Total Depth: {summary.avg_total_depth:.2f}",
            f"- Average Imbalance: {summary.avg_imbalance:.4f}",
            "",
            "## Depth Distribution",
            "",
            "| Category | Count |",
            "|----------|-------|",
        ]
        for category, count in summary.depth_distribution.items():
            lines.append(f"| {category} | {count} |")

        lines.extend([
            "",
            "---",
            "",
            "*This report is for research purposes only.*",
        ])
        return "\n".join(lines)
