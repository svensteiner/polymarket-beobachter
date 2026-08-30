# =============================================================================
# AT_OR_BELOW FORWARD SKILL (model vs market Brier)
# =============================================================================
#
# Historically only at_or_below showed positive forward skill vs market.
# This module scores resolved at_or_below paper positions and writes:
#   analytics/at_or_below_skill.json
#   analytics/at_or_below_skill.md
#
# READ-ONLY regarding trading. Fail-open.
# =============================================================================

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
POSITIONS_PATH = PROJECT_ROOT / "paper_trader" / "logs" / "paper_positions.jsonl"
RESOLUTIONS_PATH = PROJECT_ROOT / "data" / "outcomes" / "resolutions.jsonl"
OUT_JSON = PROJECT_ROOT / "analytics" / "at_or_below_skill.json"
OUT_MD = PROJECT_ROOT / "analytics" / "at_or_below_skill.md"

MIN_N_FOR_CALL = 20


def _brier(p: float, y: int) -> float:
    p = max(0.0, min(1.0, float(p)))
    return (p - float(y)) ** 2


def _load_jsonl(path: Path) -> List[Dict[str, Any]]:
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


def _load_resolutions() -> Dict[str, str]:
    out: Dict[str, str] = {}
    for row in _load_jsonl(RESOLUTIONS_PATH):
        if not row.get("resolved"):
            continue
        res = row.get("resolution")
        mid = str(row.get("market_id") or "")
        if mid and res in ("YES", "NO"):
            out[mid] = res
    return out


def analyse() -> Dict[str, Any]:
    resolutions = _load_resolutions()
    positions = _load_jsonl(POSITIONS_PATH)

    clean: List[Dict[str, Any]] = []
    for pos in positions:
        if (pos.get("market_type") or "") != "at_or_below":
            continue
        mid = str(pos.get("market_id") or "")
        res = resolutions.get(mid)
        if res not in ("YES", "NO"):
            continue
        if pos.get("model_probability") is None or pos.get("entry_price") is None:
            continue
        try:
            model_p_yes = float(pos["model_probability"])
            entry = float(pos["entry_price"])
        except (TypeError, ValueError):
            continue
        side = (pos.get("side") or "YES").upper()
        market_p_yes = entry if side == "YES" else (1.0 - entry)
        y_yes = 1 if res == "YES" else 0
        clean.append(
            {
                "market_id": mid,
                "city": pos.get("city"),
                "side": side,
                "model_p_yes": model_p_yes,
                "market_p_yes": market_p_yes,
                "y_yes": y_yes,
                "model_brier": _brier(model_p_yes, y_yes),
                "market_brier": _brier(market_p_yes, y_yes),
                "pnl_eur": pos.get("realized_pnl_eur"),
            }
        )

    n = len(clean)
    generated = datetime.now(timezone.utc).isoformat()
    if n == 0:
        report: Dict[str, Any] = {
            "generated_at": generated,
            "market_type": "at_or_below",
            "n": 0,
            "status": "NO_DATA",
            "message": (
                "Keine resolved at_or_below Positionen mit "
                "model_probability + Resolution."
            ),
            "live_gate_hint": f"Gate braucht >= {MIN_N_FOR_CALL} Samples",
        }
    else:
        model_brier = sum(r["model_brier"] for r in clean) / n
        market_brier = sum(r["market_brier"] for r in clean) / n
        beats_market = model_brier < market_brier
        delta = market_brier - model_brier
        hits = sum(
            1
            for r in clean
            if (r["model_p_yes"] >= 0.5 and r["y_yes"] == 1)
            or (r["model_p_yes"] < 0.5 and r["y_yes"] == 0)
        )
        mkt_hits = sum(
            1
            for r in clean
            if (r["market_p_yes"] >= 0.5 and r["y_yes"] == 1)
            or (r["market_p_yes"] < 0.5 and r["y_yes"] == 0)
        )
        if beats_market and n >= MIN_N_FOR_CALL:
            hint = "PASS-Kandidat (at_or_below)"
        elif n < MIN_N_FOR_CALL:
            hint = "Noch zu wenig Samples"
        else:
            hint = "Model schlaegt Markt NICHT — kein Forward-Edge"
        report = {
            "generated_at": generated,
            "market_type": "at_or_below",
            "n": n,
            "status": "OK" if n >= MIN_N_FOR_CALL else "INSUFFICIENT_N",
            "model_brier": round(model_brier, 6),
            "market_brier": round(market_brier, 6),
            "brier_delta_market_minus_model": round(delta, 6),
            "model_beats_market": beats_market,
            "model_directional_hit_rate": round(hits / n, 4),
            "market_directional_hit_rate": round(mkt_hits / n, 4),
            "live_gate_hint": hint,
            "samples": clean[:50],
        }

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    OUT_MD.write_text(_render_md(report), encoding="utf-8")
    return report


def _render_md(r: Dict[str, Any]) -> str:
    lines = [
        "# at_or_below Forward Skill",
        "",
        f"Generated: `{r.get('generated_at')}`",
        "",
        f"- n = **{r.get('n')}**",
        f"- Status: **{r.get('status')}**",
    ]
    if r.get("n"):
        better = "Model besser" if r.get("model_beats_market") else "Markt besser"
        lines += [
            f"- Model Brier: **{r.get('model_brier')}**",
            f"- Market Brier: **{r.get('market_brier')}**",
            f"- Delta (market − model): **{r.get('brier_delta_market_minus_model')}** ({better})",
            f"- Model hit-rate: **{r.get('model_directional_hit_rate')}**",
            f"- Market hit-rate: **{r.get('market_directional_hit_rate')}**",
        ]
    lines += ["", f"**Gate:** {r.get('live_gate_hint')}", ""]
    return "\n".join(lines)


def run() -> Dict[str, Any]:
    try:
        return analyse()
    except Exception as e:
        return {"status": "ERROR", "error": str(e)}


if __name__ == "__main__":
    print(json.dumps(run(), indent=2, ensure_ascii=False)[:2500])
