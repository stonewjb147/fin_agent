"""Price-based factors: momentum, short-term reversal, volatility.

All three take the date x symbol close matrix produced by
`finagent.data.panel.long_to_wide` and return a matrix of the same shape.
Values are raw (no sign flipping); the sign convention lives in `direction`
so that IC stays interpretable.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from finagent import config
from finagent.data.panel import to_returns, trailing_return
from finagent.factors.spec import FactorSpec


def momentum(close: pd.DataFrame, window: int = 20, skip: int = 1) -> pd.DataFrame:
    """Trailing return over `window` days, ignoring the most recent `skip`.

    Skipping the last day is deliberate: the most recent bar is dominated by
    short-term reversal, which would otherwise contaminate the momentum signal.
    """
    return trailing_return(close, window=window, skip=skip)


def reversal(close: pd.DataFrame, window: int = 5) -> pd.DataFrame:
    """Trailing return over `window` days. Lower (more negative) is attractive."""
    return trailing_return(close, window=window)


def volatility(close: pd.DataFrame, window: int = 20) -> pd.DataFrame:
    """Annualised standard deviation of daily returns. Lower is attractive."""
    return to_returns(close).rolling(window, min_periods=window).std() * np.sqrt(
        config.TRADING_DAYS_PER_YEAR
    )


PRICE_FACTORS: dict[str, FactorSpec] = {
    "momentum_20": FactorSpec(
        name="momentum_20",
        group="price",
        lookback=21,  # 20-day return plus the 1-day skip
        direction=1,
        description="20-day price momentum, skipping the most recent day",
        compute=lambda close: momentum(close, window=20, skip=1),
    ),
    "reversal_5": FactorSpec(
        name="reversal_5",
        group="price",
        lookback=5,
        direction=-1,
        description="5-day return; recent losers are expected to bounce",
        compute=lambda close: reversal(close, window=5),
    ),
    "volatility_20": FactorSpec(
        name="volatility_20",
        group="price",
        lookback=21,
        direction=-1,
        description="20-day realised volatility, annualised",
        compute=lambda close: volatility(close, window=20),
    ),
}
