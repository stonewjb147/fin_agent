from __future__ import annotations

import pytest

from finagent.data.cache import ParquetCache
from finagent.data.lineage import SnapshotStore


@pytest.fixture
def store(tmp_path):
    cache = ParquetCache(tmp_path / "cache")
    store = SnapshotStore(tmp_path / "snapshots")
    return cache, store


def test_build_writes_and_loads_snapshot(store, etf_frame):
    cache, snapshots = store
    cache.write("etf_daily_hfq", "510300", etf_frame, source="fixture")

    snap = snapshots.build(cache, [("etf_daily_hfq", "510300")], "2024-07-31", note="test")
    assert snap.snapshot_id.startswith("snap-20240731-")
    assert len(snap.entries) == 1

    loaded = snapshots.load(snap.snapshot_id)
    assert loaded.snapshot_id == snap.snapshot_id
    assert loaded.entries[0].key == "510300"
    assert loaded.entries[0].checksum == snap.entries[0].checksum


def test_snapshot_id_is_deterministic_for_same_bytes(store, etf_frame):
    cache, snapshots = store
    cache.write("etf_daily_hfq", "510300", etf_frame, source="fixture")

    first = snapshots.build(cache, [("etf_daily_hfq", "510300")], "2024-07-31")
    second = snapshots.build(cache, [("etf_daily_hfq", "510300")], "2024-07-31")
    assert first.snapshot_id == second.snapshot_id


def test_verify_detects_tampering(store, etf_frame):
    cache, snapshots = store
    cache.write("etf_daily_hfq", "510300", etf_frame, source="fixture")
    snap = snapshots.build(cache, [("etf_daily_hfq", "510300")], "2024-07-31")

    assert snapshots.verify(snap.snapshot_id, cache)["ok"]

    tampered = etf_frame.copy()
    tampered.loc[0, "close"] = 99.0
    cache.write("etf_daily_hfq", "510300", tampered, source="fixture")

    result = snapshots.verify(snap.snapshot_id, cache)
    assert result["ok"] is False
    assert result["entries"][0]["checksum_match"] is False


def test_build_fails_on_cache_miss(store):
    cache, snapshots = store
    with pytest.raises(FileNotFoundError):
        snapshots.build(cache, [("etf_daily_hfq", "missing")], "2024-07-31")
