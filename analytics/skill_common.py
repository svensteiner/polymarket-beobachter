# =============================================================================
# SHARED HELPERS FOR FORWARD-SKILL REPORTS
# =============================================================================
#
# City extraction, JSONL loading, and market_id dedupe so at_or_below /
# model_city skill scores are not inflated by re-entries on the same market.
# =============================================================================

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

# Longer / multi-word cities first.
_CITY_ALIASES = [
    ("new york city", "New York"),
    ("new york", "New York"),
    ("los angeles", "Los Angeles"),
    ("san francisco", "San Francisco"),
    ("buenos aires", "Buenos Aires"),
    ("mexico city", "Mexico City"),
    ("hong kong", "Hong Kong"),
    ("sao paulo", "Sao Paulo"),
    ("tel aviv", "Tel Aviv"),
]

_CITY_FROM_QUESTION_RE = re.compile(
    r"(?:highest|lowest|high|low)?\s*temperature\s+in\s+([A-Za-z][A-Za-z\s\-']+?)"
    r"\s+be\b",
    re.IGNORECASE,
)


def load_jsonl(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    rows: List[Dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def extract_city_from_question(question: str) -> Optional[str]:
    """Parse city from Polymarket weather question text."""
    if not question:
        return None
    q = str(question)
    lower = q.lower()
    for alias, canonical in _CITY_ALIASES:
        if alias in lower:
            return canonical
    m = _CITY_FROM_QUESTION_RE.search(q)
    if not m:
        return None
    raw = re.sub(r"\s+", " ", m.group(1)).strip(" ,.-")
    if not raw or len(raw) > 40:
        return None
    return raw.title()


def resolve_city(pos: Dict[str, Any]) -> str:
    """Prefer stored city; fall back to question parse; else UNKNOWN."""
    city = pos.get("city")
    if city and str(city).strip() and str(city).strip().upper() != "UNKNOWN":
        return str(city).strip()
    q = pos.get("market_question") or pos.get("question") or ""
    parsed = extract_city_from_question(str(q))
    return parsed or "UNKNOWN"


def dedupe_by_market_id(
    positions: List[Dict[str, Any]],
    *,
    time_keys: tuple = ("entry_time", "timestamp", "opened_at", "created_at"),
) -> List[Dict[str, Any]]:
    """Keep one row per market_id (latest by time key if available)."""
    best: Dict[str, Dict[str, Any]] = {}
    best_ts: Dict[str, str] = {}
    for pos in positions:
        mid = str(pos.get("market_id") or "").strip()
        if not mid:
            continue
        ts = ""
        for key in time_keys:
            val = pos.get(key)
            if val:
                ts = str(val)
                break
        prev_ts = best_ts.get(mid, "")
        if mid not in best or ts >= prev_ts:
            best[mid] = pos
            best_ts[mid] = ts
    return list(best.values())


def gate_progress(n_unique: int, target: int) -> Dict[str, Any]:
    remaining = max(0, int(target) - int(n_unique))
    pct = round(min(1.0, float(n_unique) / float(target)), 4) if target else 0.0
    return {
        "n_unique": int(n_unique),
        "target": int(target),
        "remaining": remaining,
        "progress_pct": pct,
        "ready_for_gate_eval": int(n_unique) >= int(target),
    }
