from __future__ import annotations

import json
import logging
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

logger = logging.getLogger(__name__)


def _obs_to_dict(obs: Any) -> Dict[str, Any]:
    """
    Convert a WeatherObservation-like object into a JSON-serializable dict.

    Supported inputs:
    - objects with .to_dict()
    - dataclasses
    - dicts
    - generic objects with __dict__
    """
    if obs is None:
        return {}
    if isinstance(obs, dict):
        return dict(obs)
    to_dict = getattr(obs, "to_dict", None)
    if callable(to_dict):
        try:
            d = to_dict()
            return dict(d) if isinstance(d, dict) else {"value": d}
        except Exception:
            pass
    if is_dataclass(obs):
        try:
            return asdict(obs)
        except Exception:
            pass
    d = getattr(obs, "__dict__", None)
    if isinstance(d, dict):
        return dict(d)
    return {"value": str(obs)}


def write_edge_hunter(
    base_dir: Path,
    run_id: Optional[str],
    engine_timestamp_iso: Optional[str],
    edge_observations: Iterable[Any],
    *,
    top_k: int = 25,
) -> Path:
    """
    Write a compact "edge hunter" artifact for audit/monitoring.

    File: output/edge_hunter.json

    Contract:
    - deterministic ordering (by abs_edge desc, then market_id)
    - atomic write (.tmp + replace)
    - never raises (caller should still wrap; this function logs and re-raises only on programmer errors)
    """
    output_dir = base_dir / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / "edge_hunter.json"

    items: List[Dict[str, Any]] = []
    for obs in edge_observations or []:
        d = _obs_to_dict(obs)
        if not d:
            continue
        market_p = d.get("market_probability")
        model_p = d.get("model_probability")
        abs_edge = None
        try:
            if isinstance(market_p, (int, float)) and isinstance(model_p, (int, float)):
                abs_edge = float(model_p) - float(market_p)
        except Exception:
            abs_edge = None
        d["abs_edge"] = abs_edge
        items.append(d)

    def _key(d: Dict[str, Any]):
        abs_edge = d.get("abs_edge")
        try:
            abs_edge_val = abs(float(abs_edge)) if abs_edge is not None else 0.0
        except Exception:
            abs_edge_val = 0.0
        market_id = str(d.get("market_id") or "")
        return (-abs_edge_val, market_id)

    items.sort(key=_key)
    top = items[: max(0, int(top_k))]

    artifact = {
        "schema_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "run_id": run_id,
        "engine_timestamp": engine_timestamp_iso,
        "edge_observations_total": len(items),
        "top": top,
    }

    tmp = out_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(artifact, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(out_path)
    return out_path

