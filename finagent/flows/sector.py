"""Sector money-flow factors from accumulated daily snapshots.

The free feed only publishes today's industry flow (`sector_flow_rank`); there
is no history endpoint. Every collect run therefore stores one snapshot, and
the factor is only defined once enough snapshots have accumulated. Until then
the source reports itself as unavailable instead of pretending one day is a
trend.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from finagent.data.cache import ParquetCache
from finagent.data.sources import SourceStatus

DATASET = "sector_flow_rank"
MIN_WINDOW = 5


def _snapshot_days(cache: ParquetCache, dataset: str = DATASET) -> list[tuple[date, Path]]:
    """Available snapshot files, keyed by their ISO date file name."""
    folder = cache.root / dataset
    if not folder.exists():
        return []
    days: list[tuple[date, Path]] = []
    for path in sorted(folder.glob("*.parquet")):
        try:
            days.append((date.fromisoformat(path.stem), path))
        except ValueError:
            continue
    return days


def load_sector_flow_history(
    cache_dir: str | Path, as_of: date | str, *, window: int = MIN_WINDOW
) -> tuple[pd.DataFrame, SourceStatus]:
    """All sector-flow snapshots up to `as_of`, plus an availability verdict."""
    cache = cache_dir if isinstance(cache_dir, ParquetCache) else ParquetCache(cache_dir)
    cutoff = pd.Timestamp(as_of).date()
    frames = []
    for day, path in _snapshot_days(cache):
        if day > cutoff:
            continue
        frame = pd.read_parquet(path)
        if frame is None or frame.empty:
            continue
        frames.append(frame)

    columns = ["date", "sector", "net_inflow", "pct_change", "company_count"]
    if not frames:
        return pd.DataFrame(columns=columns), SourceStatus.missing(
            DATASET, f"no {DATASET} snapshot on or before {cutoff.isoformat()}"
        )

    history = pd.concat(frames, ignore_index=True)
    for column in columns:
        if column not in history.columns:
            history[column] = np.nan
    history = history[columns].copy()
    history["date"] = pd.to_datetime(history["date"]).dt.normalize()
    history["sector"] = history["sector"].astype(str)
    history = history.dropna(subset=["date", "sector"])
    history = history.drop_duplicates(["date", "sector"], keep="last")

    days = sorted(history["date"].unique())
    n_days = len(days)
    first_date = pd.Timestamp(days[0]).date().isoformat()
    last_date = pd.Timestamp(days[-1]).date().isoformat()
    if n_days < window:
        return history, SourceStatus.missing(
            DATASET,
            f"need {window} daily snapshots, have {n_days} ({first_date}..{last_date}); "
            "collection accumulates one per trading day",
            n_records=int(len(history)),
            first_date=first_date,
            last_date=last_date,
        )
    return history, SourceStatus.ok(
        DATASET,
        f"{n_days} snapshots ({first_date}..{last_date})",
        n_records=int(len(history)),
        first_date=first_date,
        last_date=last_date,
    )


def sector_flow_scores(history: pd.DataFrame, *, window: int = MIN_WINDOW) -> pd.DataFrame:
    """date x sector cumulative flow z-score over the last `window` snapshots.

    Each day's net inflow is standardised across sectors first, so a day with
    unusually large flows everywhere does not dominate the sum; the rolling sum
    then measures persistence, not the size of the market.
    """
    if history.empty:
        return pd.DataFrame(columns=["date", "sector", "flow_z"])
    frame = history.dropna(subset=["net_inflow"]).copy()
    if frame.empty:
        return pd.DataFrame(columns=["date", "sector", "flow_z"])

    grouped = frame.groupby("date")["net_inflow"]
    mean = grouped.transform("mean")
    std = grouped.transform(lambda values: values.std(ddof=0))
    frame["flow_z_day"] = np.where(std > 0, (frame["net_inflow"] - mean) / std, 0.0)

    wide = frame.pivot(index="date", columns="sector", values="flow_z_day").sort_index()
    wide = wide.reindex(columns=sorted(wide.columns))
    rolled = wide.rolling(window, min_periods=window).sum()
    stacked = rolled.stack().rename("flow_z").reset_index()
    return stacked[["date", "sector", "flow_z"]]


def flow_factor_scores(
    history: pd.DataFrame,
    universe,
    as_of: date | str,
    *,
    window: int = MIN_WINDOW,
) -> pd.DataFrame:
    """Latest flow z per ETF, averaged across its mapped THS sectors."""
    scores = sector_flow_scores(history, window=window)
    if scores.empty:
        return pd.DataFrame(columns=["date", "symbol", "flow_z", "n_sectors", "sectors"])

    cutoff = pd.Timestamp(as_of)
    eligible = scores[scores["date"] <= cutoff]
    if eligible.empty:
        return pd.DataFrame(columns=["date", "symbol", "flow_z", "n_sectors", "sectors"])
    latest = eligible["date"].max()
    day_scores = eligible[eligible["date"] == latest].set_index("sector")["flow_z"]

    rows = []
    for etf in universe.for_date(pd.Timestamp(as_of).date()):
        mapped = [s for s in etf.flow_sectors if s in day_scores.index]
        if not mapped:
            continue
        rows.append(
            {
                "date": latest,
                "symbol": etf.symbol,
                "flow_z": float(day_scores.loc[mapped].mean()),
                "n_sectors": len(mapped),
                "sectors": ",".join(mapped),
            }
        )
    return pd.DataFrame(rows, columns=["date", "symbol", "flow_z", "n_sectors", "sectors"])


def market_flow_context(
    cache_dir: str | Path, as_of: date | str, *, window: int = 5
) -> tuple[dict, SourceStatus]:
    """Market-level main net inflow, used as context rather than a factor.

    It is one number for the whole market, so it cannot rank ETFs; applying it
    equally to every symbol would survive category neutralisation as zero. It
    is reported to explain the backdrop, not to score.
    """
    cache = cache_dir if isinstance(cache_dir, ParquetCache) else ParquetCache(cache_dir)
    frame = cache.read("market_flow", "cn")
    if frame is None or frame.empty:
        return {}, SourceStatus.missing("market_flow", "no market_flow/cn cache")
    frame = frame.copy()
    frame["date"] = pd.to_datetime(frame["date"])
    frame = frame[frame["date"] <= pd.Timestamp(as_of)].sort_values("date")
    if frame.empty:
        return {}, SourceStatus.missing("market_flow", f"no rows on or before {as_of}")
    latest = frame.iloc[-1]
    recent = frame.tail(window)["main_net_inflow_pct"].dropna()
    context = {
        "date": pd.Timestamp(latest["date"]).date().isoformat(),
        "main_net_inflow_pct": _round(latest.get("main_net_inflow_pct")),
        "main_net_inflow": _round(latest.get("main_net_inflow")),
        "mean_pct_5d": _round(float(recent.mean())) if len(recent) else None,
    }
    return context, SourceStatus.ok(
        "market_flow",
        f"latest {context['date']}",
        n_records=int(len(frame)),
        first_date=pd.Timestamp(frame["date"].min()).date().isoformat(),
        last_date=context["date"],
    )


def _round(value) -> float | None:
    if value is None or (isinstance(value, float) and not np.isfinite(value)):
        return None
    return round(float(value), 4)
