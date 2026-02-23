# =============================================================================
# FITNESS SCORING
# =============================================================================
#
# Bewertet einen Agenten basierend auf seiner Trade-History.
#
# Composite Score = 0.40 * norm_profit_factor
#                 + 0.30 * win_rate
#                 + 0.20 * calibration_bonus
#                 + 0.10 * activity_bonus
#
# Normierung: Profit Factor wird auf [0,1] normiert (PF=2.0 -> 1.0)
# =============================================================================

from __future__ import annotations

import json
import logging
import math
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)


def _load_positions(positions_file: Path) -> List[Dict[str, Any]]:
    """Lade geschlossene Positionen eines Agenten."""
    if not positions_file.exists():
        return []

    positions_by_id: Dict[str, dict] = {}
    try:
        with open(positions_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    if data.get("_type") == "LOG_HEADER":
                        continue
                    pos_id = data.get("position_id")
                    if pos_id:
                        positions_by_id[pos_id] = data
                except Exception:
                    pass
    except OSError:
        return []

    closed = []
    for pos in positions_by_id.values():
        status = pos.get("status", "")
        pnl = pos.get("realized_pnl_eur")
        if status in ("CLOSED", "RESOLVED") and pnl is not None:
            try:
                pos["realized_pnl_eur"] = float(pnl)
                closed.append(pos)
            except (TypeError, ValueError):
                pass
    return closed


def compute_fitness(agent: "Agent", pipeline_runs: int = 0) -> "AgentFitness":
    """
    Berechne Fitness-Score fuer einen Agenten.

    Args:
        agent: Der zu bewertende Agent
        pipeline_runs: Anzahl Pipeline-Runs seit letztem Reset

    Returns:
        AgentFitness mit allen Metriken
    """
    from evolution.agent import AgentFitness

    positions = _load_positions(agent.positions_file())

    if not positions:
        return AgentFitness(
            pipeline_runs=pipeline_runs,
            computed_at=datetime.now().isoformat(),
            composite_score=0.0,
        )

    pnls = [p["realized_pnl_eur"] for p in positions]
    wins = [x for x in pnls if x > 0]
    losses = [x for x in pnls if x < 0]

    total_pnl = sum(pnls)
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    win_rate = len(wins) / len(pnls) if pnls else 0.0

    if gross_loss > 0:
        profit_factor = gross_profit / gross_loss
    elif gross_profit > 0:
        profit_factor = 5.0  # Cap bei reinen Gewinnen
    else:
        profit_factor = 0.0

    # Brier Score (Kalibrierung)
    brier = _compute_quick_brier(positions)

    # Composite Score berechnen
    composite = _composite_score(
        profit_factor=profit_factor,
        win_rate=win_rate,
        brier_score=brier,
        total_trades=len(pnls),
        pipeline_runs=pipeline_runs,
    )

    return AgentFitness(
        profit_factor=round(profit_factor, 4),
        win_rate=round(win_rate, 4),
        brier_score=round(brier, 4) if brier is not None else None,
        total_pnl_eur=round(total_pnl, 2),
        total_trades=len(pnls),
        pipeline_runs=pipeline_runs,
        composite_score=round(composite, 6),
        computed_at=datetime.now().isoformat(),
    )


def _compute_quick_brier(positions: List[Dict]) -> Optional[float]:
    """Schneller Brier-Score ohne vollstaendige Kalibrierungsanalyse."""
    scored = []
    for pos in positions:
        entry_price = pos.get("entry_price")
        exit_price = pos.get("exit_price")
        if entry_price is None or exit_price is None:
            continue
        if exit_price >= 0.9:
            outcome = 1
        elif exit_price <= 0.1:
            outcome = 0
        else:
            continue
        brier_sq = (entry_price - outcome) ** 2
        scored.append(brier_sq)

    if not scored:
        return None
    return sum(scored) / len(scored)


def _composite_score(
    profit_factor: float,
    win_rate: float,
    brier_score: Optional[float],
    total_trades: int,
    pipeline_runs: int,
) -> float:
    """
    Berechne den Composite Fitness Score.

    Gewichtung:
    - 40%: Profit Factor (normiert auf [0,1], PF=2 -> 0.75)
    - 30%: Win Rate (direkt als [0,1])
    - 20%: Kalibrierungs-Bonus (1 - Brier, oder 0.5 wenn unbekannt)
    - 10%: Aktivitaets-Bonus (mehr Trades = repraesentativer)

    Penalty:
    - Weniger als 5 Trades -> Score * 0.5 (nicht repraesentativ)
    """
    # Profit Factor auf [0,1] normieren: f(x) = x / (x + 1)
    # PF=0 -> 0.0, PF=1 -> 0.5, PF=2 -> 0.67, PF=4 -> 0.8
    norm_pf = profit_factor / (profit_factor + 1.0) if profit_factor >= 0 else 0.0

    # Win Rate direkt
    norm_wr = max(0.0, min(1.0, win_rate))

    # Kalibrierung: 1 - Brier Score (niedriger Brier = besser)
    # Brier Score Bereich [0, 0.25] fuer informative Vorhersagen
    if brier_score is not None:
        calib = max(0.0, 1.0 - brier_score * 4.0)  # BS=0 -> 1.0, BS=0.25 -> 0.0
    else:
        calib = 0.5  # Neutral wenn unbekannt

    # Aktivitaets-Bonus: log-Skala
    # 1 Trade -> 0.2, 5 -> 0.5, 10 -> 0.65, 20 -> 0.77, 50 -> 0.90
    if total_trades > 0:
        activity = math.log(total_trades + 1) / math.log(51)  # normiert auf 50 Trades
        activity = min(1.0, activity)
    else:
        activity = 0.0

    composite = (
        0.40 * norm_pf
        + 0.30 * norm_wr
        + 0.20 * calib
        + 0.10 * activity
    )

    # Penalty bei zu wenig Trades
    if total_trades < 5:
        composite *= 0.5

    return max(0.0, composite)
