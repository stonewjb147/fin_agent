"""Contract tests for AKShare normalisation.

Free sources drift: these fixtures encode the raw column names observed on
2026-11-05, so a rename upstream fails here instead of silently producing
all-NaN factors.
"""

from __future__ import annotations

import pandas as pd
import pytest

from finagent.data.akshare_provider import AkshareProvider
from finagent.data.provider import DataNotAvailable


def test_normalize_etf_history_maps_em_columns():
    raw = pd.DataFrame(
        {
            "日期": ["2024-06-03", "2024-06-04"],
            "开盘": [1.0, 1.1],
            "收盘": [1.1, 1.2],
            "最高": [1.15, 1.25],
            "最低": [0.99, 1.09],
            "成交量": [1000, 1100],
            "成交额": [1100.0, 1200.0],
            "振幅": [1.0, 1.0],
            "涨跌幅": [1.0, 9.09],
            "涨跌额": [0.01, 0.1],
            "换手率": [0.5, 0.6],
        }
    )
    out = AkshareProvider.normalize_etf_history(raw, "510300")
    expected = {"date", "symbol", "open", "high", "low", "close", "volume", "amount"}
    assert expected <= set(out.columns)
    assert out["symbol"].iloc[0] == "510300"
    assert pd.api.types.is_datetime64_any_dtype(out["date"])


def test_normalize_etf_history_empty_is_empty_frame():
    out = AkshareProvider.normalize_etf_history(pd.DataFrame(), "510300")
    assert out.empty


def test_normalize_index_value_snapshot_uses_rolling_pe():
    raw = pd.DataFrame(
        {
            "日期": ["2026-11-04", "2026-11-03"],
            "指数代码": ["000300", "000300"],
            "指数简称": ["沪深300", "沪深300"],
            "市盈率1": [13.98, 13.83],
            "市盈率2": [15.43, 15.08],
            "股息率1": [3.00, 3.03],
            "股息率2": [2.65, 2.71],
        }
    )
    out = AkshareProvider.normalize_index_value_snapshot(raw, "000300")
    assert out["pe"].tolist() == [15.43, 15.08]
    assert out["pe_static"].tolist() == [13.98, 13.83]
    assert out["pb"].isna().all()
    assert out["index_code"].iloc[0] == "000300"
    assert out["dividend_yield"].iloc[0] == pytest.approx(3.00)


def test_normalize_index_value_snapshot_rejects_empty():
    with pytest.raises(DataNotAvailable):
        AkshareProvider.normalize_index_value_snapshot(pd.DataFrame(), "000300")


def test_normalize_csindex_valuation_fills_missing_columns():
    raw = pd.DataFrame(
        {
            "日期": ["2024-06-03"],
            "开盘": [3500.0],
            "收盘": [3550.0],
            "最高": [3560.0],
            "最低": [3490.0],
            "成交量": [1e8],
            "成交金额": [2e11],
            "涨跌幅": [1.2],
            "滚动市盈率": [12.5],
        }
    )
    out = AkshareProvider.normalize_csindex_valuation(raw, "000300")
    assert out["pe"].iloc[0] == 12.5
    assert out["index_code"].iloc[0] == "000300"
    assert "pb" in out.columns
