# =============================================================================
# POLYMARKET BEOBACHTER - PATTERN DETECTOR
# =============================================================================
#
# GOVERNANCE INTENT:
# Identifies systematic patterns in historical trades. Detects over/under-
# performance by city, weather type, season, and combinations.
#
# Patterns generate proposals for human review - not auto-applied.
#
# =============================================================================

import logging
import math
from datetime import datetime, timezone
from dataclasses import dataclass
from typing import Dict, Optional, List, Any, Tuple

from .learning_database import LearningDatabase, PatternStats
from .outcome_tracker import TradeContext

logger = logging.getLogger(__name__)


@dataclass
class PatternAdjustment:
    """Adjustment based on detected patterns."""
    pattern_matches: List[PatternStats]
    total_adjustment: float
    confidence: float
    reason: str


@dataclass
class PatternProposal:
    """Proposal based on pattern detection."""
    proposal_id: str
    pattern_type: str
    pattern_value: str
    win_rate: float
    sample_size: int
    confidence_interval: Tuple[float, float]
    suggested_edge_adjustment: float
    reason: str
    supporting_data: Dict[str, Any]


class PatternDetector:
    """
    Identifies and exploits patterns in historical trade data.

    Dimensions analyzed:
    - City (e.g., "Miami predictions are underpriced")
    - Weather type (e.g., "Precipitation markets are overpriced")
    - Season (e.g., "Winter forecasts are more accurate")
    - Forecast horizon (e.g., "24-hour forecasts are reliable")

    Statistical methodology:
    - Uses Wilson score confidence intervals
    - Requires minimum sample size for significance
    - Caps adjustments to prevent overfitting
    """

    DIMENSIONS = ["city", "weather_type", "season"]
    MIN_SAMPLES_DEFAULT = 20
    SIGNIFICANCE_THRESHOLD = 0.55  # Win rate must be above this to suggest positive adjustment
    MAX_EDGE_ADJUSTMENT = 0.05  # Cap pattern-based adjustment at 5%

    def __init__(
        self,
        db: LearningDatabase,
        min_samples: int = MIN_SAMPLES_DEFAULT,
        max_edge_adjustment: float = MAX_EDGE_ADJUSTMENT
    ):
        """
        Initialize pattern detector.

        Args:
            db: Learning database
            min_samples: Minimum trades to include pattern
            max_edge_adjustment: Maximum edge adjustment from patterns
        """
        self.db = db
        self.min_samples = min_samples
        self.max_edge_adjustment = max_edge_adjustment

        logger.info("PatternDetector initialized (min_samples=%d)", min_samples)

    def detect_patterns(self) -> List[PatternStats]:
        """
        Scan all dimensions for statistically significant patterns.

        Returns:
            List of detected patterns
        """
        all_patterns = []

        for dimension in self.DIMENSIONS:
            try:
                patterns = self.db.get_pattern_stats(dimension, self.min_samples)
                all_patterns.extend(patterns)

                # Save patterns to database
                for pattern in patterns:
                    self.db.save_pattern(pattern)

                logger.info("Detected %d patterns in dimension '%s'",
                           len(patterns), dimension)
            except Exception as e:
                logger.error("Error detecting patterns for %s: %s", dimension, e)

        return all_patterns

    def get_pattern_adjustment(self, context: TradeContext) -> PatternAdjustment:
        """
        Calculate edge adjustment based on matching patterns.

        Args:
            context: Trade context with city, weather_type, season

        Returns:
            PatternAdjustment with combined adjustment
        """
        active_patterns = self.db.get_active_patterns()
        matching_patterns = []
        adjustments = []

        for pattern in active_patterns:
            # Check if pattern matches context
            matches = False
            if pattern.pattern_type == "city" and context.city == pattern.pattern_value:
                matches = True
            elif pattern.pattern_type == "weather_type" and context.weather_type == pattern.pattern_value:
                matches = True
            elif pattern.pattern_type == "season" and context.season == pattern.pattern_value:
                matches = True

            if matches:
                matching_patterns.append(pattern)

                # Calculate adjustment based on win rate deviation from 50%
                # Positive adjustment if we win more than expected
                expected_win_rate = 0.5  # Random baseline
                deviation = pattern.win_rate - expected_win_rate

                # Weight by confidence (sample size)
                weight = min(1.0, pattern.total_trades / 100)
                adjustment = deviation * weight * 0.5  # Dampen effect

                adjustments.append(adjustment)

        if not matching_patterns:
            return PatternAdjustment(
                pattern_matches=[],
                total_adjustment=0.0,
                confidence=0.0,
                reason="No matching patterns"
            )

        # Combine adjustments with cap
        total_adjustment = sum(adjustments)
        total_adjustment = max(-self.max_edge_adjustment, min(self.max_edge_adjustment, total_adjustment))

        # Confidence based on number and quality of matches
        confidence = min(1.0, len(matching_patterns) / 3)

        reason_parts = []
        for pattern in matching_patterns:
            reason_parts.append(f"{pattern.pattern_type}={pattern.pattern_value} (WR:{pattern.win_rate:.0%})")

        return PatternAdjustment(
            pattern_matches=matching_patterns,
            total_adjustment=total_adjustment,
            confidence=confidence,
            reason="; ".join(reason_parts)
        )

    def generate_proposals(self) -> List[PatternProposal]:
        """
        Generate proposals for significant patterns.

        Returns:
            List of proposals for human review
        """
        proposals = []
        patterns = self.detect_patterns()

        for pattern in patterns:
            # Check if pattern is statistically significant
            # Using Wilson score lower bound
            ci_low = pattern.confidence_interval_low

            # Significant if lower bound of CI > 0.55 (better than random)
            # or < 0.45 (worse than random, indicates market inefficiency)
            is_positive_signal = ci_low > self.SIGNIFICANCE_THRESHOLD
            is_negative_signal = pattern.confidence_interval_high < (1 - self.SIGNIFICANCE_THRESHOLD)

            if is_positive_signal or is_negative_signal:
                proposal_id = f"PAT-{pattern.pattern_type[:3].upper()}-{pattern.pattern_value[:10]}-{datetime.now().strftime('%Y%m%d')}"

                if is_positive_signal:
                    suggested_adjustment = min(
                        self.max_edge_adjustment,
                        (pattern.win_rate - 0.5) * 0.5
                    )
                    reason = f"Positive edge in {pattern.pattern_type}={pattern.pattern_value}: " \
                             f"{pattern.win_rate:.0%} win rate ({pattern.total_trades} trades)"
                else:
                    suggested_adjustment = max(
                        -self.max_edge_adjustment,
                        (pattern.win_rate - 0.5) * 0.5
                    )
                    reason = f"Negative edge in {pattern.pattern_type}={pattern.pattern_value}: " \
                             f"{pattern.win_rate:.0%} win rate ({pattern.total_trades} trades)"

                proposals.append(PatternProposal(
                    proposal_id=proposal_id,
                    pattern_type=pattern.pattern_type,
                    pattern_value=pattern.pattern_value,
                    win_rate=pattern.win_rate,
                    sample_size=pattern.total_trades,
                    confidence_interval=(pattern.confidence_interval_low, pattern.confidence_interval_high),
                    suggested_edge_adjustment=suggested_adjustment,
                    reason=reason,
                    supporting_data={
                        "wins": pattern.wins,
                        "losses": pattern.losses,
                        "avg_edge": pattern.avg_edge,
                        "total_pnl": pattern.total_pnl
                    }
                ))

        if proposals:
            logger.info("Generated %d pattern proposals", len(proposals))

        return proposals

    def get_pattern_summary(self) -> Dict[str, Any]:
        """Get summary of all detected patterns."""
        active_patterns = self.db.get_active_patterns()

        by_type = {}
        for pattern in active_patterns:
            if pattern.pattern_type not in by_type:
                by_type[pattern.pattern_type] = []
            by_type[pattern.pattern_type].append({
                "value": pattern.pattern_value,
                "win_rate": f"{pattern.win_rate:.0%}",
                "trades": pattern.total_trades,
                "pnl": f"{pattern.total_pnl:.2f}",
                "ci": f"[{pattern.confidence_interval_low:.0%}-{pattern.confidence_interval_high:.0%}]"
            })

        return {
            "total_patterns": len(active_patterns),
            "by_type": by_type
        }

    def get_top_patterns(self, n: int = 5) -> List[Dict[str, Any]]:
        """Get top N patterns by absolute performance."""
        active_patterns = self.db.get_active_patterns()

        # Sort by distance from 50% win rate
        sorted_patterns = sorted(
            active_patterns,
            key=lambda p: abs(p.win_rate - 0.5),
            reverse=True
        )[:n]

        return [{
            "type": p.pattern_type,
            "value": p.pattern_value,
            "win_rate": f"{p.win_rate:.0%}",
            "deviation": f"{(p.win_rate - 0.5):+.0%}",
            "trades": p.total_trades,
            "significant": p.confidence_interval_low > 0.55 or p.confidence_interval_high < 0.45
        } for p in sorted_patterns]


def calculate_wilson_score_interval(
    successes: int,
    total: int,
    confidence: float = 0.95
) -> Tuple[float, float]:
    """
    Calculate Wilson score confidence interval for a proportion.

    Args:
        successes: Number of successes
        total: Total trials
        confidence: Confidence level (default 95%)

    Returns:
        Tuple of (lower_bound, upper_bound)
    """
    if total == 0:
        return 0.0, 0.0

    # Z-score for confidence level
    z = 1.96 if confidence == 0.95 else 2.576  # 95% or 99%

    n = total
    p = successes / total

    denominator = 1 + z**2 / n
    centre = (p + z**2 / (2 * n)) / denominator
    margin = z * math.sqrt((p * (1 - p) + z**2 / (4 * n)) / n) / denominator

    lower = max(0, centre - margin)
    upper = min(1, centre + margin)

    return lower, upper
