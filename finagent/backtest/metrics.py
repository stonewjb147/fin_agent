"""Performance statistics for a return series.

Everything is computed from daily returns so that the net (after-cost) and
gross versions of the same run are directly comparable.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np
import pandas as pd

from finagent import config


def performance(
    returns: Sequence[float] | pd.Series,
    *,
    rf: float = config.DEFAULT_RISK_FREE_RATE,
    periods: int = config.TRADING_DAYS_PER_YEAR,
) -> dict:
    """Total/CAGR/vol/Sharpe/Sortino/drawdown/hit-rate for a daily return series."""
    series = pd.Series(returns, dtype=float).replace([np.inf, -np.inf], np.nan).dropna()
    n = int(series.size)
    if n == 0:
        return _empty()
    if n == 1:
        out = _empty()
        out.update({"n_days": 1, "total_return": float(series.iloc[0])})
        return out

    values = series.to_numpy()
    equity = np.cumprod(1.0 + values)
    total = float(equity[-1] - 1.0)
    years = n / periods
    cagr = float((1.0 + total) ** (1.0 / years) - 1.0) if equity[-1] > 0 and years > 0 else float("nan")

    std = float(values.std(ddof=1))
    ann_vol = std * math.sqrt(periods)
    excess = values - rf / periods
    # A constant return series has a zero standard deviation up to rounding; the
    # ratio would come out as 1e16 rather than undefined.
    sharpe = float(excess.mean() / std * math.sqrt(periods)) if std > 1e-12 else float("nan")

    downside = values[values < 0]
    downside_std = float(downside.std(ddof=1)) if downside.size > 1 else 0.0
    sortino = float(excess.mean() / downside_std * math.sqrt(periods)) if downside_std > 0 else float("nan")

    curve = np.concatenate([[1.0], equity])
    peak = np.maximum.accumulate(curve)
    drawdown = curve / peak - 1.0
    max_dd = float(drawdown.min())
    calmar = float(cagr / abs(max_dd)) if max_dd < 0 else float("nan")

    return {
        "n_days": n,
        "years": round(float(years), 4),
        "total_return": round(total, 6),
        "cagr": round(cagr, 6),
        "ann_vol": round(ann_vol, 6),
        "sharpe": round(sharpe, 4),
        "sortino": round(sortino, 4),
        "max_drawdown": round(max_dd, 6),
        "calmar": round(calmar, 4),
        "hit_rate": round(float((values > 0).mean()), 4),
        "best_day": round(float(values.max()), 6),
        "worst_day": round(float(values.min()), 6),
        "skew": round(float(pd.Series(values).skew()), 4),
        "kurtosis": round(float(pd.Series(values).kurt()), 4),
    }


def drawdown_series(returns: Sequence[float] | pd.Series) -> pd.Series:
    series = pd.Series(returns, dtype=float)
    equity = (1.0 + series.fillna(0.0)).cumprod()
    return equity / equity.cummax() - 1.0


def annualised_turnover(daily_turnover: Sequence[float] | pd.Series, periods: int = config.TRADING_DAYS_PER_YEAR) -> float:
    series = pd.Series(daily_turnover, dtype=float).dropna()
    if series.empty:
        return float("nan")
    return float(series.sum() / (len(series) / periods))


def _empty() -> dict:
    return {
        "n_days": 0,
        "years": 0.0,
        "total_return": float("nan"),
        "cagr": float("nan"),
        "ann_vol": float("nan"),
        "sharpe": float("nan"),
        "sortino": float("nan"),
        "max_drawdown": float("nan"),
        "calmar": float("nan"),
        "hit_rate": float("nan"),
        "best_day": float("nan"),
        "worst_day": float("nan"),
        "skew": float("nan"),
        "kurtosis": float("nan"),
    }
