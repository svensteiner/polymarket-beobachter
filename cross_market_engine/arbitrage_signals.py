# =============================================================================
# CROSS-MARKET ARBITRAGE SIGNAL GENERATOR
# =============================================================================
#
# When the consistency engine finds INCONSISTENT relations, this module
# generates trading signals in the same format as Weather Signals.
#
# SIGNAL ONLY — no auto-trade. Same governance as Weather Engine.
#
# EXAMPLE:
# Market A implies Market B, but P(A)=0.60 > P(B)=0.40
# → Buy B (underpriced relative to A)
# → Sell A (overpriced relative to B)
#
# =============================================================================

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional

from .findings import Finding, FindingsSummary, ConsistencyStatus

logger = logging.getLogger(__name__)

# Signal log path
SIGNAL_LOG_PATH = Path(__file__).parent.parent / "logs" / "arbitrage_signals.jsonl"


@dataclass
class ArbitrageSignal:
    """
    A cross-market arbitrage signal.

    Generated when an IMPLIES relation is INCONSISTENT.
    Format parallels WeatherSignal for pipeline compatibility.
    """
    signal_id: str
    timestamp: str
    finding_id: str

    # Markets
    market_a_id: str
    market_b_id: str
    market_a_question: str
    market_b_question: str

    # Prices
    p_a: float
    p_b: float
    delta: float

    # Signal
    action: str  # "BUY_B" or "SELL_A" or "PAIR_TRADE"
    reasoning: str
    edge_estimate: float  # delta as edge

    # Metadata
    relation_type: str
    tolerance: float
    is_actionable: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "signal_id": self.signal_id,
            "timestamp": self.timestamp,
            "finding_id": self.finding_id,
            "market_a_id": self.market_a_id,
            "market_b_id": self.market_b_id,
            "market_a_question": self.market_a_question,
            "market_b_question": self.market_b_question,
            "p_a": self.p_a,
            "p_b": self.p_b,
            "delta": self.delta,
            "action": self.action,
            "reasoning": self.reasoning,
            "edge_estimate": self.edge_estimate,
            "relation_type": self.relation_type,
            "tolerance": self.tolerance,
            "is_actionable": self.is_actionable,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict())


def generate_signals_from_findings(
    summary: FindingsSummary,
    min_delta: float = 0.08,
) -> List[ArbitrageSignal]:
    """
    Generate arbitrage signals from consistency check findings.

    Only generates signals for INCONSISTENT findings where the
    delta exceeds min_delta.

    Args:
        summary: FindingsSummary from consistency checker
        min_delta: Minimum price delta to generate a signal

    Returns:
        List of ArbitrageSignal objects
    """
    signals: List[ArbitrageSignal] = []

    for finding in summary.findings:
        if finding.status != ConsistencyStatus.INCONSISTENT:
            continue

        if abs(finding.delta) < min_delta:
            continue

        now = datetime.utcnow().isoformat() + "Z"
        signal_id = f"arb_{finding.finding_id}"

        # If A implies B but P(A) > P(B):
        # B is underpriced (buy B) or A is overpriced (sell A)
        if finding.delta > 0:
            action = "BUY_B"
            reasoning = (
                f"Market A ({finding.p_a:.1%}) implies Market B ({finding.p_b:.1%}), "
                f"but P(A) > P(B) by {finding.delta:.1%}. "
                f"B appears underpriced relative to A. Buy B."
            )
        else:
            action = "BUY_A"
            reasoning = (
                f"Inverse inconsistency: P(B) > P(A) by {abs(finding.delta):.1%}. "
                f"A may be underpriced. Buy A."
            )

        metadata = finding.metadata or {}

        signal = ArbitrageSignal(
            signal_id=signal_id,
            timestamp=now,
            finding_id=finding.finding_id,
            market_a_id=finding.market_a_id,
            market_b_id=finding.market_b_id,
            market_a_question=metadata.get("market_a_question", finding.market_a_id),
            market_b_question=metadata.get("market_b_question", finding.market_b_id),
            p_a=finding.p_a,
            p_b=finding.p_b,
            delta=finding.delta,
            action=action,
            reasoning=reasoning,
            edge_estimate=abs(finding.delta),
            relation_type=finding.relation_type,
            tolerance=finding.tolerance,
        )

        signals.append(signal)
        logger.info(
            f"Arbitrage signal: {action} | "
            f"A={finding.market_a_id} ({finding.p_a:.1%}) → "
            f"B={finding.market_b_id} ({finding.p_b:.1%}) | "
            f"delta={finding.delta:+.1%}"
        )

    return signals


def log_signals(signals: List[ArbitrageSignal]) -> None:
    """Write arbitrage signals to JSONL log."""
    if not signals:
        return

    SIGNAL_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(SIGNAL_LOG_PATH, "a", encoding="utf-8") as f:
        for signal in signals:
            f.write(signal.to_json() + "\n")

    logger.info(f"Logged {len(signals)} arbitrage signals to {SIGNAL_LOG_PATH}")
