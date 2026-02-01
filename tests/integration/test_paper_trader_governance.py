# =============================================================================
# POLYMARKET BEOBACHTER - PAPER TRADER GOVERNANCE TESTS
# =============================================================================
#
# GOVERNANCE INTENT:
# These tests verify that paper trading maintains strict layer isolation
# and governance constraints.
#
# TEST CATEGORIES:
# 1. Import guards - paper_trader not imported by core_analyzer
# 2. Price isolation - price fields never in Layer 1 outputs
# 3. Idempotency - same proposal not executed twice
# 4. Paper-only guarantees - no trading code exists
#
# =============================================================================

import sys
import os
import ast
import json
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest


class TestImportGuards:
    """
    Tests that paper_trader is never imported by core_analyzer.

    GOVERNANCE:
    Core analyzer (Layer 1) must NEVER see price data from paper_trader.
    This is enforced by preventing any imports.
    """

    def test_core_analyzer_does_not_import_paper_trader(self):
        """
        Verify core_analyzer has no imports from paper_trader.

        This test scans all Python files in core_analyzer/ for imports.
        """
        core_analyzer_path = Path(__file__).parent.parent / "core_analyzer"

        if not core_analyzer_path.exists():
            pytest.skip("core_analyzer directory not found")

        violations = []

        for py_file in core_analyzer_path.rglob("*.py"):
            try:
                with open(py_file, 'r', encoding='utf-8') as f:
                    source = f.read()

                tree = ast.parse(source)

                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            if 'paper_trader' in alias.name:
                                violations.append(
                                    f"{py_file}: import {alias.name}"
                                )
                    elif isinstance(node, ast.ImportFrom):
                        if node.module and 'paper_trader' in node.module:
                            violations.append(
                                f"{py_file}: from {node.module} import ..."
                            )

            except SyntaxError:
                # Skip files with syntax errors
                continue

        assert len(violations) == 0, \
            f"GOVERNANCE VIOLATION: core_analyzer imports paper_trader:\n" + \
            "\n".join(violations)

    def test_proposals_does_not_import_paper_trader(self):
        """
        Verify proposals/ has no imports from paper_trader.

        Proposals are the source for paper_trader, not vice versa.
        """
        proposals_path = Path(__file__).parent.parent / "proposals"

        if not proposals_path.exists():
            pytest.skip("proposals directory not found")

        violations = []

        for py_file in proposals_path.rglob("*.py"):
            try:
                with open(py_file, 'r', encoding='utf-8') as f:
                    source = f.read()

                tree = ast.parse(source)

                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            if 'paper_trader' in alias.name:
                                violations.append(
                                    f"{py_file}: import {alias.name}"
                                )
                    elif isinstance(node, ast.ImportFrom):
                        if node.module and 'paper_trader' in node.module:
                            violations.append(
                                f"{py_file}: from {node.module} import ..."
                            )

            except SyntaxError:
                continue

        assert len(violations) == 0, \
            f"GOVERNANCE VIOLATION: proposals imports paper_trader:\n" + \
            "\n".join(violations)


class TestPriceIsolation:
    """
    Tests that price fields never appear in Layer 1 outputs.

    GOVERNANCE:
    Layer 1 (core_analyzer, proposals) must not contain price data.
    Price data is only allowed in paper_trader logs.
    """

    def test_proposals_log_has_no_price_fields(self):
        """
        Verify proposals_log.json has no price-related fields.

        Proposals contain edge and probability, but NOT market prices.
        """
        proposals_log_path = Path(__file__).parent.parent / "proposals" / "proposals_log.json"

        if not proposals_log_path.exists():
            pytest.skip("proposals_log.json not found")

        with open(proposals_log_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        forbidden_fields = [
            "entry_price",
            "exit_price",
            "best_bid",
            "best_ask",
            "mid_price",
            "slippage",
            "pnl",
            "realized_pnl",
        ]

        violations = []

        for proposal in data.get("proposals", []):
            for field in forbidden_fields:
                if field in proposal:
                    violations.append(
                        f"Proposal {proposal.get('proposal_id')}: has {field}"
                    )

        assert len(violations) == 0, \
            f"GOVERNANCE VIOLATION: proposals_log contains price data:\n" + \
            "\n".join(violations)

    def test_paper_trader_models_have_governance_notice(self):
        """
        Verify paper_trader models include governance notices.
        """
        from paper_trader.models import (
            PaperPosition,
            PaperTradeRecord,
            MarketSnapshot,
        )

        # Check PaperPosition
        pos = PaperPosition(
            position_id="TEST",
            proposal_id="TEST",
            market_id="TEST",
            market_question="Test",
            side="YES",
            status="OPEN",
            entry_time="2026-01-15T00:00:00",
            entry_price=0.5,
            entry_slippage=0.01,
            size_contracts=100,
            cost_basis_eur=50,
            exit_time=None,
            exit_price=None,
            exit_slippage=None,
            exit_reason=None,
            realized_pnl_eur=None,
            pnl_pct=None,
        )
        assert "PAPER" in pos.governance_notice.upper(), \
            "PaperPosition governance notice must mention PAPER"

        # Check PaperTradeRecord
        rec = PaperTradeRecord(
            record_id="TEST",
            timestamp="2026-01-15T00:00:00",
            proposal_id="TEST",
            market_id="TEST",
            action="PAPER_ENTER",
            reason="Test",
            position_id="TEST",
            snapshot_time=None,
            entry_price=None,
            exit_price=None,
            slippage_applied=None,
            pnl_eur=None,
        )
        assert "PAPER" in rec.governance_notice.upper(), \
            "PaperTradeRecord governance notice must mention PAPER"

        # Check MarketSnapshot
        snap = MarketSnapshot(
            market_id="TEST",
            snapshot_time="2026-01-15T00:00:00",
            best_bid=0.45,
            best_ask=0.55,
            mid_price=0.5,
            spread_pct=20.0,
            liquidity_bucket="LOW",
            is_resolved=False,
            resolved_outcome=None,
        )
        assert "PAPER" in snap.governance_notice.upper(), \
            "MarketSnapshot governance notice must mention PAPER"


class TestIdempotency:
    """
    Tests that the same proposal is not paper-executed twice.

    GOVERNANCE:
    Idempotency prevents duplicate paper trades.
    """

    def test_logger_tracks_executed_proposals(self, tmp_path):
        """
        Verify logger tracks which proposals have been executed.
        """
        from paper_trader.logger import PaperTradingLogger
        from paper_trader.models import PaperTradeRecord, TradeAction, generate_record_id

        # Create logger with temp directory
        logs_dir = tmp_path / "logs"
        reports_dir = tmp_path / "reports"
        paper_logger = PaperTradingLogger(logs_dir, reports_dir)

        # Initially no executed proposals
        executed = paper_logger.get_executed_proposal_ids()
        assert len(executed) == 0

        # Log an entry
        record = PaperTradeRecord(
            record_id=generate_record_id(),
            timestamp="2026-01-15T00:00:00",
            proposal_id="PROP-TEST-001",
            market_id="market-1",
            action=TradeAction.PAPER_ENTER.value,
            reason="Test entry",
            position_id="PAPER-TEST-001",
            snapshot_time=None,
            entry_price=0.5,
            exit_price=None,
            slippage_applied=0.01,
            pnl_eur=None,
        )
        paper_logger.log_trade(record)

        # Now should be tracked
        executed = paper_logger.get_executed_proposal_ids()
        assert "PROP-TEST-001" in executed

        # Log another entry for different proposal
        record2 = PaperTradeRecord(
            record_id=generate_record_id(),
            timestamp="2026-01-15T00:01:00",
            proposal_id="PROP-TEST-002",
            market_id="market-2",
            action=TradeAction.PAPER_ENTER.value,
            reason="Test entry 2",
            position_id="PAPER-TEST-002",
            snapshot_time=None,
            entry_price=0.6,
            exit_price=None,
            slippage_applied=0.01,
            pnl_eur=None,
        )
        paper_logger.log_trade(record2)

        executed = paper_logger.get_executed_proposal_ids()
        assert "PROP-TEST-001" in executed
        assert "PROP-TEST-002" in executed
        assert len(executed) == 2


class TestPaperOnlyGuarantees:
    """
    Tests that no live trading code exists in paper_trader.

    GOVERNANCE:
    Paper trader must not have any capability to place real orders.
    """

    def test_no_trading_library_imports(self):
        """
        Verify paper_trader doesn't import trading libraries.
        """
        paper_trader_path = Path(__file__).parent.parent / "paper_trader"

        if not paper_trader_path.exists():
            pytest.skip("paper_trader directory not found")

        forbidden_imports = [
            "ccxt",
            "py_clob_client",
            "polymarket_client",
            "web3",
            "eth_account",
        ]

        violations = []

        for py_file in paper_trader_path.rglob("*.py"):
            try:
                with open(py_file, 'r', encoding='utf-8') as f:
                    source = f.read()

                tree = ast.parse(source)

                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            for forbidden in forbidden_imports:
                                if forbidden in alias.name:
                                    violations.append(
                                        f"{py_file}: import {alias.name}"
                                    )
                    elif isinstance(node, ast.ImportFrom):
                        if node.module:
                            for forbidden in forbidden_imports:
                                if forbidden in node.module:
                                    violations.append(
                                        f"{py_file}: from {node.module}"
                                    )

            except SyntaxError:
                continue

        assert len(violations) == 0, \
            f"GOVERNANCE VIOLATION: paper_trader imports trading libraries:\n" + \
            "\n".join(violations)

    def test_no_order_placement_keywords(self):
        """
        Verify paper_trader code has no order placement keywords.
        """
        paper_trader_path = Path(__file__).parent.parent / "paper_trader"

        if not paper_trader_path.exists():
            pytest.skip("paper_trader directory not found")

        forbidden_keywords = [
            "place_order",
            "submit_order",
            "execute_order",
            "send_order",
            "create_order",
            "market_buy",
            "market_sell",
            "limit_buy",
            "limit_sell",
            "sign_transaction",
            "send_transaction",
        ]

        violations = []

        for py_file in paper_trader_path.rglob("*.py"):
            with open(py_file, 'r', encoding='utf-8') as f:
                source = f.read()
                source_lower = source.lower()

            for keyword in forbidden_keywords:
                if keyword.lower() in source_lower:
                    # Check if it's in a comment or docstring
                    # Simple heuristic: check if preceded by "no" or "don't"
                    # For now, just flag it
                    violations.append(f"{py_file}: contains '{keyword}'")

        # Allow if in comments explaining what it DOESN'T do
        actual_violations = [
            v for v in violations
            if "does not" not in v.lower() and "doesn't" not in v.lower()
        ]

        assert len(actual_violations) == 0, \
            f"GOVERNANCE VIOLATION: paper_trader has order placement code:\n" + \
            "\n".join(actual_violations)

    def test_no_wallet_or_balance_code(self):
        """
        Verify paper_trader has no wallet/balance management code.
        """
        paper_trader_path = Path(__file__).parent.parent / "paper_trader"

        if not paper_trader_path.exists():
            pytest.skip("paper_trader directory not found")

        forbidden_keywords = [
            "get_balance",
            "check_balance",
            "wallet_address",
            "private_key",
            "api_key",
            "api_secret",
        ]

        violations = []

        for py_file in paper_trader_path.rglob("*.py"):
            with open(py_file, 'r', encoding='utf-8') as f:
                source = f.read()
                source_lower = source.lower()

            for keyword in forbidden_keywords:
                if keyword.lower() in source_lower:
                    violations.append(f"{py_file}: contains '{keyword}'")

        assert len(violations) == 0, \
            f"GOVERNANCE VIOLATION: paper_trader has wallet/balance code:\n" + \
            "\n".join(violations)


class TestSlippageModel:
    """
    Tests for the conservative slippage model.

    GOVERNANCE:
    Slippage must be CONSERVATIVE - never favor paper trader.
    """

    def test_entry_price_always_higher_than_ask(self):
        """
        Entry price should be >= ask (worst case for buyer).
        """
        from paper_trader.slippage import get_slippage_model
        from paper_trader.models import MarketSnapshot

        model = get_slippage_model()

        snapshot = MarketSnapshot(
            market_id="TEST",
            snapshot_time="2026-01-15T00:00:00",
            best_bid=0.45,
            best_ask=0.55,
            mid_price=0.5,
            spread_pct=20.0,
            liquidity_bucket="MEDIUM",
            is_resolved=False,
            resolved_outcome=None,
        )

        result = model.calculate_entry_price(snapshot, "YES")
        assert result is not None

        entry_price, slippage = result
        assert entry_price >= snapshot.best_ask, \
            f"Entry price {entry_price} should be >= ask {snapshot.best_ask}"
        assert slippage > 0, "Slippage should be positive"

    def test_exit_price_always_lower_than_bid(self):
        """
        Exit price should be <= bid (worst case for seller).
        """
        from paper_trader.slippage import get_slippage_model
        from paper_trader.models import MarketSnapshot

        model = get_slippage_model()

        snapshot = MarketSnapshot(
            market_id="TEST",
            snapshot_time="2026-01-15T00:00:00",
            best_bid=0.45,
            best_ask=0.55,
            mid_price=0.5,
            spread_pct=20.0,
            liquidity_bucket="MEDIUM",
            is_resolved=False,
            resolved_outcome=None,
        )

        result = model.calculate_exit_price(snapshot, "YES", is_resolution=False)
        assert result is not None

        exit_price, slippage = result
        assert exit_price <= snapshot.best_bid, \
            f"Exit price {exit_price} should be <= bid {snapshot.best_bid}"

    def test_unknown_liquidity_uses_worst_slippage(self):
        """
        Unknown liquidity should use worst-case (5%) slippage.
        """
        from paper_trader.slippage import (
            get_slippage_model,
            SLIPPAGE_UNKNOWN_LIQUIDITY,
        )

        model = get_slippage_model()
        rate = model.get_slippage_rate("UNKNOWN")

        assert rate == SLIPPAGE_UNKNOWN_LIQUIDITY, \
            f"Unknown liquidity should use {SLIPPAGE_UNKNOWN_LIQUIDITY} slippage"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
