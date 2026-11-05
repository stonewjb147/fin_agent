"""Cross-sectional transforms.

Every function operates row by row (one row = one trading day) and never mixes
information across dates, which keeps the panel point-in-time safe.
"""

from __future__ import annotations

from collections.abc import Mapping

import numpy as np
import pandas as pd


def winsorize_cs(df: pd.DataFrame, lower: float = 0.01, upper: float = 0.99) -> pd.DataFrame:
    """Clip each row at its own quantiles so one outlier cannot dominate."""
    lo = df.quantile(lower, axis=1)
    hi = df.quantile(upper, axis=1)
    return df.clip(lower=lo, upper=hi, axis=0)


def zscore_cs(df: pd.DataFrame) -> pd.DataFrame:
    """Row-wise standardisation. Zero-variance rows become 0, not NaN."""
    mean = df.mean(axis=1)
    std = df.std(axis=1, ddof=0)
    out = df.sub(mean, axis=0).div(std.replace(0.0, np.nan), axis=0)
    return out.where(std.notna() & (std != 0), 0.0).where(df.notna())


def rank_cs(df: pd.DataFrame) -> pd.DataFrame:
    """Row-wise percentile rank in (0, 1], robust to outliers by construction."""
    return df.rank(axis=1, pct=True)


def neutralize_cs(df: pd.DataFrame, groups: Mapping[str, str], method: str = "demean") -> pd.DataFrame:
    """Remove group means from each row.

    ETFs in different categories (bond vs sector vs commodity) have different
    volatility levels, so a raw cross-sectional ranking partly ranks asset
    classes rather than signals. Demeaning per category keeps the comparison
    inside a category but requires at least two members to be meaningful —
    singleton categories are left untouched.
    """
    if method not in {"demean", "median"}:
        raise ValueError(f"unknown neutralisation method {method!r}")
    labels = pd.Series({c: groups.get(str(c)) for c in df.columns})
    out = df.copy()
    for _, symbols in labels.groupby(labels, dropna=True):
        cols = [c for c in symbols.index if c in df.columns]
        if len(cols) < 2:
            continue
        block = df[cols]
        center = block.mean(axis=1) if method == "demean" else block.median(axis=1)
        out[cols] = block.sub(center, axis=0)
    return out
