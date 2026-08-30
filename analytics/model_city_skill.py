# =============================================================================
# MODEL / CITY FORWARD SKILL
# =============================================================================
#
# Breaks at_or_below skill down by:
#   - city (from position.city or question parse)
#   - forecast source (when per_source_probabilities were logged)
#
# Uses paper positions + official resolutions, deduped by market_id.
# Also emits cities_losing_to_market for soft entry blocks.
#
# READ-ONLY for trading. Writes:
#   analytics/model_city_skill.json
#   analytics/model_city_skill.md
# =============================================================================

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

from analytics.skill_common import (
    dedupe_by_market_id,
    gate_progress,
    load_jsonl,
    resolve_city,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
POSITIONS_PATH = PROJECT_ROOT / "paper_trader" / "logs" / "paper_positions.jsonl"
RESOLUTIONS_PATH = PROJECT_ROOT / "data" / "outcomes" / "resolutions.jsonl"
OBS_GLOB_DIRS = [
    PROJECT_ROOT / "logs",
]
OUT_JSON = PROJECT_ROOT / "analytics" / "model_city_skill.json"
OUT_MD = PROJECT_ROOT / "analytics" / "model_city_skill.md"

MIN_N = 5
GATE_TARGET = 20


def _brier(p: float, y: int) -> float:
    p = max(0.0, min(1.0, float(p)))
    return (p - float(y)) ** 2


def _load_resolutions() -> Dict[str, str]:
    out: Dict[str, str] = {}
    for row in load_jsonl(RESOLUTIONS_PATH):
        if not row.get("resolved"):
            continue
        res = row.get("resolution")
        mid = str(row.get("market_id") or "")
        if mid and res in ("YES", "NO"):
            out[mid] = res
    return out


def _load_observations() -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for d in OBS_GLOB_DIRS:
        if not d.exists():
            continue
        for path in sorted(d.glob("weather_observations*.jsonl")):
            rows.extend(load_jsonl(path))
    return rows


def _agg(scores: List[Tuple[float, float, int]]) -> Dict[str, Any]:
    """scores: (model_brier, market_brier, y_yes); market_brier may be -1."""
    n = len(scores)
    if n == 0:
        return {"n": 0}
    model_b = sum(s[0] for s in scores) / n
    market_vals = [s[1] for s in scores if s[1] >= 0]
    market_b = (sum(market_vals) / len(market_vals)) if market_vals else None
    out: Dict[str, Any] = {
        "n": n,
        "model_brier": round(model_b, 6),
    }
    if market_b is not None:
        out["market_brier"] = round(market_b, 6)
        out["model_beats_market"] = model_b < market_b
        out["delta_market_minus_model"] = round(market_b - model_b, 6)
    return out


def analyse(market_type: str = "at_or_below") -> Dict[str, Any]:
    resolutions = _load_resolutions()
    positions = load_jsonl(POSITIONS_PATH)
    observations = _load_observations()

    candidates: List[Dict[str, Any]] = []
    for pos in positions:
        if (pos.get("market_type") or "") != market_type:
            continue
        mid = str(pos.get("market_id") or "")
        res = resolutions.get(mid)
        if res not in ("YES", "NO"):
            continue
        if pos.get("model_probability") is None or pos.get("entry_price") is None:
            continue
        try:
            model_p = float(pos["model_probability"])
            entry = float(pos["entry_price"])
        except (TypeError, ValueError):
            continue
        side = (pos.get("side") or "YES").upper()
        market_p_yes = entry if side == "YES" else (1.0 - entry)
        y_yes = 1 if res == "YES" else 0
        candidates.append(
            {
                **pos,
                "market_id": mid,
                "city": resolve_city(pos),
                "_model_p": model_p,
                "_market_p_yes": market_p_yes,
                "_y_yes": y_yes,
                "_mb": _brier(model_p, y_yes),
                "_kb": _brier(market_p_yes, y_yes),
            }
        )

    n_raw = len(candidates)
    unique_pos = dedupe_by_market_id(candidates)

    by_city: Dict[str, List[Tuple[float, float, int]]] = defaultdict(list)
    overall: List[Tuple[float, float, int]] = []
    for pos in unique_pos:
        city = str(pos.get("city") or "UNKNOWN")
        mb = float(pos["_mb"])
        kb = float(pos["_kb"])
        y_yes = int(pos["_y_yes"])
        by_city[city].append((mb, kb, y_yes))
        overall.append((mb, kb, y_yes))

    by_source: Dict[str, List[Tuple[float, float, int]]] = defaultdict(list)
    by_source_city: Dict[str, Dict[str, List[Tuple[float, float, int]]]] = defaultdict(
        lambda: defaultdict(list)
    )
    latest_obs: Dict[str, Dict[str, Any]] = {}
    for obs in observations:
        mid = str(obs.get("market_id") or "")
        if not mid:
            continue
        psp = obs.get("per_source_probabilities")
        if not isinstance(psp, dict) or not psp:
            continue
        ts = obs.get("timestamp_utc") or ""
        prev = latest_obs.get(mid)
        if prev is None or ts >= (prev.get("timestamp_utc") or ""):
            latest_obs[mid] = obs

    for mid, obs in latest_obs.items():
        res = resolutions.get(mid)
        if res not in ("YES", "NO"):
            continue
        y_yes = 1 if res == "YES" else 0
        city = resolve_city(obs)
        market_p = obs.get("market_probability")
        try:
            market_brier = (
                _brier(float(market_p), y_yes) if market_p is not None else -1.0
            )
        except (TypeError, ValueError):
            market_brier = -1.0
        for source, prob in (obs.get("per_source_probabilities") or {}).items():
            try:
                p = float(prob)
            except (TypeError, ValueError):
                continue
            mb = _brier(p, y_yes)
            by_source[str(source)].append((mb, market_brier, y_yes))
            by_source_city[str(source)][city].append((mb, market_brier, y_yes))

    city_table = {
        city: _agg(scores)
        for city, scores in sorted(by_city.items(), key=lambda kv: -len(kv[1]))
    }
    source_table = {
        src: _agg(scores)
        for src, scores in sorted(by_source.items(), key=lambda kv: -len(kv[1]))
    }
    source_city_table: Dict[str, Dict[str, Any]] = {}
    for src, cities in by_source_city.items():
        source_city_table[src] = {
            city: _agg(scores)
            for city, scores in sorted(cities.items(), key=lambda kv: -len(kv[1]))
            if len(scores) >= 1
        }

    city_winners = [
        {"city": c, **v}
        for c, v in city_table.items()
        if v.get("n", 0) >= MIN_N and v.get("model_beats_market") is True
    ]
    city_losers = [
        {"city": c, **v}
        for c, v in city_table.items()
        if v.get("n", 0) >= MIN_N and v.get("model_beats_market") is False
    ]
    source_winners = [
        {"source": s, **v}
        for s, v in source_table.items()
        if v.get("n", 0) >= MIN_N and v.get("model_beats_market") is True
    ]

    n_unique = len(unique_pos)
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "market_type": market_type,
        "n_raw_rows": n_raw,
        "n_unique_markets": n_unique,
        "overall": _agg(overall),
        "by_city": city_table,
        "by_source": source_table,
        "by_source_city": source_city_table,
        "city_winners_min_n": MIN_N,
        "cities_beating_market": city_winners,
        "cities_losing_to_market": city_losers,
        "sources_beating_market": source_winners,
        "gate_progress": gate_progress(n_unique, GATE_TARGET),
        "notes": [
            "Rows are deduped by market_id (latest entry wins).",
            "City falls back to parsing market_question when city field is empty.",
            "Source skill requires observations with per_source_probabilities "
            "(logged from 2026-08-30 onward) joined to resolutions.",
            "cities_losing_to_market feeds soft entry blocks when enabled.",
        ],
    }

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    OUT_MD.write_text(_render_md(report), encoding="utf-8")
    return report


def _render_md(r: Dict[str, Any]) -> str:
    gp = r.get("gate_progress") or {}
    lines = [
        "# Model / City Forward Skill",
        "",
        f"Generated: `{r.get('generated_at')}`",
        f"Market type: **{r.get('market_type')}**",
        (
            f"Unique markets: **{r.get('n_unique_markets')}** "
            f"(raw rows: {r.get('n_raw_rows')})"
        ),
        (
            f"Gate progress: **{gp.get('n_unique')}/{gp.get('target')}** "
            f"({float(gp.get('progress_pct') or 0) * 100:.1f}%)"
        ),
        "",
        "## Overall",
        "",
        f"```json\n{json.dumps(r.get('overall'), indent=2)}\n```",
        "",
        "## By city (position-based, deduped)",
        "",
    ]
    for city, stats in (r.get("by_city") or {}).items():
        flag = ""
        if stats.get("n", 0) >= MIN_N:
            flag = " ✅" if stats.get("model_beats_market") else " ❌"
        lines.append(
            f"- **{city}**: n={stats.get('n')} model={stats.get('model_brier')} "
            f"market={stats.get('market_brier')}{flag}"
        )
    lines += ["", "## By forecast source (observation-based)", ""]
    sources = r.get("by_source") or {}
    if not sources:
        lines.append(
            "_Noch keine Observations mit `per_source_probabilities` + Resolution._"
        )
    else:
        for src, stats in sources.items():
            flag = ""
            if stats.get("n", 0) >= MIN_N:
                flag = " ✅" if stats.get("model_beats_market") else " ❌"
            lines.append(
                f"- **{src}**: n={stats.get('n')} model={stats.get('model_brier')} "
                f"market={stats.get('market_brier')}{flag}"
            )
    lines += ["", "## Winners / Losers", ""]
    lines.append(
        f"- Cities beating market (n≥{MIN_N}): "
        + (", ".join(c["city"] for c in r.get("cities_beating_market") or []) or "—")
    )
    lines.append(
        f"- Cities losing to market (n≥{MIN_N}): "
        + (", ".join(c["city"] for c in r.get("cities_losing_to_market") or []) or "—")
    )
    lines.append(
        f"- Sources beating market (n≥{MIN_N}): "
        + (", ".join(s["source"] for s in r.get("sources_beating_market") or []) or "—")
    )
    lines.append("")
    return "\n".join(lines)


def run() -> Dict[str, Any]:
    try:
        return analyse()
    except Exception as e:
        return {"status": "ERROR", "error": str(e)}


if __name__ == "__main__":
    print(json.dumps(run(), indent=2, ensure_ascii=False)[:3000])
