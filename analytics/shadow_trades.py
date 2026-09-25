import json
import logging
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT / "data"
LOGS_DIR = PROJECT_ROOT / "logs"
OUTPUT_DIR = PROJECT_ROOT / "output"

GUARDRAIL_AUDIT_FILE = LOGS_DIR / "guardrail_audit.jsonl"
PAPER_TRADES_FILE = PROJECT_ROOT / "paper_trader" / "logs" / "paper_trades.jsonl"
SHADOW_TRADES_FILE = DATA_DIR / "shadow_trades.jsonl"


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
        logger.warning("shadow_trades: failed to read %s: %s", path, e)
        return []
    return list(items)


def _key(proposal_id: Any, market_id: Any) -> Tuple[str, str]:
    return (str(proposal_id or ""), str(market_id or ""))


def backfill_shadow_trades(
    run_id: Optional[str] = None,
    guardrail_tail: int = 10000,
    paper_trades_tail: int = 5000,
    max_append: int = 2000,
) -> Dict[str, Any]:
    """
    Persist "shadow" entries for:
    - guardrail-passed proposals that were SKIPped by the paper trader (e.g., low liquidity)
    - guardrail-shadow-allowed proposals (allowed without inventory), if they were blocked in policy

    This is OBSERVE-ONLY and does not place any orders.
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    guardrail = _read_jsonl_tail(GUARDRAIL_AUDIT_FILE, guardrail_tail)
    if run_id:
        guardrail = [g for g in guardrail if g.get("run_id") == run_id]

    paper = _read_jsonl_tail(PAPER_TRADES_FILE, paper_trades_tail)
    if run_id:
        paper = [p for p in paper if p.get("run_id") == run_id]

    guardrail_by_key: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for g in guardrail:
        guardrail_by_key[_key(g.get("proposal_id"), g.get("market_id"))] = g

    # Load existing shadow ids to avoid duplicates (bounded scan from tail).
    existing_ids = set()
    if SHADOW_TRADES_FILE.exists():
        for row in _read_jsonl_tail(SHADOW_TRADES_FILE, 20000):
            sid = row.get("shadow_id")
            if sid:
                existing_ids.add(str(sid))

    appended = 0
    now = datetime.now(timezone.utc).isoformat()

    def append(entry: Dict[str, Any]) -> None:
        nonlocal appended
        if appended >= max_append:
            return
        sid = str(entry.get("shadow_id") or "")
        if not sid or sid in existing_ids:
            return
        with open(SHADOW_TRADES_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        existing_ids.add(sid)
        appended += 1

    # 1) Guardrail-shadow-allowed but blocked (inventory/policy)
    for g in guardrail:
        if g.get("shadow_allowed_without_inventory") is True and g.get("allowed") is False:
            sid = f"SHADOW-{g.get('run_id','')}-{g.get('proposal_id','')}-{g.get('market_id','')}-policy"
            append(
                {
                    "shadow_id": sid,
                    "timestamp": now,
                    "kind": "POLICY_BLOCKED_BUT_SHADOW_ALLOWED",
                    "run_id": g.get("run_id"),
                    "proposal_id": g.get("proposal_id"),
                    "market_id": g.get("market_id"),
                    "reason_code": g.get("reason_code"),
                    "reason_detail": g.get("reason_detail"),
                    "city": g.get("city"),
                    "confidence_level": g.get("confidence_level"),
                    "entry_price": g.get("entry_price"),
                    "implied_probability": g.get("implied_probability"),
                    "model_probability": g.get("model_probability"),
                    "edge": g.get("edge"),
                    "market_question": g.get("market_question"),
                }
            )

    # 2) Paper SKIPs (captures liquidity/spread/etc. blockers after guardrails)
    for p in paper:
        if p.get("action") != "SKIP":
            continue
        k = _key(p.get("proposal_id"), p.get("market_id"))
        g = guardrail_by_key.get(k, {})
        sid = f"SHADOW-{p.get('run_id','')}-{p.get('proposal_id','')}-{p.get('market_id','')}-skip"
        append(
            {
                "shadow_id": sid,
                "timestamp": now,
                "kind": "PAPER_SKIPPED_ENTRY",
                "run_id": p.get("run_id"),
                "proposal_id": p.get("proposal_id"),
                "market_id": p.get("market_id"),
                "paper_skip_reason": p.get("reason"),
                "snapshot_time": p.get("snapshot_time"),
                "city": g.get("city"),
                "confidence_level": g.get("confidence_level"),
                "entry_price": g.get("entry_price"),
                "implied_probability": g.get("implied_probability"),
                "model_probability": g.get("model_probability"),
                "edge": g.get("edge"),
                "market_question": g.get("market_question"),
            }
        )

    summary = {
        "generated_at": now,
        "run_id": run_id,
        "appended": appended,
        "shadow_trades_file": str(SHADOW_TRADES_FILE),
    }
    # Lightweight "shadow resolution readiness" artifact
    (OUTPUT_DIR / "shadow_resolution_meta.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return summary

