from __future__ import annotations

import time

from paper_trader import snapshot_client
from paper_trader.snapshot_client import MarketSnapshotClient
from core.outcome_tracker import ResolutionChecker


def test_snapshot_batch_deadline_skips_remaining(monkeypatch):
    client = MarketSnapshotClient(timeout=1, max_retries=0)
    monkeypatch.setattr(snapshot_client, "SNAPSHOT_BATCH_DEADLINE_SECONDS", 0.01)
    monkeypatch.setattr(snapshot_client, "SNAPSHOT_RETRY_DELAY_SECONDS", 0.0)
    snapshot_client._SNAPSHOT_NEGATIVE_CACHE.clear()

    calls: list[str] = []

    def slow_missing(market_id: str):
        calls.append(market_id)
        time.sleep(0.02)
        return None

    monkeypatch.setattr(client, "_fetch_gamma_market", slow_missing)

    result = client.get_snapshots_batch(["m1", "m2", "m3"])

    assert set(result) == {"m1", "m2", "m3"}
    assert all(value is None for value in result.values())
    assert len(calls) < 3


def test_negative_cache_avoids_repeat_fetch(monkeypatch):
    client = MarketSnapshotClient(timeout=1, max_retries=0)
    snapshot_client._SNAPSHOT_NEGATIVE_CACHE.clear()
    snapshot_client._remember_missing_snapshot("missing-market")

    def fail_if_called(market_id: str):
        raise AssertionError("negative cache should avoid network fetch")

    monkeypatch.setattr(client, "_fetch_gamma_market", fail_if_called)

    assert client.get_snapshot("missing-market") is None


def test_resolution_update_deadline_limits_checks(monkeypatch):
    class FakeStorage:
        def get_unresolved_market_ids(self):
            return ["m1", "m2", "m3"]

        def write_resolution(self, resolution):
            return True, ""

    checker = ResolutionChecker(FakeStorage())
    calls: list[str] = []

    def slow_resolution(market_id: str):
        calls.append(market_id)
        time.sleep(0.02)
        return None

    monkeypatch.setattr(checker, "check_market_resolution", slow_resolution)

    result = checker.update_resolutions(max_checks=3, max_seconds=0.01)

    assert result["deadline_hit"] is True
    assert result["checked"] < 3
    assert len(calls) < 3
