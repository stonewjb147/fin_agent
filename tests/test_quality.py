from __future__ import annotations

import pandas as pd

from finagent.data.quality import check_frame, check_freshness, merge_reports


def codes(report) -> set[str]:
    return {i.code for i in report.issues}


def test_clean_frame_has_no_issues(etf_frame):
    report = check_frame(etf_frame, "etf_daily_hfq", "510300", "2024-07-31")
    assert report.ok
    assert not report.has_warnings
    assert report.metrics["last_date"] == "2024-07-31"


def test_future_data_is_an_error(etf_frame):
    report = check_frame(etf_frame, "etf_daily_hfq", "510300", "2024-06-30")
    assert not report.ok
    assert "future_data" in codes(report)


def test_allow_future_is_for_forward_looking_calendars():
    df = pd.DataFrame({"date": ["2024-06-03", "2024-12-31"], "value": [1, 2]})
    flagged = check_frame(df, "trade_calendar", "all", "2024-06-30", price_cols=())
    assert "future_data" in codes(flagged)

    allowed = check_frame(
        df, "trade_calendar", "all", "2024-06-30", price_cols=(), allow_future=True
    )
    assert allowed.ok


def test_empty_frame_is_an_error():
    report = check_frame(pd.DataFrame(), "etf_daily_hfq", "x", "2024-06-30")
    assert not report.ok
    assert "empty" in codes(report)


def test_non_positive_price_is_an_error(etf_frame):
    bad = etf_frame.copy()
    bad.loc[0, "close"] = 0.0
    report = check_frame(bad, "etf_daily_hfq", "510300", "2024-07-31")
    assert "non_positive_price" in codes(report)
    assert not report.ok


def test_duplicate_dates_detected_when_keys_given():
    df = pd.DataFrame({"date": ["2024-06-03", "2024-06-03"], "symbol": "x", "close": [1.0, 1.1]})
    report = check_frame(df, "etf_daily_hfq", "x", "2024-07-01", keys=("date", "symbol"))
    assert "duplicate_keys" in codes(report)


def test_high_missing_ratio_is_a_warning(etf_frame):
    df = etf_frame.copy()
    df.loc[df.index[:10], "close"] = None
    report = check_frame(df, "etf_daily_hfq", "510300", "2024-07-31")
    assert report.ok  # warnings do not fail the gate
    assert "high_missing" in codes(report)


def test_missing_date_column_is_fatal():
    report = check_frame(pd.DataFrame({"close": [1.0]}), "x", "x", "2024-06-30")
    assert "missing_date_column" in codes(report)


def test_freshness_flags_stale_data():
    fresh = check_freshness("2024-06-28", "2024-06-30", dataset="d", key="k")
    assert fresh.ok

    stale = check_freshness("2024-05-01", "2024-06-30", dataset="d", key="k", max_lag_days=5)
    assert not stale.ok
    assert "stale" in codes(stale)

    missing = check_freshness(None, "2024-06-30", dataset="d", key="k")
    assert "no_last_date" in codes(missing)


def test_merge_reports_aggregates_ok():
    good = check_frame(pd.DataFrame({"date": ["2024-06-03"], "close": [1.0]}), "d", "k", "2024-06-30")
    bad = check_frame(pd.DataFrame(), "d", "k2", "2024-06-30")
    merged = merge_reports([good, bad])
    assert merged["ok"] is False
    assert len(merged["reports"]) == 2
