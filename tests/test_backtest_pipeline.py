"""End-to-end suite on a synthetic cache: report shape and point-in-time safety."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from finagent.backtest.costs import cost_from_bps
from finagent.backtest.report import run_backtest_suite
from finagent.data.cache import ParquetCache
from finagent.data.universe import ETF, Universe


def _cache(tmp_path, n_symbols: int = 12, n_days: int = 300, n_future: int = 40):
    rng = np.random.default_rng(21)
    index = pd.bdate_range("2024-01-01", periods=n_days + n_future)
    drift = np.linspace(-0.0004, 0.0006, n_symbols)
    prices = 100 * np.cumprod(1 + rng.normal(0, 0.008, size=(len(index), n_symbols)) + drift, axis=0)
    cache = ParquetCache(tmp_path / "cache")
    symbols = [f"51{i:04d}" for i in range(n_symbols)]
    for j, symbol in enumerate(symbols):
        frame = pd.DataFrame(
            {
                "date": index,
                "symbol": symbol,
                "open": prices[:, j] * 1.001,
                "high": prices[:, j] * 1.005,
                "low": prices[:, j] * 0.995,
                "close": prices[:, j],
                "volume": 1_000_000.0,
                "amount": 2e8,
            }
        )
        path = cache.parquet_path("etf_daily_hfq", symbol)
        path.parent.mkdir(parents=True, exist_ok=True)
        frame.to_parquet(path, index=False)
    universe = Universe(
        version="u-test",
        etfs=[
            ETF(symbol=s, name=f"ETF{j}", category="broad" if j % 2 == 0 else "sector")
            for j, s in enumerate(symbols)
        ],
    )
    return cache.root, universe, index, symbols


def _run(cache_dir, universe, start, end, out_dir=None, **kwargs):
    return run_backtest_suite(
        universe,
        start=start,
        end=end,
        cache_dir=cache_dir,
        write=out_dir is not None,
        out_dir=out_dir,
        **kwargs,
    )


def test_suite_writes_a_complete_report(tmp_path):
    cache_dir, universe, index, _ = _cache(tmp_path)
    out_dir = tmp_path / "reports"
    payload = _run(
        cache_dir, universe, index[80].date(), index[-1].date(), out_dir=out_dir, cost=cost_from_bps(7)
    )
    report = payload["report"]

    assert set(report["strategies"]) == {"equal_weight", "policy_no_tilt", "policy_tilt", "top_10"}
    for block in report["strategies"].values():
        for key in ("cagr", "ann_vol", "sharpe", "max_drawdown", "annual_turnover", "annual_cost"):
            assert key in block["metrics"]
    assert report["diagnostics"]["pbo"]["n_combinations"] > 0
    assert report["diagnostics"]["cpcv"]["summary"]
    assert set(report["diagnostics"]["dsr"]) == set(report["strategies"])

    written = json.loads((out_dir / f"backtest_{index[-1].date()}.json").read_text("utf-8"))
    assert written["window"]["end"] == index[-1].date().isoformat()
    nav = pd.read_csv(out_dir / f"backtest_{index[-1].date()}_daily.csv", parse_dates=["date"]).set_index("date")
    assert list(nav.columns) == list(report["strategies"])
    assert np.isfinite(nav.to_numpy()).all()


def test_results_do_not_change_when_later_data_is_added(tmp_path):
    cache_dir, universe, index, _ = _cache(tmp_path)
    early_end = index[-41].date()
    short = _run(cache_dir, universe, index[80].date(), early_end)
    long = _run(cache_dir, universe, index[80].date(), index[-1].date())

    for name in short["results"]:
        a = short["results"][name].daily["nav"]
        b = long["results"][name].daily["nav"].reindex(a.index)
        assert np.allclose(a.to_numpy(), b.to_numpy(), equal_nan=True), name


def test_rebalance_frequency_changes_turnover(tmp_path):
    cache_dir, universe, index, _ = _cache(tmp_path)
    daily = _run(cache_dir, universe, index[80].date(), index[-1].date(), rebalance_days=1)
    monthly = _run(cache_dir, universe, index[80].date(), index[-1].date(), rebalance_days=21)
    daily_to = daily["report"]["strategies"]["policy_tilt"]["metrics"]["annual_turnover"]
    monthly_to = monthly["report"]["strategies"]["policy_tilt"]["metrics"]["annual_turnover"]
    assert daily_to > monthly_to


def test_costs_reduce_the_net_sharpe(tmp_path):
    cache_dir, universe, index, _ = _cache(tmp_path)
    free = _run(cache_dir, universe, index[80].date(), index[-1].date(), cost=cost_from_bps(0))
    costly = _run(cache_dir, universe, index[80].date(), index[-1].date(), cost=cost_from_bps(50))
    for name in free["report"]["strategies"]:
        assert (
            costly["report"]["strategies"][name]["metrics"]["sharpe"]
            <= free["report"]["strategies"][name]["gross_metrics"]["sharpe"] + 1e-9
        )


def test_empty_window_is_rejected(tmp_path):
    cache_dir, universe, index, _ = _cache(tmp_path)
    with pytest.raises(ValueError, match="no price data"):
        _run(cache_dir, universe, "2030-01-01", "2030-02-01")
