"""Overfitting diagnostics: CPCV, PBO (CSCV) and deflated Sharpe.

A single walk-forward Sharpe number is not evidence. These three tools ask the
same question from different angles:

* **CPCV** (combinatorial purged cross-validation) — retrain-free here, but the
  split logic still matters: evaluate each variant on many held-out block
  combinations instead of one, and report the *distribution* of test Sharpe.
* **PBO** (probability of backtest overfitting, Bailey et al. 2015) — when the
  best variant is chosen in-sample, how often does it land below the median
  out-of-sample? Above ~0.5 the selection carries no information.
* **DSR** (`finagent.research.stats.deflated_sharpe`) — probability the true
  Sharpe exceeds zero after accounting for how many variants were tried.

Purging: blocks are contiguous in time and returns are autocorrelated, so
`embargo` days on either side of every test block are dropped from the training
set. Nothing is dropped from the test block itself.
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Iterator, Sequence

import numpy as np
import pandas as pd

from finagent import config


def _sharpe(values: np.ndarray, periods: int = config.TRADING_DAYS_PER_YEAR) -> float:
    values = values[np.isfinite(values)]
    if values.size < 2:
        return float("nan")
    std = float(values.std(ddof=1))
    if std <= 1e-12:
        return float("nan")
    return float(values.mean() / std * math.sqrt(periods))


def block_bounds(n_samples: int, n_groups: int) -> list[tuple[int, int]]:
    """Contiguous, near-equal [start, end) blocks covering all samples."""
    if n_groups < 2:
        raise ValueError("n_groups must be >= 2")
    if n_samples < n_groups:
        raise ValueError("need at least one sample per group")
    edges = np.linspace(0, n_samples, n_groups + 1).round().astype(int)
    return [(int(edges[i]), int(edges[i + 1])) for i in range(n_groups)]


def cpcv_splits(
    n_samples: int,
    n_groups: int = 8,
    k_test: int = 2,
    embargo: int = 5,
) -> Iterator[tuple[np.ndarray, np.ndarray]]:
    """Yield (train_index, test_index) with embargoed samples removed from train."""
    bounds = block_bounds(n_samples, n_groups)
    all_index = np.arange(n_samples)
    for combo in itertools.combinations(range(n_groups), k_test):
        test_ranges = [bounds[g] for g in combo]
        test = np.concatenate([all_index[a:b] for a, b in test_ranges])
        dropped = np.zeros(n_samples, dtype=bool)
        if embargo > 0:
            for a, b in test_ranges:
                dropped[max(0, a - embargo) : min(n_samples, b + embargo)] = True
        train = all_index[~dropped]
        if train.size == 0 or test.size == 0:
            continue
        yield train, np.sort(test)


def cpcv_sharpes(
    returns: pd.DataFrame,
    n_groups: int = 8,
    k_test: int = 2,
    embargo: int = 5,
) -> pd.DataFrame:
    """Test-set Sharpe per (combination, variant).

    The training set is unused for fitting here — these strategies have no
    parameters fitted on the sample — but it is returned by `cpcv_splits` so a
    future parameterised strategy can use it, and the embargo keeps the reported
    distribution honest either way.
    """
    if returns.shape[1] < 1:
        raise ValueError("need at least one variant")
    values = returns.to_numpy(dtype=float)
    rows = []
    for combo, (_, test) in enumerate(cpcv_splits(len(returns), n_groups, k_test, embargo)):
        rows.append({"combo": combo, **{name: _sharpe(values[test, j]) for j, name in enumerate(returns.columns)}})
    return pd.DataFrame(rows).set_index("combo")


def cpcv_summary(cpcv: pd.DataFrame) -> dict:
    if cpcv.empty:
        return {}
    summary = {}
    for name in cpcv.columns:
        values = cpcv[name].dropna()
        summary[name] = {
            "mean": round(float(values.mean()), 4),
            "median": round(float(values.median()), 4),
            "p05": round(float(values.quantile(0.05)), 4),
            "p95": round(float(values.quantile(0.95)), 4),
            "positive_fraction": round(float((values > 0).mean()), 4),
            "n_splits": int(values.size),
        }
    return summary


def probability_of_backtest_overfitting(
    returns: pd.DataFrame,
    n_blocks: int = 12,
    periods: int = config.TRADING_DAYS_PER_YEAR,
) -> dict:
    """CSCV estimate of PBO (Bailey, Borwein, Lopez de Prado, Zhu 2015).

    Splits the return matrix into `n_blocks` contiguous blocks, uses every
    half-and-half split as in-sample / out-of-sample, picks the in-sample best
    variant and records where it ranks out-of-sample.
    """
    if returns.shape[1] < 2:
        raise ValueError("PBO needs at least two variants to compare")
    if n_blocks < 4 or n_blocks % 2:
        raise ValueError("n_blocks must be even and >= 4")

    m = returns.shape[1]
    bounds = block_bounds(len(returns), n_blocks)
    # drop the tail so every block has the same length
    size = min(b - a for a, b in bounds)
    values = returns.to_numpy(dtype=float)[: size * n_blocks].reshape(n_blocks, size, m)

    logits = []
    for is_blocks in itertools.combinations(range(n_blocks), n_blocks // 2):
        mask = np.zeros(n_blocks, dtype=bool)
        mask[list(is_blocks)] = True
        is_values = values[mask].reshape(-1, m)
        oos_values = values[~mask].reshape(-1, m)
        is_stats = np.array([_sharpe(is_values[:, j], periods) for j in range(m)])
        oos_stats = np.array([_sharpe(oos_values[:, j], periods) for j in range(m)])
        if not np.isfinite(is_stats).any() or not np.isfinite(oos_stats).any():
            continue
        best = int(np.nanargmax(is_stats))
        # rank 1 = worst; relative rank in (0, 1); logit < 0 means below median
        order = np.argsort(oos_stats, kind="stable")
        rank = int(np.where(order == best)[0][0]) + 1
        omega = rank / (m + 1.0)
        logits.append(math.log(omega / (1.0 - omega)))

    if not logits:
        return {"pbo": float("nan"), "n_combinations": 0}
    logits_arr = np.array(logits)
    return {
        "pbo": round(float((logits_arr <= 0).mean()), 4),
        "n_combinations": int(logits_arr.size),
        "mean_logit": round(float(logits_arr.mean()), 4),
        "n_blocks": n_blocks,
        "block_days": int(size),
        "variants": list(returns.columns),
    }


def dsr_table(
    returns: pd.DataFrame,
    n_trials: int,
    periods: int = config.TRADING_DAYS_PER_YEAR,
) -> dict:
    """Deflated Sharpe for every variant, using one shared trial count."""
    from finagent.research.stats import deflated_sharpe

    out = {}
    for name in returns.columns:
        stats = deflated_sharpe(returns[name], n_trials=min(max(int(n_trials), 1), periods))
        out[name] = {
            "sharpe": _round(stats.get("sharpe")),
            "dsr": _round(stats.get("dsr")),
            "sr0": _round(stats.get("sr0")),
        }
    return out


def _round(value: float | None) -> float:
    if value is None or not np.isfinite(value):
        return float("nan")
    return round(float(value), 4)


def returns_matrix(results: Sequence) -> pd.DataFrame:
    """Align several `BacktestResult`s into one date x strategy return matrix."""
    series = {r.name: r.daily["ret"] for r in results}
    return pd.DataFrame(series).sort_index().fillna(0.0)
