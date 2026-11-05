from __future__ import annotations

import numpy as np
import pandas as pd

from finagent.research.report import bh_qvalues
from finagent.research.stats import (
    bh_fdr,
    deflated_sharpe,
    newey_west_lags,
    newey_west_tstat,
    sharpe_ratio,
)


def test_zero_lag_newey_west_matches_the_textbook_t_statistic():
    x = pd.Series([0.1, -0.2, 0.3, 0.0, 0.25, -0.05, 0.15, 0.2])
    t_hac, _ = newey_west_tstat(x, lags=0)
    t_classic = x.mean() / (x.std(ddof=1) / np.sqrt(len(x)))
    assert np.isclose(t_hac, t_classic)


def test_newey_west_lag_floor_covers_overlapping_returns():
    assert newey_west_lags(100, horizon=20) == 19  # horizon dominates
    assert newey_west_lags(400, horizon=1) >= 1


def test_newey_west_shrinks_t_when_autocorrelation_is_positive():
    rng = np.random.default_rng(5)
    noise = rng.normal(size=400)
    x = pd.Series(np.convolve(noise, np.ones(5) / 5, mode="same"))  # strong MA(5) overlap
    t_classic = x.mean() / (x.std(ddof=1) / np.sqrt(len(x)))
    t_hac, p_value = newey_west_tstat(x, lags=4)
    assert abs(t_hac) < abs(t_classic)
    assert 0.0 <= p_value <= 1.0


def test_newey_west_is_undefined_for_constant_series():
    t_stat, p_value = newey_west_tstat([0.01] * 10, lags=1)
    assert np.isnan(t_stat) and np.isnan(p_value)


def test_bh_fdr_rejects_the_clear_signal_only():
    pvalues = [0.001, 0.008, 0.039, 0.041, 0.042, 0.06, 0.074, 0.205, 0.212]
    rejected = bh_fdr(pvalues, q=0.05)
    # Thresholds are 0.05*i/9: 0.008 clears 0.0111 but 0.039 does not clear 0.0167.
    assert rejected[:2] == [True, True]
    assert not any(rejected[2:])


def test_bh_qvalues_are_monotone_in_p_and_match_rejections():
    pvalues = [0.001, 0.04, 0.03, 0.2]
    qvalues = bh_qvalues(pvalues)
    assert all(q >= p for q, p in zip(qvalues, pvalues, strict=True))
    assert qvalues[0] == min(qvalues)


def test_deflated_sharpe_penalises_more_trials():
    rng = np.random.default_rng(9)
    returns = pd.Series(rng.normal(0.0008, 0.01, size=500))
    few = deflated_sharpe(returns, n_trials=1)["dsr"]
    many = deflated_sharpe(returns, n_trials=100)["dsr"]
    assert few > many


def test_deflated_sharpe_prefers_a_strong_track_record():
    rng = np.random.default_rng(13)
    strong = pd.Series(rng.normal(0.002, 0.01, size=750))
    weak = pd.Series(rng.normal(-0.001, 0.01, size=750))
    assert deflated_sharpe(strong, n_trials=9)["dsr"] > 0.9
    assert deflated_sharpe(weak, n_trials=9)["dsr"] < 0.1


def test_sharpe_ratio_is_annualised():
    rng = np.random.default_rng(21)
    returns = pd.Series(rng.normal(0.0005, 0.01, size=1000))
    # Roughly 0.05%/1% per day, so annualised Sharpe should be a small positive number.
    assert 0.0 < sharpe_ratio(returns) < 3.0


def test_empty_inputs_do_not_raise():
    assert bh_fdr([]) == []
    assert bh_qvalues([]) == []
    assert np.isnan(deflated_sharpe([], n_trials=1)["dsr"])
    assert np.isnan(newey_west_tstat([])[0])
