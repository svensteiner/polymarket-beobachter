"""
scripts/generate_edge_hunter.py

Erzeugt ein kompaktes Edge-/Blocker-Dashboard fuer die Produktionsreife.

Input (lokal, ohne API Keys):
- logs/guardrail_audit.jsonl
- paper_trader/logs/paper_trades.jsonl

Output:
- output/edge_hunter.json

Ziel: Mehr saubere Opportunity-Abdeckung durch bessere Beobachtbarkeit
ohne Guardrails zu lockern (nur Reporting).
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


PROJECT_ROOT = Path(__file__).parent.parent
AUDIT_FILE = PROJECT_ROOT / "logs" / "guardrail_audit.jsonl"
PAPER_TRADES_FILE = PROJECT_ROOT / "paper_trader" / "logs" / "paper_trades.jsonl"
OUT_FILE = PROJECT_ROOT / "output" / "edge_hunter.json"


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso(ts: str) -> Optional[datetime]:
    try:
        # Python's fromisoformat supports offsets but not trailing Z reliably in older versions.
        if ts.endswith("Z"):
            ts = ts[:-1] + "+00:00"
        return datetime.fromisoformat(ts)
    except Exception:
        return None


def _read_jsonl(path: Path) -> Iterable[Dict[str, Any]]:
    if not path.exists():
        return []
    items: List[Dict[str, Any]] = []
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            if isinstance(obj, dict):
                items.append(obj)
    return items


def _extract_low_liq(trade_reason: str) -> bool:
    if not trade_reason:
        return False
    return "LOW-liquidity" in trade_reason or "LOW-liq" in trade_reason


def _extract_skip_bucket(trade_reason: str) -> str:
    if not trade_reason:
        return "unknown"
    if _extract_low_liq(trade_reason):
        return "low_liquidity"
    if "YES-only mode active" in trade_reason:
        return "yes_only"
    if "NO bet requires" in trade_reason:
        return "no_requires_edge"
    if "city cooldown" in trade_reason:
        return "city_cooldown"
    if "max entry" in trade_reason or "max_entry_price" in trade_reason:
        return "max_entry_price"
    return "other"


def _top_shadow_candidates(decisions: List[Dict[str, Any]], top_n: int = 15) -> List[Dict[str, Any]]:
    """
    Actionable: policy-blocked but shadow-eligible, with positive edge.
    Wir nehmen nur edge>0 (aus Audit) und sortieren nach edge desc.
    """
    candidates: List[Dict[str, Any]] = []
    for d in decisions:
        if d.get("allowed") is True:
            continue
        if not d.get("shadow_allowed_without_inventory"):
            continue
        edge = d.get("edge")
        try:
            edge_val = float(edge)
        except Exception:
            continue
        if edge_val <= 0:
            continue
        candidates.append(
            {
                "timestamp": d.get("timestamp"),
                "run_id": d.get("run_id"),
                "proposal_id": d.get("proposal_id"),
                "market_id": d.get("market_id"),
                "reason_code": d.get("reason_code"),
                "policy_open_positions_count": d.get("policy_open_positions_count"),
                "shadow_reason_code": d.get("shadow_reason_code"),
                "edge": edge_val,
                "implied_probability": d.get("implied_probability"),
                "model_probability": d.get("model_probability"),
                "confidence_level": d.get("confidence_level"),
                "city": d.get("city"),
                "entry_price": d.get("entry_price"),
                "market_question": d.get("market_question"),
            }
        )
    candidates.sort(key=lambda x: x.get("edge", 0.0), reverse=True)
    return candidates[:top_n]


def generate_edge_hunter() -> Dict[str, Any]:
    decisions = list(_read_jsonl(AUDIT_FILE))
    trades = list(_read_jsonl(PAPER_TRADES_FILE))

    # Guardrail decisions: summary + freshness
    reason_counter: Counter[str] = Counter()
    blocked_reason_counter: Counter[str] = Counter()
    shadow_counter: Counter[str] = Counter()
    last_decision_ts: Optional[datetime] = None

    for d in decisions:
        code = str(d.get("reason_code") or "unknown")
        reason_counter[code] += 1
        if not d.get("allowed"):
            blocked_reason_counter[code] += 1
        shadow_code = str(d.get("shadow_reason_code") or "unknown")
        if d.get("shadow_allowed_without_inventory"):
            shadow_counter[shadow_code] += 1
        ts = _parse_iso(str(d.get("timestamp") or ""))
        if ts and (last_decision_ts is None or ts > last_decision_ts):
            last_decision_ts = ts

    # Paper trades: SKIP buckets
    skip_bucket_counter: Counter[str] = Counter()
    total_trades_with_pnl = 0
    pnl_sum = 0.0
    last_trade_ts: Optional[datetime] = None

    for t in trades:
        action = str(t.get("action") or "")
        if action == "SKIP":
            bucket = _extract_skip_bucket(str(t.get("reason") or ""))
            skip_bucket_counter[bucket] += 1
        pnl = t.get("pnl_eur")
        if pnl is not None:
            try:
                pnl_sum += float(pnl)
                total_trades_with_pnl += 1
            except Exception:
                pass
        ts = _parse_iso(str(t.get("timestamp") or ""))
        if ts and (last_trade_ts is None or ts > last_trade_ts):
            last_trade_ts = ts

    report = {
        "generated_at": _utcnow_iso(),
        "inputs": {
            "guardrail_audit_exists": AUDIT_FILE.exists(),
            "paper_trades_exists": PAPER_TRADES_FILE.exists(),
            "guardrail_audit_records": len(decisions),
            "paper_trade_records": len(trades),
        },
        "freshness": {
            "last_guardrail_decision_ts": last_decision_ts.isoformat() if last_decision_ts else None,
            "last_paper_trade_ts": last_trade_ts.isoformat() if last_trade_ts else None,
        },
        "blockers": {
            "guardrails_total_decisions": sum(reason_counter.values()),
            "guardrails_blocked_decisions": sum(blocked_reason_counter.values()),
            "guardrails_top_block_reasons": blocked_reason_counter.most_common(10),
            "paper_skips_by_bucket": skip_bucket_counter.most_common(10),
        },
        "actionable_edge": {
            "shadow_eligible_positive_edge": _top_shadow_candidates(decisions, top_n=15),
        },
        "paper_pnl_snapshot": {
            "pnl_items_count": total_trades_with_pnl,
            "pnl_sum_eur": round(pnl_sum, 6),
        },
        "notes": [
            "Dieses File ist reines Reporting. Es aendert keine Guardrails/Trades.",
            "Actionable Edge = policy-blocked aber shadow-eligible UND edge>0.",
        ],
    }
    return report


def main() -> int:
    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = generate_edge_hunter()
    tmp = OUT_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(OUT_FILE)
    print(f"Wrote {OUT_FILE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

