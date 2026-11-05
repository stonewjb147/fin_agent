"""Shared fixtures. Tests are offline: no AKShare, no network."""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest


@pytest.fixture
def trading_days() -> pd.DatetimeIndex:
    return pd.bdate_range("2024-06-03", "2024-07-31")


@pytest.fixture
def etf_frame(trading_days) -> pd.DataFrame:
    n = len(trading_days)
    close = 3.0 * np.cumprod(1 + np.linspace(-0.002, 0.003, n))
    return pd.DataFrame(
        {
            "date": trading_days,
            "symbol": "510300",
            "open": close * 0.999,
            "high": close * 1.004,
            "low": close * 0.996,
            "close": close,
            "volume": np.full(n, 1_000_000),
            "amount": np.full(n, 3_000_000.0),
        }
    )


@pytest.fixture
def universe_yaml(tmp_path):
    payload = """
version: u-test
etfs:
  - symbol: "510300"
    name: 沪深300ETF
    category: broad
    tracked_index: "000300"
    benchmark: true
    effective_from: "2012-05-28"
  - symbol: "512880"
    name: 证券ETF
    category: sector
    tracked_index: "399975"
    effective_from: "2016-08-08"
  - symbol: "511010"
    name: 国债ETF
    category: bond
    tracked_index: "000140"
    index_data: false
    effective_from: "2013-03-25"
    effective_to: "2025-01-01"
"""
    path = tmp_path / "universe.yaml"
    path.write_text(payload, encoding="utf-8")
    return path


@pytest.fixture
def as_of() -> date:
    return date(2024, 6, 30)
