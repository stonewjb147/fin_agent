"""Factor evaluation report: IC, ICIR, HAC t, BH-FDR and Deflated Sharpe."""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from finagent import config
from finagent.data.panel import as_date, forward_returns
from finagent.factors import (
    build_factor_panel,
    factor_wide,
    get_factor,
    load_close_panel,
    neutralize_cs,
    rank_cs,
    winsorize_cs,
    zscore_cs,
)
from finagent.research.ic import cross_sectional_ic, ic_summary, quantile_spread_returns
from finagent.research.stats import bh_fdr, deflated_sharpe, sharpe_ratio

DEFAULT_HORIZONS = (1, 5, 20)
MIN_SYMBOLS = 8


def _stacked(wide: pd.DataFrame, name: str) -> pd.DataFrame:
    """date x symbol matrix -> tidy (date, symbol, <name>) frame."""
    out = wide.stack().dropna().rename(name).reset_index()
    out.columns = ["date", "symbol", name]
    return out


def factor_snapshot(close: pd.DataFrame, names: Iterable[str], min_obs: int = MIN_SYMBOLS) -> pd.DataFrame:
    """Long frame with raw value plus rank and z-score, one row per factor-day-symbol."""
    specs = [get_factor(n) for n in names]
    panel = build_factor_panel(close, specs, min_obs=min_obs)
    frames = []
    for spec in specs:
        wide = factor_wide(panel, spec.name)
        if wide.empty:
            continue
        value = _stacked(wide, "value")
        value["factor"] = spec.name
        value = value.merge(_stacked(rank_cs(wide), "rank_cs"), on=["date", "symbol"], how="left")
        value = value.merge(
            _stacked(zscore_cs(winsorize_cs(wide)), "z_cs"), on=["date", "symbol"], how="left"
        )
        frames.append(value)
    if not frames:
        return pd.DataFrame(columns=["date", "symbol", "factor", "value", "rank_cs", "z_cs"])
    return pd.concat(frames, ignore_index=True)[
        ["date", "symbol", "factor", "value", "rank_cs", "z_cs"]
    ]


def evaluate(
    close: pd.DataFrame,
    factors: pd.DataFrame,
    groups: pd.Series,
    names: Sequence[str],
    horizons: Sequence[int] = DEFAULT_HORIZONS,
    *,
    min_symbols: int = MIN_SYMBOLS,
    q: float = 0.10,
    execution_lag: int = config.EXECUTION_LAG_DAYS,
) -> dict:
    """Evaluate every factor x horizon pair and correct across the whole family.

    Signals are formed after the close of day t and executed on t+lag, so the
    forward return is P(t+lag+h)/P(t+lag)-1, not P(t+h)/P(t)-1.
    """
    tests: list[dict] = []
    for name in names:
        spec = get_factor(name)
        wide = factor_wide(factors, name)
        if wide.empty:
            continue
        neutral = neutralize_cs(zscore_cs(winsorize_cs(wide)), groups)
        fwd_close = close.reindex(index=wide.index, columns=wide.columns)

        for horizon in horizons:
            fwd = forward_returns(fwd_close, horizon).shift(-execution_lag)
            ic = cross_sectional_ic(wide, fwd, min_symbols=min_symbols)
            summary = ic_summary(ic, horizon)
            ic_neutral = cross_sectional_ic(neutral, fwd, min_symbols=min_symbols)
            neutral_summary = ic_summary(ic_neutral, horizon)

            long_short = quantile_spread_returns(
                wide, fwd, direction=spec.direction, min_symbols=min_symbols
            )
            sampled = long_short.iloc[::horizon] if len(long_short) else long_short
            periods = max(1, config.TRADING_DAYS_PER_YEAR // horizon)
            dsr = deflated_sharpe(sampled, n_trials=len(names) * len(horizons))

            # Same long-short book after removing category means: this is the
            # part of the trade that cannot be earned by simply owning the
            # category that happened to do well.
            long_short_neutral = quantile_spread_returns(
                neutral, fwd, direction=spec.direction, min_symbols=min_symbols
            )
            sampled_neutral = (
                long_short_neutral.iloc[::horizon] if len(long_short_neutral) else long_short_neutral
            )
            dsr_neutral = deflated_sharpe(sampled_neutral, n_trials=len(names) * len(horizons))

            available = int((wide.notna().sum(axis=1) >= min_symbols).sum())
            tests.append(
                {
                    "factor": name,
                    "group": spec.group,
                    "direction": spec.direction,
                    "horizon": horizon,
                    **summary,
                    "ic_mean_directional": summary["ic_mean"] * spec.direction,
                    "ic_mean_neutral": neutral_summary["ic_mean"],
                    "nw_t_neutral": neutral_summary["nw_t"],
                    "p_value_neutral": neutral_summary["p_value"],
                    "icir_neutral": neutral_summary["icir"],
                    "coverage": summary["n"] / available if available else float("nan"),
                    "long_short_sr": sharpe_ratio(sampled, periods=periods),
                    "dsr": dsr["dsr"],
                    "long_short_sr_neutral": sharpe_ratio(sampled_neutral, periods=periods),
                    "dsr_neutral": dsr_neutral["dsr"],
                }
            )

    pvalues = [t["p_value"] for t in tests]
    qvalues = bh_qvalues(pvalues)
    for test, q_value, reject in zip(tests, qvalues, bh_fdr(pvalues, q=q), strict=True):
        test["q_value"] = q_value
        test["significant"] = bool(reject)

    # The category-neutral IC is the primary metric. A raw IC mixes "which
    # asset class won" into "which ETF within the class won"; in this pool the
    # first effect dwarfs the second, so testing raw IC answers the wrong
    # question. Both families are corrected separately and reported.
    pvalues_neutral = [t["p_value_neutral"] for t in tests]
    qvalues_neutral = bh_qvalues(pvalues_neutral)
    for test, q_value, reject in zip(
        tests, qvalues_neutral, bh_fdr(pvalues_neutral, q=q), strict=True
    ):
        test["q_value_neutral"] = q_value
        test["significant_neutral"] = bool(reject)

    return {
        "tests": tests,
        "meta": {
            "trading_days_per_year": config.TRADING_DAYS_PER_YEAR,
            "min_symbols": min_symbols,
            "horizons": list(horizons),
            "n_factors": len(names),
            "m_tests": len(tests),
            "fdr_q": q,
            "ic_method": "spearman",
            "execution_lag": execution_lag,
            "dsr_n_trials": len(names) * len(horizons),
            "notes": (
                "IC is the daily cross-sectional rank correlation with the h-day forward "
                "return starting execution_lag days after the signal; the last h+lag days "
                "are NaN by construction. ICIR annualises by sqrt(252/h). t-statistics use "
                "Newey-West with max(h-1, 4*(n/100)^(2/9)) lags. Long-short returns are "
                "top-vs-bottom thirds, equal weight, no costs, sampled every h days for the "
                "Sharpe/DSR statistics. The *_neutral columns repeat everything after "
                "subtracting each date's category mean, so the signal cannot be earned by "
                "owning the category that happened to do well; they are the primary "
                "read, the raw columns are kept for comparison."
            ),
        },
    }


def bh_qvalues(pvalues: Sequence[float]) -> list[float]:
    """Benjamini-Hochberg adjusted p-values, aligned with the input order.

    A NaN p-value is treated as 1.0: it cannot be rejected, and letting NaN into
    the running minimum would poison every earlier (smaller) p-value.
    """
    arr = np.asarray(pvalues, dtype=float)
    m = arr.size
    if m == 0:
        return []
    arr = np.where(np.isfinite(arr), arr, 1.0)
    order = np.argsort(arr, kind="stable")
    adjusted = arr[order] * m / np.arange(1, m + 1)
    adjusted = np.minimum.accumulate(adjusted[::-1])[::-1].clip(0.0, 1.0)
    out = np.empty(m, dtype=float)
    out[order] = adjusted
    return out.tolist()


class NoDataError(RuntimeError):
    """The requested `as_of` has no price data in the cache.

    Raised instead of writing `factors/<as_of>.parquet` from an earlier date:
    every artefact is named after its as_of, so a stale panel would put a
    holiday's or a failed collection's date on someone else's numbers.
    """


def run_factor_report(
    universe,
    *,
    as_of: date | str,
    cache_dir: str | Path | None = None,
    factor_names: Sequence[str] | None = None,
    horizons: Sequence[int] = DEFAULT_HORIZONS,
    execution_lag: int = config.EXECUTION_LAG_DAYS,
    write: bool = True,
    out_dir: str | Path | None = None,
    quality_dir: str | Path | None = None,
) -> dict:
    """End-to-end report for one `as_of`. Returns the report dict."""
    as_of = as_date(as_of)
    names = list(factor_names or ["momentum_20", "reversal_5", "volatility_20"])
    cache_dir = Path(cache_dir or config.CACHE_DIR)
    symbols = universe.symbols(as_of)

    close = load_close_panel(cache_dir, symbols, as_of)
    if pd.Timestamp(as_of) not in close.index:
        latest = close.index.max().date().isoformat() if len(close) else "none"
        raise NoDataError(f"no price data on {as_of} (panel ends {latest}); run `collect` first")
    factors = factor_snapshot(close, names)
    if factors.empty:
        raise ValueError(f"no factor values could be computed as of {as_of}")

    report = evaluate(
        close,
        factors,
        universe.groups(as_of),
        names,
        horizons,
        execution_lag=execution_lag,
    )
    report.update(
        {
            "as_of": as_of.isoformat(),
            "universe_version": universe.version,
            "n_symbols": int(close.shape[1]),
            "data_start": close.index.min().date().isoformat(),
            "data_end": close.index.max().date().isoformat(),
        }
    )

    if write:
        out_dir = Path(out_dir or (config.DATA_DIR / "factors"))
        quality_dir = Path(quality_dir or config.QUALITY_DIR)
        out_dir.mkdir(parents=True, exist_ok=True)
        quality_dir.mkdir(parents=True, exist_ok=True)
        factors.to_parquet(out_dir / f"{as_of.isoformat()}.parquet", index=False)
        report["factor_file"] = str(out_dir / f"{as_of.isoformat()}.parquet")

        report_path = quality_dir / f"factor_report_{as_of.isoformat()}.json"
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        report["report_file"] = str(report_path)
    return report


def format_summary(report: dict) -> str:
    """Compact text table for terminals and cron logs."""
    lines = [
        f"Factor report {report['as_of']}  symbols={report['n_symbols']}  "
        f"universe={report['universe_version']}  data={report['data_start']}..{report['data_end']}",
        "",
        f"{'FACTOR':14s} {'H':>3s} {'N':>5s} {'IC':>7s} {'IC_N':>7s} {'t_N':>6s} "
        f"{'q_N':>6s} {'LS':>6s} {'LS_N':>6s} {'DSR_N':>5s}  SIG",
    ]
    for test in report["tests"]:
        lines.append(
            f"{test['factor']:14s} {test['horizon']:3d} {test['n']:5d} "
            f"{test['ic_mean']:7.3f} {test['ic_mean_neutral']:7.3f} {test['nw_t_neutral']:6.2f} "
            f"{test['q_value_neutral']:6.3f} {test['long_short_sr']:6.2f} "
            f"{test['long_short_sr_neutral']:6.2f} {test['dsr_neutral']:5.2f}  "
            f"{'yes' if test['significant_neutral'] else ''}"
        )
    meta = report["meta"]
    lines.append(
        f"\nm={meta['m_tests']} tests, BH-FDR q={meta['fdr_q']}, "
        f"IC method={meta['ic_method']}, annualisation={meta['trading_days_per_year']} days"
    )
    lines.append(
        "columns: IC raw mean, IC_N category-neutral mean, t_N/q_N neutral HAC t and BH q, "
        "LS raw long-short Sharpe, LS_N neutral long-short Sharpe, DSR_N neutral Deflated Sharpe"
    )
    lines.append("SIG is decided on the category-neutral family; raw q_value stays in the JSON")
    return "\n".join(lines)
