"""ETF-level flow proxies: share changes and premium/discount.

Both need data the free feed publishes irregularly (`etf_scale_sse` is SSE-only
and often lags; `etf_nav` is T-1 at best). Each loader returns an explicit
status so the pipeline can degrade and annotate instead of inventing values.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from finagent.data.cache import ParquetCache
from finagent.data.sources import SourceStatus

SHARE_DATASET = "etf_scale_sse"
NAV_DATASET = "etf_nav"
SHARE_WINDOW_DAYS = 20


def _zscore(series: pd.Series) -> pd.Series:
    values = pd.to_numeric(series, errors="coerce")
    std = values.std(ddof=0)
    if not np.isfinite(std) or std <= 0:
        return pd.Series(0.0, index=values.index)
    return (values - values.mean()) / std


def load_share_snapshots(
    cache_dir: str | Path, as_of: date | str
) -> tuple[pd.DataFrame, SourceStatus]:
    """Accumulated `etf_scale_sse` snapshots on or before `as_of`."""
    cache = cache_dir if isinstance(cache_dir, ParquetCache) else ParquetCache(cache_dir)
    folder = cache.root / SHARE_DATASET
    cutoff = pd.Timestamp(as_of)
    frames = []
    for path in sorted(folder.glob("*.parquet")):
        try:
            day = pd.Timestamp(date.fromisoformat(path.stem))
        except ValueError:
            continue
        if day > cutoff:
            continue
        frame = pd.read_parquet(path)
        if frame is None or frame.empty:
            continue
        frames.append(frame)
    columns = ["date", "symbol", "shares"]
    if not frames:
        return pd.DataFrame(columns=columns), SourceStatus.missing(
            SHARE_DATASET, f"no {SHARE_DATASET} snapshot on or before {cutoff.date()}"
        )
    history = pd.concat(frames, ignore_index=True)
    for column in columns:
        if column not in history.columns:
            history[column] = np.nan
    history = history[columns].copy()
    history["date"] = pd.to_datetime(history["date"]).dt.normalize()
    history["symbol"] = history["symbol"].astype(str).str.zfill(6)
    history["shares"] = pd.to_numeric(history["shares"], errors="coerce")
    history = history.dropna(subset=["date", "symbol", "shares"])
    history = history.drop_duplicates(["date", "symbol"], keep="last")
    days = sorted(history["date"].unique())
    return history, SourceStatus.ok(
        SHARE_DATASET,
        f"{len(days)} snapshots",
        n_records=int(len(history)),
        first_date=pd.Timestamp(days[0]).date().isoformat(),
        last_date=pd.Timestamp(days[-1]).date().isoformat(),
    )


def share_change_scores(
    history: pd.DataFrame, *, window_days: int = SHARE_WINDOW_DAYS
) -> tuple[pd.DataFrame, SourceStatus]:
    """Cross-sectional z of share growth between the latest and an older snapshot.

    A rising share count is usually creation (money coming in), but it also
    happens on a distribution or a split, so the value is a proxy, not a fund
    flow measurement. `span_days` is reported with every score.
    """
    columns = ["date", "symbol", "share_change", "share_z", "span_days"]
    if history.empty:
        return pd.DataFrame(columns=columns), SourceStatus.missing(
            SHARE_DATASET, "no share snapshots"
        )
    days = sorted(history["date"].unique())
    latest = days[-1]
    if len(days) < 2:
        return pd.DataFrame(columns=columns), SourceStatus.missing(
            SHARE_DATASET, "need at least two snapshots to measure a change"
        )
    target = latest - pd.Timedelta(days=window_days)
    older_days = [day for day in days[:-1] if day <= target]
    base = older_days[-1] if older_days else days[0]
    span = int((latest - base).days)

    now = history[history["date"] == latest].set_index("symbol")["shares"]
    before = history[history["date"] == base].set_index("symbol")["shares"]
    common = now.index.intersection(before.index)
    if len(common) < 2:
        return pd.DataFrame(columns=columns), SourceStatus.missing(
            SHARE_DATASET, "fewer than two symbols have both snapshots"
        )
    change = (now.loc[common] / before.loc[common] - 1.0).replace([np.inf, -np.inf], np.nan)
    frame = change.dropna().rename("share_change").reset_index()
    frame["share_z"] = _zscore(frame["share_change"])
    frame["date"] = latest
    frame["span_days"] = span
    status = SourceStatus.ok(
        SHARE_DATASET,
        f"change {base.date()}..{latest.date()} ({span} days)",
        n_records=int(len(frame)),
        first_date=base.date().isoformat(),
        last_date=latest.date().isoformat(),
    )
    return frame[columns], status


def load_nav_history(
    cache_dir: str | Path, symbols: list[str], as_of: date | str
) -> tuple[pd.DataFrame, SourceStatus]:
    """Unit NAV history for `symbols`, truncated to `as_of`."""
    cache = cache_dir if isinstance(cache_dir, ParquetCache) else ParquetCache(cache_dir)
    cutoff = pd.Timestamp(as_of)
    frames = []
    for symbol in symbols:
        frame = cache.read(NAV_DATASET, symbol)
        if frame is None or frame.empty or "unit_nav" not in frame.columns:
            continue
        frame = frame[["date", "symbol", "unit_nav"]].copy()
        frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
        frame = frame[frame["date"] <= cutoff]
        if not frame.empty:
            frames.append(frame)
    if not frames:
        return pd.DataFrame(columns=["date", "symbol", "unit_nav"]), SourceStatus.missing(
            NAV_DATASET, f"no cached unit NAV on or before {cutoff.date()}"
        )
    history = pd.concat(frames, ignore_index=True).dropna(subset=["date", "unit_nav"])
    return history, SourceStatus.ok(
        NAV_DATASET,
        f"{history['symbol'].nunique()} symbols",
        n_records=int(len(history)),
        first_date=pd.Timestamp(history["date"].min()).date().isoformat(),
        last_date=pd.Timestamp(history["date"].max()).date().isoformat(),
    )


def premium_discount_scores(
    close: pd.DataFrame, nav: pd.DataFrame, *, min_symbols: int = 2
) -> tuple[pd.DataFrame, SourceStatus]:
    """Close vs same-day unit NAV, cross-sectionally z-scored.

    The NAV feed is published with a lag, so the latest available NAV date is
    used per symbol and reported; comparing a T close with a T-2 NAV would make
    the premium meaningless without saying so.
    """
    columns = ["date", "symbol", "premium", "premium_z", "nav_date"]
    if nav.empty or close.empty:
        return pd.DataFrame(columns=columns), SourceStatus.missing(NAV_DATASET, "no NAV or price data")
    latest_nav = (
        nav.sort_values("date").groupby("symbol", as_index=False).tail(1).set_index("symbol")
    )
    rows = []
    for symbol, row in latest_nav.iterrows():
        day = pd.Timestamp(row["date"])
        if symbol not in close.columns or day not in close.index:
            continue
        price = close.at[day, symbol]
        unit_nav = float(row["unit_nav"])
        if not np.isfinite(price) or not np.isfinite(unit_nav) or unit_nav <= 0:
            continue
        rows.append(
            {
                "date": day,
                "symbol": symbol,
                "premium": float(price) / unit_nav - 1.0,
                "nav_date": day.date().isoformat(),
            }
        )
    if len(rows) < min_symbols:
        return pd.DataFrame(columns=columns), SourceStatus.missing(
            NAV_DATASET, f"only {len(rows)} symbols have a same-day close and NAV"
        )
    frame = pd.DataFrame(rows)
    frame["premium_z"] = _zscore(frame["premium"])
    status = SourceStatus.ok(
        NAV_DATASET,
        f"{len(frame)} symbols, latest NAV {frame['nav_date'].max()}",
        n_records=int(len(frame)),
        last_date=frame["nav_date"].max(),
    )
    return frame[columns], status
