# =============================================================================
# MICROSTRUCTURE RESEARCH - SPREAD ANALYSIS
# =============================================================================
#
# ╔═══════════════════════════════════════════════════════════════════════════╗
# ║                    RESEARCH ONLY - NO DECISION AUTHORITY                  ║
# ╚═══════════════════════════════════════════════════════════════════════════╝
#
# PURPOSE:
# Analyze bid-ask spread patterns in Polymarket markets.
# Output is purely statistical - NO trade recommendations.
#
# =============================================================================

import logging
from dataclasses import dataclass
from typing import List, Dict, Any, Optional
from statistics import mean, median, stdev

logger = logging.getLogger(__name__)


@dataclass
class SpreadStatistics:
    """
    Statistical summary of spread analysis.

    RESEARCH OUTPUT ONLY - NOT A TRADE SIGNAL.
    """
    sample_size: int
    mean_spread: float
    median_spread: float
    std_dev_spread: float
    min_spread: float
    max_spread: float
    percentile_25: float
    percentile_75: float


class SpreadAnalyzer:
    """
    Analyzes bid-ask spread patterns in market data.

    ┌─────────────────────────────────────────────────────────────────┐
    │ THIS CLASS PRODUCES RESEARCH OUTPUT ONLY.                       │
    │ IT DOES NOT GENERATE TRADE RECOMMENDATIONS.                     │
    │ IT HAS NO DECISION AUTHORITY.                                   │
    └─────────────────────────────────────────────────────────────────┘

    This analyzer studies:
    - Spread distributions across markets
    - Spread patterns by market category
    - Spread evolution over time

    Output is purely statistical for research purposes.
    """

    def __init__(self):
        """Initialize the spread analyzer."""
        self._analysis_count = 0

    def analyze_spreads(
        self,
        market_data: List[Dict[str, Any]],
    ) -> Optional[SpreadStatistics]:
        """
        Analyze spread statistics from market data.

        RESEARCH OUTPUT ONLY - NO TRADE RECOMMENDATIONS.

        Args:
            market_data: List of market records with bid/ask data

        Returns:
            SpreadStatistics if sufficient data, None otherwise
        """
        logger.info("Starting spread analysis (RESEARCH ONLY)")
        self._analysis_count += 1

        # Extract spreads from market data
        spreads = []
        for market in market_data:
            bid = market.get("best_bid")
            ask = market.get("best_ask")
            if bid is not None and ask is not None and bid > 0 and ask > 0:
                spread = (ask - bid) / ((ask + bid) / 2) * 100  # Percentage spread
                spreads.append(spread)

        if len(spreads) < 10:
            logger.warning("Insufficient data for spread analysis")
            return None

        # Sort for percentile calculation
        sorted_spreads = sorted(spreads)
        n = len(sorted_spreads)

        stats = SpreadStatistics(
            sample_size=n,
            mean_spread=mean(spreads),
            median_spread=median(spreads),
            std_dev_spread=stdev(spreads) if n > 1 else 0.0,
            min_spread=min(spreads),
            max_spread=max(spreads),
            percentile_25=sorted_spreads[n // 4],
            percentile_75=sorted_spreads[3 * n // 4],
        )

        logger.info(f"Spread analysis complete: {n} samples")
        return stats

    def generate_report(self, stats: SpreadStatistics) -> str:
        """
        Generate a markdown report of spread analysis.

        RESEARCH REPORT - NO TRADE RECOMMENDATIONS.

        Args:
            stats: Spread statistics to report

        Returns:
            Markdown formatted report string
        """
        lines = [
            "# Spread Analysis Report",
            "",
            "**RESEARCH OUTPUT ONLY - NO TRADE RECOMMENDATIONS**",
            "",
            "## Summary Statistics",
            "",
            f"- Sample Size: {stats.sample_size}",
            f"- Mean Spread: {stats.mean_spread:.4f}%",
            f"- Median Spread: {stats.median_spread:.4f}%",
            f"- Std Dev: {stats.std_dev_spread:.4f}%",
            f"- Min Spread: {stats.min_spread:.4f}%",
            f"- Max Spread: {stats.max_spread:.4f}%",
            f"- 25th Percentile: {stats.percentile_25:.4f}%",
            f"- 75th Percentile: {stats.percentile_75:.4f}%",
            "",
            "---",
            "",
            "*This report is for research purposes only.*",
            "*It does not constitute a trade recommendation.*",
        ]
        return "\n".join(lines)
