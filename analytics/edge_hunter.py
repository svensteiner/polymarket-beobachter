import json
import logging
from collections import Counter, deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent
LOGS_DIR = PROJECT_ROOT / "logs"
OUTPUT_DIR = PROJECT_ROOT / "output"
PAPER_TRADES_FILE = PROJECT_ROOT / "paper_trader" / "logs" / "paper_trades.jsonl"
GUARDRAIL_AUDIT_FILE = LOGS_DIR / "guardrail_audit.jsonl"


def _read_jsonl_tail(path: Path, limit: int) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    items: deque[Dict[str, Any]] = deque(maxlen=limit)
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    items.append(json.loads(line))
                except Exception:
                    continue
    except Exception as e:
        logger.warning("edge_hunter: failed to read %s: %s", path, e)
        return []
    return list(items)


def _parse_iso(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except Exception:
        return None


def _abs_edge(item: Dict[str, Any]) -> float:
    try:
        return abs(float(item.get("edge", 0.0) or 0.0))
    except Exception:
        return 0.0


def _compact_candidate(item: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "timestamp": item.get("timestamp"),
        "run_id": item.get("run_id"),
        "proposal_id": item.get("proposal_id"),
        "market_id": item.get("market_id"),
        "allowed": item.get("allowed"),
        "reason_code": item.get("reason_code"),
        "shadow_allowed_without_inventory": item.get("shadow_allowed_without_inventory"),
        "city": item.get("city"),
        "confidence_level": item.get("confidence_level"),
        "entry_price": item.get("entry_price"),
        "implied_probability": item.get("implied_probability"),
        "model_probability": item.get("model_probability"),
        "edge": item.get("edge"),
        "market_question": item.get("market_question"),
    }


def build_edge_hunter_report(
    run_id: Optional[str] = None,
    guardrail_tail: int = 5000,
    paper_trades_tail: int = 1500,
    top_n: int = 25,
) -> Dict[str, Any]:
    guardrail = _read_jsonl_tail(GUARDRAIL_AUDIT_FILE, guardrail_tail)
    if run_id:
        guardrail = [g for g in guardrail if g.get("run_id") == run_id]

    paper = _read_jsonl_tail(PAPER_TRADES_FILE, paper_trades_tail)
    if run_id:
        paper = [p for p in paper if p.get("run_id") == run_id]

    guardrail_total = len(guardrail)
    allowed = [g for g in guardrail if g.get("allowed") is True]
    blocked = [g for g in guardrail if g.get("allowed") is False]
    shadow_allowed = [g for g in guardrail if g.get("shadow_allowed_without_inventory") is True]

    blocked_by_reason = Counter((g.get("reason_code") or "unknown") for g in blocked)
    allowed_by_city = Counter((g.get("city") or "unknown") for g in allowed)

    last_guardrail_ts = None
    if guardrail:
        last_guardrail_ts = max((_parse_iso(g.get("timestamp")) for g in guardrail), default=None)

    # Paper trades: actionable blockers (liquidity, price, etc.)
    paper_actions = Counter((p.get("action") or "UNKNOWN") for p in paper)
    skip_reasons = Counter()
    for p in paper:
        if p.get("action") == "SKIP":
            r = str(p.get("reason") or "")
            if "LOW-liquidity" in r or "LOW liquidity" in r or "LOW-liq" in r:
                skip_reasons["low_liquidity"] += 1
            elif "max_entry_price" in r or "max entry" in r or "Entry-Preis" in r:
                skip_reasons["max_entry_price"] += 1
            elif "inventory" in r or "open positions" in r or "inventory_limit" in r:
                skip_reasons["inventory_limit"] += 1
            else:
                skip_reasons["other"] += 1

    last_paper_ts = None
    if paper:
        last_paper_ts = max((_parse_iso(p.get("timestamp")) for p in paper), default=None)

    top_guardrail_allowed = sorted(allowed, key=_abs_edge, reverse=True)[:top_n]
    top_guardrail_blocked = sorted(blocked, key=_abs_edge, reverse=True)[:top_n]
    top_shadow_blocked = sorted(
        [g for g in shadow_allowed if g.get("allowed") is False],
        key=_abs_edge,
        reverse=True,
    )[:top_n]

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "run_id": run_id,
        "inputs": {
            "guardrail_audit_file": str(GUARDRAIL_AUDIT_FILE),
            "paper_trades_file": str(PAPER_TRADES_FILE),
            "guardrail_tail": guardrail_tail,
            "paper_trades_tail": paper_trades_tail,
        },
        "freshness": {
            "last_guardrail_timestamp": last_guardrail_ts.isoformat() if last_guardrail_ts else None,
            "last_paper_trade_timestamp": last_paper_ts.isoformat() if last_paper_ts else None,
        },
        "guardrails": {
            "evaluated": guardrail_total,
            "allowed": len(allowed),
            "blocked": len(blocked),
            "blocked_ratio": (len(blocked) / guardrail_total) if guardrail_total else 0.0,
            "shadow_allowed_without_inventory": len(shadow_allowed),
            "shadow_allowed_ratio_without_inventory": (len(shadow_allowed) / guardrail_total) if guardrail_total else 0.0,
            "blocked_by_reason": dict(blocked_by_reason.most_common(20)),
            "allowed_by_city": dict(allowed_by_city.most_common(20)),
        },
        "paper": {
            "actions": dict(paper_actions),
            "skip_reasons": dict(skip_reasons),
        },
        "top": {
            "guardrail_allowed_by_abs_edge": [_compact_candidate(x) for x in top_guardrail_allowed],
            "guardrail_blocked_by_abs_edge": [_compact_candidate(x) for x in top_guardrail_blocked],
            "shadow_blocked_by_abs_edge": [_compact_candidate(x) for x in top_shadow_blocked],
        },
    }
    return report


def write_edge_hunter_report(run_id: Optional[str] = None) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    report = build_edge_hunter_report(run_id=run_id)
    out = OUTPUT_DIR / "edge_hunter.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return out

