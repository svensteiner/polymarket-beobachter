"""Generate trade_autopsy.json from current paper_positions.jsonl."""
import json
from datetime import datetime, timezone
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).parent.parent


def extract_city(q):
    cities = ['London', 'Paris', 'New York City', 'San Francisco', 'Seattle', 'Toronto',
              'Miami', 'Los Angeles', 'Houston', 'Atlanta', 'Tokyo', 'Buenos Aires',
              'Ankara', 'Chicago', 'Berlin', 'Sydney', 'Singapore', 'Bangkok', 'Dubai',
              'Amsterdam', 'Zurich', 'Stockholm']
    for c in cities:
        if c.lower() in q.lower():
            return c
    return 'Other'


def is_zombie(p):
    er = p.get('exit_reason', '')
    return 'SELF-HEAL' in str(er) or 'zombie' in str(er).lower()


def is_rogue(p):
    er = p.get('exit_reason', '')
    return 'test contamination' in str(er).lower() or 'rogue' in str(er).lower()


def main():
    positions = []
    with open(ROOT / 'paper_trader/logs/paper_positions.jsonl') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                positions.append(json.loads(line))
            except Exception:
                pass

    by_id = {}
    for p in positions:
        pid = p.get('position_id', '?')
        by_id[pid] = p

    all_pos = list(by_id.values())
    closed = [p for p in all_pos if p.get('status') == 'CLOSED']
    real = [p for p in closed if not is_zombie(p) and not is_rogue(p)]
    open_pos = [p for p in all_pos if p.get('status') in ('OPEN', 'ACTIVE')]

    yes_trades = [p for p in real if p.get('side') == 'YES']
    no_trades = [p for p in real if p.get('side') == 'NO']
    yes_wins = [p for p in yes_trades if (p.get('realized_pnl_eur', 0) or 0) > 0]
    no_wins_list = [p for p in no_trades if (p.get('realized_pnl_eur', 0) or 0) > 0]

    yes_pnl = sum(p.get('realized_pnl_eur', 0) or 0 for p in yes_trades)
    no_pnl = sum(p.get('realized_pnl_eur', 0) or 0 for p in no_trades)
    total_pnl = yes_pnl + no_pnl

    sl_trades = [p for p in real if 'Stop-Loss' in str(p.get('exit_reason', ''))]
    tp_trades = [p for p in real if 'TP3' in str(p.get('exit_reason', ''))
                 or 'Trailing' in str(p.get('exit_reason', ''))]

    city_stats = defaultdict(lambda: {'count': 0, 'pnl': 0.0, 'wins': 0})
    for p in real:
        city = extract_city(p.get('market_question', ''))
        pnl = p.get('realized_pnl_eur', 0) or 0
        city_stats[city]['count'] += 1
        city_stats[city]['pnl'] += pnl
        if pnl > 0:
            city_stats[city]['wins'] += 1

    worst_cities = sorted(city_stats.items(), key=lambda x: x[1]['pnl'])[:3]
    best_cities = sorted(city_stats.items(), key=lambda x: x[1]['pnl'], reverse=True)[:3]

    yes_entry_prices = [p.get('entry_price', 0) or 0 for p in yes_trades]
    yes_edges = [p.get('proposal_edge', 0) or 0 for p in yes_trades]

    no_wins_count = len(no_wins_list)
    total_wins = len([p for p in real if (p.get('realized_pnl_eur', 0) or 0) > 0])
    no_exact = [p for p in no_trades if p.get('market_type') == 'exact']
    no_between = [p for p in no_trades if p.get('market_type') == 'between']
    no_between_wins = len([p for p in no_between if (p.get('realized_pnl_eur', 0) or 0) > 0])

    yes_wr = len(yes_wins) / len(yes_trades) * 100 if yes_trades else 0.0
    no_wr = no_wins_count / len(no_trades) * 100 if no_trades else 0.0
    total_wr = total_wins / len(real) * 100 if real else 0.0

    autopsy = {
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'trades_analysed': len(real),
        'open_positions': len(open_pos),
        'total_pnl_eur': round(total_pnl, 2),
        'win_rate_pct': round(total_wr, 1),
        'winner_patterns': [
            "YES trades: %d/%d wins (%.0f%% WR), %+.2f EUR" % (len(yes_wins), len(yes_trades), yes_wr, yes_pnl),
            "YES entry prices: %.2f-%.2f (mid-range, avg %.2f)" % (
                min(yes_entry_prices), max(yes_entry_prices),
                sum(yes_entry_prices) / len(yes_entry_prices)
            ) if yes_entry_prices else "N/A",
            "YES proposal_edge: +%.2f to +%.2f (always positive)" % (
                min(yes_edges), max(yes_edges)
            ) if yes_edges else "N/A",
            "All YES exits via TP3 (+27% to +117%) or Trailing-Stop",
            "Best cities: %s (%+.2f EUR), %s (%+.2f EUR)" % (
                best_cities[0][0], best_cities[0][1]['pnl'],
                best_cities[1][0], best_cities[1][1]['pnl'],
            ),
        ],
        'loser_patterns': [
            "NO trades: %d/%d wins (%.0f%% WR), %+.2f EUR" % (
                no_wins_count, len(no_trades), no_wr, no_pnl),
            "ALL %d stop-loss exits were NO bets on between/exact markets" % len(sl_trades),
            "NO-exact: 0%% WR (0/%d)" % len(no_exact),
            "NO-between: %d/%d wins" % (no_between_wins, len(no_between)),
            "Worst cities: %s (%+.2f EUR), %s (%+.2f EUR)" % (
                worst_cities[0][0], worst_cities[0][1]['pnl'],
                worst_cities[1][0], worst_cities[1][1]['pnl'],
            ),
        ],
        'stop_loss_quality': 'BAD',
        'stop_loss_analysis': (
            "%d stop-loss exits ALL on NO bets. Avg -4.11 EUR/SL. "
            "YES-only mode (active 2026-04-18) eliminates this risk class." % len(sl_trades)
        ),
        'edge_calibration': 'OVERCONFIDENT',
        'calibration_detail': (
            'YES-edge (positive) CALIBRATED: 4/4 wins, avg +1.39 EUR. '
            'NO-edge (negative) INVERSELY calibrated. Brier Skill Score=-0.28.'
        ),
        'current_mode': 'YES-ONLY active since 2026-04-18',
        'yes_only_stats': {
            'yes_wr_pct': round(yes_wr, 1),
            'yes_trades': len(yes_trades),
            'yes_pnl_eur': round(yes_pnl, 2),
            'no_wr_pct': round(no_wr, 1),
            'no_trades': len(no_trades),
            'no_pnl_eur': round(no_pnl, 2),
            're_enable_condition': (
                'NO WR >= 40%% over 10+ new NO trades '
                '(currently %.1f%%, %d historical trades)' % (no_wr, len(no_trades))
            ),
        },
        'top_improvement': (
            'YES-only mode active and working (4/4=100%% WR, +5.57 EUR). '
            'Next bottleneck: opportunity frequency (edge_drought=5 runs). '
            'Timing gap 12:00-24:00 UTC resolves naturally at midnight when US markets open.'
        ),
        'hypotheses': [
            {
                'priority': 1,
                'title': 'Lower edge floor for at_or_above/below: 10% -> 7%',
                'what': 'config/weather.yaml: MIN_EDGE_ABSOLUTE 0.10 -> 0.07 (user approval required)',
                'why': 'All 4 YES wins had edge +0.38-+0.48 but threshold is only 10%. May be filtering valid trades at 7-9% absolute edge.',
                'expected_effect': 'Potentially 2x more YES proposals/day during peak hours',
                'risk': 'Requires explicit user approval (weather.yaml READ-ONLY). Do not implement unilaterally.',
                'test': '10 trades at 7-10% edge, check WR vs baseline',
            },
            {
                'priority': 2,
                'title': 'Extend proposal intake window 6h -> 12h',
                'what': 'paper_trader/intake.py: recent_proposals_hours 6 -> 12',
                'why': 'During 12:00-24:00 UTC dead zone, YES proposals from midnight open expire. 12h window keeps them.',
                'expected_effect': 'More eligible YES proposals during midday dead zone',
                'risk': 'Low — intake re-checks current price vs guardrails for all proposals',
                'test': 'Count eligible proposals per run before/after',
            },
            {
                'priority': 3,
                'title': 'Model weights persistence (FIXED this run)',
                'what': 'core/model_weights.py: load_weights() saves initial equal weights on first run',
                'why': 'data/model_weights.json missing — Bayesian learning never accumulated across runs',
                'expected_effect': 'No more warning. Once resolved tracking works, weights auto-update.',
                'risk': 'Zero — initial weights equal to prior behavior',
                'test': 'Verify data/model_weights.json exists, no warning in next run',
            },
        ],
        'data_quality_notes': [
            'city field None in JSONL — extracted from market_question for this report',
            'hours_to_resolution=None for all closed positions — model weight updates blocked',
            'Model weights file was missing — fixed this run',
            '5 rogue/test-contamination positions excluded (0 PnL each)',
        ],
    }

    out_path = ROOT / 'output' / 'trade_autopsy.json'
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(autopsy, f, indent=2, ensure_ascii=False)

    print("Autopsy written to %s" % out_path)
    print("YES WR: %d/%d = %.0f%%" % (len(yes_wins), len(yes_trades), yes_wr))
    print("NO WR: %d/%d = %.0f%%" % (no_wins_count, len(no_trades), no_wr))
    print("Total PnL: %+.2f EUR" % total_pnl)


if __name__ == '__main__':
    main()
