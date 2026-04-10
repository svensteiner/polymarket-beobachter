#!/usr/bin/env python3
"""Backtest analysis of all closed paper trading positions.

Reads paper_positions.jsonl, deduplicates by position_id (latest entry wins),
filters to closed/resolved positions, and produces a structured analysis.

Key insight: NO positions that exited via TP with NEGATIVE P&L were affected
by the _calc_unrealized_pct bug (comparing NO entry price with YES mid-price).
"""

import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from datetime import datetime

# ── Paths ──────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parents[1]
POSITIONS_FILE = BASE_DIR / "paper_trader" / "logs" / "paper_positions.jsonl"
OUTPUT_DIR = BASE_DIR / "output"
OUTPUT_FILE = OUTPUT_DIR / "backtest_results.json"

# ── Bug fix timestamp ─────────────────────────────────────────────────────
# Commit 5156edc: 2026-03-28 21:52:40 +0100
# "fix: correct NO-position unrealized P&L and trailing stop calculation"
# Position exit_times without timezone are in local time (+0100), so we compare
# in local time. Times with +00:00 suffix are handled by stripping the suffix
# and adding 1 hour.
BUG_FIX_TIMESTAMP = "2026-03-28T21:52:40"


def parse_city_date_threshold(question: str) -> dict:
    """Parse market question to extract city, date, and threshold temperature."""
    result = {"city": None, "date": None, "threshold": None}

    # Extract city: "in <City> be" or "in <City Name> be"
    city_match = re.search(r"in\s+(.+?)\s+be\b", question)
    if city_match:
        result["city"] = city_match.group(1).strip()

    # Extract date: "on March 22" etc.
    date_match = re.search(r"on\s+(March\s+\d+)", question)
    if date_match:
        result["date"] = date_match.group(1)

    # Extract threshold temperature
    temp_match = re.search(r"be\s+(between\s+)?(\d+(?:-\d+)?)\s*(?:°|\\u00b0)?\s*([FC])", question)
    if temp_match:
        result["threshold"] = temp_match.group(0).replace("be ", "")

    return result


def is_affected_by_tp_sl_bug(position: dict) -> bool:
    """Determine if a position was affected by the _calc_unrealized_pct bug.

    The bug: for NO positions, _calc_unrealized_pct compared NO entry price
    with YES mid-price directly, instead of converting to NO terms first.
    This caused:
    - NO positions with high entry to show false gains -> false TP triggers
    - NO positions with low entry to show false losses -> false SL triggers

    Detection criteria:
    1. Must be a NO position
    2. Must have exited BEFORE the bug fix (2026-03-28T20:52:40 UTC)
    3. Must have exited via TP with negative actual P&L
       OR exited via SL with impossibly high reported percentage
       (e.g., -340%, -487% which is impossible for real price movement)
    """
    if position.get("side") != "NO":
        return False

    exit_time = position.get("exit_time", "")
    if not exit_time:
        return False

    # Normalize exit_time to local time (+0100) for comparison with BUG_FIX_TIMESTAMP.
    # Some exit_times have "+00:00" (UTC), others have no timezone (local +0100).
    if "+00:00" in exit_time:
        # Convert UTC to local (+0100) by parsing and adding 1 hour
        utc_str = exit_time.replace("+00:00", "")
        try:
            utc_dt = datetime.fromisoformat(utc_str)
            from datetime import timedelta
            local_dt = utc_dt + timedelta(hours=1)
            exit_clean = local_dt.isoformat()
        except ValueError:
            exit_clean = utc_str
    else:
        exit_clean = exit_time.replace("Z", "")

    # Must be before bug fix (both in local time +0100)
    if exit_clean > BUG_FIX_TIMESTAMP:
        return False

    exit_reason = position.get("exit_reason", "")
    realized_pnl = position.get("realized_pnl_eur", 0.0)
    pnl_pct = position.get("pnl_pct", 0.0)

    # Case 1: NO position exited via TP but has negative P&L
    if "TP" in exit_reason and (realized_pnl is not None and realized_pnl < 0):
        return True

    # Case 2: NO position exited via SL with impossibly large percentage
    # Real SL at -35% should not produce -340% or -487% reported unrealized
    if "Stop-Loss" in exit_reason:
        sl_match = re.search(r"Stop-Loss\s*\(([+-]?\d+\.?\d*)%\)", exit_reason)
        if sl_match:
            reported_pct = abs(float(sl_match.group(1)))
            # The configured SL is -35%, so anything beyond ~50% reported
            # unrealized is clearly a bug artifact
            if reported_pct > 50:
                return True

    # Case 3: NO position exited via Trailing-Stop with anomalous behavior
    # (trailing stop price was calculated wrong for NO positions too)
    if "Trailing-Stop" in exit_reason and position.get("side") == "NO":
        # Before the fix, trailing stop for NO was also broken
        # Check if the stop price referenced in the reason matches entry (should not)
        return True

    return False


def load_positions() -> list[dict]:
    """Load all positions from JSONL, deduplicate keeping latest entry per position_id."""
    positions_by_id = {}
    line_numbers_by_id = {}

    with open(POSITIONS_FILE, "r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                pos = json.loads(line)
            except json.JSONDecodeError:
                print(f"  WARNING: Skipping malformed JSON on line {line_num}", file=sys.stderr)
                continue

            pid = pos.get("position_id")
            if pid:
                # Later entries overwrite earlier ones (latest state wins)
                positions_by_id[pid] = pos
                line_numbers_by_id[pid] = line_num

    return list(positions_by_id.values())


def main():
    print("=" * 70)
    print("BACKTEST ANALYSIS - Paper Trading Positions")
    print("=" * 70)

    # Load and deduplicate
    all_positions = load_positions()
    print(f"\nUnique positions (latest state): {len(all_positions)}")

    # Filter to closed/resolved only
    closed_positions = [
        p for p in all_positions
        if p.get("status") in ("CLOSED", "RESOLVED")
        and p.get("exit_time") is not None
        and p.get("exit_reason") is not None
        # Exclude zero-PnL self-heal/model-fix closures that aren't real trades
    ]

    print(f"Closed/resolved positions: {len(closed_positions)}")

    # Build trades list
    trades = []
    for pos in closed_positions:
        question = pos.get("market_question", "")
        parsed = parse_city_date_threshold(question)

        affected = is_affected_by_tp_sl_bug(pos)

        trade = {
            "position_id": pos.get("position_id"),
            "market_id": pos.get("market_id"),
            "city": parsed["city"],
            "question": question,
            "side": pos.get("side"),
            "model_probability": pos.get("model_probability"),
            "entry_price": pos.get("entry_price"),
            "exit_price": pos.get("exit_price"),
            "exit_reason": pos.get("exit_reason"),
            "pnl_eur": pos.get("realized_pnl_eur", 0.0) or 0.0,
            "pnl_pct": pos.get("pnl_pct", 0.0) or 0.0,
            "cost_basis_eur": pos.get("cost_basis_eur"),
            "entry_time": pos.get("entry_time"),
            "exit_time": pos.get("exit_time"),
            "market_type": pos.get("market_type"),
            "affected_by_tp_sl_bug": affected,
        }
        trades.append(trade)

    # Sort by entry_time
    trades.sort(key=lambda t: t.get("entry_time", ""))

    # ── Compute summary statistics ─────────────────────────────────────────
    total_closed = len(trades)

    # Real trades (exclude zero-PnL administrative closures like SELF-HEAL, MODEL_FIX)
    real_trades = [t for t in trades if abs(t["pnl_eur"]) > 0.001]
    admin_closures = [t for t in trades if abs(t["pnl_eur"]) <= 0.001]

    wins = [t for t in real_trades if t["pnl_eur"] > 0]
    losses = [t for t in real_trades if t["pnl_eur"] < 0]
    win_count = len(wins)
    loss_count = len(losses)
    win_rate = (win_count / len(real_trades) * 100) if real_trades else 0.0

    total_pnl = sum(t["pnl_eur"] for t in trades)
    avg_pnl = total_pnl / len(real_trades) if real_trades else 0.0

    yes_positions = [t for t in trades if t["side"] == "YES"]
    no_positions = [t for t in trades if t["side"] == "NO"]

    # NO positions that hit TP with negative P&L (false TP due to bug)
    no_false_tp = [
        t for t in trades
        if t["side"] == "NO"
        and "TP" in (t["exit_reason"] or "")
        and t["pnl_eur"] < 0
    ]

    # NO positions that hit SL with impossibly high percentages (false SL due to bug)
    no_false_sl = []
    for t in trades:
        if t["side"] == "NO" and "Stop-Loss" in (t["exit_reason"] or ""):
            sl_match = re.search(r"Stop-Loss\s*\(([+-]?\d+\.?\d*)%\)", t["exit_reason"] or "")
            if sl_match:
                reported_pct = abs(float(sl_match.group(1)))
                if reported_pct > 50:
                    no_false_sl.append(t)

    # Exit reason counts
    resolution_exits = len([t for t in trades if "resolved" in (t["exit_reason"] or "").lower()])
    tp_exits = len([t for t in trades if "TP" in (t["exit_reason"] or "")])
    sl_exits = len([t for t in trades if "Stop-Loss" in (t["exit_reason"] or "")])
    trailing_exits = len([t for t in trades if "Trailing-Stop" in (t["exit_reason"] or "")])
    self_heal_exits = len([t for t in trades if "SELF-HEAL" in (t["exit_reason"] or "")])
    model_fix_exits = len([t for t in trades if "MODEL_FIX" in (t["exit_reason"] or "")])

    bug_affected_count = len([t for t in trades if t["affected_by_tp_sl_bug"]])

    summary = {
        "total_closed": total_closed,
        "real_trades": len(real_trades),
        "admin_closures": len(admin_closures),
        "wins": win_count,
        "losses": loss_count,
        "win_rate_pct": round(win_rate, 2),
        "total_pnl_eur": round(total_pnl, 4),
        "avg_pnl_eur": round(avg_pnl, 4),
        "avg_win_eur": round(sum(t["pnl_eur"] for t in wins) / win_count, 4) if wins else 0.0,
        "avg_loss_eur": round(sum(t["pnl_eur"] for t in losses) / loss_count, 4) if losses else 0.0,
        "yes_positions": len(yes_positions),
        "no_positions": len(no_positions),
        "no_positions_false_tp": len(no_false_tp),
        "no_positions_false_sl": len(no_false_sl),
        "resolution_exits": resolution_exits,
        "tp_exits": tp_exits,
        "sl_exits": sl_exits,
        "trailing_stop_exits": trailing_exits,
        "self_heal_exits": self_heal_exits,
        "model_fix_exits": model_fix_exits,
        "bug_affected_positions": bug_affected_count,
    }

    # ── Build output ───────────────────────────────────────────────────────
    output = {
        "generated_at": datetime.now(tz=__import__('datetime').timezone.utc).isoformat(),
        "data_source": str(POSITIONS_FILE),
        "bug_fix_commit": "5156edc (2026-03-28T21:52:40+01:00)",
        "bug_description": (
            "_calc_unrealized_pct compared NO entry price with YES mid-price "
            "directly, instead of converting to NO terms (1 - YES). This caused "
            "false TP triggers (with negative actual P&L) and false SL triggers "
            "(with impossibly large reported percentages like -340%, -487%)."
        ),
        "trades": trades,
        "summary": summary,
    }

    # ── Write output ───────────────────────────────────────────────────────
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"\nOutput written to: {OUTPUT_FILE}")

    # ── Print summary ──────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"  Total closed positions:     {total_closed}")
    print(f"    Real trades (non-zero PnL): {len(real_trades)}")
    print(f"    Admin closures (zero PnL):  {len(admin_closures)}")
    print(f"  Wins:                        {win_count}")
    print(f"  Losses:                      {loss_count}")
    print(f"  Win rate:                    {win_rate:.1f}%")
    print(f"  Total P&L:                   {total_pnl:+.4f} EUR")
    print(f"  Avg P&L (real trades):       {avg_pnl:+.4f} EUR")
    if wins:
        print(f"  Avg win:                     {sum(t['pnl_eur'] for t in wins)/win_count:+.4f} EUR")
    if losses:
        print(f"  Avg loss:                    {sum(t['pnl_eur'] for t in losses)/loss_count:+.4f} EUR")

    print(f"\n  YES positions:               {len(yes_positions)}")
    print(f"  NO positions:                {len(no_positions)}")

    print(f"\n  Exit reasons:")
    print(f"    Market resolved:           {resolution_exits}")
    print(f"    Take-Profit (TP):          {tp_exits}")
    print(f"    Stop-Loss (SL):            {sl_exits}")
    print(f"    Trailing-Stop:             {trailing_exits}")
    print(f"    Self-Heal:                 {self_heal_exits}")
    print(f"    Model-Fix:                 {model_fix_exits}")

    print(f"\n  Bug analysis (_calc_unrealized_pct):")
    print(f"    Positions affected by bug: {bug_affected_count}")
    print(f"    NO+TP with negative P&L:   {len(no_false_tp)} (false TP triggers)")
    print(f"    NO+SL with >50% reported:  {len(no_false_sl)} (false SL triggers)")

    # ── Detail: bug-affected trades ────────────────────────────────────────
    if no_false_tp:
        print(f"\n  --- False TP triggers (NO side, TP exit, negative P&L) ---")
        for t in no_false_tp:
            print(f"    {t['position_id']}: {t['exit_reason']}, "
                  f"P&L={t['pnl_eur']:+.2f} EUR ({t['pnl_pct']:+.1f}%), "
                  f"entry={t['entry_price']:.4f}, exit={t['exit_price']:.4f}, "
                  f"city={t['city']}")

    if no_false_sl:
        print(f"\n  --- False SL triggers (NO side, SL with >50% reported) ---")
        for t in no_false_sl:
            print(f"    {t['position_id']}: {t['exit_reason']}, "
                  f"P&L={t['pnl_eur']:+.2f} EUR ({t['pnl_pct']:+.1f}%), "
                  f"entry={t['entry_price']:.4f}, exit={t['exit_price']:.4f}, "
                  f"city={t['city']}")

    # ── Detail: all real trades by P&L ─────────────────────────────────────
    print(f"\n  --- All real trades sorted by P&L ---")
    real_sorted = sorted(real_trades, key=lambda t: t["pnl_eur"], reverse=True)
    for t in real_sorted:
        bug_flag = " [BUG]" if t["affected_by_tp_sl_bug"] else ""
        print(f"    {t['position_id']}: {t['side']:3s} {t['city'] or '?':20s} "
              f"P&L={t['pnl_eur']:+8.2f} EUR ({t['pnl_pct']:+7.1f}%) "
              f"via {t['exit_reason']}{bug_flag}")

    print("\n" + "=" * 70)
    print("DONE")
    print("=" * 70)


if __name__ == "__main__":
    main()
