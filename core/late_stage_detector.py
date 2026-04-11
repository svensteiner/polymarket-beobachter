"""Late-Stage YES/NO Detector — Polymarket Weather Strategy.

Strategie-Grundlage (aus signal_darwin.json, 2026-04):
  HIGH confidence + between:     71% Win-Rate (25W/10L)
  HIGH confidence + exact:       74% Win-Rate (20W/7L)
  HIGH confidence + at_or_below: 71% Win-Rate (5W/2L)
  MEDIUM confidence (alle):      11% Win-Rate (1W/8L) <-- VERMEIDEN

Kernidee:
  Wettervorhersagen werden in den letzten 48h vor Aufloesung sehr praezise
  (Sigma-Faktor 0.8 fuer 1-Tag vs 2.0 fuer 10-Tage).
  Wenn der Marktpreis die Wahrscheinlichkeit noch nicht eingepreist hat,
  entsteht ein handelbarer Edge.

Klassifizierung:
  PRIME    (<= 24h, HIGH, edge >= 8%)  — beste Trades
  STRONG   (<= 48h, HIGH, edge >= 8%)  — gute Trades
  MARGINAL (<= 72h, HIGH, edge >= 6%)  — akzeptabel
  SKIP     (MEDIUM/LOW oder edge < 6%) — nicht handeln
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

# ─── Thresholds ───────────────────────────────────────────────────────────────

PRIME_HOURS    = 24.0   # <= 24h bis Aufloesung = PRIME
STRONG_HOURS   = 48.0   # <= 48h                = STRONG
MARGINAL_HOURS = 72.0   # <= 72h                = MARGINAL (=HIGH confidence window)

PRIME_MIN_EDGE    = 0.08
STRONG_MIN_EDGE   = 0.08
MARGINAL_MIN_EDGE = 0.06

# Bonus-Gewichtung: PRIME Trades bekommen hoeheren effective_edge
PRIME_EDGE_BONUS  = 0.10
STRONG_EDGE_BONUS = 0.05

# Welche market_types sind historisch profitabel?
PROFITABLE_TYPES = {"between", "exact", "at_or_below"}
RISKY_TYPES      = {"at_or_above"}   # historisch schlechte Win-Rate

# Erlaubte Confidence-Level
ALLOWED_CONFIDENCE = {"HIGH"}


# ─── Data models ──────────────────────────────────────────────────────────────

@dataclass
class LateStageSignal:
    proposal_id: str
    market_id: str
    market_question: str
    side: str                   # "YES" oder "NO"
    confidence_level: str       # HIGH / MEDIUM / LOW
    market_type: str            # between / exact / at_or_above / at_or_below / unknown
    implied_probability: float
    model_probability: float
    edge: float
    effective_edge: float       # edge + bonus fuer late-stage
    hours_to_resolution: float | None
    stage: str                  # PRIME / STRONG / MARGINAL / SKIP
    skip_reason: str            # leer wenn nicht SKIP
    late_stage_score: float     # 0-100, hoeher = besser

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def is_tradeable(self) -> bool:
        return self.stage != "SKIP"


# ─── Resolution date parser ────────────────────────────────────────────────────

# Patterns fuer Datumsangaben in market_questions
_DATE_PATTERNS = [
    # "April 12", "April 12, 2026"
    r"(?:January|February|March|April|May|June|July|August|September|October|November|December)"
    r"\s+(\d{1,2})(?:,?\s+(\d{4}))?",
    # "12 April", "12 April 2026"
    r"(\d{1,2})\s+(?:January|February|March|April|May|June|July|August|September|October|November|December)"
    r"(?:\s+(\d{4}))?",
    # "2026-04-12"
    r"(\d{4}-\d{2}-\d{2})",
]

_MONTH_MAP = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
}


def _extract_resolution_date(question: str) -> datetime | None:
    """Try to extract a resolution date from market_question text."""
    now = datetime.now(timezone.utc)
    q_lower = question.lower()

    # ISO date pattern
    iso = re.search(r"(\d{4}-\d{2}-\d{2})", question)
    if iso:
        try:
            return datetime.fromisoformat(iso.group(1)).replace(tzinfo=timezone.utc)
        except ValueError:
            pass

    # "Month Day" pattern
    month_day = re.search(
        r"(january|february|march|april|may|june|july|august|"
        r"september|october|november|december)\s+(\d{1,2})",
        q_lower,
    )
    if month_day:
        month = _MONTH_MAP[month_day.group(1)]
        day = int(month_day.group(2))
        year = now.year
        # If the resulting date is in the past, try next year
        candidate = datetime(year, month, day, 20, 0, 0, tzinfo=timezone.utc)
        if candidate < now - __import__("datetime").timedelta(days=1):
            candidate = datetime(year + 1, month, day, 20, 0, 0, tzinfo=timezone.utc)
        return candidate

    return None


def _hours_to_resolution(question: str) -> float | None:
    """Compute hours until market resolution based on question date."""
    res_date = _extract_resolution_date(question)
    if res_date is None:
        return None
    now = datetime.now(timezone.utc)
    diff = (res_date - now).total_seconds() / 3600
    return max(0.0, diff)


# ─── Market type detection ─────────────────────────────────────────────────────

def _detect_market_type(question: str) -> str:
    """Classify market type from question text."""
    q = question.lower()
    if "between" in q:
        return "between"
    if "exactly" in q or "be exactly" in q or re.search(r"\bexact\b", q):
        return "exact"
    if "at or below" in q or "below or at" in q or "<=" in q:
        return "at_or_below"
    if "at or above" in q or "above or at" in q or ">=" in q:
        return "at_or_above"
    return "unknown"


# ─── Main classifier ──────────────────────────────────────────────────────────

def classify_proposal(proposal: dict[str, Any]) -> LateStageSignal:
    """Classify a single proposal for late-stage tradability.

    Args:
        proposal: dict from proposals_log.json (or Proposal.to_dict())

    Returns:
        LateStageSignal with stage and effective_edge
    """
    pid       = proposal.get("proposal_id", "?")
    mid       = proposal.get("market_id", "?")
    question  = proposal.get("market_question", "")
    conf      = proposal.get("confidence_level", "MEDIUM")
    implied   = float(proposal.get("implied_probability", 0.5))
    model     = float(proposal.get("model_probability", 0.5))
    edge      = float(proposal.get("edge", 0.0))  # model - implied
    decision  = proposal.get("decision", "NO_TRADE")

    market_type = _detect_market_type(question)
    hours       = _hours_to_resolution(question)
    abs_edge    = abs(edge)

    # Determine trade side: if edge > 0, YES is underpriced → BUY YES
    side = "YES" if edge > 0 else "NO"

    # --- SKIP checks ---
    skip_reason = ""

    if conf not in ALLOWED_CONFIDENCE:
        skip_reason = f"confidence={conf} (only HIGH allowed)"
    elif decision != "TRADE":
        skip_reason = f"decision={decision}"
    elif market_type in RISKY_TYPES and abs_edge < 0.12:
        skip_reason = f"risky_type={market_type} without premium edge"
    elif implied >= 0.85:
        skip_reason = f"implied={implied:.0%} too high (>85%, at_or_above trap)"
    elif implied <= 0.05:
        skip_reason = f"implied={implied:.0%} too low (<5%, illiquid)"

    if skip_reason:
        return LateStageSignal(
            proposal_id=pid, market_id=mid, market_question=question,
            side=side, confidence_level=conf, market_type=market_type,
            implied_probability=implied, model_probability=model, edge=edge,
            effective_edge=abs_edge, hours_to_resolution=hours,
            stage="SKIP", skip_reason=skip_reason, late_stage_score=0.0,
        )

    # --- Stage classification ---
    if hours is not None and hours <= PRIME_HOURS and abs_edge >= PRIME_MIN_EDGE:
        stage        = "PRIME"
        edge_bonus   = PRIME_EDGE_BONUS
        base_score   = 90.0
    elif hours is not None and hours <= STRONG_HOURS and abs_edge >= STRONG_MIN_EDGE:
        stage        = "STRONG"
        edge_bonus   = STRONG_EDGE_BONUS
        base_score   = 70.0
    elif (hours is None or hours <= MARGINAL_HOURS) and abs_edge >= MARGINAL_MIN_EDGE:
        stage        = "MARGINAL"
        edge_bonus   = 0.0
        base_score   = 40.0
    else:
        stage        = "SKIP"
        skip_reason  = f"edge={abs_edge:.1%} too low or hours={hours} outside window"
        edge_bonus   = 0.0
        base_score   = 0.0

    effective_edge = abs_edge + edge_bonus

    # Score: base + edge bonus + market type bonus + hours bonus
    score = base_score
    score += min(20.0, abs_edge * 100)             # up to +20 for edge size
    if market_type in PROFITABLE_TYPES:
        score += 10.0                               # profitable market type bonus
    if hours is not None:
        score += max(0.0, (MARGINAL_HOURS - hours) / MARGINAL_HOURS * 10)  # closer = better
    score = min(100.0, score)

    return LateStageSignal(
        proposal_id=pid, market_id=mid, market_question=question,
        side=side, confidence_level=conf, market_type=market_type,
        implied_probability=implied, model_probability=model, edge=edge,
        effective_edge=effective_edge, hours_to_resolution=hours,
        stage=stage, skip_reason=skip_reason,
        late_stage_score=round(score, 1),
    )


# ─── Batch classifier ─────────────────────────────────────────────────────────

def get_late_stage_signals(
    proposals: list[dict[str, Any]],
    top_n: int = 10,
) -> list[LateStageSignal]:
    """Classify all proposals and return top tradeable signals.

    Sorted by: PRIME > STRONG > MARGINAL, then by late_stage_score descending.
    """
    stage_order = {"PRIME": 0, "STRONG": 1, "MARGINAL": 2, "SKIP": 3}

    classified = [classify_proposal(p) for p in proposals]
    tradeable  = [s for s in classified if s.is_tradeable]

    tradeable.sort(key=lambda s: (stage_order.get(s.stage, 9), -s.late_stage_score))

    logger.info(
        "[LateStage] %d proposals -> %d PRIME, %d STRONG, %d MARGINAL, %d SKIP",
        len(classified),
        sum(1 for s in classified if s.stage == "PRIME"),
        sum(1 for s in classified if s.stage == "STRONG"),
        sum(1 for s in classified if s.stage == "MARGINAL"),
        sum(1 for s in classified if s.stage == "SKIP"),
    )

    return tradeable[:top_n]


# ─── Convenience: load from proposals_log.json ────────────────────────────────

def load_and_classify(
    proposals_log_path: str | None = None,
    top_n: int = 10,
) -> list[LateStageSignal]:
    """Load proposals from disk and return top late-stage signals."""
    import json
    from pathlib import Path

    path = Path(proposals_log_path or
                "C:/Users/botrunner/projects/polymarket-beobachter/proposals/proposals_log.json")
    if not path.exists():
        logger.warning("[LateStage] proposals_log.json not found at %s", path)
        return []

    try:
        raw = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        proposals = raw if isinstance(raw, list) else raw.get("proposals", [])
    except Exception as exc:
        logger.error("[LateStage] Failed to load proposals: %s", exc)
        return []

    # Only TRADE decisions
    trade_proposals = [p for p in proposals if p.get("decision") == "TRADE"]
    return get_late_stage_signals(trade_proposals, top_n=top_n)
