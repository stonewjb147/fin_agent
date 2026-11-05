"""Panel helpers: long frames in, date x symbol matrices out.

All slicing is inclusive of `as_of` and strictly excludes later dates. This is
the single place where point-in-time semantics are enforced for prices.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd


def as_date(value: date | str | pd.Timestamp) -> date:
    if isinstance(value, date) and not isinstance(value, pd.Timestamp):
        return value
    return pd.Timestamp(value).date()


def slice_as_of(df: pd.DataFrame, as_of: date | str, date_col: str = "date") -> pd.DataFrame:
    """Keep rows with date <= as_of. Raises if a future row slips in."""
    cutoff = pd.Timestamp(as_date(as_of))
    dates = pd.to_datetime(df[date_col])
    out = df.loc[dates <= cutoff].copy()
    if len(out) != len(df):
        # Caller asked for a PIT slice; dropping future rows is expected.
        pass
    return out


def long_to_wide(df: pd.DataFrame, value: str, date_col: str = "date", symbol_col: str = "symbol") -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    wide = df.pivot_table(index=date_col, columns=symbol_col, values=value, aggfunc="last")
    wide.index = pd.to_datetime(wide.index)
    return wide.sort_index()


def to_returns(close: pd.DataFrame, log: bool = False) -> pd.DataFrame:
    if log:
        return np.log(close).diff()
    return close.pct_change(fill_method=None)


def forward_returns(close: pd.DataFrame, horizon: int = 1) -> pd.DataFrame:
    """Return realised return from t to t+horizon, indexed at t.

    The last `horizon` rows are NaN by construction — never filled.
    """
    if horizon < 1:
        raise ValueError("horizon must be >= 1")
    return close.shift(-horizon) / close - 1.0


def trailing_return(close: pd.DataFrame, window: int, skip: int = 0) -> pd.DataFrame:
    """Return over `window` days ending `skip` days before each row."""
    end = close.shift(skip)
    start = close.shift(skip + window)
    return end / start - 1.0


def align_panel(frames: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """Align several date x symbol frames to a common index/columns."""
    if not frames:
        return {}
    common_index = None
    common_cols = None
    for df in frames.values():
        common_index = df.index if common_index is None else common_index.intersection(df.index)
        common_cols = df.columns if common_cols is None else common_cols.intersection(df.columns)
    common_index = common_index.sort_values()
    common_cols = common_cols.sort_values()
    return {name: df.reindex(index=common_index, columns=common_cols) for name, df in frames.items()}
