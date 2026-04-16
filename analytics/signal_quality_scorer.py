# =============================================================================
# POLYMARKET BEOBACHTER - SIGNAL QUALITY SCORER
# =============================================================================
#
# PURPOSE:
# Computes a composite quality score (0.0–1.0) for each trade signal before
# entry. Only signals above MIN_QUALITY_SCORE are allowed to enter.
#
# The score integrates five independent quality dimensions:
#   1. Edge magnitude        — how large is the model-vs-market divergence?
#   2. Ensemble agreement    — do all weather models agree?
#   3. Forecast horizon      — is resolution in the NWP sweet-spot (24-72h)?
#   4. Market type           — which market types historically win?
#   5. Confidence level      — what is the engine's confidence rating?
#
# DESIGN PRINCIPLE:
# Each dimension is scored 0.0–1.0 and weighted. A signal must clear the
# overall minimum to qualify. This prevents any single weak dimension from
# being masked by strength in others (and vice versa).
#
# BSS=-0.31 analysis: the primary failure mode was "HIGH confidence" signals
# with moderate edge (10-20%) and medium variance (0.06-0.10). The scorer
# penalises exactly this combination with sub-threshold scores.
#
# =============================================================================

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Minimum acceptable score to enter a trade
# ---------------------------------------------------------------------------
# Reverted 0.72 → 0.62 (2026-04-17): over-hardening caused 0 entries for 12+h.
# Root analysis: hours_to_resolution was always None → neutral h_score 0.55;
# with that default, the 0.72 bar requires >25% abs_edge even in the Goldilocks
# price zone.  0.62 (original threshold) allows Chicago-like signals (16% abs_edge
# at 60% market price) while still blocking noise (<15% abs_edge).
MIN_QUALITY_SCORE: float = 0.62


# ---------------------------------------------------------------------------
# Dimension weights (must sum to 1.0)
# ---------------------------------------------------------------------------
WEIGHT_EDGE: float = 0.30          # Edge: primary alpha source
WEIGHT_ENSEMBLE: float = 0.22
WEIGHT_HORIZON: float = 0.18
WEIGHT_MARKET_TYPE: float = 0.15
WEIGHT_CONFIDENCE: float = 0.05    # Confidence alone is not a proxy for quality
WEIGHT_ENTRY_PRICE: float = 0.10   # NEW: entry price sweet-spot (0.40-0.75 YES zone)


# ---------------------------------------------------------------------------
# Market type historical win-rate scores (from paper trading data)
# 2026-04-16 update: "between"/"exact" are practically blocked via the
# NO-bet rule in simulator.py. Scores reflect YES-bet track record.
# ---------------------------------------------------------------------------
_MARKET_TYPE_SCORE: dict[str, float] = {
    "at_or_above": 0.90,   # 100% YES WR in paper data — strongest signal type
    "at_or_below": 0.90,   # symmetric — similar edge profile to at_or_above
    "exact": 0.20,          # YES volatile, NO blocked → effectively blocked
    "between": 0.10,        # 0% historical WR on NO; YES also unreliable
    "unknown": 0.35,        # default penalty for unclassified markets
}


# ---------------------------------------------------------------------------
# NO-bet penalty multiplier: apply to composite score for NO-direction trades
# Paper data: 0/10 NO bets won (0% WR) vs 5/5 YES bets (100% WR).
# Multiply composite by this factor when side == "NO".
# 0.80 means a NO-bet must score 0.72/0.80 = 0.90 pre-penalty to pass.
# ---------------------------------------------------------------------------
NO_BET_SCORE_MULTIPLIER: float = 0.80

# ---------------------------------------------------------------------------
# YES-Premium Multiplikator für Premiümsignale:
# YES-Bets auf at_or_above/at_or_below mit niedriger Ensemble-Varianz
# und optimalem Horizont (24-72h) erhalten einen Bonus.
# Begründung: 5/5 YES-Bets gewonnen (100% WR) — dies sind unsere
# stärksten und zuverlässigsten Signale.
# ---------------------------------------------------------------------------
YES_PREMIUM_MULTIPLIER: float = 1.08  # +8% Bonus für Premium-YES-Signale
YES_PREMIUM_MARKET_TYPES: frozenset = frozenset({"at_or_above", "at_or_below"})
YES_PREMIUM_MAX_VARIANCE: float = 0.04   # Ensemblevarianz < 4% für Premium
YES_PREMIUM_MIN_HORIZON: float = 24.0    # Mindest-Horizont 24h
YES_PREMIUM_MAX_HORIZON: float = 72.0    # Optimal-Horizont bis 72h


@dataclass
class SignalQualityResult:
    """Result of a signal quality assessment."""

    score: float
    allowed: bool
    reason: str

    # Sub-scores for transparency
    edge_score: float = 0.0
    ensemble_score: float = 0.0
    horizon_score: float = 0.0
    market_type_score: float = 0.0
    confidence_score: float = 0.0
    entry_price_score: float = 0.0  # NEW: entry price sweet-spot
    yes_premium: bool = False       # NEW: YES premium multiplier applied


def _score_edge(edge_abs: float) -> float:
    """
    Score absolute edge magnitude.

    Target range: 0.10 → 0.20+ maps to 0.0 → 1.0.
    Below 0.10: failing score (should not reach here after guardrails).
    Above 0.35: capped at 1.0 (diminishing returns beyond 35% absolute gap).

    Examples:
        0.10 → 0.33   (minimum passing threshold)
        0.15 → 0.55   (moderate edge)
        0.20 → 0.78   (strong edge)
        0.30 → 1.00   (premium edge, capped)
    """
    if edge_abs <= 0:
        return 0.0
    # Linear ramp from 0 at 0.05 to 1.0 at 0.35
    score = (edge_abs - 0.05) / (0.35 - 0.05)
    return float(max(0.0, min(1.0, score)))


def _score_ensemble(variance: Optional[float]) -> float:
    """
    Score ensemble model agreement.

    Low variance = models agree = high quality signal.
    variance=0.00 → 1.00 (perfect agreement)
    variance=0.03 → 0.75 (good)
    variance=0.06 → 0.50 (threshold)
    variance=0.10 → 0.17 (poor)
    variance>=0.15 → 0.00 (rejected)
    """
    if variance is None:
        return 0.60  # neutral when not available
    if variance >= 0.15:
        return 0.0
    score = 1.0 - (variance / 0.15)
    return float(max(0.0, min(1.0, score)))


def _score_horizon(hours_to_resolution: Optional[float]) -> float:
    """
    Score forecast horizon relative to NWP accuracy window.

    NWP models (GFS, ECMWF) have a well-known accuracy profile:
      <6h:   poor (analysis uncertainty)
      6-24h: improving (0.5)
      24-72h: best window (1.0)
      72-96h: still good (0.75)
      >96h:  degrading; >120h essentially noise (0.0)

    Resolution forced to <=96h by simulator, but score here for nuance.
    """
    if hours_to_resolution is None:
        return 0.55  # neutral when unknown

    h = float(hours_to_resolution)
    if h < 6:
        return 0.20
    elif h < 24:
        return 0.50
    elif h <= 48:
        return 1.00   # sweet spot
    elif h <= 72:
        return 0.85
    elif h <= 96:
        return 0.65
    elif h <= 120:
        return 0.35
    else:
        return 0.10


def _score_market_type(market_type: str) -> float:
    """Score based on historical win-rate of this market type."""
    return _MARKET_TYPE_SCORE.get(str(market_type or "unknown").lower(), 0.40)


def _score_confidence(confidence_level: Optional[str]) -> float:
    """Score based on engine confidence rating."""
    mapping = {
        "HIGH": 1.00,
        "MEDIUM": 0.45,
        "LOW": 0.10,
    }
    return mapping.get(str(confidence_level or "").upper(), 0.30)


def _score_entry_price(market_price: Optional[float], is_no_bet: bool) -> float:
    """
    Score based on entry price sweet-spot for YES/NO bets.

    Für YES-Bets: Optimaler Preisbereich 0.40–0.75.
    - Unter 0.40: Markt preist Ereignis als unwahrscheinlich ein → Edge-Signale
      weniger zuverlässig, hohe implizite Volatilität.
    - 0.40–0.75: Maximale Unsicherheit → größtes Potential für Vorhersage-Edge.
    - Über 0.75: Markt fast eingepreist → wenig Spielraum für Gewinn, Slippage
      kostet relativ mehr.

    Für NO-Bets: Gespiegelt — NO-Preis = 1 - YES-Preis.
    """
    if market_price is None:
        return 0.55  # neutral

    p = float(market_price)
    p = max(0.0, min(1.0, p))

    # Für NO-Bets: arbeite mit dem NO-Preis
    if is_no_bet:
        p = 1.0 - p

    # YES-Preisbereich-Scoring
    if p < 0.15:
        return 0.10   # Near-zero: fast sicher NEIN → riskantes Terrain
    elif p < 0.30:
        return 0.35   # Niedrig: Modell-Unsicherheit hoch
    elif p < 0.40:
        return 0.60   # Grenzzone
    elif p <= 0.75:
        return 1.00   # Goldilocks-Zone: maximale Unsicherheit, bestes Edge-Potential
    elif p <= 0.85:
        return 0.70   # Höher als ideal, aber noch akzeptabel
    elif p <= 0.92:
        return 0.40   # Nahe Auflösung: wenig Upside, Slippage-Risiko
    else:
        return 0.15   # >92%: fast sicher JA → minimaler Upside


def compute_signal_quality(
    edge: float,
    ensemble_variance: Optional[float],
    hours_to_resolution: Optional[float],
    market_type: str,
    confidence_level: Optional[str],
    is_no_bet: bool = False,
    market_price: Optional[float] = None,
) -> SignalQualityResult:
    """
    Compute a composite signal quality score (6 Dimensionen).

    Args:
        edge:                 Absolute edge value (model_prob - market_prob).
        ensemble_variance:    Variance across ensemble members (None = unknown).
        hours_to_resolution:  Hours until market resolves (None = unknown).
        market_type:          Market type string ('at_or_above', 'between', etc.)
        confidence_level:     Engine confidence rating ('HIGH', 'MEDIUM', 'LOW').
        is_no_bet:            True if this is a NO-direction bet.
        market_price:         Current YES market price (None = unknown).

    Returns:
        SignalQualityResult with composite score and pass/fail decision.
    """
    edge_abs = abs(float(edge or 0))

    e_score = _score_edge(edge_abs)
    ens_score = _score_ensemble(ensemble_variance)
    h_score = _score_horizon(hours_to_resolution)
    mt_score = _score_market_type(market_type)
    conf_score = _score_confidence(confidence_level)
    ep_score = _score_entry_price(market_price, is_no_bet)

    composite = (
        WEIGHT_EDGE * e_score
        + WEIGHT_ENSEMBLE * ens_score
        + WEIGHT_HORIZON * h_score
        + WEIGHT_MARKET_TYPE * mt_score
        + WEIGHT_CONFIDENCE * conf_score
        + WEIGHT_ENTRY_PRICE * ep_score
    )

    # YES-Premium: Bonus für Premium-YES-Signale (at_or_above/at_or_below,
    # niedrige Varianz, optimaler Horizont 24-72h).
    # Begründung: 5/5 YES-Bets auf diesen Märkten gewonnen (100% WR).
    yes_premium_applied = False
    if (
        not is_no_bet
        and str(market_type).lower() in YES_PREMIUM_MARKET_TYPES
        and (ensemble_variance is None or ensemble_variance <= YES_PREMIUM_MAX_VARIANCE)
        and hours_to_resolution is not None
        and YES_PREMIUM_MIN_HORIZON <= hours_to_resolution <= YES_PREMIUM_MAX_HORIZON
    ):
        composite *= YES_PREMIUM_MULTIPLIER
        yes_premium_applied = True

    # NO-bet penalty: require substantially higher pre-penalty score.
    # Paper data shows 0/10 NO bets won (0% WR). Apply multiplier to
    # raise the effective bar until NO-bet WR exceeds 40% over >=20 trades.
    no_bet_penalty_applied = False
    if is_no_bet:
        composite *= NO_BET_SCORE_MULTIPLIER
        no_bet_penalty_applied = True

    # Cap composite at 1.0 (premium can push above)
    composite = min(1.0, composite)

    allowed = composite >= MIN_QUALITY_SCORE
    no_tag = " [NO-bet penalty]" if no_bet_penalty_applied else ""
    yes_tag = " [YES-premium]" if yes_premium_applied else ""
    reason = (
        f"SQS={composite:.3f}{yes_tag}{no_tag} "
        f"[edge={e_score:.2f} ens={ens_score:.2f} hz={h_score:.2f} "
        f"mt={mt_score:.2f} conf={conf_score:.2f} ep={ep_score:.2f}]"
    )

    if not allowed:
        reason = f"Signal quality below threshold ({composite:.3f} < {MIN_QUALITY_SCORE}): {reason}"
        logger.debug(reason)
    else:
        logger.debug("Signal quality OK: %s", reason)

    return SignalQualityResult(
        score=composite,
        allowed=allowed,
        reason=reason,
        edge_score=e_score,
        ensemble_score=ens_score,
        horizon_score=h_score,
        market_type_score=mt_score,
        confidence_score=conf_score,
        entry_price_score=ep_score,
        yes_premium=yes_premium_applied,
    )


def assess_signal_from_proposal(proposal: Any, market_type: str = "unknown") -> SignalQualityResult:
    """
    Convenience wrapper: extract all fields from a Proposal object.

    Args:
        proposal:    Proposal object (duck-typed).
        market_type: Pre-detected market type string.

    Returns:
        SignalQualityResult
    """
    raw_edge = float(getattr(proposal, "edge", 0) or 0)
    edge = abs(raw_edge)
    variance = getattr(proposal, "ensemble_variance", None)
    hours = getattr(proposal, "hours_to_resolution", None)
    confidence = getattr(proposal, "confidence_level", None)
    # Current YES market price for entry price scoring
    market_price = getattr(proposal, "implied_probability", None)
    # Negative edge = NO bet (model probability < market price)
    is_no_bet = raw_edge < 0

    return compute_signal_quality(
        edge=edge,
        ensemble_variance=variance,
        hours_to_resolution=hours,
        market_type=market_type,
        confidence_level=confidence,
        is_no_bet=is_no_bet,
        market_price=market_price,
    )
