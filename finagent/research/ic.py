"""Cross-sectional information coefficient.

IC_t is the rank correlation between the factor and the forward return on the
same cross-section. Daily IC series are extremely noisy on their own, so the
summary always reports the mean, the ICIR and a HAC t-statistic together.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from finagent import config
from finagent.research.stats import newey_west_lags, newey_west_tstat


def _row_corr(a: pd.DataFrame, b: pd.DataFrame, min_symbols: int) -> pd.Series:
    """Row-wise Pearson correlation over the pairwise-valid entries."""
    common = a.index.intersection(b.index)
    cols = a.columns.intersection(b.columns)
    a = a.reindex(index=common, columns=cols)
    b = b.reindex(index=common, columns=cols)

    mask = a.notna() & b.notna()
    count = mask.sum(axis=1)
    a = a.where(mask)
    b = b.where(mask)
    a = a.sub(a.mean(axis=1), axis=0)
    b = b.sub(b.mean(axis=1), axis=0)
    numerator = (a * b).sum(axis=1)
    denominator = np.sqrt((a**2).sum(axis=1) * (b**2).sum(axis=1))
    corr = numerator / denominator.replace(0.0, np.nan)
    return corr.where((count >= min_symbols) & corr.notna())


def cross_sectional_ic(
    factor: pd.DataFrame,
    forward_returns: pd.DataFrame,
    *,
    min_symbols: int = 8,
    method: str = "spearman",
) -> pd.Series:
    """IC per date. Dates with fewer than `min_symbols` pairs are dropped."""
    if method not in {"spearman", "pearson"}:
        raise ValueError(f"unknown IC method {method!r}")
    if method == "spearman":
        factor = factor.rank(axis=1)
        forward_returns = forward_returns.rank(axis=1)
    ic = _row_corr(factor, forward_returns, min_symbols)
    return ic.dropna().rename("ic")


def ic_summary(ic: pd.Series, horizon: int = 1, trading_days: int | None = None) -> dict:
    """Mean IC, ICIR, HAC t-stat and hit rate for one factor-horizon pair."""
    trading_days = trading_days or config.TRADING_DAYS_PER_YEAR
    ic = pd.Series(ic).dropna()
    n = int(ic.size)
    if n == 0:
        return {
            "n": 0,
            "ic_mean": float("nan"),
            "ic_std": float("nan"),
            "icir": float("nan"),
            "nw_t": float("nan"),
            "p_value": float("nan"),
            "lags": None,
            "positive_ratio": float("nan"),
        }

    mean = float(ic.mean())
    std = float(ic.std(ddof=1)) if n > 1 else float("nan")
    icir = mean / std * math.sqrt(trading_days / horizon) if std and std > 0 else float("nan")
    lags = newey_west_lags(n, horizon)
    t_stat, p_value = newey_west_tstat(ic, lags=lags)
    return {
        "n": n,
        "ic_mean": mean,
        "ic_std": std,
        "icir": icir,
        "nw_t": t_stat,
        "p_value": p_value,
        "lags": lags,
        "positive_ratio": float((ic > 0).mean()),
    }


def quantile_spread_returns(
    factor: pd.DataFrame,
    forward_returns: pd.DataFrame,
    *,
    direction: int = 1,
    quantile: float = 1 / 3,
    min_symbols: int = 8,
) -> pd.Series:
    """Daily long-short return: top `quantile` minus bottom `quantile`.

    The factor is multiplied by `direction` first, so a negative factor such as
    volatility is shorted on the high side. Costs are ignored here; the
    cost-aware version belongs to the Phase 4 backtest.
    """
    score = factor * direction
    fwd = forward_returns.reindex_like(score)
    out = {}
    for day, row in score.iterrows():
        values = row.dropna()
        if len(values) < min_symbols:
            continue
        realised = fwd.loc[day].reindex(values.index).dropna()
        values = values.reindex(realised.index)
        if len(values) < min_symbols:
            continue
        k = max(1, int(len(values) * quantile))
        ordered = values.sort_values()
        short = realised.loc[ordered.index[:k]].mean()
        long = realised.loc[ordered.index[-k:]].mean()
        out[day] = float(long - short)
    return pd.Series(out, name="long_short").sort_index()
