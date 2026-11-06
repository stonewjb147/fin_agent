from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from finagent.backtest.metrics import annualised_turnover, drawdown_series, performance


def test_performance_of_a_known_series():
    returns = pd.Series([0.1, -0.2, 0.05])
    stats = performance(returns, rf=0.0)
    assert stats["total_return"] == pytest.approx(1.1 * 0.8 * 1.05 - 1.0)
    assert stats["max_drawdown"] == pytest.approx(0.88 / 1.1 - 1.0)
    assert stats["hit_rate"] == pytest.approx(2 / 3, rel=1e-3)


def test_constant_positive_returns_have_no_sharpe_but_a_drawdown_of_zero():
    stats = performance(pd.Series([0.001] * 20), rf=0.0)
    assert math.isnan(stats["sharpe"])
    assert stats["max_drawdown"] == pytest.approx(0.0)
    assert stats["total_return"] == pytest.approx(1.001**20 - 1.0, rel=1e-4)


def test_sharpe_matches_the_textbook_formula():
    rng = np.random.default_rng(1)
    returns = pd.Series(rng.normal(0.0005, 0.01, 250))
    stats = performance(returns, rf=0.0)
    expected = returns.mean() / returns.std(ddof=1) * math.sqrt(252)
    assert stats["sharpe"] == pytest.approx(expected, rel=1e-3)


def test_cagr_annualises_the_total_return():
    returns = pd.Series([0.001] * 252)
    stats = performance(returns, rf=0.0)
    assert stats["cagr"] == pytest.approx(1.001**252 - 1.0, rel=1e-6)


def test_sortino_ignores_upside_volatility():
    one_sided = performance(pd.Series([0.01, 0.02, 0.03, 0.01]), rf=0.0)
    two_sided = performance(pd.Series([0.01, -0.02, 0.03, -0.01]), rf=0.0)
    assert math.isnan(one_sided["sortino"])  # no downside days at all
    assert np.isfinite(two_sided["sortino"])


def test_empty_and_single_day_series_are_handled():
    assert performance(pd.Series(dtype=float))["n_days"] == 0
    single = performance(pd.Series([0.01]))
    assert single["n_days"] == 1
    assert single["total_return"] == pytest.approx(0.01)


def test_drawdown_series_tracks_the_peak():
    dd = drawdown_series(pd.Series([0.1, -0.2, 0.05]))
    assert dd.iloc[0] == pytest.approx(0.0)
    assert dd.iloc[1] == pytest.approx(0.88 / 1.1 - 1.0)
    assert dd.iloc[2] < 0


def test_annualised_turnover_scales_with_the_window():
    daily = pd.Series([0.1] * 126)
    assert annualised_turnover(daily) == pytest.approx(25.2)
