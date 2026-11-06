"""Turn backtest output into numbers a person can act on.

The Phase 4 report already has CAGR / Sharpe / drawdown. What it does not say
is: how bad was the worst year, how long was the money underwater, would a
plain 510300 have been better, and how cheap would trading have to be for a
high-turnover strategy to pay for itself. Those are the questions here.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path

import numpy as np
import pandas as pd

from finagent import config
from finagent.backtest.costs import cost_from_bps
from finagent.backtest.engine import BacktestConfig, run_backtest
from finagent.backtest.metrics import performance
from finagent.data.panel import forward_returns
from finagent.factors import get_factor, neutralize_cs, winsorize_cs, zscore_cs
from finagent.factors.build import factor_wide
from finagent.research.ic import cross_sectional_ic


def worst_rolling_return(returns: Sequence[float] | pd.Series, window: int = 252) -> float:
    """Worst return over any `window`-day stretch (total return if shorter)."""
    series = pd.Series(returns, dtype=float).fillna(0.0)
    if series.empty:
        return float("nan")
    equity = (1.0 + series).cumprod()
    if len(equity) <= window:
        return float(equity.iloc[-1] - 1.0)
    base = equity.shift(window)
    rolling = equity / base - 1.0
    return float(rolling.dropna().min())


def underwater_stats(returns: Sequence[float] | pd.Series) -> dict:
    """Share of days below a previous peak, and the longest such run."""
    series = pd.Series(returns, dtype=float).fillna(0.0)
    if series.empty:
        return {"share_underwater": float("nan"), "longest_underwater_days": 0}
    equity = (1.0 + series).cumprod()
    drawdown = equity / equity.cummax() - 1.0
    under = (drawdown < -1e-12).to_numpy()
    longest = current = 0
    for flag in under:
        current = current + 1 if flag else 0
        longest = max(longest, current)
    return {
        "share_underwater": round(float(under.mean()), 4),
        "longest_underwater_days": int(longest),
    }


def relative_metrics(returns: Sequence[float] | pd.Series, benchmark: Sequence[float] | pd.Series) -> dict:
    """Beta, correlation, tracking error, information ratio, up/down capture."""
    frame = pd.concat(
        [pd.Series(returns, dtype=float).rename("r"), pd.Series(benchmark, dtype=float).rename("b")],
        axis=1,
        join="inner",
    ).dropna()
    if len(frame) < 2 or float(frame["b"].var(ddof=1)) <= 1e-12:
        return {"beta": float("nan"), "corr": float("nan"), "tracking_error": float("nan"), "info_ratio": float("nan"), "up_capture": float("nan"), "down_capture": float("nan")}
    r, b = frame["r"], frame["b"]
    diff = r - b
    up = b > 0
    down = b < 0
    period = math.sqrt(config.TRADING_DAYS_PER_YEAR)
    return {
        "beta": round(float(r.cov(b) / b.var(ddof=1)), 4),
        "corr": round(float(r.corr(b)), 4),
        "tracking_error": round(float(diff.std(ddof=1) * period), 6),
        "info_ratio": round(float(diff.mean() / diff.std(ddof=1) * period), 4)
        if float(diff.std(ddof=1)) > 1e-12
        else float("nan"),
        "up_capture": round(float(r[up].mean() / b[up].mean()), 4) if up.any() and abs(float(b[up].mean())) > 1e-12 else float("nan"),
        "down_capture": round(float(r[down].mean() / b[down].mean()), 4) if down.any() and abs(float(b[down].mean())) > 1e-12 else float("nan"),
    }


def extended_metrics(
    returns: Sequence[float] | pd.Series,
    benchmark: Sequence[float] | pd.Series | None = None,
    *,
    rf: float = config.DEFAULT_RISK_FREE_RATE,
) -> dict:
    """`performance` plus the path-dependent numbers people actually feel."""
    out = performance(returns, rf=rf)
    out["worst_12m"] = round(worst_rolling_return(returns, config.TRADING_DAYS_PER_YEAR), 6)
    out.update(underwater_stats(returns))
    if benchmark is not None:
        out.update(relative_metrics(returns, benchmark))
    return out


def yearly_returns(returns: Sequence[float] | pd.Series) -> dict[str, float]:
    """Calendar-year total return, so one good year cannot hide two bad ones."""
    series = pd.Series(returns, dtype=float).dropna()
    if series.empty:
        return {}
    series.index = pd.to_datetime(series.index)
    return {
        str(int(year)): round(float((1.0 + group).prod() - 1.0), 6)
        for year, group in series.groupby(series.index.year)
    }


def cost_sensitivity(
    panels: dict[str, pd.DataFrame],
    strategies: dict,
    cfg: BacktestConfig,
    bps: Iterable[float] = (0.0, 7.0, 20.0),
) -> dict[str, dict[str, dict]]:
    """Rerun every strategy at several one-way costs.

    This is a real rerun, not `gross_metrics`: adding costs back ignores the
    compounding of smaller positions, which is exactly what a high-turnover
    strategy suffers from.
    """
    out: dict[str, dict[str, dict]] = {}
    for level in bps:
        cost = cost_from_bps(float(level))
        out[f"{float(level):g}"] = {
            name: run_backtest(panels, strategy, cfg, cost).metrics for name, strategy in strategies.items()
        }
    return out


def net_increment_by_cost(
    sensitivity: Mapping[str, Mapping[str, dict]],
    baseline: str,
    levels: Sequence[float],
    basis: str = "cagr",
) -> dict[str, dict[str, float]]:
    """A strategy's return minus the baseline's at the same cost level.

    This is the primary read on a strat: not "it made 10%", but "it beat doing
    nothing by X after paying its own costs". A strategy that leads at 0bp and
    trails at 20bp has no edge, only turnover.
    """
    keys = [f"{float(level):g}" for level in levels]
    out: dict[str, dict[str, float]] = {}
    for name in sensitivity[keys[0]]:
        base = {key: float(sensitivity[key][baseline][basis]) for key in keys}
        out[name] = {
            key: round(float(sensitivity[key][name][basis]) - base[key], 6) for key in keys
        }
    return out


def break_even_bps(levels: Sequence[tuple[float, float, float]]) -> float | None:
    """One-way cost at which strategy A's CAGR falls to strategy B's.

    `levels` is a sequence of ``(bps, cagr_a, cagr_b)`` sorted by bps. Returns
    the linearly interpolated crossing, or None if A is never ahead or never
    behind in the sampled range.
    """
    ordered = sorted(levels, key=lambda row: row[0])
    for (b0, a0, c0), (b1, a1, c1) in zip(ordered, ordered[1:], strict=False):
        d0, d1 = a0 - c0, a1 - c1
        if d0 > 0 and d1 < 0:
            return round(b0 + (b1 - b0) * d0 / (d0 - d1), 2)
    return None


def ic_by_year(
    close: pd.DataFrame,
    factors: pd.DataFrame,
    names: Sequence[str],
    horizons: Sequence[int] = (1, 5, 20),
    *,
    execution_lag: int = config.EXECUTION_LAG_DAYS,
    min_symbols: int = 8,
    groups: Mapping[str, str] | None = None,
) -> list[dict]:
    """Directional IC per calendar year, to show whether a factor is stable.

    Same convention as `research.report.evaluate`: the signal is formed at t's
    close and the return is measured from t+lag to t+lag+h. With `groups`, also
    reports the category-neutral IC, which is the one that answers "can this
    factor pick a winner inside a category" rather than "did the right category
    happen to do well".
    """
    rows: list[dict] = []
    for name in names:
        spec = get_factor(name)
        wide = factor_wide(factors, name)
        if wide.empty:
            continue
        neutral = (
            neutralize_cs(zscore_cs(winsorize_cs(wide)), groups) if groups is not None else None
        )
        fwd_close = close.reindex(index=wide.index, columns=wide.columns)
        for horizon in horizons:
            fwd = forward_returns(fwd_close, horizon).shift(-execution_lag)
            ic = cross_sectional_ic(wide, fwd, min_symbols=min_symbols)
            if ic.empty:
                continue
            ic_neutral = (
                cross_sectional_ic(neutral, fwd, min_symbols=min_symbols) if neutral is not None else None
            )
            for year, group in ic.groupby(ic.index.year):
                neutral_value = None
                if ic_neutral is not None and len(ic_neutral):
                    neutral_year = ic_neutral[ic_neutral.index.year == year]
                    if len(neutral_year):
                        neutral_value = round(float(neutral_year.mean()) * spec.direction, 4)
                rows.append(
                    {
                        "factor": name,
                        "horizon": int(horizon),
                        "year": int(year),
                        "ic_mean": round(float(group.mean()) * spec.direction, 4),
                        "ic_neutral": neutral_value,
                        "n_days": int(len(group)),
                    }
                )
    return rows


def effective_breadth(returns: pd.DataFrame, min_periods: int = 60) -> dict:
    """How many independent bets a cross-section really contains.

    With average pairwise correlation rho, `N` assets behave like
    `N / (1 + (N-1) * rho)` independent ones. Fifty ETFs whose daily returns
    correlate 0.36 are worth about 2.7 bets, which is the number that matters
    for both statistical power and the economics.
    """
    corr = returns.corr(min_periods=min_periods)
    n = int(corr.shape[0])
    if n < 2:
        return {"n_symbols": n, "avg_corr": float("nan"), "n_eff": float(n), "n_pairs": 0}
    mask = np.triu(np.ones(corr.shape, dtype=bool), k=1)
    pairs = corr.where(mask).stack().dropna()
    rho = float(pairs.mean()) if len(pairs) else float("nan")
    if not np.isfinite(rho):
        n_eff = float(n)
    else:
        n_eff = float(np.clip(n / (1.0 + (n - 1.0) * rho), 1.0, float(n)))
    return {
        "n_symbols": n,
        "avg_corr": round(rho, 4) if np.isfinite(rho) else None,
        "n_eff": round(n_eff, 2),
        "n_pairs": int(len(pairs)),
    }


def expected_ir(ic: float, n_eff: float, horizon: int = 1, days: int | None = None) -> float:
    """Fundamental law: IR ≈ IC × sqrt(breadth), breadth = n_eff × days/horizon.

    This is an upper bound on a paper portfolio that pays no costs and bets the
    full cross-section every `horizon` days. It is here to translate an IC into
    something comparable with a Sharpe ratio, not as a forecast.
    """
    days = days or config.TRADING_DAYS_PER_YEAR
    breadth = max(n_eff, 1.0) * days / max(horizon, 1)
    return float(ic * math.sqrt(breadth))


def required_settled(margin: float = 0.05, p: float = 0.5, z: float = 1.96) -> int:
    """Independent settled calls needed for a +-margin hit-rate interval."""
    return int(math.ceil(z * z * p * (1.0 - p) / (margin * margin)))


def ledger_state(root: str | Path, as_of, calendar: Sequence | None = None, horizon: int | None = None) -> dict:
    """What the prediction ledger knows so far, and when it can know more.

    `calendar` is a sorted sequence of trading dates including dates after
    `as_of` (the cached exchange calendar); without it the first settlement
    date is reported as unknown rather than guessed.
    """
    from finagent.predictions.ledger import PredictionLedger

    ledger = PredictionLedger(root)
    frame = ledger.load()
    settled = ledger.settlements()
    out: dict = {
        "n_predictions": int(len(frame)),
        "n_settled": int(settled["signal_id"].nunique()) if not settled.empty else 0,
        "n_pending": 0,
        "first_signal_date": None,
        "first_settlement_date": None,
        "required_settled_5pct": required_settled(0.05),
        "required_settled_10pct": required_settled(0.10),
    }
    out["n_pending"] = max(out["n_predictions"] - out["n_settled"], 0)
    if frame.empty:
        return out
    first = frame.sort_values("as_of").iloc[0]
    out["first_signal_date"] = str(first["as_of"])
    out["horizon"] = int(first["horizon"])
    if calendar is None:
        return out
    dates = pd.DatetimeIndex(pd.to_datetime(list(calendar))).sort_values()
    signal_date = pd.Timestamp(str(first["as_of"]))
    pos = int(dates.searchsorted(signal_date, side="left"))
    entry = pos + int(first["execution_lag"])
    exit_pos = entry + int(first["horizon"])
    if pos < len(dates) and dates[pos] == signal_date and exit_pos < len(dates):
        out["first_settlement_date"] = dates[exit_pos].date().isoformat()
    return out
