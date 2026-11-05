from __future__ import annotations

import json

import pandas as pd

from finagent.data.cache import ParquetCache, checksum, safe_key


def test_safe_key_handles_path_separators():
    assert "/" not in safe_key("2026/11/05")
    assert safe_key("600000.SH") == "600000.SH"
    assert safe_key("***") == "default"


def test_write_then_read_roundtrip(tmp_path, etf_frame):
    cache = ParquetCache(tmp_path)
    manifest = cache.write("etf_daily_hfq", "510300", etf_frame, source="fixture")

    assert manifest.rows == len(etf_frame)
    assert manifest.first_date == "2024-06-03"
    assert manifest.last_date == "2024-07-31"
    assert manifest.checksum == checksum(cache.parquet_path("etf_daily_hfq", "510300"))

    back = cache.read("etf_daily_hfq", "510300")
    pd.testing.assert_frame_equal(back, etf_frame)


def test_manifest_is_valid_json_and_reloads(tmp_path, etf_frame):
    cache = ParquetCache(tmp_path)
    cache.write("etf_daily_hfq", "510300", etf_frame, source="fixture", params={"adjust": "hfq"})

    raw = json.loads(cache.manifest_path("etf_daily_hfq", "510300").read_text(encoding="utf-8"))
    assert raw["source"] == "fixture"
    assert raw["params"] == {"adjust": "hfq"}

    manifest = cache.manifest("etf_daily_hfq", "510300")
    assert manifest is not None
    assert manifest.fetched_on is not None


def test_write_replaces_previous_version(tmp_path, etf_frame):
    cache = ParquetCache(tmp_path)
    cache.write("etf_daily_hfq", "510300", etf_frame.iloc[:5], source="fixture")
    first = cache.manifest("etf_daily_hfq", "510300").checksum

    cache.write("etf_daily_hfq", "510300", etf_frame, source="fixture")
    second = cache.manifest("etf_daily_hfq", "510300").checksum

    assert first != second
    assert len(cache.read("etf_daily_hfq", "510300")) == len(etf_frame)
    assert not list((tmp_path / "etf_daily_hfq").glob("*.tmp"))


def test_missing_dataset_returns_none(tmp_path):
    cache = ParquetCache(tmp_path)
    assert cache.read("nope", "nope") is None
    assert cache.manifest("nope", "nope") is None
    assert cache.describe("nope") == []
