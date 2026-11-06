from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from finagent.backtest.overfitting import (
    block_bounds,
    cpcv_sharpes,
    cpcv_splits,
    cpcv_summary,
    dsr_table,
    probability_of_backtest_overfitting,
    returns_matrix,
)


def test_block_bounds_cover_every_sample_once():
    bounds = block_bounds(100, 8)
    assert bounds[0][0] == 0
    assert bounds[-1][1] == 100
    assert sum(b - a for a, b in bounds) == 100
    for (_, prev_end), (next_start, _) in zip(bounds, bounds[1:], strict=False):
        assert prev_end == next_start


def test_cpcv_splits_are_disjoint_and_embargoed():
    n, embargo = 120, 5
    splits = list(cpcv_splits(n, n_groups=6, k_test=2, embargo=embargo))
    assert len(splits) == 15  # C(6, 2)
    for train, test in splits:
        assert np.intersect1d(train, test).size == 0
        # every contiguous test block keeps an embargo on both sides
        runs = np.split(test, np.where(np.diff(test) != 1)[0] + 1)
        forbidden: set[int] = set()
        for run in runs:
            forbidden |= set(range(max(0, run[0] - embargo), min(n, run[-1] + 1 + embargo)))
        assert not (set(train.tolist()) & forbidden)


def test_purging_actually_removes_samples_around_each_test_block():
    n, embargo = 60, 3
    for train, test in cpcv_splits(n, n_groups=4, k_test=1, embargo=embargo):
        # a single test block: nothing in [start-embargo, end+embargo) may train
        start, end = test.min(), test.max() + 1
        forbidden = set(range(max(0, start - embargo), min(n, end + embargo)))
        assert not (set(train.tolist()) & forbidden)
        assert train.size == n - len(forbidden)


def test_cpcv_sharpes_has_one_column_per_variant():
    rng = np.random.default_rng(3)
    returns = pd.DataFrame(
        {"a": rng.normal(0.001, 0.01, 200), "b": rng.normal(0.0, 0.01, 200)}
    )
    cpcv = cpcv_sharpes(returns, n_groups=6, k_test=2, embargo=5)
    assert list(cpcv.columns) == ["a", "b"]
    assert len(cpcv) == 15
    summary = cpcv_summary(cpcv)
    assert set(summary) == {"a", "b"}
    assert 0.0 <= summary["a"]["positive_fraction"] <= 1.0


def test_pbo_is_zero_when_one_variant_dominates_everywhere():
    rng = np.random.default_rng(7)
    dominant = rng.normal(0.004, 0.005, 240)
    weak = rng.normal(-0.001, 0.005, 240)
    returns = pd.DataFrame({"dominant": dominant, "weak": weak})
    stats = probability_of_backtest_overfitting(returns, n_blocks=8)
    assert stats["pbo"] == pytest.approx(0.0)
    assert stats["n_combinations"] == 70  # C(8, 4)


def test_pbo_on_pure_noise_sits_near_the_convention_centre():
    """With M variants and random data, PBO ~ P(rank <= M/2) under omega = rank/(M+1)."""
    rng = np.random.default_rng(11)
    returns = pd.DataFrame({f"s{i}": rng.normal(0, 0.01, 400) for i in range(5)})
    stats = probability_of_backtest_overfitting(returns, n_blocks=10)
    assert 0.3 <= stats["pbo"] <= 0.9
    assert stats["pbo"] > 0.0


def test_pbo_needs_at_least_two_variants():
    returns = pd.DataFrame({"only": np.zeros(50)})
    with pytest.raises(ValueError, match="at least two"):
        probability_of_backtest_overfitting(returns)


def test_dsr_table_reports_every_variant():
    rng = np.random.default_rng(13)
    returns = pd.DataFrame({"a": rng.normal(0.001, 0.01, 300), "b": rng.normal(-0.001, 0.01, 300)})
    table = dsr_table(returns, n_trials=2)
    assert set(table) == {"a", "b"}
    assert table["a"]["dsr"] > table["b"]["dsr"]


class _Result:
    def __init__(self, name, ret):
        self.name = name
        self.daily = pd.DataFrame({"ret": ret})


def test_returns_matrix_aligns_strategies_on_the_same_dates():
    index = pd.bdate_range("2024-01-01", periods=3)
    first = _Result("a", pd.Series([0.01, 0.02, 0.03], index=index))
    second = _Result("b", pd.Series([0.0, -0.01, 0.0], index=index))
    matrix = returns_matrix([first, second])
    assert list(matrix.columns) == ["a", "b"]
    assert matrix.loc[index[1], "b"] == pytest.approx(-0.01)
