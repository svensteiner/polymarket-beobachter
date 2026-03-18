#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SignalDarwin — Darwinistische Gewichtung von Signal-Typen fuer den Polymarket Bot.
===================================================================================

Adaptiert von ContentStrategyDarwin (marketingbot/learning/content_strategy_darwin.py).

Strategien  : Kombinationen aus confidence_level × market_type
              z.B. "HIGH_at_or_above", "MEDIUM_exact", "HIGH_between" usw.
              Plus Catch-All: "HIGH_unknown", "MEDIUM_unknown"

Win-Kriterium: Trade mit realized_pnl_eur > 0

Gewichte:     Kelly-Multiplikatoren (0.3 bis 1.5)
              Startwert: 1.0 fuer alle Strategien

Rebalancing:  Alle 2 Tage, wenn >= MIN_RESULTS_PER_STRATEGY Resultate vorhanden
              Top-Strategie +STEP, Bottom-Strategie -STEP
              Emergency-Degrade: <10% Win-Rate bei >= 5 Trades → sofort auf MIN

Persistenz:   data/signal_darwin.json
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

log = logging.getLogger("SIGNAL_DARWIN")

# ---------------------------------------------------------------------------
# Konfiguration
# ---------------------------------------------------------------------------

STATE_FILE = Path(__file__).resolve().parent.parent / "data" / "signal_darwin.json"

CONFIDENCE_LEVELS = ["HIGH", "MEDIUM"]
MARKET_TYPES = ["exact", "at_or_above", "at_or_below", "between", "unknown"]

# Alle moeglichen Kombinations-Buckets
STRATEGIES: List[str] = [
    f"{conf}_{mtype}"
    for conf in CONFIDENCE_LEVELS
    for mtype in MARKET_TYPES
]

# Gewichts-Grenzen (Kelly-Multiplikatoren)
_WEIGHT_MIN = 0.3
_WEIGHT_MAX = 1.5
_DEFAULT_WEIGHT = 1.0

_STEP_TOP = 0.10       # Bonus fuer beste Strategie pro Rebalancing
_STEP_BOTTOM = 0.10    # Malus fuer schlechteste Strategie

_REBALANCE_INTERVAL_SEC = 2 * 24 * 3600   # 2 Tage
_MIN_RESULTS_PER_STRATEGY = 3              # Minimum Trades fuer Rebalancing
_EMERGENCY_MIN_TRADES = 5                  # Minimum fuer Emergency-Degrade
_EMERGENCY_WIN_RATE = 0.10                 # <10% → sofort degrade


# ---------------------------------------------------------------------------
# Klasse
# ---------------------------------------------------------------------------

class SignalDarwin:
    """Darwinistisches Gewichtungssystem fuer Signal-Typen.

    Jeder Trade gibt Feedback: welcher Signal-Typ (Confidence × Market-Type)
    hat gewonnen oder verloren. Darwin passt die Kelly-Multiplikatoren an.

    Beispiel:
        darwin = SignalDarwin()
        multiplier = darwin.get_multiplier("HIGH", "at_or_above")  # z.B. 1.1
        darwin.record_result("HIGH", "at_or_above", win=True)
        darwin.maybe_rebalance()
    """

    def __init__(self, state_path: Optional[Path] = None):
        self.state_path = state_path or STATE_FILE
        self._state = self._load()

    # ------------------------------------------------------------------
    # Persistenz
    # ------------------------------------------------------------------

    def _load(self) -> dict:
        if self.state_path.exists():
            try:
                with open(self.state_path, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                weights = data.get("weights", {})
                results = data.setdefault("results", {})
                for s in STRATEGIES:
                    weights.setdefault(s, _DEFAULT_WEIGHT)
                    results.setdefault(s, {"wins": 0, "losses": 0})
                data["weights"] = weights
                return data
            except (json.JSONDecodeError, OSError, KeyError) as exc:
                log.warning("Darwin: State-Load fehlgeschlagen (%s), nutze Defaults", exc)

        return {
            "weights": {s: _DEFAULT_WEIGHT for s in STRATEGIES},
            "results": {s: {"wins": 0, "losses": 0} for s in STRATEGIES},
            "last_rebalance_ts": 0.0,
            "rebalance_count": 0,
            "version": 1,
        }

    def _save(self) -> None:
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.state_path.with_suffix(".tmp")
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(self._state, fh, indent=2, ensure_ascii=False)
            tmp.replace(self.state_path)
        except OSError as exc:
            log.error("Darwin: State-Save fehlgeschlagen: %s", exc)

    # ------------------------------------------------------------------
    # Bucket-Mapping
    # ------------------------------------------------------------------

    @staticmethod
    def _bucket(confidence_level: Optional[str], market_type: Optional[str]) -> str:
        """Erstellt Bucket-Key aus Confidence und Market-Type."""
        conf = confidence_level if confidence_level in CONFIDENCE_LEVELS else "MEDIUM"
        mtype = market_type if market_type in MARKET_TYPES else "unknown"
        return f"{conf}_{mtype}"

    # ------------------------------------------------------------------
    # Kernfunktionen
    # ------------------------------------------------------------------

    def record_result(
        self,
        confidence_level: Optional[str],
        market_type: Optional[str],
        win: bool,
    ) -> None:
        """Speichert Trade-Ergebnis fuer einen Signal-Typ.

        Args:
            confidence_level: "HIGH" oder "MEDIUM"
            market_type: "exact", "at_or_above", "at_or_below", "between", "unknown"
            win: True wenn realized_pnl_eur > 0
        """
        try:
            bucket = self._bucket(confidence_level, market_type)
            results = self._state.setdefault("results", {})
            entry = results.setdefault(bucket, {"wins": 0, "losses": 0})
            if win:
                entry["wins"] = entry.get("wins", 0) + 1
            else:
                entry["losses"] = entry.get("losses", 0) + 1
            log.debug("Darwin: record(%s, win=%s) → %s", bucket, win, entry)
            self._save()
        except Exception as exc:
            log.warning("Darwin: record_result fehlgeschlagen: %s", exc)

    def get_multiplier(
        self,
        confidence_level: Optional[str],
        market_type: Optional[str],
    ) -> float:
        """Gibt den aktuellen Kelly-Multiplikator fuer einen Signal-Typ zurueck.

        Args:
            confidence_level: "HIGH" oder "MEDIUM"
            market_type: "exact", "at_or_above", "at_or_below", "between", "unknown"

        Returns:
            Multiplikator zwischen _WEIGHT_MIN und _WEIGHT_MAX (default: 1.0)
        """
        try:
            bucket = self._bucket(confidence_level, market_type)
            w = float(self._state.get("weights", {}).get(bucket, _DEFAULT_WEIGHT))
            return max(_WEIGHT_MIN, min(_WEIGHT_MAX, w))
        except Exception as exc:
            log.warning("Darwin: get_multiplier fehlgeschlagen: %s", exc)
            return _DEFAULT_WEIGHT

    def emergency_degrade(self) -> List[str]:
        """Sofort-Degradierung von Signal-Typen mit katastrophaler Win-Rate.

        Unabhaengig vom Rebalancing: Signal-Typen mit >= _EMERGENCY_MIN_TRADES
        Resultaten und < _EMERGENCY_WIN_RATE Win-Rate → sofort auf _WEIGHT_MIN.

        Returns:
            Liste der degradierten Bucket-Namen
        """
        degraded: List[str] = []
        try:
            results = self._state.get("results", {})
            weights = {s: float(self._state["weights"].get(s, _DEFAULT_WEIGHT)) for s in STRATEGIES}
            changed = False
            for s in STRATEGIES:
                bucket = results.get(s, {})
                total = bucket.get("wins", 0) + bucket.get("losses", 0)
                if total < _EMERGENCY_MIN_TRADES:
                    continue
                win_rate = bucket.get("wins", 0) / total
                if win_rate < _EMERGENCY_WIN_RATE and weights[s] > _WEIGHT_MIN:
                    log.warning(
                        "Darwin: EMERGENCY DEGRADE %s (%.1f%% WR bei %d Trades) → %.1f",
                        s, win_rate * 100, total, _WEIGHT_MIN,
                    )
                    weights[s] = _WEIGHT_MIN
                    degraded.append(s)
                    changed = True
            if changed:
                self._state["weights"] = weights
                self._save()
        except Exception as exc:
            log.warning("Darwin: emergency_degrade fehlgeschlagen: %s", exc)
        return degraded

    def maybe_rebalance(self) -> bool:
        """Fuehrt Rebalancing durch, wenn genug Zeit und Daten vorhanden.

        Logik:
          1. Emergency-Check (sofort, unabhaengig vom Interval)
          2. Pruefe ob >= _REBALANCE_INTERVAL_SEC seit letztem Rebalancing
          3. Pruefe ob alle Strategien >= _MIN_RESULTS_PER_STRATEGY Trades haben
          4. Top-Bucket +_STEP_TOP, Bottom-Bucket -_STEP_BOTTOM
          5. Clamp [_WEIGHT_MIN, _WEIGHT_MAX]

        Returns:
            True wenn Rebalancing durchgefuehrt wurde
        """
        try:
            self.emergency_degrade()

            now = time.time()
            last = float(self._state.get("last_rebalance_ts", 0))
            if now - last < _REBALANCE_INTERVAL_SEC:
                return False

            results = self._state.get("results", {})

            # Pruefe Datenlage — nur Buckets mit genuegend Daten einbeziehen
            eligible: List[Tuple[str, float]] = []
            for s in STRATEGIES:
                bucket = results.get(s, {})
                total = bucket.get("wins", 0) + bucket.get("losses", 0)
                if total < _MIN_RESULTS_PER_STRATEGY:
                    continue
                win_rate = bucket.get("wins", 0) / total
                eligible.append((s, win_rate))

            if len(eligible) < 2:
                log.info("Darwin: Rebalancing verschoben — zu wenig Daten (%d Buckets)", len(eligible))
                return False

            sorted_eligible = sorted(eligible, key=lambda x: x[1], reverse=True)
            top_s, top_wr = sorted_eligible[0]
            bottom_s, bottom_wr = sorted_eligible[-1]

            weights = {s: float(self._state["weights"].get(s, _DEFAULT_WEIGHT)) for s in STRATEGIES}

            if top_s != bottom_s:
                weights[top_s] = min(_WEIGHT_MAX, weights[top_s] + _STEP_TOP)
                weights[bottom_s] = max(_WEIGHT_MIN, weights[bottom_s] - _STEP_BOTTOM)

            self._state["weights"] = weights
            self._state["last_rebalance_ts"] = now
            self._state["rebalance_count"] = self._state.get("rebalance_count", 0) + 1

            log.info(
                "Darwin: Rebalancing #%d | Top=%s(%.1f%% WR +%.0f%%) | "
                "Bottom=%s(%.1f%% WR -%.0f%%)",
                self._state["rebalance_count"],
                top_s, top_wr * 100, _STEP_TOP * 100,
                bottom_s, bottom_wr * 100, _STEP_BOTTOM * 100,
            )
            self._save()
            return True
        except Exception as exc:
            log.warning("Darwin: maybe_rebalance fehlgeschlagen: %s", exc)
            return False

    def get_stats(self) -> dict:
        """Gibt aktuellen Status des Darwin-Systems zurueck."""
        try:
            results = self._state.get("results", {})
            weights = self._state.get("weights", {})

            strategy_stats = {}
            for s in STRATEGIES:
                bucket = results.get(s, {"wins": 0, "losses": 0})
                wins = bucket.get("wins", 0)
                losses = bucket.get("losses", 0)
                total = wins + losses
                if total == 0:
                    continue  # Leere Buckets nicht anzeigen
                strategy_stats[s] = {
                    "weight": round(float(weights.get(s, _DEFAULT_WEIGHT)), 3),
                    "wins": wins,
                    "losses": losses,
                    "total": total,
                    "win_rate": round(wins / total, 3),
                }

            last_ts = float(self._state.get("last_rebalance_ts", 0))
            ago_days = (time.time() - last_ts) / 86400 if last_ts > 0 else None

            return {
                "buckets_with_data": len(strategy_stats),
                "strategies": strategy_stats,
                "rebalance_count": self._state.get("rebalance_count", 0),
                "last_rebalance_ago_days": round(ago_days, 1) if ago_days else None,
                "next_rebalance_in_days": round(
                    max(0, _REBALANCE_INTERVAL_SEC - (time.time() - last_ts)) / 86400, 1
                ) if last_ts > 0 else 2.0,
            }
        except Exception as exc:
            log.warning("Darwin: get_stats fehlgeschlagen: %s", exc)
            return {"error": str(exc)}


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_darwin: Optional[SignalDarwin] = None


def get_darwin() -> SignalDarwin:
    global _darwin
    if _darwin is None:
        _darwin = SignalDarwin()
    return _darwin
