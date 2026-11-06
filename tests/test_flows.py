"""Phase 5 flow factors: status-first loaders and PIT-safe scores."""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from finagent.data.cache import ParquetCache
from finagent.data.universe import ETF, Universe
from finagent.flows import (
    build_flows_report,
    flow_factor_scores,
    load_nav_history,
    load_sector_flow_history,
    load_share_snapshots,
    premium_discount_scores,
    share_change_scores,
)


def _universe() -> Universe:
    return Universe(
        version="u-test",
        etfs=[
            ETF(symbol="510300", name="沪深300ETF", category="broad"),
            ETF(symbol="512880", name="证券ETF", category="sector", flow_sectors=("证券",)),
            ETF(symbol="512800", name="银行ETF", category="sector", flow_sectors=("银行",)),
        ],
    )


def _write_flow(cache: ParquetCache, day: str, rows: list[tuple[str, float]]) -> None:
    frame = pd.DataFrame(
        [
            {"date": day, "sector": sector, "net_inflow": inflow, "pct_change": 0.0, "company_count": 10}
            for sector, inflow in rows
        ]
    )
    cache.write("sector_flow_rank", day, frame, source="test")


def test_one_snapshot_is_not_a_flow_trend(tmp_path):
    cache = ParquetCache(tmp_path)
    _write_flow(cache, "2024-06-28", [("证券", 5.0), ("银行", -3.0)])

    history, status = load_sector_flow_history(cache, "2024-06-28", window=5)

    assert not status.available
    assert "need 5" in status.reason
    assert len(history) == 2


def test_flow_scores_use_accumulated_snapshots_and_respect_as_of(tmp_path):
    cache = ParquetCache(tmp_path)
    days = ["2024-06-24", "2024-06-25", "2024-06-26", "2024-06-27", "2024-06-28"]
    for index, day in enumerate(days):
        _write_flow(cache, day, [("证券", 10.0 + index), ("银行", -10.0 - index)])
    # A snapshot after as_of must never reach the factor.
    _write_flow(cache, "2024-07-01", [("证券", -100.0), ("银行", 100.0)])

    history, status = load_sector_flow_history(cache, "2024-06-28", window=5)
    scores = flow_factor_scores(history, _universe(), "2024-06-28", window=5).set_index("symbol")

    assert status.available
    assert scores.loc["512880", "flow_z"] > 0
    assert scores.loc["512800", "flow_z"] < 0
    assert "510300" not in scores.index  # no sector mapping, no flow factor
    assert scores.loc["512880", "sectors"] == "证券"


def test_share_change_needs_two_snapshots_and_reports_its_span(tmp_path):
    cache = ParquetCache(tmp_path)
    first = pd.DataFrame(
        [{"date": "2024-06-01", "symbol": "512880", "name": "A", "shares": 100.0},
         {"date": "2024-06-01", "symbol": "512800", "name": "B", "shares": 100.0}]
    )
    second = pd.DataFrame(
        [{"date": "2024-06-21", "symbol": "512880", "name": "A", "shares": 150.0},
         {"date": "2024-06-21", "symbol": "512800", "name": "B", "shares": 100.0}]
    )
    cache.write("etf_scale_sse", "2024-06-01", first, source="test")
    cache.write("etf_scale_sse", "2024-06-21", second, source="test")

    history, status = load_share_snapshots(cache, "2024-06-21")
    scores, change_status = share_change_scores(history, window_days=20)
    scores = scores.set_index("symbol")

    assert status.available and change_status.available
    assert scores.loc["512880", "share_change"] == pytest.approx(0.5)
    assert scores.loc["512880", "share_z"] > scores.loc["512800", "share_z"]
    assert scores.loc["512880", "span_days"] == 20


def test_premium_is_close_over_the_same_day_nav(tmp_path):
    cache = ParquetCache(tmp_path)
    nav = pd.DataFrame(
        [
            {"date": "2024-06-27", "symbol": "512880", "unit_nav": 1.0},
            {"date": "2024-06-27", "symbol": "512800", "unit_nav": 1.0},
        ]
    )
    cache.write("etf_nav", "512880", nav[nav["symbol"] == "512880"], source="test")
    cache.write("etf_nav", "512800", nav[nav["symbol"] == "512800"], source="test")
    close = pd.DataFrame(
        {"512880": [1.10], "512800": [1.00]}, index=pd.DatetimeIndex(["2024-06-27"])
    )

    history, status = load_nav_history(cache, ["512880", "512800"], "2024-06-27")
    scores, nav_status = premium_discount_scores(close, history)
    scores = scores.set_index("symbol")

    assert status.available and nav_status.available
    assert scores.loc["512880", "premium"] == pytest.approx(0.10)
    assert scores.loc["512880", "premium_z"] > scores.loc["512800", "premium_z"]
    assert scores.loc["512880", "nav_date"] == "2024-06-27"


def test_flows_report_names_every_missing_source(tmp_path):
    cache = ParquetCache(tmp_path)
    # Only sector flow exists, and only one day of it.
    _write_flow(cache, "2024-06-28", [("证券", 5.0), ("银行", -3.0)])
    report = build_flows_report(_universe(), date(2024, 6, 28), cache_dir=cache)

    assert report["sources"]["sector_flow_rank"]["available"] is False
    assert report["sources"]["etf_scale_sse"]["available"] is False
    assert report["sources"]["etf_nav"]["available"] is False
    assert report["sources"]["news"]["available"] is False
    assert report["sector_flow"] == []
    assert report["premium_discount"] == []
