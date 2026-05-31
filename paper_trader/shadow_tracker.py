# =============================================================================
# POLYMARKET BEOBACHTER - SHADOW TRADE TRACKER (Hebel 2)
# =============================================================================
#
# GOVERNANCE INTENT:
# Records blocked YES proposals as shadow trades with hypothetical P&L.
# Goal: empirical basis for deciding whether DEFENSIVE mode leaves edge
# on the table. After 30 shadow trades we can evaluate with evidence.
#
# DATA FLOW:
#   intake.py (blocked YES) → shadow_tracker.py → data/shadow_trades.jsonl
#   cockpit.py (each run)   → update_open_shadow_trades() → resolves open entries
#
# PAPER TRADING ONLY - no real money involved.
# =============================================================================

import json
import logging
import os
import tempfile
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Tuple

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent
SHADOW_TRADES_PATH = PROJECT_ROOT / "data" / "shadow_trades.jsonl"

# Simulated position size for hypothetical P&L (matches current paper cap under DEFENSIVE)
SHADOW_POSITION_SIZE_EUR: float = float(os.environ.get("SHADOW_POSITION_SIZE_EUR", "5.0"))


# =============================================================================
# INTERNAL HELPERS
# =============================================================================

def _load_all() -> List[Dict[str, Any]]:
    if not SHADOW_TRADES_PATH.exists():
        return []
    records = []
    try:
        with open(SHADOW_TRADES_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        records.append(json.loads(line))
                    except Exception:
                        pass
    except Exception as e:
        logger.warning("shadow_tracker: failed to read %s: %s", SHADOW_TRADES_PATH, e)
    return records


def _append(record: Dict[str, Any]) -> None:
    try:
        SHADOW_TRADES_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(SHADOW_TRADES_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as e:
        logger.warning("shadow_tracker: failed to append record: %s", e)


def _rewrite(records: List[Dict[str, Any]]) -> None:
    """Atomically overwrite the file with updated records."""
    try:
        SHADOW_TRADES_PATH.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(SHADOW_TRADES_PATH.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                for rec in records:
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            os.replace(tmp, str(SHADOW_TRADES_PATH))
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
    except Exception as e:
        logger.warning("shadow_tracker: failed to rewrite file: %s", e)


def _open_market_ids() -> set:
    """Return set of market_ids that currently have an OPEN shadow trade."""
    return {r["market_id"] for r in _load_all() if r.get("status") == "OPEN"}


# =============================================================================
# PUBLIC API
# =============================================================================

def record_shadow_entry(
    proposal: Any,
    reason_code: str,
    reason_detail: str,
) -> None:
    """
    Record a blocked YES proposal as an OPEN shadow trade.

    Only records YES bets (edge > 0). Skips if this market_id already
    has an OPEN shadow trade (idempotency across pipeline runs).

    Args:
        proposal: Proposal object that was blocked
        reason_code: Short code for block reason (e.g. "defensive_mode")
        reason_detail: Full block explanation
    """
    edge = float(getattr(proposal, "edge", 0) or 0)
    if edge <= 0:
        return  # Only track YES bets (positive edge = model > market)

    market_id = str(getattr(proposal, "market_id", "") or "")
    if not market_id:
        return

    # Idempotency: skip if already tracking this market
    if market_id in _open_market_ids():
        return

    shadow_id = f"SHADOW-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}"
    entry_price = float(getattr(proposal, "implied_probability", 0.5) or 0.5)

    record = {
        "shadow_id": shadow_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "proposal_id": str(getattr(proposal, "proposal_id", "") or ""),
        "market_id": market_id,
        "market_question": str(getattr(proposal, "market_question", "") or "")[:120],
        "city": str(getattr(proposal, "city", "") or ""),
        "side": "YES",
        "blocked_by": reason_code,
        "blocked_reason": reason_detail[:200],
        "entry_price": entry_price,
        "edge": edge,
        "model_probability": float(getattr(proposal, "model_probability", 0) or 0),
        "hours_to_resolution": float(getattr(proposal, "hours_to_resolution", 0) or 0),
        "confidence_level": str(getattr(proposal, "confidence_level", "") or ""),
        "position_size_eur": SHADOW_POSITION_SIZE_EUR,
        "status": "OPEN",
        "last_price": entry_price,
        "last_price_at": datetime.now(timezone.utc).isoformat(),
        "resolution_price": None,
        "hypothetical_pnl_eur": None,
        "hypothetical_pnl_pct": None,
        "outcome": None,
        "resolved_at": None,
    }
    _append(record)
    logger.info(
        "SHADOW_ENTER: %s | market=%s edge=+%.1f%% ep=%.1f%% blocked_by=%s",
        shadow_id, market_id, edge * 100, entry_price * 100, reason_code,
    )


def update_open_shadow_trades() -> Tuple[int, int]:
    """
    Update OPEN shadow trades with current market prices.
    Resolves entries when the market closes.

    Returns:
        Tuple of (updated_count, resolved_count)
    """
    records = _load_all()
    open_records = [r for r in records if r.get("status") == "OPEN"]
    if not open_records:
        return 0, 0

    # Fetch snapshots for all open market_ids in one batch
    try:
        from paper_trader.snapshot_client import get_market_snapshots
        market_ids = list({r["market_id"] for r in open_records})
        snapshots = get_market_snapshots(market_ids)
    except Exception as e:
        logger.warning("shadow_tracker: snapshot fetch failed: %s", e)
        return 0, 0

    updated = 0
    resolved = 0
    now_iso = datetime.now(timezone.utc).isoformat()

    for record in records:
        if record.get("status") != "OPEN":
            continue

        mid = record["market_id"]
        snap = snapshots.get(mid)

        # Stale-expire: entry_time + hours_to_resolution + 48h buffer past now → EXPIRED.
        # Vermeidet, dass Records ewig OPEN bleiben, wenn der Snapshot nie wieder verfügbar ist
        # (Gamma API entfernt resolved markets nach ein paar Tagen aus der Liste).
        try:
            _entry_iso = record.get("timestamp") or record.get("shadow_entry_time")
            _entry_dt = datetime.fromisoformat(_entry_iso.replace("Z", "+00:00")) if _entry_iso else None
            if _entry_dt is not None and _entry_dt.tzinfo is None:
                _entry_dt = _entry_dt.replace(tzinfo=timezone.utc)
            _htr = float(record.get("hours_to_resolution", 0) or 0)
            if _entry_dt is not None:
                _expected_res = _entry_dt + timedelta(hours=_htr + 48)
                if datetime.now(timezone.utc) > _expected_res:
                    record["status"] = "EXPIRED"
                    record["resolved_at"] = now_iso
                    resolved += 1
                    logger.info(
                        "SHADOW_EXPIRE_STALE: %s | market=%s — entry+%dh+48h past",
                        record["shadow_id"], mid, int(_htr),
                    )
                    continue
        except Exception:
            pass

        if snap is None:
            # Snapshot nicht verfügbar (Markt aus Gamma raus = wahrscheinlich resolved).
            # Wenn der Entry schon einige Tage alt ist, EXPIRED markieren statt ewig OPEN.
            try:
                _entry_iso = record.get("timestamp")
                if _entry_iso:
                    _entry_dt = datetime.fromisoformat(_entry_iso.replace("Z", "+00:00"))
                    if _entry_dt.tzinfo is None:
                        _entry_dt = _entry_dt.replace(tzinfo=timezone.utc)
                    if (datetime.now(timezone.utc) - _entry_dt).total_seconds() > 7 * 24 * 3600:
                        record["status"] = "EXPIRED"
                        record["resolved_at"] = now_iso
                        resolved += 1
                        logger.info(
                            "SHADOW_EXPIRE_NOSNAP: %s | market=%s — no snapshot 7+ days",
                            record["shadow_id"], mid,
                        )
            except Exception:
                pass
            continue

        record["last_price"] = snap.mid_price
        record["last_price_at"] = now_iso
        updated += 1

        if snap.is_resolved and snap.resolved_outcome is not None:
            # Calculate hypothetical P&L
            entry = record["entry_price"]
            size_eur = record["position_size_eur"]
            # YES win: contracts × 1.0; YES loss: contracts × 0.0
            if snap.resolved_outcome == "YES":
                exit_price = 1.0
            else:
                exit_price = 0.0
            contracts = size_eur / entry if entry > 0 else 0
            pnl_eur = contracts * exit_price - size_eur
            pnl_pct = (pnl_eur / size_eur * 100) if size_eur > 0 else 0.0

            record["status"] = "RESOLVED"
            record["resolution_price"] = exit_price
            record["hypothetical_pnl_eur"] = round(pnl_eur, 4)
            record["hypothetical_pnl_pct"] = round(pnl_pct, 2)
            record["outcome"] = "WIN" if pnl_eur > 0 else "LOSS"
            record["resolved_at"] = now_iso
            resolved += 1
            logger.info(
                "SHADOW_RESOLVE: %s | market=%s outcome=%s pnl=%+.2f EUR (%.1f%%)",
                record["shadow_id"], mid, record["outcome"], pnl_eur, pnl_pct,
            )
        elif record.get("hours_to_resolution", 999) < -48:
            # Stale: resolution window passed without resolving → expire
            record["status"] = "EXPIRED"
            record["resolved_at"] = now_iso
            logger.info("SHADOW_EXPIRE: %s | market=%s — resolution overdue", record["shadow_id"], mid)

    _rewrite(records)
    return updated, resolved


def get_shadow_summary() -> Dict[str, Any]:
    """
    Return summary statistics for all shadow trades.

    Used to decide whether DEFENSIVE mode should be relaxed.
    """
    records = _load_all()
    if not records:
        return {"total": 0, "open": 0, "resolved": 0, "win_rate": None, "avg_pnl_eur": None}

    open_recs = [r for r in records if r.get("status") == "OPEN"]
    resolved_recs = [r for r in records if r.get("status") == "RESOLVED"]
    wins = [r for r in resolved_recs if r.get("outcome") == "WIN"]
    pnls = [r["hypothetical_pnl_eur"] for r in resolved_recs if r.get("hypothetical_pnl_eur") is not None]

    by_reason: Dict[str, int] = {}
    for r in records:
        k = r.get("blocked_by", "unknown")
        by_reason[k] = by_reason.get(k, 0) + 1

    return {
        "total": len(records),
        "open": len(open_recs),
        "resolved": len(resolved_recs),
        "win_rate": len(wins) / len(resolved_recs) if resolved_recs else None,
        "avg_pnl_eur": round(sum(pnls) / len(pnls), 3) if pnls else None,
        "total_hypothetical_pnl_eur": round(sum(pnls), 3) if pnls else None,
        "blocked_by_reason": by_reason,
        "milestone_30_reached": len(resolved_recs) >= 30,
    }
