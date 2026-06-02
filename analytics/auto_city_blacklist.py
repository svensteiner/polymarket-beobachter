"""
AUTO CITY BLACKLIST
===================

Autonomous city cooldown engine. Reads paper_positions.jsonl, computes win rate
per city over the last N trades, and writes a self-managed cooldown list to
`data/agent_memory/auto_city_cooldowns.json`.

DESIGN GOAL: agentic decision making without manual edits to weather.yaml.
The cooldown file decays over time — a blocked city is re-evaluated after
COOLDOWN_REVIEW_DAYS, so a recovering city un-blocks itself when new trades
demonstrate improvement.

Read by `paper_trader.entry_guardrails` as an additional cooldown source on
top of the human-controlled `agent_policy.cooldown_cities`.

Audit-Trail in `logs/autonomous_decisions.jsonl`.
"""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
from collections import defaultdict
from dataclasses import dataclass, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
POSITIONS_PATH = PROJECT_ROOT / "paper_trader" / "logs" / "paper_positions.jsonl"
OUTPUT_PATH = PROJECT_ROOT / "data" / "agent_memory" / "auto_city_cooldowns.json"
AUDIT_LOG = PROJECT_ROOT / "logs" / "autonomous_decisions.jsonl"

# Decision thresholds. Conservative defaults: a city needs to have proven
# itself bad over multiple trades before we block it.
# 2026-06-02: MIN_TRADES_FOR_VERDICT 3->4. Three-trade verdicts produced
# false positives (1/3 = 33% blocked at threshold 34%) on cities that were
# coin-flip results, choking productivity (Ankara/Atlanta/LA blocked at 1 win
# of 3 trades). Four trades is still thin but rejects pure-luck blocks.
MIN_TRADES_FOR_VERDICT = 4
BLOCK_WIN_RATE_THRESHOLD = 0.34   # below 34% -> blacklist
UNBLOCK_WIN_RATE_THRESHOLD = 0.55  # above 55% on recent trades -> rehab
COOLDOWN_REVIEW_DAYS = 7
LOOKBACK_TRADES_PER_CITY = 10  # use only the most recent N trades per city


@dataclass(frozen=True)
class CityVerdict:
    city: str
    trades: int
    wins: int
    win_rate: float
    total_pnl_eur: float
    blocked: bool
    blocked_since: Optional[str]
    review_after: Optional[str]
    reason: str


def _safe_read_jsonl(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    records: List[Dict[str, Any]] = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError as exc:
        logger.warning("Konnte %s nicht lesen: %s", path, exc)
    return records


_CITY_RE = re.compile(
    r"temperature in ([A-Za-z][A-Za-z\s]+?)\s+(?:be|exceed|reach|"
    r"or above|or below)",
    re.IGNORECASE,
)


def _extract_city(question: str) -> Optional[str]:
    if not question:
        return None
    m = _CITY_RE.search(question)
    return m.group(1).strip() if m else None


def _parse_iso(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts.strip().rstrip("Z"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (ValueError, AttributeError):
        return None


def _atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, sort_keys=True)
        os.replace(tmp, str(path))
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _append_audit(decision: Dict[str, Any]) -> None:
    try:
        AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(AUDIT_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(decision, sort_keys=True) + "\n")
    except OSError as exc:
        logger.debug("Audit-Log schreiben fehlgeschlagen: %s", exc)


def _load_existing() -> Dict[str, Dict[str, Any]]:
    if not OUTPUT_PATH.exists():
        return {}
    try:
        data = json.loads(OUTPUT_PATH.read_text(encoding="utf-8"))
        # Stored as {"cities": {"Miami": {...}}, ...}
        return data.get("cities", {}) if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _verdict_for_city(
    city: str,
    trades: List[Dict[str, Any]],
    existing: Optional[Dict[str, Any]],
) -> CityVerdict:
    """Decide whether to keep blocking, start blocking, or rehabilitate a city."""
    now = datetime.now(timezone.utc)

    # Only consider the most recent N closed trades for this city.
    recent = trades[-LOOKBACK_TRADES_PER_CITY:] if trades else []
    n = len(recent)
    wins = sum(1 for r in recent if float(r.get("realized_pnl_eur") or 0) > 0)
    wr = (wins / n) if n else 0.0
    total_pnl = round(sum(float(r.get("realized_pnl_eur") or 0) for r in recent), 2)

    was_blocked = bool(existing and existing.get("blocked"))
    blocked_since_str = existing.get("blocked_since") if existing else None

    review_after_str = existing.get("review_after") if existing else None
    review_after_dt = _parse_iso(review_after_str)
    review_due = review_after_dt is None or now >= review_after_dt

    # Rehab path: previously blocked, review window passed, recent trades good
    if was_blocked and review_due and n >= MIN_TRADES_FOR_VERDICT and wr >= UNBLOCK_WIN_RATE_THRESHOLD:
        return CityVerdict(
            city=city,
            trades=n,
            wins=wins,
            win_rate=round(wr, 3),
            total_pnl_eur=total_pnl,
            blocked=False,
            blocked_since=None,
            review_after=None,
            reason=(
                f"REHABILITATED: WR {wr:.0%} >= {UNBLOCK_WIN_RATE_THRESHOLD:.0%} "
                f"ueber {n} aktuelle Trades"
            ),
        )

    # Block path: not enough wins
    if n >= MIN_TRADES_FOR_VERDICT and wr < BLOCK_WIN_RATE_THRESHOLD:
        new_block_since = blocked_since_str if was_blocked else now.isoformat()
        new_review = (now + timedelta(days=COOLDOWN_REVIEW_DAYS)).isoformat()
        return CityVerdict(
            city=city,
            trades=n,
            wins=wins,
            win_rate=round(wr, 3),
            total_pnl_eur=total_pnl,
            blocked=True,
            blocked_since=new_block_since,
            review_after=new_review,
            reason=(
                f"BLOCK: WR {wr:.0%} < {BLOCK_WIN_RATE_THRESHOLD:.0%} "
                f"ueber {n} Trades, P&L {total_pnl:+.2f} EUR"
            ),
        )

    # Block stays during review window even if WR can't be re-evaluated yet
    if was_blocked and not review_due:
        return CityVerdict(
            city=city,
            trades=n,
            wins=wins,
            win_rate=round(wr, 3),
            total_pnl_eur=total_pnl,
            blocked=True,
            blocked_since=blocked_since_str,
            review_after=review_after_str,
            reason="BLOCK CONTINUED: Review-Fenster noch nicht abgelaufen",
        )

    # Default: free
    return CityVerdict(
        city=city,
        trades=n,
        wins=wins,
        win_rate=round(wr, 3),
        total_pnl_eur=total_pnl,
        blocked=False,
        blocked_since=None,
        review_after=None,
        reason=f"OK: {n} Trades, WR {wr:.0%} (ueber Schwelle)",
    )


def evaluate_and_persist() -> Dict[str, Any]:
    """Recompute the auto cooldown set and persist atomically."""
    raw = _safe_read_jsonl(POSITIONS_PATH)
    # Last state per position
    by_pid: Dict[str, Dict[str, Any]] = {}
    for rec in raw:
        pid = rec.get("position_id")
        if pid:
            by_pid[pid] = rec
    closed = [
        p for p in by_pid.values()
        if (p.get("status") or "").upper() in ("CLOSED", "RESOLVED")
    ]
    closed.sort(
        key=lambda p: _parse_iso(p.get("exit_time"))
        or datetime.min.replace(tzinfo=timezone.utc)
    )

    trades_by_city: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for rec in closed:
        city = _extract_city(rec.get("market_question") or "")
        if not city:
            # Fallback to explicit city field
            city = rec.get("city")
        if not city:
            continue
        trades_by_city[city].append(rec)

    existing = _load_existing()
    verdicts: Dict[str, CityVerdict] = {}
    changes: List[Dict[str, Any]] = []

    seen = set()
    for city, trades in trades_by_city.items():
        seen.add(city)
        prev = existing.get(city)
        v = _verdict_for_city(city, trades, prev)
        verdicts[city] = v
        prev_blocked = bool(prev and prev.get("blocked"))
        if v.blocked != prev_blocked:
            changes.append(
                {
                    "city": city,
                    "from": "BLOCKED" if prev_blocked else "FREE",
                    "to": "BLOCKED" if v.blocked else "FREE",
                    "win_rate": v.win_rate,
                    "trades": v.trades,
                    "total_pnl_eur": v.total_pnl_eur,
                    "reason": v.reason,
                }
            )

    # Keep already-blocked cities even if no recent trades, until review expires
    for city, prev in existing.items():
        if city in seen:
            continue
        review_dt = _parse_iso(prev.get("review_after"))
        if prev.get("blocked") and review_dt and datetime.now(timezone.utc) < review_dt:
            verdicts[city] = CityVerdict(
                city=city,
                trades=0,
                wins=0,
                win_rate=0.0,
                total_pnl_eur=0.0,
                blocked=True,
                blocked_since=prev.get("blocked_since"),
                review_after=prev.get("review_after"),
                reason="BLOCK KEPT: keine neuen Trades, Review-Fenster offen",
            )

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "min_trades_for_verdict": MIN_TRADES_FOR_VERDICT,
        "block_win_rate_threshold": BLOCK_WIN_RATE_THRESHOLD,
        "unblock_win_rate_threshold": UNBLOCK_WIN_RATE_THRESHOLD,
        "cooldown_review_days": COOLDOWN_REVIEW_DAYS,
        "lookback_trades_per_city": LOOKBACK_TRADES_PER_CITY,
        "cities": {city: asdict(v) for city, v in verdicts.items()},
        "blocked_cities": sorted(
            [v.city for v in verdicts.values() if v.blocked]
        ),
        "governance_notice": (
            "Autonomously managed city cooldown. Read by entry_guardrails as "
            "an additional veto layer on top of agent_policy.cooldown_cities."
        ),
    }
    _atomic_write_json(OUTPUT_PATH, payload)

    if changes:
        for change in changes:
            _append_audit(
                {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "component": "auto_city_blacklist",
                    "decision": change,
                }
            )
            logger.info(
                "Auto-City: %s %s->%s (WR=%.0f%%, trades=%d, pnl=%+.2f) — %s",
                change["city"],
                change["from"],
                change["to"],
                change["win_rate"] * 100,
                change["trades"],
                change["total_pnl_eur"],
                change["reason"],
            )

    return {
        "blocked_cities": payload["blocked_cities"],
        "changes": changes,
        "evaluated": len(verdicts),
    }


def get_blocked_cities() -> List[str]:
    """Read the persisted blocked-cities list. Used by entry_guardrails."""
    if not OUTPUT_PATH.exists():
        return []
    try:
        data = json.loads(OUTPUT_PATH.read_text(encoding="utf-8"))
        blocked = data.get("blocked_cities", [])
        return [c for c in blocked if isinstance(c, str)]
    except (OSError, json.JSONDecodeError):
        return []


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    result = evaluate_and_persist()
    print(json.dumps(result, indent=2))
