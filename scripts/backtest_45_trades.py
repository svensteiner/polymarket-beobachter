#!/usr/bin/env python3
"""
Backtest Analysis of All 45 Closed Trades
==========================================
Validates:
1. Side selection correctness (edge sign → side)
2. P&L accounting with partial exits (TP1/TP2/TP3)
3. Fee-aware edge computation
4. Entry price reasonableness for NO positions
5. Capital reconciliation
"""

import json
import sys
from pathlib import Path
from collections import defaultdict

# Add project root
sys.path.insert(0, str(Path(__file__).parent.parent))


def load_positions():
    """Load all positions from JSONL log."""
    positions = []
    log_path = Path(__file__).parent.parent / "paper_trader" / "logs" / "paper_positions.jsonl"
    with open(log_path, "r") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    positions.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return positions


def load_trade_records():
    """Load all trade records from JSONL log."""
    records = []
    log_path = Path(__file__).parent.parent / "paper_trader" / "logs" / "paper_trades.jsonl"
    if not log_path.exists():
        return records
    with open(log_path, "r") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return records


def analyze_side_selection(positions):
    """Verify side selection: positive edge → YES, negative → NO."""
    print("\n" + "=" * 70)
    print("SIDE SELECTION ANALYSIS")
    print("=" * 70)

    latest = {}
    for p in positions:
        latest[p["position_id"]] = p

    bugs = []
    for p in latest.values():
        edge = p.get("proposal_edge", 0)
        side = p.get("side", "")
        expected_side = "YES" if edge > 0 else "NO"

        if side != expected_side:
            bugs.append({
                "position_id": p["position_id"],
                "edge": edge,
                "side": side,
                "expected": expected_side,
                "question": p.get("market_question", "")[:60],
            })

    if bugs:
        print(f"\n  SIDE SELECTION BUGS FOUND: {len(bugs)}")
        for b in bugs:
            print(f"    {b['position_id']}: edge={b['edge']:+.3f} side={b['side']} "
                  f"expected={b['expected']} | {b['question']}")
    else:
        print("\n  Side selection: ALL CORRECT (edge sign matches side)")

    # Distribution
    yes_count = sum(1 for p in latest.values() if p["side"] == "YES")
    no_count = sum(1 for p in latest.values() if p["side"] == "NO")
    print(f"\n  Distribution: {yes_count} YES / {no_count} NO")

    return bugs


def analyze_tp_sl_pnl(positions, trade_records):
    """Analyze TP/SL P&L accounting issues."""
    print("\n" + "=" * 70)
    print("TP/SL P&L ANALYSIS")
    print("=" * 70)

    latest = {}
    for p in positions:
        latest[p["position_id"]] = p

    closed = [p for p in latest.values() if p["status"] in ("CLOSED", "RESOLVED")]

    # Check for TP exits with negative P&L (the bug we fixed)
    tp_with_loss = []
    for p in closed:
        reason = p.get("exit_reason", "") or ""
        pnl = p.get("realized_pnl_eur", 0) or 0
        if "TP" in reason and pnl <= 0:
            tp_with_loss.append(p)

    print(f"\n  Total closed positions: {len(closed)}")
    print(f"  TP exits with negative P&L (BUG pre-fix): {len(tp_with_loss)}")

    if tp_with_loss:
        print("\n  Affected TP positions (P&L doesn't include partial exits):")
        for p in tp_with_loss:
            print(f"    {p['position_id']}: {p['exit_reason'][:40]} "
                  f"pnl={p.get('realized_pnl_eur', 0):+.2f} EUR")

    # Compute what partial exits contributed
    if trade_records:
        partial_pnl_by_position = defaultdict(float)
        for r in trade_records:
            if r.get("action") == "PARTIAL_EXIT":
                pid = r.get("position_id", "")
                partial_pnl_by_position[pid] += r.get("pnl_eur", 0) or 0

        if partial_pnl_by_position:
            print(f"\n  Partial exit P&L recovered from trade records:")
            for pid, ppnl in sorted(partial_pnl_by_position.items()):
                pos = latest.get(pid)
                if pos:
                    recorded_pnl = pos.get("realized_pnl_eur", 0) or 0
                    true_pnl = recorded_pnl + ppnl
                    print(f"    {pid}: recorded={recorded_pnl:+.2f} "
                          f"+ partial={ppnl:+.2f} = true={true_pnl:+.2f} EUR")

    # Check for impossible SL percentages
    impossible_sl = []
    for p in closed:
        reason = p.get("exit_reason", "") or ""
        if "Stop-Loss" in reason:
            # Extract percentage from reason string
            import re
            match = re.search(r"Stop-Loss \(([-+]?\d+\.?\d*)%\)", reason)
            if match:
                sl_pct = float(match.group(1))
                if sl_pct < -100:
                    impossible_sl.append({
                        "position_id": p["position_id"],
                        "side": p["side"],
                        "entry_price": p.get("entry_price", 0),
                        "sl_pct": sl_pct,
                        "pnl": p.get("realized_pnl_eur", 0),
                        "question": p.get("market_question", "")[:50],
                    })

    print(f"\n  Impossible Stop-Loss (< -100%): {len(impossible_sl)}")
    for s in impossible_sl:
        print(f"    {s['position_id']}: {s['side']} entry={s['entry_price']:.3f} "
              f"SL={s['sl_pct']:.1f}% pnl={s['pnl']:+.2f} | {s['question']}")


def analyze_fee_impact(positions):
    """Analyze fee-aware edge computation impact."""
    print("\n" + "=" * 70)
    print("FEE EDGE ASYMMETRY ANALYSIS")
    print("=" * 70)

    latest = {}
    for p in positions:
        latest[p["position_id"]] = p

    # Check how many NO trades would be filtered with correct fee handling
    from core.fee_model import polymarket_taker_fee
    import math

    marginal_no_trades = []
    for p in latest.values():
        edge = p.get("proposal_edge", 0) or 0
        if edge >= 0:
            continue  # Only check NO trades

        side = p.get("side", "")
        if side != "NO":
            continue

        # Reconstruct market price from entry
        entry_price = p.get("entry_price", 0)
        # entry_price is NO price, so YES price ≈ 1 - entry
        yes_price = 1.0 - entry_price
        fee = polymarket_taker_fee(yes_price)

        # Old: net_edge = edge - fee (inflates magnitude)
        old_net = edge - fee
        # New: net_edge = copysign(abs(edge) - fee, edge)
        new_net = math.copysign(abs(edge) - fee, edge) if edge != 0 else 0

        # Check if this trade would fail the 12% threshold with new calculation
        old_passes = abs(old_net) >= 0.12
        new_passes = abs(new_net) >= 0.12

        if old_passes and not new_passes:
            marginal_no_trades.append({
                "position_id": p["position_id"],
                "edge": edge,
                "fee": fee,
                "old_net": old_net,
                "new_net": new_net,
                "pnl": p.get("realized_pnl_eur", 0),
                "question": p.get("market_question", "")[:50],
            })

    print(f"\n  NO trades that would be FILTERED with correct fee:")
    print(f"  {len(marginal_no_trades)} marginal trades removed")
    for t in marginal_no_trades:
        print(f"    edge={t['edge']:+.3f} fee={t['fee']:.4f} "
              f"old_net={t['old_net']:+.3f} new_net={t['new_net']:+.3f} "
              f"pnl={t['pnl']:+.2f} | {t['question']}")


def compute_corrected_metrics(positions, trade_records):
    """Compute corrected win rate and P&L including partial exits."""
    print("\n" + "=" * 70)
    print("CORRECTED PERFORMANCE METRICS")
    print("=" * 70)

    latest = {}
    for p in positions:
        latest[p["position_id"]] = p

    closed = [p for p in latest.values() if p["status"] in ("CLOSED", "RESOLVED")]

    # Accumulate partial exit P&L
    partial_pnl = defaultdict(float)
    if trade_records:
        for r in trade_records:
            if r.get("action") == "PARTIAL_EXIT":
                pid = r.get("position_id", "")
                partial_pnl[pid] += r.get("pnl_eur", 0) or 0

    # Corrected metrics
    corrected_wins = 0
    corrected_losses = 0
    corrected_total_pnl = 0.0
    original_total_pnl = 0.0

    for p in closed:
        pid = p["position_id"]
        recorded_pnl = p.get("realized_pnl_eur", 0) or 0
        true_pnl = recorded_pnl + partial_pnl.get(pid, 0)

        original_total_pnl += recorded_pnl
        corrected_total_pnl += true_pnl

        if true_pnl > 0:
            corrected_wins += 1
        else:
            corrected_losses += 1

    original_wins = sum(1 for p in closed if (p.get("realized_pnl_eur", 0) or 0) > 0)

    print(f"\n  Original win rate:  {original_wins}/{len(closed)} = "
          f"{original_wins / max(1, len(closed)) * 100:.1f}%")
    print(f"  Corrected win rate: {corrected_wins}/{len(closed)} = "
          f"{corrected_wins / max(1, len(closed)) * 100:.1f}%")
    print(f"\n  Original total P&L:  {original_total_pnl:+.2f} EUR")
    print(f"  Corrected total P&L: {corrected_total_pnl:+.2f} EUR")
    print(f"  P&L difference:     {corrected_total_pnl - original_total_pnl:+.2f} EUR")


def analyze_entry_prices(positions):
    """Check entry price reasonableness."""
    print("\n" + "=" * 70)
    print("ENTRY PRICE ANALYSIS")
    print("=" * 70)

    latest = {}
    for p in positions:
        latest[p["position_id"]] = p

    # Check NO positions with very high entry prices (expensive NO)
    expensive_no = []
    for p in latest.values():
        if p["side"] == "NO" and p.get("entry_price", 0) > 0.80:
            expensive_no.append(p)

    print(f"\n  NO positions with entry > 0.80 (very expensive): {len(expensive_no)}")
    for p in sorted(expensive_no, key=lambda x: x.get("entry_price", 0), reverse=True):
        print(f"    entry={p['entry_price']:.3f} edge={p.get('proposal_edge', 0):+.3f} "
              f"pnl={(p.get('realized_pnl_eur') or 0):+.2f} | "
              f"{p.get('market_question', '')[:50]}")

    # Check for model_probability near 0 (model thinks event is impossible)
    low_model = []
    for p in latest.values():
        mp = p.get("model_probability")
        if mp is not None and mp < 0.05:
            low_model.append(p)

    print(f"\n  Positions with model_probability < 5%: {len(low_model)}")
    for p in sorted(low_model, key=lambda x: x.get("model_probability", 1)):
        mp = p.get("model_probability", 0)
        print(f"    model_p={mp:.4f} side={p['side']} entry={p.get('entry_price', 0):.3f} "
              f"edge={p.get('proposal_edge', 0):+.3f} | "
              f"{p.get('market_question', '')[:50]}")


def analyze_capital_reconciliation(positions):
    """Check capital reconciliation."""
    print("\n" + "=" * 70)
    print("CAPITAL RECONCILIATION")
    print("=" * 70)

    latest = {}
    for p in positions:
        latest[p["position_id"]] = p

    total_allocated = 0.0
    total_released = 0.0
    total_pnl = 0.0

    for p in latest.values():
        cost = p.get("cost_basis_eur", 0) or 0
        pnl = p.get("realized_pnl_eur", 0) or 0
        status = p.get("status", "")

        if status == "OPEN":
            total_allocated += cost
        elif status in ("CLOSED", "RESOLVED"):
            total_released += cost
            total_pnl += pnl

    open_positions = [p for p in latest.values() if p["status"] == "OPEN"]

    print(f"\n  Open positions: {len(open_positions)}")
    print(f"  Allocated capital (open): {total_allocated:+.2f} EUR")
    print(f"  Released capital (closed): {total_released:+.2f} EUR")
    print(f"  Total realized P&L: {total_pnl:+.2f} EUR")

    # Load capital config
    capital_path = Path(__file__).parent.parent / "data" / "capital_config.json"
    if capital_path.exists():
        with open(capital_path) as f:
            cap = json.load(f)
        print(f"\n  Capital config:")
        print(f"    initial:   {cap.get('initial_capital_eur', 'N/A')} EUR")
        print(f"    available: {cap.get('available_capital_eur', 'N/A')} EUR")
        print(f"    allocated: {cap.get('allocated_capital_eur', 'N/A')} EUR")
        print(f"    realized:  {cap.get('realized_pnl_eur', 'N/A')} EUR")

        # Check consistency
        initial = cap.get("initial_capital_eur", 0)
        available = cap.get("available_capital_eur", 0)
        allocated = cap.get("allocated_capital_eur", 0)
        realized = cap.get("realized_pnl_eur", 0)

        expected_available = initial + realized - allocated
        diff = available - expected_available
        if abs(diff) > 0.01:
            print(f"\n  CAPITAL MISMATCH: available={available:.2f} "
                  f"expected={expected_available:.2f} diff={diff:+.2f}")
        else:
            print(f"\n  Capital reconciliation: OK")


def main():
    print("=" * 70)
    print("BACKTEST ANALYSIS: ALL 45 TRADES")
    print("=" * 70)

    positions = load_positions()
    trade_records = load_trade_records()

    print(f"\nLoaded {len(positions)} position records")
    print(f"Loaded {len(trade_records)} trade records")

    analyze_side_selection(positions)
    analyze_tp_sl_pnl(positions, trade_records)
    analyze_fee_impact(positions)
    analyze_entry_prices(positions)
    compute_corrected_metrics(positions, trade_records)
    analyze_capital_reconciliation(positions)

    print("\n" + "=" * 70)
    print("BACKTEST COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    main()
