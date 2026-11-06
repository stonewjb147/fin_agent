"""Price panels for the backtest: open/high/low/volume, not just close.

The rest of the project only ever needs closes, so `finagent.factors` drops
everything else at load time. The engine needs the rest: fills happen at the
open or the close, suspensions show up as a zero-volume day, and a limit move
can only be recognised from the price change.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import date
from pathlib import Path

import pandas as pd

from finagent.data.cache import ParquetCache
from finagent.data.panel import as_date, long_to_wide, slice_as_of

PRICE_FIELDS: tuple[str, ...] = ("open", "close", "high", "low", "volume", "amount")


def load_price_panels(
    cache_dir: str | Path | ParquetCache,
    symbols: Iterable[str],
    as_of: date | str,
    fields: Sequence[str] = PRICE_FIELDS,
) -> dict[str, pd.DataFrame]:
    """One date x symbol panel per field, truncated to `as_of` inclusive.

    Every panel shares the same index and columns, so `panels["close"]` and
    `panels["volume"]` are always aligned. A missing value means the ETF did not
    trade that day; it is never filled in here.
    """
    cache = cache_dir if isinstance(cache_dir, ParquetCache) else ParquetCache(cache_dir)
    frames = []
    for symbol in symbols:
        frame = cache.read("etf_daily_hfq", symbol)
        if frame is None or frame.empty:
            continue
        frame = frame.copy()
        frame["symbol"] = str(symbol)
        columns = ["date", "symbol", *[f for f in fields if f in frame.columns]]
        frames.append(frame[columns])
    if not frames:
        raise ValueError("no cached ETF daily data for the requested symbols")

    long = pd.concat(frames, ignore_index=True)
    long = slice_as_of(long, as_of)
    long["date"] = pd.to_datetime(long["date"])
    missing = [f for f in fields if f not in long.columns]
    if missing:
        raise ValueError(f"cached ETF data is missing field(s): {', '.join(missing)}")

    panels = {field: long_to_wide(long, field) for field in fields}
    index = panels["close"].index
    columns = panels["close"].columns
    for field in fields:
        panels[field] = panels[field].reindex(index=index, columns=columns)
        # A panel holding a row after as_of would silently leak into a backtest.
        if len(panels[field]) and pd.Timestamp(panels[field].index.max()).date() > as_date(as_of):
            raise ValueError("point-in-time violation while loading price panels")
    return panels
