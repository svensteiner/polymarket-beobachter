# =============================================================================
# POLYMARKET BEOBACHTER - PER-CITY FORWARD SKILL TRACKER (model vs MARKET)
# =============================================================================
#
# WHY:
#   forward_validation.py proves the model has no aggregate/per-type edge over
#   the market. But edge could hide in a single CITY where the local forecast is
#   unusually good. This module checks that dimension RIGOROUSLY: per city it
#   computes model-vs-market Brier skill AND a paired significance test on the
#   per-observation Brier differences, so a city is only ever flagged as
#   forward-eligible when its edge is BOTH sizeable and statistically real
#   (n>=MIN, t>2, directional hit-rate advantage) — not a look-elsewhere artefact
#   from scanning ~18 cities.
#
#   READ-ONLY. Writes analytics/city_skill.json + .md. It does NOT itself unblock
#   trading; it is the evidence surface that would justify a per-city gate once a
#   city crosses the significance bar (today: none do — the best, Ankara, is
#   t=0.6, i.e. noise).
# =============================================================================

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUT_JSON = PROJECT_ROOT / "analytics" / "city_skill.json"
OUT_MD = PROJECT_ROOT / "analytics" / "city_skill.md"

DEFAULT_LEAD_HOURS = 24.0
MIN_N_FOR_ELIGIBLE = 50       # minimum resolved markets for a city
MIN_T_FOR_ELIGIBLE = 2.0      # paired t-stat on Brier differences (model better)


def _num(v: Any) -> Optional[float]:
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def _paired_t(diffs: List[float]) -> Optional[float]:
    """Paired t-stat of per-observation (market_sq - model_sq); >0 = model better."""
    n = len(diffs)
    if n < 2:
        return None
    m = sum(diffs) / n
    sd = math.sqrt(sum((d - m) ** 2 for d in diffs) / (n - 1))
    if sd == 0:
        return None
    return m / (sd / math.sqrt(n))


def compute_city_skill(observations: List[Dict[str, Any]],
                       resolutions: Dict[str, int],
                       lead_hours: float = DEFAULT_LEAD_HOURS) -> Dict[str, Any]:
    """Per-city model-vs-market Brier skill + paired significance. Pure."""
    # one observation per resolved market, nearest to lead_hours
    best: Dict[str, Any] = {}
    for o in observations:
        mid = str(o.get("market_id"))
        if mid not in resolutions:
            continue
        h = _num(o.get("hours_to_resolution"))
        mp = _num(o.get("model_probability"))
        kp = _num(o.get("market_probability"))
        if h is None or mp is None or kp is None:
            continue
        dist = abs(h - lead_hours)
        cur = best.get(mid)
        if cur is None or dist < cur[0]:
            best[mid] = (dist, o, mp, kp)

    by_city: Dict[str, Dict[str, Any]] = {}
    for _, o, mp, kp in best.values():
        outcome = resolutions[str(o.get("market_id"))]
        city = str(o.get("city") or "?")
        b = by_city.setdefault(city, {"model_sq": [], "market_sq": [], "diffs": [],
                                       "model_hits": 0, "market_hits": 0, "n": 0})
        b["model_sq"].append((mp - outcome) ** 2)
        b["market_sq"].append((kp - outcome) ** 2)
        b["diffs"].append((kp - outcome) ** 2 - (mp - outcome) ** 2)
        b["model_hits"] += int((mp >= 0.5) == bool(outcome))
        b["market_hits"] += int((kp >= 0.5) == bool(outcome))
        b["n"] += 1

    cities = []
    for city, b in by_city.items():
        n = b["n"]
        mb = sum(b["model_sq"]) / n
        kb = sum(b["market_sq"]) / n
        skill = round(1 - mb / kb, 4) if kb else None
        t = _paired_t(b["diffs"])
        mh = b["model_hits"] / n
        kh = b["market_hits"] / n
        eligible = bool(n >= MIN_N_FOR_ELIGIBLE and t is not None and t > MIN_T_FOR_ELIGIBLE and mh > kh)
        cities.append({
            "city": city, "n": n,
            "model_brier": round(mb, 4), "market_brier": round(kb, 4),
            "skill_vs_market": skill, "t_stat": round(t, 3) if t is not None else None,
            "model_hit_rate": round(mh, 3), "market_hit_rate": round(kh, 3),
            "forward_eligible": eligible,
        })
    cities.sort(key=lambda c: (c["t_stat"] if c["t_stat"] is not None else -99), reverse=True)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "lead_hours": lead_hours,
        "min_n": MIN_N_FOR_ELIGIBLE, "min_t": MIN_T_FOR_ELIGIBLE,
        "cities": cities,
        "eligible_cities": [c["city"] for c in cities if c["forward_eligible"]],
    }


def _render_md(rep: Dict[str, Any]) -> str:
    lines = [
        "# Per-City Forward Skill (Modell vs MARKT, mit Signifikanz)",
        "",
        f"**Generiert:** {rep['generated_at']}  ",
        f"**Eligible-Kriterium:** n≥{rep['min_n']} · paired t>{rep['min_t']} · Modell-Hit > Markt-Hit  ",
        f"**Forward-eligible Städte:** {rep['eligible_cities'] or '— (keine; kein signifikanter Per-City-Edge)'}",
        "",
        "| Stadt | n | model_brier | market_brier | skill | t | mHit | kHit | eligible |",
        "|---|---:|---:|---:|---:|---:|---:|---:|:--:|",
    ]
    for c in rep["cities"]:
        if c["n"] < 20:
            continue
        lines.append(
            f"| {c['city']} | {c['n']} | {c['model_brier']} | {c['market_brier']} | "
            f"{c['skill_vs_market']} | {c['t_stat']} | {c['model_hit_rate']} | "
            f"{c['market_hit_rate']} | {'✅' if c['forward_eligible'] else '·'} |"
        )
    lines += [
        "",
        "**Lesart:** Ein positiver `skill` allein ist beim Scannen vieler Städte "
        "Look-elsewhere-Rauschen. Erst `t>2` (gepaarter Test) + Hit-Rate-Vorteil + n≥50 "
        "belegen echten Per-City-Edge. Solche Städte könnten dann evidenz-gesteuert "
        "freigeschaltet werden — analog zum per-Typ Auto-Unblock.",
        "",
    ]
    return "\n".join(lines)


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)


def run() -> Dict[str, Any]:
    from analytics.forward_validation import load_all_observations, load_resolutions
    rep = compute_city_skill(load_all_observations(full=True), load_resolutions())
    try:
        _atomic_write(OUT_JSON, json.dumps(rep, indent=2, ensure_ascii=False))
        _atomic_write(OUT_MD, _render_md(rep))
    except Exception:
        pass
    return rep


def main() -> None:
    print(json.dumps(run(), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
