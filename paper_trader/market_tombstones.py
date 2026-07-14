# =============================================================================
# POLYMARKET BEOBACHTER - MARKET TOMBSTONES
# =============================================================================
#
# PURPOSE:
# Persistent "this market is gone" cache. The in-memory negative cache in
# snapshot_client only lives for one process; since the pipeline runs every
# 15 min as a fresh process, permanently-removed markets (e.g. resolved and
# purged from the Gamma API) get re-fetched forever and spam
# logs/snapshot_errors.log.
#
# This module counts consecutive not-found results across runs and, after a
# threshold, tombstones the market so snapshots skip it silently.
#
# READ-ONLY toward the market: this only tracks failures, it never trades.
# =============================================================================

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any

logger = logging.getLogger(__name__)

_TOMBSTONE_FILE = Path(__file__).parent.parent / "data" / "market_tombstones.json"

# Consecutive not-found results before a market is considered gone.
MISS_THRESHOLD = int(os.getenv("MARKET_TOMBSTONE_MISS_THRESHOLD", "3"))

# In-memory view of the persisted store: market_id -> record dict.
_store: Dict[str, Dict[str, Any]] = {}
_loaded = False


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load() -> None:
    """Load the tombstone store from disk once per process."""
    global _store, _loaded
    if _loaded:
        return
    try:
        if _TOMBSTONE_FILE.exists():
            with open(_TOMBSTONE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                _store = data
    except Exception as e:  # pragma: no cover - corrupt file is non-fatal
        logger.warning(f"Could not load market tombstones: {e}")
        _store = {}
    _loaded = True


def _save() -> None:
    """Persist the tombstone store atomically."""
    try:
        _TOMBSTONE_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = _TOMBSTONE_FILE.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(_store, f, indent=2, sort_keys=True)
        os.replace(tmp, _TOMBSTONE_FILE)
    except Exception as e:  # pragma: no cover - disk error is non-fatal
        logger.warning(f"Could not save market tombstones: {e}")


def is_tombstoned(market_id: str) -> bool:
    """Return True if the market has been permanently marked as gone."""
    _load()
    rec = _store.get(str(market_id))
    return bool(rec and rec.get("tombstoned"))


def record_hit(market_id: str) -> None:
    """Market came back — clear any partial miss streak."""
    _load()
    mid = str(market_id)
    if mid in _store and not _store[mid].get("tombstoned"):
        _store.pop(mid, None)
        _save()


def record_miss(market_id: str) -> bool:
    """
    Record a not-found result for a market.

    Returns True if this miss just crossed the threshold and tombstoned the
    market (so the caller can log it once), False otherwise.
    """
    _load()
    mid = str(market_id)
    rec = _store.get(mid)
    if rec and rec.get("tombstoned"):
        return False  # already gone

    if rec is None:
        rec = {"miss_count": 0, "first_missed": _now()}

    rec["miss_count"] = int(rec.get("miss_count", 0)) + 1
    rec["last_missed"] = _now()

    newly_tombstoned = False
    if rec["miss_count"] >= MISS_THRESHOLD:
        rec["tombstoned"] = True
        rec["tombstoned_at"] = _now()
        newly_tombstoned = True

    _store[mid] = rec
    _save()
    return newly_tombstoned


def active_tombstones() -> int:
    """Number of markets currently tombstoned (for status/reporting)."""
    _load()
    return sum(1 for r in _store.values() if r.get("tombstoned"))
