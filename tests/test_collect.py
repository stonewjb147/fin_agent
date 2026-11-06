"""The collect report must name the snapshot it actually built."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pandas as pd

from finagent import config
from finagent.data.cache import ParquetCache
from finagent.data.collect import collect
from finagent.data.provider import DataNotAvailable, ProviderError
from finagent.data.universe import load_universe


class _FakeProvider:
    """Serves the ETF history and fails everything else, offline."""

    def __init__(self, cache: ParquetCache, frame: pd.DataFrame):
        self.cache = cache
        self.frame = frame

    def _source_name(self, dataset: str) -> str:
        return "fake"

    def etf_daily(self, symbols, start, end, force: bool = False) -> pd.DataFrame:
        frames = []
        for symbol in symbols:
            frame = self.frame.copy()
            frame["symbol"] = symbol
            self.cache.write("etf_daily_hfq", symbol, frame, source="fake")
            frames.append(frame)
        out = pd.concat(frames, ignore_index=True)
        out.attrs["failures"] = []
        return out

    def index_daily(self, *args, **kwargs):
        raise ProviderError("offline")

    def index_valuation(self, *args, **kwargs):
        raise ProviderError("offline")

    def macro(self, *args, **kwargs):
        raise DataNotAvailable("offline")

    def bond_yield(self, *args, **kwargs):
        raise ProviderError("offline")

    def market_flow(self, *args, **kwargs):
        raise ProviderError("offline")

    def margin_sse(self, *args, **kwargs):
        raise ProviderError("offline")

    def trade_calendar(self, *args, **kwargs):
        raise ProviderError("offline")


def test_collect_report_names_the_snapshot_it_built(tmp_path, monkeypatch, etf_frame, universe_yaml):
    monkeypatch.setattr(config, "QUALITY_DIR", tmp_path / "quality")
    monkeypatch.setattr(config, "SNAPSHOT_DIR", tmp_path / "snapshots")
    universe = load_universe(universe_yaml)
    cache = ParquetCache(tmp_path / "cache")
    provider = _FakeProvider(cache, etf_frame)

    result = collect(provider, universe, date(2024, 6, 3), date(2024, 7, 31), snapshots="off")

    assert result.snapshot_id
    assert result.quality_path is not None
    payload = json.loads(Path(result.quality_path).read_text(encoding="utf-8"))
    assert payload["snapshot_id"] == result.snapshot_id
    snapshot_file = tmp_path / "snapshots" / f"{result.snapshot_id}.json"
    assert snapshot_file.exists()
