"""Build factor panels from the Parquet cache, strictly as of a date."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from pathlib import Path

import pandas as pd

from finagent.data.cache import ParquetCache
from finagent.data.panel import as_date, long_to_wide, slice_as_of
from finagent.factors.spec import FactorSpec


def load_price_frame(cache: ParquetCache, symbols: Iterable[str], as_of: date | str) -> pd.DataFrame:
    """Long price frame for `symbols`, truncated to `as_of` (inclusive)."""
    frames = []
    for symbol in symbols:
        frame = cache.read("etf_daily_hfq", symbol)
        if frame is None or frame.empty:
            continue
        frame = frame.copy()
        frame["symbol"] = str(symbol)
        frames.append(frame[["date", "symbol", "close", "amount"]])
    if not frames:
        raise ValueError("no cached ETF daily data for the requested symbols")

    long = pd.concat(frames, ignore_index=True)
    long = slice_as_of(long, as_of)
    long["date"] = pd.to_datetime(long["date"])
    return long.sort_values(["date", "symbol"]).reset_index(drop=True)


def load_close_panel(
    cache_dir: str | Path | ParquetCache, symbols: Iterable[str], as_of: date | str
) -> pd.DataFrame:
    """Date x symbol close matrix, guaranteed to contain nothing after `as_of`."""
    cache = cache_dir if isinstance(cache_dir, ParquetCache) else ParquetCache(cache_dir)
    long = load_price_frame(cache, symbols, as_of)
    close = long_to_wide(long, "close")
    assert_pit(close, as_of)
    return close


def assert_pit(panel: pd.DataFrame, as_of: date | str) -> None:
    """Fail loudly if a future row ever reaches a factor computation."""
    if panel.empty:
        return
    latest = pd.Timestamp(panel.index.max()).date()
    if latest > as_date(as_of):
        raise ValueError(f"point-in-time violation: panel has {latest} > as_of {as_of}")


def build_factor_panel(
    close: pd.DataFrame,
    specs: Iterable[FactorSpec],
    *,
    min_obs: int = 10,
) -> pd.DataFrame:
    """Long frame: date, symbol, factor, value.

    Dates with fewer than `min_obs` valid symbols are dropped: a cross-section
    that thin cannot support a ranking, and keeping it would make coverage
    statistics look better than the data really is.
    """
    rows = []
    for spec in specs:
        wide = spec.compute(close).reindex(index=close.index, columns=close.columns)
        wide = wide.loc[wide.notna().sum(axis=1) >= min_obs]
        stacked = wide.stack().dropna().rename("value").reset_index()
        stacked.columns = ["date", "symbol", "value"]
        stacked["factor"] = spec.name
        rows.append(stacked)
    if not rows:
        return pd.DataFrame(columns=["date", "symbol", "factor", "value"])
    return pd.concat(rows, ignore_index=True)[["date", "symbol", "factor", "value"]]


def factor_wide(factor_panel: pd.DataFrame, name: str) -> pd.DataFrame:
    """Slice one factor out of the long panel as a date x symbol matrix."""
    subset = factor_panel[factor_panel["factor"] == name]
    if subset.empty:
        return pd.DataFrame()
    return subset.pivot(index="date", columns="symbol", values="value").sort_index()
