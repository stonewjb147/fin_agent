from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from finagent.data.panel import (
    align_panel,
    forward_returns,
    long_to_wide,
    slice_as_of,
    to_returns,
    trailing_return,
)


def test_slice_as_of_excludes_future_rows(etf_frame):
    sliced = slice_as_of(etf_frame, "2024-06-30")
    assert len(sliced) > 0
    assert pd.to_datetime(sliced["date"]).max() <= pd.Timestamp("2024-06-30")
    assert pd.to_datetime(etf_frame["date"]).max() > pd.Timestamp("2024-06-30")


def test_slice_as_of_is_inclusive():
    df = pd.DataFrame({"date": ["2024-06-28", "2024-06-30", "2024-07-01"], "close": [1, 2, 3]})
    out = slice_as_of(df, "2024-06-30")
    assert out["close"].tolist() == [1, 2]


def test_panel_as_of_2024_06_30_has_no_later_data(etf_frame):
    """Phase 1 acceptance: a 2024-06-30 panel must not see July."""
    wide = long_to_wide(etf_frame, "close")
    pit = wide.loc[wide.index <= pd.Timestamp("2024-06-30")]
    assert pit.index.max() <= pd.Timestamp("2024-06-30")
    assert pit.shape[0] < wide.shape[0]


def test_long_to_wide_pivots_on_date_and_symbol():
    df = pd.DataFrame(
        {
            "date": ["2024-06-03", "2024-06-03", "2024-06-04"],
            "symbol": ["510300", "510500", "510300"],
            "close": [1.0, 2.0, 1.1],
        }
    )
    wide = long_to_wide(df, "close")
    assert list(wide.columns) == ["510300", "510500"]
    assert wide.loc[pd.Timestamp("2024-06-04"), "510300"] == pytest.approx(1.1)
    assert np.isnan(wide.loc[pd.Timestamp("2024-06-04"), "510500"])


def test_forward_returns_are_nan_at_the_tail():
    close = pd.DataFrame({"a": [1.0, 2.0, 3.0, 4.0]})
    fwd = forward_returns(close, horizon=2)
    assert fwd["a"].iloc[0] == pytest.approx(2.0)
    assert fwd["a"].iloc[-2:].isna().all()


def test_forward_returns_rejects_bad_horizon():
    with pytest.raises(ValueError):
        forward_returns(pd.DataFrame({"a": [1.0]}), horizon=0)


def test_trailing_return_skips_recent_days():
    close = pd.DataFrame({"a": [1.0, 1.1, 1.2, 1.3, 1.4]})
    trailing = trailing_return(close, window=2, skip=1)
    # at row 3: close[2]=1.2 / close[0]=1.0 - 1
    assert trailing["a"].iloc[3] == pytest.approx(0.2)


def test_returns_and_align():
    close = pd.DataFrame({"a": [1.0, 1.1, 1.21]}, index=pd.bdate_range("2024-01-01", periods=3))
    rets = to_returns(close)
    assert np.isnan(rets["a"].iloc[0])
    assert rets["a"].iloc[1] == pytest.approx(0.1)

    other = pd.DataFrame({"a": [5.0, 6.0], "b": [1.0, 1.0]}, index=close.index[1:])
    aligned = align_panel({"x": close, "y": other})
    pd.testing.assert_index_equal(aligned["x"].index, aligned["y"].index)
    pd.testing.assert_index_equal(aligned["x"].columns, aligned["y"].columns)
