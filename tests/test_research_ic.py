from __future__ import annotations

import numpy as np
import pandas as pd

from finagent.research.ic import cross_sectional_ic, ic_summary, quantile_spread_returns


def _panel(n_days: int = 30, n_symbols: int = 10) -> tuple[pd.DataFrame, pd.DataFrame]:
    index = pd.bdate_range("2024-01-01", periods=n_days)
    columns = [f"s{i:02d}" for i in range(n_symbols)]
    rng = np.random.default_rng(3)
    factor = pd.DataFrame(rng.normal(size=(n_days, n_symbols)), index=index, columns=columns)
    # Forward returns are a noisy but monotone function of the factor.
    forward = factor * 0.01 + rng.normal(scale=0.001, size=factor.shape)
    return factor, pd.DataFrame(forward, index=index, columns=columns)


def test_ic_is_one_for_a_perfect_ranking():
    factor, _ = _panel()
    ic = cross_sectional_ic(factor, factor)
    assert np.allclose(ic.to_numpy(), 1.0)


def test_ic_is_minus_one_when_returns_are_reversed():
    factor, _ = _panel()
    ic = cross_sectional_ic(factor, -factor)
    assert np.allclose(ic.to_numpy(), -1.0)


def test_ic_skips_dates_with_too_few_symbols():
    factor, forward = _panel()
    factor = factor.copy()
    factor.iloc[:, 2:] = np.nan  # only two symbols left in every cross-section
    ic = cross_sectional_ic(factor, forward, min_symbols=8)
    assert ic.empty


def test_ic_ignores_nan_pairs_without_producing_inf():
    factor, forward = _panel()
    factor = factor.mask(factor.rank(axis=1) < 3)  # knock out the bottom two
    forward = forward.mask(np.random.default_rng(0).random(forward.shape) < 0.1)
    ic = cross_sectional_ic(factor, forward, min_symbols=5)
    assert not ic.empty
    assert np.isfinite(ic.to_numpy()).all()


def test_ranks_use_the_common_support_only():
    """A symbol with a forward return but no factor must not shift the ranks.

    Regression: ranking each panel over its own support and intersecting
    afterwards biases the IC. Here the factor is known for A, B, D and the
    forward return for A, B, C, D. The IC must equal the rank correlation on
    A, B, D.
    """
    index = pd.bdate_range("2024-01-01", periods=1)
    factor = pd.DataFrame({"A": [1.0], "B": [2.0], "D": [3.0], "C": [np.nan]}, index=index)
    forward = pd.DataFrame({"A": [0.01], "B": [0.03], "C": [0.02], "D": [0.04]}, index=index)

    ic = cross_sectional_ic(factor, forward, min_symbols=3)
    assert np.isclose(ic.iloc[0], 1.0)


def test_ic_summary_reports_hac_statistics():
    factor, forward = _panel(60)
    summary = ic_summary(cross_sectional_ic(factor, forward), horizon=1)
    assert summary["n"] > 0
    assert summary["ic_mean"] > 0.1
    assert summary["lags"] >= 0
    assert np.isfinite(summary["nw_t"])


def test_quantile_spread_follows_direction():
    factor, forward = _panel(40)
    long_short = quantile_spread_returns(factor, forward, direction=1, min_symbols=5)
    assert long_short.mean() > 0
    flipped = quantile_spread_returns(factor, forward, direction=-1, min_symbols=5)
    assert np.isclose(flipped.mean(), -long_short.mean(), rtol=0.2)
