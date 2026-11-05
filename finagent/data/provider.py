"""Provider protocol: the only surface the rest of the system may use.

Every method is point-in-time aware (`as_of`) and returns normalised English
column names. Concrete providers are responsible for retries, caching and
degradation; callers only see clean frames or a ProviderError.
"""

from __future__ import annotations

from datetime import date
from typing import Protocol, runtime_checkable

import pandas as pd

# Canonical schemas -------------------------------------------------------
DATE = "date"
SYMBOL = "symbol"

ETF_DAILY_COLUMNS = [
    "date",
    "symbol",
    "open",
    "close",
    "high",
    "low",
    "volume",
    "amount",
    "amplitude",
    "pct_change",
    "change",
    "turnover",
]
INDEX_DAILY_COLUMNS = [
    "date",
    "index_code",
    "open",
    "close",
    "high",
    "low",
    "volume",
    "amount",
    "amplitude",
    "pct_change",
    "change",
    "turnover",
]
VALUATION_COLUMNS = ["date", "index_code", "pe", "pb", "dividend_yield"]
SECTOR_FLOW_COLUMNS = [
    "date",
    "sector",
    "pct_change",
    "main_net_inflow",
    "main_net_inflow_pct",
    "super_large_net_inflow",
    "large_net_inflow",
    "medium_net_inflow",
    "small_net_inflow",
]
MACRO_NAMES = ("pmi", "cpi", "ppi", "m2", "lpr")


class ProviderError(RuntimeError):
    """Source failed and no acceptable cached fallback exists."""


class DataNotAvailable(ProviderError):
    """The source does not publish this dataset for the requested key."""


class StaleDataWarning(UserWarning):
    """Returned cached data, but it is older than requested."""


@runtime_checkable
class DataProvider(Protocol):
    def etf_daily(self, symbols: list[str], start: date, end: date) -> pd.DataFrame: ...

    def etf_snapshot(self, as_of: date) -> pd.DataFrame: ...

    def index_daily(self, index_code: str, start: date, end: date) -> pd.DataFrame: ...

    def index_valuation(self, index_code: str, start: date, end: date) -> pd.DataFrame: ...

    def sector_flow_rank(self, as_of: date, indicator: str = "今日") -> pd.DataFrame: ...

    def sector_flow_hist(self, sector: str, start: date, end: date) -> pd.DataFrame: ...

    def trade_calendar(self) -> pd.DataFrame: ...

    def macro(self, name: str) -> pd.DataFrame: ...

    def bond_yield(self, start: date, end: date) -> pd.DataFrame: ...
