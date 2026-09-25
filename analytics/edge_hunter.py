import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def write_edge_hunter_snapshot(
    *,
    project_root: Path,
    run_id: str,
    output_path: Optional[Path] = None,
    audit_path: Optional[Path] = None,
    top_n: int = 25,
) -> Dict[str, Any]:
    """
    Create a deterministic, audit-friendly snapshot of the strongest 'edge candidates'
    evaluated in a specific run (based on guardrail audit decisions).

    Governance:
    - Read-only analysis; does not influence trading decisions.
    - Best-effort: caller should wrap in try/except.
    - Output is atomic (.tmp + rename).
    """
    if output_path is None:
        output_path = project_root / "output" / "edge_hunter.json"
    if audit_path is None:
        audit_path = project_root / "logs" / "guardrail_audit.jsonl"

    decisions = _load_audit_decisions_for_run(audit_path=audit_path, run_id=run_id)
    snapshot = _build_snapshot(run_id=run_id, decisions=decisions, top_n=top_n)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write_json(output_path, snapshot)
    return snapshot


def _load_audit_decisions_for_run(*, audit_path: Path, run_id: str) -> List[Dict[str, Any]]:
    if not audit_path.exists():
        return []
    out: List[Dict[str, Any]] = []
    with open(audit_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except Exception:
                continue
            if d.get("run_id") == run_id:
                out.append(d)
    return out


def _safe_float(v: Any) -> float:
    try:
        return float(v)
    except Exception:
        return 0.0


def _build_snapshot(*, run_id: str, decisions: List[Dict[str, Any]], top_n: int) -> Dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    allowed = [d for d in decisions if d.get("allowed") is True]
    blocked = [d for d in decisions if d.get("allowed") is False]

    # Deterministic ranking: absolute edge desc, then market_id/proposal_id.
    def rank_key(d: Dict[str, Any]):
        edge = _safe_float(d.get("edge"))
        return (-abs(edge), str(d.get("market_id") or ""), str(d.get("proposal_id") or ""))

    ranked = sorted(decisions, key=rank_key)
    top = ranked[: max(0, int(top_n))]

    def project(d: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "timestamp": d.get("timestamp"),
            "proposal_id": d.get("proposal_id"),
            "market_id": d.get("market_id"),
            "allowed": d.get("allowed"),
            "reason_code": d.get("reason_code"),
            "reason_detail": d.get("reason_detail"),
            "shadow_allowed_without_inventory": d.get("shadow_allowed_without_inventory"),
            "shadow_reason_code": d.get("shadow_reason_code"),
            "shadow_reason_detail": d.get("shadow_reason_detail"),
            "edge": d.get("edge"),
            "implied_probability": d.get("implied_probability"),
            "model_probability": d.get("model_probability"),
            "confidence_level": d.get("confidence_level"),
            "city": d.get("city"),
            "market_question": d.get("market_question"),
        }

    return {
        "schema_version": 1,
        "generated_at": now,
        "run_id": run_id,
        "counts": {
            "evaluated": len(decisions),
            "allowed": len(allowed),
            "blocked": len(blocked),
            "shadow_eligible_without_inventory": sum(
                1 for d in decisions if d.get("shadow_allowed_without_inventory")
            ),
        },
        "top_candidates": [project(d) for d in top],
    }


def _atomic_write_json(path: Path, obj: Dict[str, Any]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    data = json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True)
    tmp.write_text(data, encoding="utf-8")
    os.replace(str(tmp), str(path))

