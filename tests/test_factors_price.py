from __future__ import annotations

import numpy as np
import pandas as pd

from finagent.factors import FACTORS, get_factor
from finagent.factors.price import momentum, reversal, volatility


def _close(series: dict[str, np.ndarray], index: pd.DatetimeIndex) -> pd.DataFrame:
    return pd.DataFrame(series, index=index)


def test_registry_exposes_three_price_factors():
    assert set(FACTORS) >= {"momentum_20", "reversal_5", "volatility_20"}
    assert [get_factor(n).direction for n in ("momentum_20", "reversal_5", "volatility_20")] == [
        1,
        -1,
        -1,
    ]
    assert get_factor("momentum_20").lookback >= 21


def test_momentum_ranks_geometric_growth():
    index = pd.bdate_range("2024-01-01", periods=40)
    fast = 100 * 1.01 ** np.arange(40)
    slow = 100 * 1.002 ** np.arange(40)
    flat = np.full(40, 100.0)
    close = _close({"fast": fast, "slow": slow, "flat": flat}, index)

    result = momentum(close, window=20, skip=1)
    last = result.iloc[-1]
    assert last["fast"] > last["slow"] > last["flat"]


def test_momentum_skips_the_most_recent_day():
    index = pd.bdate_range("2024-01-01", periods=30)
    close = _close({"a": np.full(30, 100.0)}, index)
    # A one-day spike on the last bar must not enter a momentum that skips it.
    close.iloc[-1, 0] = 200.0
    result = momentum(close, window=20, skip=1)
    assert result.iloc[-1, 0] == 0.0


def test_constant_price_has_zero_volatility():
    index = pd.bdate_range("2024-01-01", periods=40)
    close = _close({"a": np.full(40, 3.5)}, index)
    result = volatility(close, window=20).iloc[-1, 0]
    assert result == 0.0


def test_reversal_is_the_raw_trailing_return():
    index = pd.bdate_range("2024-01-01", periods=20)
    close = _close({"a": np.linspace(10, 20, 20)}, index)
    # Values stay raw (a rise shows up positive); the "-1" lives in direction.
    assert reversal(close, window=5).iloc[-1, 0] > 0
    assert get_factor("reversal_5").direction == -1


def test_no_lookahead_when_future_rows_are_appended():
    index = pd.bdate_range("2024-01-01", periods=60)
    rng = np.random.default_rng(7)
    prices = 100 * np.cumprod(1 + rng.normal(0, 0.01, size=(60, 3)), axis=0)
    close = pd.DataFrame(prices, index=index, columns=["a", "b", "c"])

    cutoff = 40
    past = close.iloc[:cutoff]
    for spec in ("momentum_20", "reversal_5", "volatility_20"):
        full = get_factor(spec).compute(close).iloc[:cutoff]
        truncated = get_factor(spec).compute(past)
        pd.testing.assert_frame_equal(full, truncated, check_freq=False)


def test_shifted_windows_keep_history_unchanged():
    index = pd.bdate_range("2024-01-01", periods=80)
    rng = np.random.default_rng(11)
    close = pd.DataFrame(
        100 * np.cumprod(1 + rng.normal(0, 0.02, size=(80, 2)), axis=0),
        index=index,
        columns=["x", "y"],
    )
    full = get_factor("momentum_20").compute(close)
    partial = get_factor("momentum_20").compute(close.iloc[:55])
    pd.testing.assert_frame_equal(full.iloc[:55], partial, check_freq=False)
