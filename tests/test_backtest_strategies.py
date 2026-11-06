"""Strategies: same data in, comparable weights out."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from finagent.backtest.strategies import (
    EqualWeightStrategy,
    PolicyStrategy,
    TopNStrategy,
    default_strategies,
    score_as_of,
)
from finagent.data.universe import ETF, Universe
from finagent.portfolio.policy import PortfolioPolicy


def _universe(n: int = 12) -> Universe:
    etfs = [
        ETF(symbol=f"51{i:04d}", name=f"ETF{i}", category="broad" if i < 6 else "sector")
        for i in range(n)
    ]
    return Universe(version="u-test", etfs=etfs)


def _close(index: pd.DatetimeIndex, n: int = 12, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    prices = 100 * np.cumprod(1 + rng.normal(0, 0.01, size=(len(index), n)), axis=0)
    return pd.DataFrame(prices, index=index, columns=[f"51{i:04d}" for i in range(n)])


def _scores(index: pd.DatetimeIndex, n: int = 12, seed: int = 1) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows = []
    for day in index[::5]:
        for i in range(n):
            rows.append({"date": day, "symbol": f"51{i:04d}", "composite": float(rng.normal()), "confidence": 0.6, "n_factors": 3})
    return pd.DataFrame(rows)


@pytest.fixture()
def index() -> pd.DatetimeIndex:
    return pd.bdate_range("2024-01-01", periods=90)


def test_equal_weight_sums_to_one_and_skips_missing_prices(index):
    close = _close(index)
    close.loc[index[-1], "510000"] = np.nan
    weights = EqualWeightStrategy(universe=_universe()).target_weights(index[-1], close)
    assert weights.sum() == pytest.approx(1.0)
    assert "510000" not in weights.index
    assert len(weights) == 11


def test_top_n_holds_the_highest_scores(index):
    close, scores = _close(index), _scores(index)
    weights = TopNStrategy(universe=_universe(), scores=scores, n=4).target_weights(index[-1], close)
    latest = score_as_of(scores, index[-1])
    assert set(weights.index) == set(latest.sort_values(ascending=False).head(4).index)
    assert weights.sum() == pytest.approx(1.0)


def test_score_as_of_never_reads_the_future(index):
    scores = _scores(index)
    first = scores["date"].min()
    before = score_as_of(scores, first - pd.Timedelta(days=1))
    assert before.empty
    at_first = score_as_of(scores, first)
    assert not at_first.empty


def test_policy_without_tilt_ignores_the_scores(index):
    close = _close(index)
    policy = PortfolioPolicy()
    scores_a = _scores(index, seed=1)
    scores_b = _scores(index, seed=99)

    no_tilt_a = PolicyStrategy(universe=_universe(), scores=scores_a, policy=policy, tilt=False)
    no_tilt_b = PolicyStrategy(universe=_universe(), scores=scores_b, policy=policy, tilt=False)
    assert np.allclose(
        no_tilt_a.target_weights(index[-1], close).sort_index(),
        no_tilt_b.target_weights(index[-1], close).sort_index(),
    )


def test_the_tilt_does_move_weights(index):
    close = _close(index)
    policy = PortfolioPolicy()
    scores = _scores(index)
    tilted = PolicyStrategy(universe=_universe(), scores=scores, policy=policy, tilt=True)
    plain = PolicyStrategy(universe=_universe(), scores=scores, policy=policy, tilt=False)
    a = tilted.target_weights(index[-1], close)
    b = plain.target_weights(index[-1], close)
    assert not np.allclose(a.sort_index(), b.sort_index())


def test_default_suite_exposes_the_ablation_set(index):
    suite = default_strategies(_universe(), _scores(index), PortfolioPolicy(), top_n=5)
    assert list(suite) == ["equal_weight", "policy_no_tilt", "policy_tilt", "top_5"]
    assert all(hasattr(strategy, "target_weights") for strategy in suite.values())


def test_strategies_return_non_negative_weights(index):
    close = _close(index)
    scores = _scores(index)
    for name, strategy in default_strategies(_universe(), scores).items():
        weights = strategy.target_weights(index[-1], close)
        assert (weights >= 0).all(), name
        assert weights.sum() == pytest.approx(1.0, abs=1e-9), name
