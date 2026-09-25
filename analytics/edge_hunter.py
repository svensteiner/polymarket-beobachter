"""
analytics/edge_hunter.py - Brutaler Edge-/Guardrail-Scanner (READ-ONLY).

Ziel:
- Schnelles Lagebild aus `logs/guardrail_audit.jsonl`
- Keine Strategie-Aenderungen, nur Diagnose-Artefakt:
  `output/edge_hunter.json`

Design-Regeln:
- deterministisch
- fail-closed (bei Fehler: kein Crash der Pipeline)
- begrenzter IO (tail der JSONL statt Vollscan)
"""

from __future__ import annotations

import json
import logging
import statistics
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent
GUARDRAIL_AUDIT = PROJECT_ROOT / "logs" / "guardrail_audit.jsonl"
OUT_FILE = PROJECT_ROOT / "output" / "edge_hunter.json"


def _tail_lines(path: Path, *, max_lines: int = 5000, chunk_size: int = 128 * 1024) -> list[str]:
    if max_lines <= 0:
        return []
    if not path.exists():
        return []

    lines: list[str] = []
    try:
        with open(path, "rb") as handle:
            handle.seek(0, 2)
            file_size = handle.tell()
            pos = file_size
            carry = b""
            while pos > 0 and len(lines) < max_lines:
                read_size = min(chunk_size, pos)
                pos -= read_size
                handle.seek(pos)
                chunk = handle.read(read_size)
                buf = chunk + carry
                parts = buf.split(b"\n")
                carry = parts[0] if pos > 0 else b""
                for raw in reversed(parts[1:] if pos > 0 else parts):
                    if len(lines) >= max_lines:
                        break
                    if not raw:
                        continue
                    lines.append(raw.decode("utf-8", errors="replace"))
    except OSError as exc:
        logger.debug("edge_hunter tail read fehlgeschlagen (%s): %s", path, exc)
        return []

    lines.reverse()
    return lines


def _iter_decisions(lines: Iterable[str]) -> Iterable[dict[str, Any]]:
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            yield data


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _quantiles(values: list[float]) -> dict[str, float]:
    if not values:
        return {}
    values_sorted = sorted(values)

    def _pick(p: float) -> float:
        idx = int(round((len(values_sorted) - 1) * p))
        idx = max(0, min(idx, len(values_sorted) - 1))
        return float(values_sorted[idx])

    return {
        "p05": _pick(0.05),
        "p25": _pick(0.25),
        "p50": _pick(0.50),
        "p75": _pick(0.75),
        "p95": _pick(0.95),
    }


def build_edge_hunter_report(*, max_lines: int = 5000) -> dict[str, Any]:
    lines = _tail_lines(GUARDRAIL_AUDIT, max_lines=max_lines)
    decisions = list(_iter_decisions(lines))

    edges: list[float] = []
    allowed = 0
    blocked = 0
    shadow_allowed = 0
    reason_codes = Counter()
    shadow_reason_codes = Counter()
    confidence = Counter()
    cities = Counter()

    top_shadow: list[dict[str, Any]] = []
    top_edge: list[dict[str, Any]] = []

    for d in decisions:
        if bool(d.get("allowed")):
            allowed += 1
        else:
            blocked += 1

        if bool(d.get("shadow_allowed_without_inventory")):
            shadow_allowed += 1

        reason_codes[str(d.get("reason_code") or "unknown")] += 1
        shadow_reason_codes[str(d.get("shadow_reason_code") or "unknown")] += 1
        confidence[str(d.get("confidence_level") or "UNKNOWN")] += 1

        city = d.get("city")
        if city:
            cities[str(city)] += 1

        edge = _safe_float(d.get("edge"))
        if edge is not None:
            edges.append(edge)

        # Kandidaten: shadow-pass, aber policy-blocked
        if bool(d.get("shadow_allowed_without_inventory")) and not bool(d.get("allowed")):
            e = _safe_float(d.get("edge"))
            if e is not None:
                top_shadow.append(
                    {
                        "timestamp": d.get("timestamp"),
                        "proposal_id": d.get("proposal_id"),
                        "market_id": d.get("market_id"),
                        "city": d.get("city"),
                        "confidence_level": d.get("confidence_level"),
                        "edge": e,
                        "entry_price": _safe_float(d.get("entry_price")),
                        "reason_code": d.get("reason_code"),
                    }
                )

        # Top edges allgemein (egal ob allowed)
        e2 = _safe_float(d.get("edge"))
        if e2 is not None:
            top_edge.append(
                {
                    "timestamp": d.get("timestamp"),
                    "proposal_id": d.get("proposal_id"),
                    "market_id": d.get("market_id"),
                    "city": d.get("city"),
                    "confidence_level": d.get("confidence_level"),
                    "edge": e2,
                    "allowed": bool(d.get("allowed")),
                    "reason_code": d.get("reason_code"),
                }
            )

    top_shadow_sorted = sorted(top_shadow, key=lambda x: float(x.get("edge") or 0.0), reverse=True)[:25]
    top_edge_sorted = sorted(top_edge, key=lambda x: float(x.get("edge") or 0.0), reverse=True)[:25]

    edge_stats: dict[str, Any] = {}
    if edges:
        edge_stats = {
            "count": len(edges),
            "mean": float(statistics.fmean(edges)),
            "median": float(statistics.median(edges)),
            "min": float(min(edges)),
            "max": float(max(edges)),
            "quantiles": _quantiles(edges),
        }

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": str(GUARDRAIL_AUDIT),
        "window": {"max_lines": max_lines, "lines_read": len(lines), "decisions": len(decisions)},
        "counts": {
            "allowed": allowed,
            "blocked": blocked,
            "shadow_allowed_without_inventory": shadow_allowed,
            "blocked_ratio": (blocked / (allowed + blocked)) if (allowed + blocked) else 0.0,
        },
        "edge_stats": edge_stats,
        "breakdown": {
            "reason_code": dict(reason_codes.most_common(25)),
            "shadow_reason_code": dict(shadow_reason_codes.most_common(25)),
            "confidence_level": dict(confidence.most_common(25)),
            "city": dict(cities.most_common(25)),
        },
        "top": {
            "shadow_eligible_but_blocked": top_shadow_sorted,
            "highest_edges": top_edge_sorted,
        },
    }


def write_edge_hunter_report(*, max_lines: int = 5000) -> bool:
    try:
        report = build_edge_hunter_report(max_lines=max_lines)
        OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
        OUT_FILE.write_text(json.dumps(report, indent=2, sort_keys=False), encoding="utf-8")
        return True
    except Exception as exc:
        logger.debug("edge_hunter write fehlgeschlagen (unkritisch): %s", exc)
        return False

