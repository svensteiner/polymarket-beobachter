# =============================================================================
# POLYMARKET BEOBACHTER - PAPER TRADING REPORTER
# =============================================================================
#
# GOVERNANCE INTENT:
# This module generates reports for paper trading results.
# Reports are stored in paper_trader/reports/ directory.
#
# PAPER TRADING ONLY:
# All reports are based on simulated data.
# They do NOT represent real trading performance.
#
# =============================================================================

import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from paper_trader.logger import get_paper_logger, REPORTS_DIR
from paper_trader.position_manager import get_position_summary
from paper_trader.models import PaperPosition, PaperTradeRecord, TradeAction


# =============================================================================
# REPORTER
# =============================================================================


class PaperTradingReporter:
    """
    Generates reports for paper trading results.

    GOVERNANCE:
    Reports are based on PAPER trading data only.
    They must clearly indicate this is simulated data.
    """

    def __init__(self, reports_dir: Path = None):
        """Initialize the reporter."""
        self.reports_dir = reports_dir or REPORTS_DIR
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        self._paper_logger = get_paper_logger()

    def generate_daily_report(self) -> str:
        """
        Generate a daily summary report.

        Returns:
            Path to the generated report file
        """
        now = datetime.now()
        date_str = now.strftime("%Y-%m-%d")
        report_path = self.reports_dir / f"daily_report_{date_str}.md"

        # Gather data
        stats = self._paper_logger.get_statistics()
        position_summary = get_position_summary()
        trades = self._paper_logger.read_all_trades()
        positions = self._paper_logger.read_all_positions()

        # Build report
        lines = [
            "# Paper Trading Daily Report",
            "",
            f"**Date:** {date_str}",
            f"**Generated:** {now.isoformat()}",
            "",
            "---",
            "",
            "## GOVERNANCE NOTICE",
            "",
            "> **This is a PAPER TRADING report.**",
            "> All trades are SIMULATED. No real funds were used.",
            "> Performance figures are hypothetical and do not represent actual results.",
            "",
            "---",
            "",
            "## Summary Statistics",
            "",
            f"| Metric | Value |",
            f"|--------|-------|",
            f"| Total Paper Trades | {stats['total_trades']} |",
            f"| Paper Enters | {stats['paper_enters']} |",
            f"| Paper Exits | {stats['paper_exits']} |",
            f"| Skipped | {stats['skips']} |",
            f"| Open Positions | {position_summary['open']} |",
            f"| Closed Positions | {position_summary['closed']} |",
            f"| Resolved Positions | {position_summary['resolved']} |",
            "",
            "## P&L Summary (Paper Only)",
            "",
            f"| Metric | Value |",
            f"|--------|-------|",
            f"| Total Realized P&L | {stats['total_realized_pnl_eur']:+.2f} EUR |",
            f"| Positions with P&L | {stats['positions_with_pnl']} |",
            f"| Open Cost Basis | {position_summary['open_cost_basis_eur']:.2f} EUR |",
            "",
        ]

        # Open positions table
        if position_summary['open'] > 0:
            open_positions = self._get_open_positions(positions)
            lines.extend([
                "## Open Positions",
                "",
                "| Position ID | Market | Side | Entry Price | Cost Basis |",
                "|-------------|--------|------|-------------|------------|",
            ])
            for pos in open_positions[:20]:  # Limit to 20
                market_short = pos.market_question[:40] + "..." if len(pos.market_question) > 40 else pos.market_question
                lines.append(
                    f"| {pos.position_id} | {market_short} | {pos.side} | "
                    f"{pos.entry_price:.4f} | {pos.cost_basis_eur:.2f} EUR |"
                )
            if len(open_positions) > 20:
                lines.append(f"| ... | ({len(open_positions) - 20} more) | | | |")
            lines.append("")

        # Closed positions table
        closed_positions = self._get_closed_positions(positions)
        if closed_positions:
            lines.extend([
                "## Recently Closed Positions",
                "",
                "| Position ID | Side | Entry | Exit | P&L |",
                "|-------------|------|-------|------|-----|",
            ])
            for pos in closed_positions[:10]:  # Last 10
                pnl_str = f"{pos.realized_pnl_eur:+.2f}" if pos.realized_pnl_eur else "N/A"
                lines.append(
                    f"| {pos.position_id} | {pos.side} | "
                    f"{pos.entry_price:.4f} | {pos.exit_price:.4f} | {pnl_str} EUR |"
                )
            lines.append("")

        # Recent activity
        recent_trades = sorted(trades, key=lambda t: t.timestamp, reverse=True)[:10]
        if recent_trades:
            lines.extend([
                "## Recent Activity",
                "",
                "| Time | Action | Market | Reason |",
                "|------|--------|--------|--------|",
            ])
            for trade in recent_trades:
                time_short = trade.timestamp[:19]  # Remove microseconds
                reason_short = trade.reason[:50] + "..." if len(trade.reason) > 50 else trade.reason
                lines.append(
                    f"| {time_short} | {trade.action} | {trade.market_id[:20]} | {reason_short} |"
                )
            lines.append("")

        # Footer
        lines.extend([
            "---",
            "",
            "## Notes",
            "",
            "- All P&L figures are PAPER ONLY and do not represent real performance",
            "- Slippage model uses conservative estimates",
            "- No hindsight is used in price simulation",
            "- Market resolution determines exit price (1.0 or 0.0)",
            "",
            f"*Report generated by Paper Trading Module v0.1.0*",
        ])

        # Write report
        report_content = "\n".join(lines)
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write(report_content)

        return str(report_path)

    def _get_open_positions(self, positions: List[PaperPosition]) -> List[PaperPosition]:
        """Get latest state of open positions."""
        position_states: Dict[str, PaperPosition] = {}
        for pos in positions:
            position_states[pos.position_id] = pos
        return [p for p in position_states.values() if p.status == "OPEN"]

    def _get_closed_positions(self, positions: List[PaperPosition]) -> List[PaperPosition]:
        """Get latest state of closed positions."""
        position_states: Dict[str, PaperPosition] = {}
        for pos in positions:
            position_states[pos.position_id] = pos
        closed = [p for p in position_states.values() if p.status in ["CLOSED", "RESOLVED"]]
        return sorted(closed, key=lambda p: p.exit_time or "", reverse=True)

    def print_summary(self):
        """Print a quick summary to console."""
        stats = self._paper_logger.get_statistics()
        position_summary = get_position_summary()

        print("\n" + "=" * 60)
        print("PAPER TRADING SUMMARY (SIMULATED - NO REAL TRADES)")
        print("=" * 60)
        print(f"Paper Enters:       {stats['paper_enters']}")
        print(f"Paper Exits:        {stats['paper_exits']}")
        print(f"Skipped:            {stats['skips']}")
        print(f"Open Positions:     {position_summary['open']}")
        print(f"Closed Positions:   {position_summary['closed'] + position_summary['resolved']}")
        print(f"Total Paper P&L:    {stats['total_realized_pnl_eur']:+.2f} EUR")
        print("=" * 60 + "\n")


# =============================================================================
# MODULE-LEVEL FUNCTIONS
# =============================================================================


def generate_daily_report() -> str:
    """Generate daily report and return path."""
    reporter = PaperTradingReporter()
    return reporter.generate_daily_report()


def print_summary():
    """Print quick summary to console."""
    reporter = PaperTradingReporter()
    reporter.print_summary()
