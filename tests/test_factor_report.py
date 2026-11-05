from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from finagent.data.cache import ParquetCache
from finagent.data.universe import ETF, Universe
from finagent.factors import get_factor, load_close_panel
from finagent.research.report import run_factor_report


def _synthetic_cache(tmp_path, n_symbols: int = 12, n_days: int = 220, n_future: int = 30) -> tuple:
    """Write a cache with a known momentum effect plus `n_future` days after as_of."""
    rng = np.random.default_rng(42)
    index = pd.bdate_range("2024-01-01", periods=n_days + n_future)
    drift = np.linspace(-0.0006, 0.0006, n_symbols)  # cross-sectional dispersion
    shocks = rng.normal(0, 0.008, size=(len(index), n_symbols))
    prices = 100 * np.cumprod(1 + shocks + drift, axis=0)

    cache = ParquetCache(tmp_path / "cache")
    symbols = [f"51{i:04d}" for i in range(n_symbols)]
    for j, symbol in enumerate(symbols):
        frame = pd.DataFrame(
            {
                "date": index,
                "symbol": symbol,
                "open": prices[:, j],
                "high": prices[:, j] * 1.005,
                "low": prices[:, j] * 0.995,
                "close": prices[:, j],
                "volume": 1_000_000,
                "amount": 2e8,
            }
        )
        path = cache.parquet_path("etf_daily_hfq", symbol)
        path.parent.mkdir(parents=True, exist_ok=True)
        frame.to_parquet(path, index=False)

    etfs = [
        ETF(symbol=s, name=f"ETF{j}", category="broad" if j % 2 else "sector")
        for j, s in enumerate(symbols)
    ]
    universe = Universe(version="u-test", etfs=etfs)
    as_of = index[n_days - 1].date()
    return cache.root, universe, as_of, index


def test_report_is_written_and_complete(tmp_path):
    cache_dir, universe, as_of, _ = _synthetic_cache(tmp_path)
    out_dir = tmp_path / "factors"
    quality_dir = tmp_path / "quality"

    report = run_factor_report(
        universe,
        as_of=as_of,
        cache_dir=cache_dir,
        horizons=(1, 5, 20),
        out_dir=out_dir,
        quality_dir=quality_dir,
    )

    assert (out_dir / f"{as_of.isoformat()}.parquet").exists()
    path = quality_dir / f"factor_report_{as_of.isoformat()}.json"
    assert path.exists()
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["as_of"] == as_of.isoformat()
    assert len(saved["tests"]) == 9
    for test in saved["tests"]:
        for key in (
            "ic_mean",
            "ic_std",
            "icir",
            "nw_t",
            "p_value",
            "q_value",
            "coverage",
            "long_short_sr",
            "dsr",
            "lags",
        ):
            assert key in test
    assert saved["meta"]["m_tests"] == 9
    assert saved["meta"]["execution_lag"] == 1
    assert report["n_symbols"] == 12


def test_report_never_uses_data_after_as_of(tmp_path):
    cache_dir, universe, as_of, index = _synthetic_cache(tmp_path)
    report = run_factor_report(
        universe,
        as_of=as_of,
        cache_dir=cache_dir,
        write=False,
    )
    assert report["data_end"] == as_of.isoformat()

    factors = run_factor_report(
        universe, as_of=as_of, cache_dir=cache_dir, write=True,
        out_dir=tmp_path / "f", quality_dir=tmp_path / "q",
    )
    panel = pd.read_parquet(factors["factor_file"])
    assert pd.to_datetime(panel["date"]).max().date() <= as_of


def test_appending_future_rows_does_not_change_the_report(tmp_path):
    cache_dir, universe, as_of, _ = _synthetic_cache(tmp_path)
    first = run_factor_report(universe, as_of=as_of, cache_dir=cache_dir, write=False)

    # Extend every cached symbol with more rows; the as_of report must not move.
    cache = ParquetCache(cache_dir)
    for symbol in universe.symbols(as_of):
        frame = cache.read("etf_daily_hfq", symbol)
        extra = frame.iloc[-1:].copy()
        extra["date"] = pd.to_datetime(extra["date"]) + pd.Timedelta(days=1)
        pd.concat([frame, extra], ignore_index=True).to_parquet(
            cache.parquet_path("etf_daily_hfq", symbol), index=False
        )
    second = run_factor_report(universe, as_of=as_of, cache_dir=cache_dir, write=False)

    assert first["data_end"] == second["data_end"] == as_of.isoformat()
    assert [t["ic_mean"] for t in first["tests"]] == pytest.approx(
        [t["ic_mean"] for t in second["tests"]]
    )


def test_load_close_panel_rejects_a_future_as_of_argument(tmp_path):
    cache_dir, universe, as_of, index = _synthetic_cache(tmp_path)
    close = load_close_panel(cache_dir, universe.symbols(as_of), as_of)
    assert close.index.max() <= pd.Timestamp(as_of)
    assert close.shape[1] == len(universe.etfs)


def test_unknown_factor_name_is_rejected():
    with pytest.raises(KeyError, match="available"):
        get_factor("momentum_999")


def test_report_rejects_an_universe_without_prices(tmp_path):
    cache_dir, _, as_of, _ = _synthetic_cache(tmp_path)
    etfs = [ETF(symbol="999999", name="ETF", category="broad")]
    universe = Universe(version="u-empty", etfs=etfs)
    with pytest.raises(ValueError):
        run_factor_report(universe, as_of=as_of, cache_dir=cache_dir, write=False)


def test_execution_lag_shifts_the_last_usable_date(tmp_path):
    cache_dir, universe, as_of, _ = _synthetic_cache(tmp_path)
    lagged = run_factor_report(
        universe, as_of=as_of, cache_dir=cache_dir, horizons=(1,), execution_lag=1, write=False
    )
    same_day = run_factor_report(
        universe, as_of=as_of, cache_dir=cache_dir, horizons=(1,), execution_lag=0, write=False
    )
    assert lagged["tests"][0]["n"] < same_day["tests"][0]["n"]
