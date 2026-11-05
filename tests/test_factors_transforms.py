from __future__ import annotations

import numpy as np
import pandas as pd

from finagent.factors.transforms import neutralize_cs, rank_cs, winsorize_cs, zscore_cs


def _frame() -> pd.DataFrame:
    index = pd.bdate_range("2024-01-01", periods=2)
    return pd.DataFrame(
        {
            "a": [1.0, 10.0],
            "b": [2.0, 20.0],
            "c": [3.0, 30.0],
            "d": [1000.0, 40.0],
        },
        index=index,
    )


def test_winsorize_clips_the_outlier():
    df = _frame()
    clipped = winsorize_cs(df, lower=0.0, upper=0.75)
    assert clipped.loc[index := clipped.index[0], "d"] < 1000.0
    assert clipped.loc[index, "a"] == 1.0


def test_zscore_is_zero_mean_unit_std_per_row():
    z = zscore_cs(_frame()[["a", "b", "c"]])
    assert np.allclose(z.mean(axis=1), 0.0)
    assert np.allclose(z.std(axis=1, ddof=0), 1.0)


def test_zscore_of_constant_row_is_zero_not_nan():
    df = pd.DataFrame(
        {"a": [5.0, 5.0], "b": [5.0, 5.0]}, index=pd.bdate_range("2024-01-01", periods=2)
    )
    z = zscore_cs(df)
    assert (z == 0.0).all().all()


def test_rank_is_a_percentile_per_row():
    r = rank_cs(_frame())
    assert np.allclose(r.loc[r.index[1]].sort_values().to_numpy(), [0.25, 0.5, 0.75, 1.0])


def test_neutralize_demeans_within_category():
    df = _frame()
    groups = {"a": "broad", "b": "broad", "c": "sector", "d": "sector"}
    out = neutralize_cs(df, groups)
    for row in out.index:
        assert abs(out.loc[row, ["a", "b"]].mean()) < 1e-12
        assert abs(out.loc[row, ["c", "d"]].mean()) < 1e-12


def test_neutralize_leaves_singletons_alone():
    df = _frame()
    groups = {"a": "broad", "b": "broad", "c": "sector", "d": "commodity"}
    out = neutralize_cs(df, groups)
    assert out.loc[out.index[0], "d"] == df.loc[df.index[0], "d"]


def test_neutralize_rejects_unknown_method():
    import pytest

    with pytest.raises(ValueError):
        neutralize_cs(_frame(), {}, method="winsorize")
