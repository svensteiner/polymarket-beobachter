# =============================================================================
# CONFIDENCE TRACKER - Adaptive Kelly basierend auf historischer Win-Rate
# =============================================================================
#
# Liest paper_positions.jsonl und berechnet Win-Rate pro:
#   - Confidence-Level (HIGH / MEDIUM)
#   - Market-Type (exact / at_or_above / at_or_below / between)
#
# Gibt Kelly-Multiplikatoren zurueck die Kelly proportional zur
# historischen Genauigkeit skalieren:
#   - Win-Rate 60%+ → Multiplikator 1.2 (mehr Kelly)
#   - Win-Rate 40-60% → Multiplikator 1.0 (Standard)
#   - Win-Rate 20-40% → Multiplikator 0.7 (weniger Kelly)
#   - Win-Rate <20% → Multiplikator 0.4 (stark reduziert)
#
# MINIMUM_SAMPLES = 10 — unter diesem Wert: Standard-Multiplikator
# =============================================================================

import json
import logging
from pathlib import Path
from typing import Dict, Optional

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent.parent
POSITIONS_FILE = BASE_DIR / "paper_trader" / "logs" / "paper_positions.jsonl"
STATS_FILE = BASE_DIR / "data" / "confidence_stats.json"

MINIMUM_SAMPLES = 10  # Weniger als N Trades → kein Adjustment

# Default-Multiplikatoren falls keine Daten
DEFAULTS = {
    "HIGH": 1.2,
    "MEDIUM": 1.0,
    "LOW": 0.5,
}

MARKET_TYPE_DEFAULTS = {
    "exact": 0.8,        # "be X°F" — engste Schwelle, schwerer zu treffen
    "at_or_above": 1.1,  # "above X°F" — breiter
    "at_or_below": 1.1,  # "below X°F" — breiter
    "between": 0.9,      # "between X-Y°F" — mittel
    "unknown": 1.0,
}


def _winrate_to_multiplier(win_rate: float, n: int) -> float:
    """Konvertiert Win-Rate (0-1) in Kelly-Multiplikator."""
    if n < MINIMUM_SAMPLES:
        return 1.0
    if win_rate >= 0.60:
        return 1.2
    if win_rate >= 0.40:
        return 1.0
    if win_rate >= 0.20:
        return 0.7
    return 0.4


def compute_stats() -> Dict:
    """
    Berechnet Win-Rate Statistiken aus dem Position-Log.
    Gibt Dict mit Multiplikatoren pro confidence_level und market_type zurueck.
    """
    if not POSITIONS_FILE.exists():
        return {}

    # Bucketed stats: {key: {"wins": int, "losses": int}}
    by_confidence: Dict[str, Dict] = {}
    by_market_type: Dict[str, Dict] = {}

    try:
        with open(POSITIONS_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    p = json.loads(line)
                except json.JSONDecodeError:
                    continue

                if p.get("status") != "CLOSED":
                    continue

                pnl = p.get("realized_pnl_eur")
                if pnl is None:
                    continue

                is_win = pnl > 0
                conf = p.get("confidence_level")
                mtype = p.get("market_type")

                if conf:
                    if conf not in by_confidence:
                        by_confidence[conf] = {"wins": 0, "losses": 0}
                    if is_win:
                        by_confidence[conf]["wins"] += 1
                    else:
                        by_confidence[conf]["losses"] += 1

                if mtype:
                    if mtype not in by_market_type:
                        by_market_type[mtype] = {"wins": 0, "losses": 0}
                    if is_win:
                        by_market_type[mtype]["wins"] += 1
                    else:
                        by_market_type[mtype]["losses"] += 1

    except Exception as e:
        logger.warning(f"confidence_tracker: Fehler beim Lesen der Positionen: {e}")
        return {}

    # Multiplikatoren berechnen
    confidence_multipliers = {}
    for conf, s in by_confidence.items():
        n = s["wins"] + s["losses"]
        wr = s["wins"] / n if n > 0 else 0.0
        confidence_multipliers[conf] = {
            "win_rate": round(wr, 3),
            "trades": n,
            "multiplier": _winrate_to_multiplier(wr, n),
        }

    market_type_multipliers = {}
    for mtype, s in by_market_type.items():
        n = s["wins"] + s["losses"]
        wr = s["wins"] / n if n > 0 else 0.0
        market_type_multipliers[mtype] = {
            "win_rate": round(wr, 3),
            "trades": n,
            "multiplier": _winrate_to_multiplier(wr, n),
        }

    stats = {
        "by_confidence": confidence_multipliers,
        "by_market_type": market_type_multipliers,
    }

    # Persistieren fuer Dashboard / Strategy Agent
    try:
        STATS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(STATS_FILE, "w", encoding="utf-8") as f:
            json.dump(stats, f, indent=2)
    except Exception as e:
        logger.warning(f"confidence_tracker: Konnte Stats nicht speichern: {e}")

    return stats


def get_kelly_multiplier(
    confidence_level: Optional[str],
    market_type: Optional[str],
) -> float:
    """
    Gibt kombinierten Kelly-Multiplikator basierend auf historischer Accuracy zurueck.

    Nutzt gespeicherte Stats wenn verfuegbar, sonst Defaults.
    Minimum-Samples-Guard: bei zu wenig Daten → 1.0 (kein Adjustment).

    Args:
        confidence_level: "HIGH", "MEDIUM", "LOW" oder None
        market_type: "exact", "at_or_above", "at_or_below", "between", "unknown" oder None

    Returns:
        Multiplikator fuer Kelly-Fraction (0.4 - 1.2)
    """
    # Versuche gespeicherte Stats zu laden
    stats = {}
    if STATS_FILE.exists():
        try:
            with open(STATS_FILE, "r", encoding="utf-8") as f:
                stats = json.load(f)
        except Exception:
            pass

    conf_mult = 1.0
    if confidence_level:
        conf_data = stats.get("by_confidence", {}).get(confidence_level)
        if conf_data and conf_data.get("trades", 0) >= MINIMUM_SAMPLES:
            conf_mult = conf_data["multiplier"]
        else:
            conf_mult = DEFAULTS.get(confidence_level, 1.0)

    type_mult = 1.0
    if market_type:
        type_data = stats.get("by_market_type", {}).get(market_type)
        if type_data and type_data.get("trades", 0) >= MINIMUM_SAMPLES:
            type_mult = type_data["multiplier"]
        else:
            type_mult = MARKET_TYPE_DEFAULTS.get(market_type, 1.0)

    # Kombination: geometrisches Mittel beider Multiplikatoren
    combined = (conf_mult * type_mult) ** 0.5
    # Clamp: 0.3 bis 1.5
    return round(max(0.3, min(1.5, combined)), 3)
