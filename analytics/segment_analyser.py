"""
Segmentanalyse fuer Entry-Qualitaet und Guardrails.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent
POSITIONS_FILE = PROJECT_ROOT / "paper_trader" / "logs" / "paper_positions.jsonl"
OUTPUT_FILE = PROJECT_ROOT / "output" / "segment_analysis.json"


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _extract_city(question: str) -> str:
    match = re.search(r"temperature in ([A-Za-z\s]+?)(?:\s+be|\s+reach|\s+exceed)", question or "", re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return "Unknown"


def _detect_market_type(question: str) -> str:
    q = (question or "").lower()
    if re.search(r"between\s+\d", q):
        return "between"
    if re.search(r"or\s+below|or\s+less|or\s+under|or\s+lower", q):
        return "at_or_below"
    if re.search(r"or\s+above|or\s+higher|or\s+more|or\s+over", q):
        return "at_or_above"
    if re.search(r"\bexactly\s+\d+|\bbe\s+\d+", q):
        return "exact"
    return "unknown"


def _price_band(price: float) -> str:
    if price < 0.10:
        return "0.00-0.10"
    if price < 0.20:
        return "0.10-0.20"
    if price < 0.35:
        return "0.20-0.35"
    if price < 0.50:
        return "0.35-0.50"
    if price < 0.70:
        return "0.50-0.70"
    if price < 0.85:
        return "0.70-0.85"
    return "0.85-1.00"


def _load_latest_position_states() -> List[Dict[str, Any]]:
    if not POSITIONS_FILE.exists():
        return []

    latest: Dict[str, Dict[str, Any]] = {}
    try:
        for raw_line in POSITIONS_FILE.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if payload.get("_type") == "LOG_HEADER":
                continue
            position_id = payload.get("position_id")
            if position_id:
                latest[position_id] = payload
    except OSError as exc:
        logger.debug("Segmentanalyse konnte Positionslog nicht lesen: %s", exc)
    return list(latest.values())


def _summarize_group(items: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    data = list(items)
    trades = len(data)
    wins = sum(1 for item in data if _safe_float(item.get("realized_pnl_eur")) > 0)
    total_pnl = sum(_safe_float(item.get("realized_pnl_eur")) for item in data)
    avg_entry_price = sum(_safe_float(item.get("entry_price")) for item in data) / trades if trades else 0.0
    stop_loss_like = sum(
        1
        for item in data
        if "stop-loss" in str(item.get("exit_reason", "")).lower()
        or "trailing-stop" in str(item.get("exit_reason", "")).lower()
    )
    return {
        "trades": trades,
        "wins": wins,
        "win_rate_pct": round((wins / trades * 100.0) if trades else 0.0, 2),
        "total_pnl_eur": round(total_pnl, 2),
        "avg_entry_price": round(avg_entry_price, 4),
        "stop_loss_ratio": round((stop_loss_like / trades) if trades else 0.0, 3),
    }


def _rank_risky_segments(grouped: Dict[str, List[Dict[str, Any]]], min_trades: int, pnl_cutoff: float) -> List[Dict[str, Any]]:
    risky: List[Dict[str, Any]] = []
    for segment, items in grouped.items():
        summary = _summarize_group(items)
        if summary["trades"] < min_trades:
            continue
        if summary["total_pnl_eur"] > pnl_cutoff:
            continue
        risky.append({"segment": segment, **summary})
    risky.sort(key=lambda item: (item["total_pnl_eur"], item["win_rate_pct"]))
    return risky


def run_segment_analysis() -> Dict[str, Any]:
    positions = _load_latest_position_states()
    closed = [
        item for item in positions
        if str(item.get("status", "")).upper() in {"CLOSED", "RESOLVED", "EXPIRED"}
    ]
    open_positions = [
        item for item in positions
        if str(item.get("status", "")).upper() == "OPEN"
    ]

    by_city: Dict[str, List[Dict[str, Any]]] = {}
    by_price_band: Dict[str, List[Dict[str, Any]]] = {}
    by_market_type: Dict[str, List[Dict[str, Any]]] = {}

    for item in closed:
        question = str(item.get("market_question", ""))
        city = _extract_city(question)
        market_type = _detect_market_type(question)
        band = _price_band(_safe_float(item.get("entry_price")))

        by_city.setdefault(city, []).append(item)
        by_price_band.setdefault(band, []).append(item)
        by_market_type.setdefault(market_type, []).append(item)

    risky_cities = _rank_risky_segments(by_city, min_trades=3, pnl_cutoff=-150.0)
    risky_price_bands = _rank_risky_segments(by_price_band, min_trades=3, pnl_cutoff=-150.0)
    risky_market_types = _rank_risky_segments(by_market_type, min_trades=3, pnl_cutoff=-150.0)

    suggested_max_entry_price = 0.85
    expensive_risk = next((item for item in risky_price_bands if item["segment"] == "0.85-1.00"), None)
    if expensive_risk:
        suggested_max_entry_price = 0.75
    elif any(item["segment"] == "0.70-0.85" for item in risky_price_bands):
        suggested_max_entry_price = 0.80

    analysis = {
        "generated_at": datetime.now().isoformat(),
        "positions_considered": len(closed),
        "open_positions": len(open_positions),
        "segments": {
            "city": {segment: _summarize_group(items) for segment, items in by_city.items()},
            "price_band": {segment: _summarize_group(items) for segment, items in by_price_band.items()},
            "market_type": {segment: _summarize_group(items) for segment, items in by_market_type.items()},
        },
        "risk_flags": {
            "risky_cities": risky_cities[:5],
            "risky_price_bands": risky_price_bands[:5],
            "risky_market_types": risky_market_types[:5],
            "suggested_city_cooldowns": [item["segment"] for item in risky_cities[:3]],
            "suggested_price_band_blocks": [item["segment"] for item in risky_price_bands[:2]],
            "suggested_market_type_cooldowns": [item["segment"] for item in risky_market_types[:2]],
            "suggested_max_entry_price": suggested_max_entry_price,
        },
    }

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(json.dumps(analysis, indent=2, ensure_ascii=False), encoding="utf-8")
    return analysis


def load_latest_analysis() -> Dict[str, Any]:
    if not OUTPUT_FILE.exists():
        return {}
    try:
        return json.loads(OUTPUT_FILE.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.debug("Segmentanalyse nicht lesbar: %s", exc)
        return {}
