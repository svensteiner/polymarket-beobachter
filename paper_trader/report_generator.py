# =============================================================================
# POLYMARKET BEOBACHTER - TRADE REPORT GENERATOR
# =============================================================================
#
# Generiert kurze Berichte/Begründungen warum eine Position eröffnet wurde.
# Reports werden in der zentralen Datenbank gespeichert.
#
# =============================================================================

import logging
from datetime import datetime, date
from typing import Dict, Any, Optional

from paper_trader.models import PaperPosition
from proposals.models import Proposal

logger = logging.getLogger(__name__)


class TradeReportGenerator:
    """
    Generates human-readable reports explaining why a position was opened.
    """

    def generate_report(
        self,
        position: PaperPosition,
        proposal: Proposal,
        category: str = "GENERIC"
    ) -> Dict[str, Any]:
        """
        Generate a trade report for an opened position.

        Args:
            position: The opened paper position
            proposal: The proposal that triggered the trade
            category: Market category (POLITICAL, CORPORATE, COURT, etc.)

        Returns:
            Report dictionary ready for database insertion
        """
        now = datetime.now()

        # Calculate days until resolution
        try:
            # Try to parse end_date from proposal if available
            days_until = None
            if hasattr(proposal, 'target_date'):
                target = proposal.target_date
                if isinstance(target, str):
                    target = date.fromisoformat(target[:10])
                days_until = (target - date.today()).days
        except (ValueError, AttributeError):
            days_until = None

        # Build decision reason
        decision_reason = self._build_decision_reason(proposal, position.side)

        # Build short summary (1-2 sentences)
        short_summary = self._build_short_summary(
            position, proposal, category, days_until
        )

        # Build full report
        full_report = self._build_full_report(
            position, proposal, category, days_until, decision_reason
        )

        return {
            "position_id": position.position_id,
            "market_id": position.market_id,
            "report_time": now.isoformat(),
            "market_title": position.market_question,
            "side": position.side,
            "entry_price": position.entry_price,
            "decision_reason": decision_reason,
            "category": category,
            "edge_pct": proposal.edge * 100 if proposal.edge else 0,
            "confidence": proposal.confidence_level,
            "days_until_resolution": days_until,
            "implied_probability": proposal.implied_probability,
            "model_probability": proposal.model_probability,
            "short_summary": short_summary,
            "full_report": full_report,
        }

    def _build_decision_reason(self, proposal: Proposal, side: str) -> str:
        """Build the main decision reason."""
        edge = proposal.edge * 100 if proposal.edge else 0
        confidence = proposal.confidence_level or "MEDIUM"

        if side == "YES":
            direction = "undervalued"
            action = "BUY YES"
        else:
            direction = "overvalued"
            action = "BUY NO"

        return (
            f"Market appears {direction} by {abs(edge):.1f}%. "
            f"Confidence: {confidence}. Action: {action}."
        )

    def _build_short_summary(
        self,
        position: PaperPosition,
        proposal: Proposal,
        category: str,
        days_until: Optional[int]
    ) -> str:
        """Build a 1-2 sentence summary."""
        edge = abs(proposal.edge * 100) if proposal.edge else 0
        price = position.entry_price * 100

        # Build time context
        time_ctx = ""
        if days_until is not None:
            if days_until <= 7:
                time_ctx = f" Resolution in {days_until} days."
            elif days_until <= 30:
                time_ctx = f" Resolution in ~{days_until // 7} weeks."

        return (
            f"Opened {position.side} position at {price:.0f}c "
            f"with {edge:.1f}% edge ({category}).{time_ctx}"
        )

    def _build_full_report(
        self,
        position: PaperPosition,
        proposal: Proposal,
        category: str,
        days_until: Optional[int],
        decision_reason: str
    ) -> str:
        """Build a detailed report."""
        lines = []

        # Header
        lines.append(f"=== TRADE REPORT ===")
        lines.append(f"Position ID: {position.position_id}")
        lines.append(f"Market: {position.market_question[:80]}...")
        lines.append("")

        # Trade details
        lines.append("TRADE DETAILS:")
        lines.append(f"  Side: {position.side}")
        lines.append(f"  Entry Price: {position.entry_price:.4f} ({position.entry_price*100:.1f}c)")
        lines.append(f"  Size: {position.size_contracts:.2f} contracts")
        lines.append(f"  Cost: {position.cost_basis_eur:.2f} EUR")
        lines.append(f"  Slippage: {position.entry_slippage:.4f}")
        lines.append("")

        # Analysis
        lines.append("ANALYSIS:")
        lines.append(f"  Category: {category}")
        lines.append(f"  Implied Prob: {proposal.implied_probability*100:.1f}%")
        lines.append(f"  Model Prob: {proposal.model_probability*100:.1f}%")
        edge_pct = proposal.edge * 100 if proposal.edge else 0
        lines.append(f"  Edge: {edge_pct:+.1f}%")
        lines.append(f"  Confidence: {proposal.confidence_level}")
        lines.append("")

        # Timing
        if days_until is not None:
            lines.append("TIMING:")
            lines.append(f"  Days until resolution: {days_until}")
            if days_until <= 7:
                lines.append(f"  Status: SHORT-TERM (high attention)")
            elif days_until <= 30:
                lines.append(f"  Status: MEDIUM-TERM")
            else:
                lines.append(f"  Status: LONG-TERM")
            lines.append("")

        # Decision
        lines.append("DECISION:")
        lines.append(f"  {decision_reason}")
        lines.append("")

        # Justification from proposal
        if proposal.justification_summary:
            lines.append("JUSTIFICATION:")
            lines.append(f"  {proposal.justification_summary[:300]}")
            lines.append("")

        # Warnings
        if proposal.warnings:
            lines.append("WARNINGS:")
            for w in proposal.warnings[:5]:
                lines.append(f"  - {w}")
            lines.append("")

        lines.append(f"Generated: {datetime.now().isoformat()}")

        return "\n".join(lines)


# Module-level instance
_generator: Optional[TradeReportGenerator] = None


def get_report_generator() -> TradeReportGenerator:
    """Get the global report generator instance."""
    global _generator
    if _generator is None:
        _generator = TradeReportGenerator()
    return _generator


def generate_trade_report(
    position: PaperPosition,
    proposal: Proposal,
    category: str = "GENERIC"
) -> Dict[str, Any]:
    """Convenience function to generate a trade report."""
    return get_report_generator().generate_report(position, proposal, category)
