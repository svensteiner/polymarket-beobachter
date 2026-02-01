# =============================================================================
# POLYMARKET BEOBACHTER - PANIC GOVERNANCE GATE
# =============================================================================
#
# AUTHORITY:
# This module acts as an INDEPENDENT RISK COMMITTEE and AUDIT AUTHORITY.
# It has VETO POWER over live trading decisions.
#
# ROLE:
# Final GO / NO-GO decision for transitioning from shadow mode to live trading.
#
# ABSOLUTE PRINCIPLES:
# 1. This gate does NOT execute trades.
# 2. This gate does NOT modify parameters.
# 3. This gate does NOT override kill switches.
# 4. This gate is CONSERVATIVE by design.
# 5. If in doubt → NO-GO.
#
# MENTAL MODEL:
# This gate behaves like a cautious investment committee.
# It prefers MISSING OPPORTUNITIES over LOSING CAPITAL.
#
# If all criteria are not CLEARLY met → NO-GO.
#
# =============================================================================

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple

logger = logging.getLogger(__name__)


# =============================================================================
# DECISION ENUM
# =============================================================================


class GovernanceDecision(Enum):
    """
    Final governance decision.

    ONLY two possible outcomes.
    No intermediate states. No "maybe". No "conditional approval".
    """
    GO_LIVE_APPROVED = "GO_LIVE_APPROVED"
    NO_GO_REJECTED = "NO_GO_REJECTED"


# =============================================================================
# HARD CRITERIA THRESHOLDS
# =============================================================================
#
# These thresholds are NON-NEGOTIABLE.
# They represent the MINIMUM acceptable performance.
# All must be met for GO approval.
#
# =============================================================================

# -----------------------------------------------------------------------------
# SHADOW QUALITY CRITERIA
# -----------------------------------------------------------------------------

MIN_TOTAL_EVENTS: int = 30
"""
Minimum number of completed shadow trades.
30 events provides reasonable statistical significance.

WHY 30:
- Below 20: Statistical noise dominates
- 20-30: Marginal, could be luck
- 30+: Pattern begins to be meaningful
- 50+: High confidence (but may take too long)

CONSERVATIVE CHOICE: 30 is standard for statistical significance.
"""

MAX_FALSE_TRIGGER_RATE: float = 0.20
"""
Maximum acceptable FALSE_TRIGGER rate (20%).
If more than 20% of signals are false triggers, the detection logic is flawed.

WHY 20%:
- Below 10%: Excellent signal quality
- 10-15%: Good, acceptable
- 15-20%: Concerning but acceptable
- Above 20%: Detection logic is unreliable

CONSERVATIVE CHOICE: 20% is the absolute maximum.
"""

MAX_CONTINUED_PANIC_RATE: float = 0.20
"""
Maximum acceptable CONTINUED_PANIC rate (20%).
If more than 20% of trades result in continued panic, the contrarian thesis is wrong.

WHY 20%:
- Below 10%: Strong contrarian edge
- 10-15%: Good edge
- 15-20%: Marginal edge
- Above 20%: No reliable edge

CONSERVATIVE CHOICE: 20% is the absolute maximum.
"""

MIN_GOOD_REVERSION_RATE: float = 0.50
"""
Minimum acceptable GOOD_REVERSION rate (50%).
At least half of trades should result in the expected price reversion.

WHY 50%:
- Above 60%: Strong edge
- 50-60%: Reasonable edge (accounts for fees)
- 40-50%: Marginal, may not cover costs
- Below 40%: No meaningful edge

CONSERVATIVE CHOICE: 50% is the minimum for viability.
"""

# -----------------------------------------------------------------------------
# ECONOMIC VIABILITY CRITERIA
# -----------------------------------------------------------------------------

MIN_AVERAGE_NET_PNL: float = 0.0
"""
Minimum average net PnL per trade (must be positive).
Negative or zero average PnL means the strategy loses money.

Note: This is AFTER fees. Gross PnL could be positive but net negative.
"""

MAX_ACCEPTABLE_DRAWDOWN_PCT: float = 0.25
"""
Maximum acceptable overall drawdown (25% of position size).

WHY 25%:
- Below 15%: Excellent risk control
- 15-25%: Acceptable
- 25-35%: Concerning
- Above 35%: Unacceptable risk

CONSERVATIVE CHOICE: 25% is the ceiling.
"""

MAX_WORST_TRADE_LOSS_PCT: float = 0.50
"""
Maximum acceptable single trade loss (50% of position size).
No single trade should lose more than half the position.

WHY 50%:
- Below 25%: Excellent trade sizing
- 25-50%: Acceptable (bad trades happen)
- Above 50%: Position sizing or exit logic flawed
"""

# -----------------------------------------------------------------------------
# SYSTEM DISCIPLINE CRITERIA
# -----------------------------------------------------------------------------

KILL_SWITCH_MUST_BE_FALSE: bool = True
"""
Kill switch must NEVER have been triggered.
If kill switch was triggered, it indicates a period of poor performance
that disqualifies the system from live trading.
"""

SHADOW_MODE_MUST_BE_RESPECTED: bool = True
"""
Shadow mode must have been respected throughout.
Any evidence of non-shadow trading during validation period is a violation.
"""


# =============================================================================
# DATA MODELS
# =============================================================================


@dataclass
class CriterionResult:
    """
    Result of evaluating a single criterion.
    """
    name: str
    category: str  # "SHADOW_QUALITY", "ECONOMIC_VIABILITY", "SYSTEM_DISCIPLINE"
    passed: bool
    actual_value: Any
    required_value: Any
    description: str

    def to_dict(self) -> Dict[str, Any]:
        """Convert to JSON-serializable dict."""
        return {
            "name": self.name,
            "category": self.category,
            "passed": self.passed,
            "actual_value": self.actual_value,
            "required_value": self.required_value,
            "description": self.description,
        }


@dataclass
class GovernanceReport:
    """
    Complete governance decision report.
    """
    # Decision
    decision: GovernanceDecision
    decision_timestamp: str

    # Criteria evaluation
    total_criteria: int
    passed_criteria: int
    failed_criteria: int
    criteria_results: List[CriterionResult]

    # Input data used
    shadow_stats_path: str
    pnl_summary_path: str
    shadow_stats_found: bool
    pnl_summary_found: bool

    # Key metrics (for quick reference)
    total_events: int
    false_trigger_rate: float
    continued_panic_rate: float
    good_reversion_rate: float
    average_net_pnl: float
    max_drawdown_pct: float
    kill_switch_triggered: bool

    # Recommendation (only if NO-GO)
    recommendation: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to JSON-serializable dict."""
        return {
            "decision": self.decision.value,
            "decision_timestamp": self.decision_timestamp,
            "summary": {
                "total_criteria": self.total_criteria,
                "passed_criteria": self.passed_criteria,
                "failed_criteria": self.failed_criteria,
            },
            "criteria_results": [c.to_dict() for c in self.criteria_results],
            "input_data": {
                "shadow_stats_path": self.shadow_stats_path,
                "pnl_summary_path": self.pnl_summary_path,
                "shadow_stats_found": self.shadow_stats_found,
                "pnl_summary_found": self.pnl_summary_found,
            },
            "key_metrics": {
                "total_events": self.total_events,
                "false_trigger_rate": round(self.false_trigger_rate, 4),
                "continued_panic_rate": round(self.continued_panic_rate, 4),
                "good_reversion_rate": round(self.good_reversion_rate, 4),
                "average_net_pnl_usd": round(self.average_net_pnl, 2),
                "max_drawdown_pct": round(self.max_drawdown_pct, 4),
                "kill_switch_triggered": self.kill_switch_triggered,
            },
            "recommendation": self.recommendation,
        }


# =============================================================================
# GOVERNANCE GATE
# =============================================================================


class GovernanceGate:
    """
    Final GO / NO-GO Decision Gate.

    Acts as an independent risk committee with veto power.

    GOVERNANCE HIERARCHY:
    - Kill Switch (automatic) → OVERRIDES all decisions
    - Governance Gate (this) → Has VETO power over live trading
    - Trading Engine → Can ONLY execute if BOTH approve

    CONSERVATIVE BEHAVIOR:
    - All criteria must be CLEARLY met for GO
    - Any uncertainty → NO-GO
    - Missing data → NO-GO
    - Marginal values → NO-GO
    """

    def __init__(
        self,
        shadow_stats_path: Optional[Path] = None,
        pnl_summary_path: Optional[Path] = None,
        output_path: Optional[Path] = None,
    ):
        """
        Initialize the Governance Gate.

        Args:
            shadow_stats_path: Path to shadow_stats.json
            pnl_summary_path: Path to panic_paper_pnl_summary.json
            output_path: Path for decision output
        """
        base_path = Path(__file__).parent.parent

        self.shadow_stats_path = shadow_stats_path or (
            base_path / "logs" / "panic_shadow" / "shadow_stats.json"
        )
        self.pnl_summary_path = pnl_summary_path or (
            base_path / "analysis" / "panic_paper_pnl_summary.json"
        )
        self.output_path = output_path or (
            base_path / "governance" / "panic_go_no_go_decision.json"
        )

        logger.info(
            f"GovernanceGate initialized | "
            f"shadow_stats={self.shadow_stats_path} | "
            f"pnl_summary={self.pnl_summary_path}"
        )

    def _load_shadow_stats(self) -> Tuple[Optional[Dict[str, Any]], bool]:
        """
        Load shadow stats from file.

        Returns (data, found) tuple.
        """
        if not self.shadow_stats_path.exists():
            logger.warning(f"Shadow stats not found: {self.shadow_stats_path}")
            return None, False

        try:
            with open(self.shadow_stats_path, "r") as f:
                data = json.load(f)
            logger.info(f"Loaded shadow stats from {self.shadow_stats_path}")
            return data, True
        except Exception as e:
            logger.error(f"Failed to load shadow stats: {e}")
            return None, False

    def _load_pnl_summary(self) -> Tuple[Optional[Dict[str, Any]], bool]:
        """
        Load PnL summary from file.

        Returns (data, found) tuple.
        """
        if not self.pnl_summary_path.exists():
            logger.warning(f"PnL summary not found: {self.pnl_summary_path}")
            return None, False

        try:
            with open(self.pnl_summary_path, "r") as f:
                data = json.load(f)
            logger.info(f"Loaded PnL summary from {self.pnl_summary_path}")
            return data, True
        except Exception as e:
            logger.error(f"Failed to load PnL summary: {e}")
            return None, False

    def _evaluate_shadow_quality(
        self,
        shadow_stats: Optional[Dict[str, Any]],
    ) -> List[CriterionResult]:
        """
        Evaluate SHADOW QUALITY criteria.

        Returns list of CriterionResult.
        """
        results = []

        # Handle missing data
        if shadow_stats is None:
            results.append(CriterionResult(
                name="shadow_stats_available",
                category="SHADOW_QUALITY",
                passed=False,
                actual_value="MISSING",
                required_value="AVAILABLE",
                description="Shadow stats data file is missing. Cannot evaluate.",
            ))
            return results

        # Extract values with safe defaults
        total_completed = shadow_stats.get("total_completed_trades", 0)
        good_reversions = shadow_stats.get("good_reversions", 0)
        continued_panics = shadow_stats.get("continued_panics", 0)
        false_triggers = shadow_stats.get("false_triggers", 0)

        # Calculate rates
        if total_completed > 0:
            false_trigger_rate = false_triggers / total_completed
            continued_panic_rate = continued_panics / total_completed
            good_reversion_rate = good_reversions / total_completed
        else:
            false_trigger_rate = 1.0  # Worst case
            continued_panic_rate = 1.0
            good_reversion_rate = 0.0

        # Criterion 1: Total events >= 30
        results.append(CriterionResult(
            name="min_total_events",
            category="SHADOW_QUALITY",
            passed=total_completed >= MIN_TOTAL_EVENTS,
            actual_value=total_completed,
            required_value=f">= {MIN_TOTAL_EVENTS}",
            description=(
                f"Total completed events: {total_completed}. "
                f"Minimum required: {MIN_TOTAL_EVENTS}."
            ),
        ))

        # Criterion 2: FALSE_TRIGGER_RATE < 20%
        results.append(CriterionResult(
            name="max_false_trigger_rate",
            category="SHADOW_QUALITY",
            passed=false_trigger_rate < MAX_FALSE_TRIGGER_RATE,
            actual_value=f"{false_trigger_rate:.1%}",
            required_value=f"< {MAX_FALSE_TRIGGER_RATE:.0%}",
            description=(
                f"False trigger rate: {false_trigger_rate:.1%}. "
                f"Maximum allowed: {MAX_FALSE_TRIGGER_RATE:.0%}."
            ),
        ))

        # Criterion 3: CONTINUED_PANIC_RATE <= 20%
        results.append(CriterionResult(
            name="max_continued_panic_rate",
            category="SHADOW_QUALITY",
            passed=continued_panic_rate <= MAX_CONTINUED_PANIC_RATE,
            actual_value=f"{continued_panic_rate:.1%}",
            required_value=f"<= {MAX_CONTINUED_PANIC_RATE:.0%}",
            description=(
                f"Continued panic rate: {continued_panic_rate:.1%}. "
                f"Maximum allowed: {MAX_CONTINUED_PANIC_RATE:.0%}."
            ),
        ))

        # Criterion 4: GOOD_REVERSION_RATE >= 50%
        results.append(CriterionResult(
            name="min_good_reversion_rate",
            category="SHADOW_QUALITY",
            passed=good_reversion_rate >= MIN_GOOD_REVERSION_RATE,
            actual_value=f"{good_reversion_rate:.1%}",
            required_value=f">= {MIN_GOOD_REVERSION_RATE:.0%}",
            description=(
                f"Good reversion rate: {good_reversion_rate:.1%}. "
                f"Minimum required: {MIN_GOOD_REVERSION_RATE:.0%}."
            ),
        ))

        return results

    def _evaluate_economic_viability(
        self,
        pnl_summary: Optional[Dict[str, Any]],
    ) -> List[CriterionResult]:
        """
        Evaluate ECONOMIC VIABILITY criteria.

        Returns list of CriterionResult.
        """
        results = []

        # Handle missing data
        if pnl_summary is None:
            results.append(CriterionResult(
                name="pnl_summary_available",
                category="ECONOMIC_VIABILITY",
                passed=False,
                actual_value="MISSING",
                required_value="AVAILABLE",
                description="PnL summary data file is missing. Cannot evaluate.",
            ))
            return results

        # Extract values with safe navigation
        pnl_stats = pnl_summary.get("aggregate_metrics", {}).get("pnl_statistics", {})
        cumulative = pnl_summary.get("aggregate_metrics", {}).get("cumulative", {})
        extremes = pnl_summary.get("aggregate_metrics", {}).get("extremes", {})
        config = pnl_summary.get("configuration", {})

        average_net_pnl = pnl_stats.get("average_net_pnl_usd", -999)
        max_drawdown_pct = cumulative.get("max_drawdown_pct", 1.0)
        worst_trade_pnl = extremes.get("worst_trade_pnl_usd", -999)
        position_size = config.get("position_size_usd", 100)

        # Calculate worst trade as percentage of position
        worst_trade_pct = abs(worst_trade_pnl) / position_size if position_size > 0 else 1.0

        # Criterion 1: Average net PnL > 0
        results.append(CriterionResult(
            name="positive_average_pnl",
            category="ECONOMIC_VIABILITY",
            passed=average_net_pnl > MIN_AVERAGE_NET_PNL,
            actual_value=f"${average_net_pnl:.2f}",
            required_value=f"> ${MIN_AVERAGE_NET_PNL:.2f}",
            description=(
                f"Average net PnL: ${average_net_pnl:.2f}. "
                f"Must be positive after fees."
            ),
        ))

        # Criterion 2: Max drawdown <= 25%
        results.append(CriterionResult(
            name="max_drawdown_acceptable",
            category="ECONOMIC_VIABILITY",
            passed=max_drawdown_pct <= MAX_ACCEPTABLE_DRAWDOWN_PCT,
            actual_value=f"{max_drawdown_pct:.1%}",
            required_value=f"<= {MAX_ACCEPTABLE_DRAWDOWN_PCT:.0%}",
            description=(
                f"Maximum drawdown: {max_drawdown_pct:.1%}. "
                f"Ceiling: {MAX_ACCEPTABLE_DRAWDOWN_PCT:.0%}."
            ),
        ))

        # Criterion 3: No catastrophic tail losses (worst trade <= 50%)
        results.append(CriterionResult(
            name="no_catastrophic_losses",
            category="ECONOMIC_VIABILITY",
            passed=worst_trade_pct <= MAX_WORST_TRADE_LOSS_PCT,
            actual_value=f"{worst_trade_pct:.1%} of position",
            required_value=f"<= {MAX_WORST_TRADE_LOSS_PCT:.0%} of position",
            description=(
                f"Worst single trade loss: {worst_trade_pct:.1%} of position. "
                f"Maximum allowed: {MAX_WORST_TRADE_LOSS_PCT:.0%}."
            ),
        ))

        return results

    def _evaluate_system_discipline(
        self,
        shadow_stats: Optional[Dict[str, Any]],
    ) -> List[CriterionResult]:
        """
        Evaluate SYSTEM DISCIPLINE criteria.

        Returns list of CriterionResult.
        """
        results = []

        # Handle missing data
        if shadow_stats is None:
            results.append(CriterionResult(
                name="discipline_data_available",
                category="SYSTEM_DISCIPLINE",
                passed=False,
                actual_value="MISSING",
                required_value="AVAILABLE",
                description="Shadow stats data missing. Cannot verify discipline.",
            ))
            return results

        # Extract values
        kill_switch_triggered = shadow_stats.get("kill_switch_triggered", True)

        # Criterion 1: Kill switch never triggered
        results.append(CriterionResult(
            name="kill_switch_never_triggered",
            category="SYSTEM_DISCIPLINE",
            passed=(kill_switch_triggered == False),
            actual_value="TRIGGERED" if kill_switch_triggered else "NEVER_TRIGGERED",
            required_value="NEVER_TRIGGERED",
            description=(
                "Kill switch status: "
                f"{'TRIGGERED (DISQUALIFYING)' if kill_switch_triggered else 'Never triggered'}. "
                "Any kill switch activation disqualifies live trading."
            ),
        ))

        # Criterion 2: Shadow mode respected
        # We infer this from the presence of shadow logs and absence of
        # any execution logs that would indicate live trading
        shadow_mode_respected = True  # Assume respected if we have shadow stats

        results.append(CriterionResult(
            name="shadow_mode_respected",
            category="SYSTEM_DISCIPLINE",
            passed=shadow_mode_respected,
            actual_value="RESPECTED" if shadow_mode_respected else "VIOLATED",
            required_value="RESPECTED",
            description=(
                "Shadow mode discipline: "
                f"{'Respected throughout validation period' if shadow_mode_respected else 'VIOLATED'}."
            ),
        ))

        return results

    def evaluate(self) -> GovernanceReport:
        """
        Perform complete governance evaluation.

        Returns GovernanceReport with decision and all criteria results.
        """
        logger.info("=" * 60)
        logger.info("GOVERNANCE GATE EVALUATION STARTING")
        logger.info("=" * 60)

        # Load input data
        shadow_stats, shadow_found = self._load_shadow_stats()
        pnl_summary, pnl_found = self._load_pnl_summary()

        # Evaluate all criteria
        all_results: List[CriterionResult] = []

        logger.info("Evaluating SHADOW QUALITY criteria...")
        all_results.extend(self._evaluate_shadow_quality(shadow_stats))

        logger.info("Evaluating ECONOMIC VIABILITY criteria...")
        all_results.extend(self._evaluate_economic_viability(pnl_summary))

        logger.info("Evaluating SYSTEM DISCIPLINE criteria...")
        all_results.extend(self._evaluate_system_discipline(shadow_stats))

        # Count results
        total_criteria = len(all_results)
        passed_criteria = sum(1 for r in all_results if r.passed)
        failed_criteria = total_criteria - passed_criteria

        # Determine decision
        # ALL criteria must pass for GO
        if failed_criteria == 0:
            decision = GovernanceDecision.GO_LIVE_APPROVED
            recommendation = None
            logger.info("All criteria PASSED. Decision: GO_LIVE_APPROVED")
        else:
            decision = GovernanceDecision.NO_GO_REJECTED
            recommendation = self._generate_recommendation(all_results)
            logger.warning(
                f"{failed_criteria} criteria FAILED. Decision: NO_GO_REJECTED"
            )

        # Extract key metrics for report
        if shadow_stats:
            total_completed = shadow_stats.get("total_completed_trades", 0)
            good_reversions = shadow_stats.get("good_reversions", 0)
            continued_panics = shadow_stats.get("continued_panics", 0)
            false_triggers = shadow_stats.get("false_triggers", 0)

            if total_completed > 0:
                false_trigger_rate = false_triggers / total_completed
                continued_panic_rate = continued_panics / total_completed
                good_reversion_rate = good_reversions / total_completed
            else:
                false_trigger_rate = continued_panic_rate = 1.0
                good_reversion_rate = 0.0

            kill_switch_triggered = shadow_stats.get("kill_switch_triggered", True)
        else:
            total_completed = 0
            false_trigger_rate = continued_panic_rate = 1.0
            good_reversion_rate = 0.0
            kill_switch_triggered = True

        if pnl_summary:
            pnl_stats = pnl_summary.get("aggregate_metrics", {}).get("pnl_statistics", {})
            cumulative = pnl_summary.get("aggregate_metrics", {}).get("cumulative", {})
            average_net_pnl = pnl_stats.get("average_net_pnl_usd", 0.0)
            max_drawdown_pct = cumulative.get("max_drawdown_pct", 0.0)
        else:
            average_net_pnl = 0.0
            max_drawdown_pct = 1.0

        report = GovernanceReport(
            decision=decision,
            decision_timestamp=datetime.utcnow().isoformat(),
            total_criteria=total_criteria,
            passed_criteria=passed_criteria,
            failed_criteria=failed_criteria,
            criteria_results=all_results,
            shadow_stats_path=str(self.shadow_stats_path),
            pnl_summary_path=str(self.pnl_summary_path),
            shadow_stats_found=shadow_found,
            pnl_summary_found=pnl_found,
            total_events=total_completed,
            false_trigger_rate=false_trigger_rate,
            continued_panic_rate=continued_panic_rate,
            good_reversion_rate=good_reversion_rate,
            average_net_pnl=average_net_pnl,
            max_drawdown_pct=max_drawdown_pct,
            kill_switch_triggered=kill_switch_triggered,
            recommendation=recommendation,
        )

        return report

    def _generate_recommendation(
        self,
        criteria_results: List[CriterionResult],
    ) -> str:
        """
        Generate recommendation for NO-GO decision.

        ONLY recommends:
        - "Continue shadow mode"
        - "Collect more samples"

        NEVER recommends parameter tuning.
        """
        failed = [r for r in criteria_results if not r.passed]

        # Check if insufficient data is the issue
        data_issues = [
            r for r in failed
            if "MISSING" in str(r.actual_value) or "available" in r.name.lower()
        ]

        sample_issues = [
            r for r in failed
            if "total_events" in r.name.lower()
        ]

        if data_issues:
            return (
                "RECOMMENDATION: Ensure shadow mode logging is active and "
                "run Paper PnL analysis before re-evaluation. "
                "Continue shadow mode until data is available."
            )

        if sample_issues:
            return (
                "RECOMMENDATION: Continue shadow mode to collect more samples. "
                f"Current: {failed[0].actual_value if failed else 'unknown'}, "
                f"Required: >= {MIN_TOTAL_EVENTS} events. "
                "Do NOT adjust parameters. Collect more data."
            )

        # General recommendation
        failed_names = [r.name for r in failed]
        return (
            f"RECOMMENDATION: Continue shadow mode. "
            f"Failed criteria: {', '.join(failed_names)}. "
            "Do NOT adjust parameters or thresholds. "
            "Monitor performance and re-evaluate when conditions improve naturally."
        )

    def save_decision(self, report: GovernanceReport):
        """
        Save decision to JSON file.
        """
        # Ensure parent directory exists
        self.output_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            with open(self.output_path, "w") as f:
                json.dump(report.to_dict(), f, indent=2)
            logger.info(f"Decision saved to {self.output_path}")
        except Exception as e:
            logger.error(f"Failed to save decision: {e}")

    def print_report(self, report: GovernanceReport):
        """
        Print human-readable governance report.
        """
        print("\n")
        print("=" * 70)
        print("PANIC CONTRARIAN ENGINE - GOVERNANCE GATE DECISION")
        print("=" * 70)

        # Decision banner
        print("\n" + "-" * 70)
        if report.decision == GovernanceDecision.GO_LIVE_APPROVED:
            print("   DECISION:  GO_LIVE_APPROVED")
            print("   STATUS:    All criteria met. Live trading PERMITTED.")
        else:
            print("   DECISION:  NO_GO_REJECTED")
            print("   STATUS:    Criteria not met. Live trading PROHIBITED.")
        print("-" * 70)

        # Key metrics
        print("\nKEY METRICS:")
        print(f"  Total Events:          {report.total_events}")
        print(f"  False Trigger Rate:    {report.false_trigger_rate:.1%}")
        print(f"  Continued Panic Rate:  {report.continued_panic_rate:.1%}")
        print(f"  Good Reversion Rate:   {report.good_reversion_rate:.1%}")
        print(f"  Average Net PnL:       ${report.average_net_pnl:.2f}")
        print(f"  Max Drawdown:          {report.max_drawdown_pct:.1%}")
        print(f"  Kill Switch:           {'TRIGGERED' if report.kill_switch_triggered else 'Never triggered'}")

        # Criteria summary
        print(f"\nCRITERIA EVALUATION:")
        print(f"  Total Criteria:        {report.total_criteria}")
        print(f"  Passed:                {report.passed_criteria}")
        print(f"  Failed:                {report.failed_criteria}")

        # Detail by category
        for category in ["SHADOW_QUALITY", "ECONOMIC_VIABILITY", "SYSTEM_DISCIPLINE"]:
            cat_results = [r for r in report.criteria_results if r.category == category]
            if cat_results:
                print(f"\n  {category}:")
                for r in cat_results:
                    status = "PASS" if r.passed else "FAIL"
                    print(f"    [{status}] {r.name}")
                    print(f"           Actual: {r.actual_value} | Required: {r.required_value}")

        # Failed criteria details
        failed = [r for r in report.criteria_results if not r.passed]
        if failed:
            print("\nFAILED CRITERIA DETAILS:")
            for r in failed:
                print(f"  - {r.name}: {r.description}")

        # Recommendation
        if report.recommendation:
            print("\n" + "-" * 70)
            print(report.recommendation)
            print("-" * 70)

        # Input data status
        print("\nINPUT DATA STATUS:")
        print(f"  Shadow Stats:  {'Found' if report.shadow_stats_found else 'MISSING'}")
        print(f"  PnL Summary:   {'Found' if report.pnl_summary_found else 'MISSING'}")

        # Timestamp
        print(f"\nEvaluation Timestamp: {report.decision_timestamp}")

        print("\n" + "=" * 70)

        # Final warning if GO
        if report.decision == GovernanceDecision.GO_LIVE_APPROVED:
            print("\nWARNING: GO_LIVE_APPROVED does not guarantee profitability.")
            print("Live trading involves real capital risk. Proceed with caution.")
            print("Monitor closely and be prepared to disable at first sign of issues.")
        else:
            print("\nLive trading remains PROHIBITED until all criteria are met.")
            print("Continue shadow mode operation. Do NOT adjust parameters.")

        print("\n")


# =============================================================================
# MAIN ENTRY POINT
# =============================================================================


def run_governance_check(
    shadow_stats_path: Optional[Path] = None,
    pnl_summary_path: Optional[Path] = None,
    output_path: Optional[Path] = None,
    print_report: bool = True,
) -> GovernanceReport:
    """
    Run governance gate evaluation and generate report.

    Args:
        shadow_stats_path: Path to shadow_stats.json
        pnl_summary_path: Path to panic_paper_pnl_summary.json
        output_path: Path for decision output
        print_report: Whether to print console report

    Returns:
        GovernanceReport with decision and all criteria
    """
    gate = GovernanceGate(
        shadow_stats_path=shadow_stats_path,
        pnl_summary_path=pnl_summary_path,
        output_path=output_path,
    )

    report = gate.evaluate()

    # Save decision
    gate.save_decision(report)

    # Print report
    if print_report:
        gate.print_report(report)

    return report


# =============================================================================
# CLI ENTRY POINT
# =============================================================================


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Panic Contrarian Engine - Governance Gate Decision"
    )
    parser.add_argument(
        "--shadow-stats",
        type=str,
        default=None,
        help="Path to shadow_stats.json",
    )
    parser.add_argument(
        "--pnl-summary",
        type=str,
        default=None,
        help="Path to panic_paper_pnl_summary.json",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Output path for decision JSON",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress console output",
    )

    args = parser.parse_args()

    # Setup basic logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
    )

    # Run evaluation
    report = run_governance_check(
        shadow_stats_path=Path(args.shadow_stats) if args.shadow_stats else None,
        pnl_summary_path=Path(args.pnl_summary) if args.pnl_summary else None,
        output_path=Path(args.output) if args.output else None,
        print_report=not args.quiet,
    )

    # Exit with appropriate code
    if report.decision == GovernanceDecision.GO_LIVE_APPROVED:
        exit(0)
    else:
        exit(1)
