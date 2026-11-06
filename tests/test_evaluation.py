from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from finagent.backtest.costs import cost_from_bps
from finagent.backtest.engine import BacktestConfig, run_backtest
from finagent.backtest.strategies import EqualWeightStrategy
from finagent.data.universe import ETF, Universe
from finagent.evaluation.benchmarks import (
    FixedWeightStrategy,
    benchmark_specs,
    pick_bond_etf,
    run_benchmarks,
)
from finagent.evaluation.checks import check_backtest, check_pit_rerun
from finagent.evaluation.value import (
    break_even_bps,
    cost_sensitivity,
    extended_metrics,
    ic_by_year,
    ledger_state,
    relative_metrics,
    required_settled,
    underwater_stats,
    worst_rolling_return,
)


def _panels(n: int = 140, symbols=("510300", "511010"), seed: int = 5):
    rng = np.random.default_rng(seed)
    index = pd.bdate_range("2024-01-01", periods=n)
    drift = np.linspace(0.0001, 0.0004, len(symbols))
    prices = 100 * np.cumprod(1 + rng.normal(0, 0.005, size=(n, len(symbols))) + drift, axis=0)
    close = pd.DataFrame(prices, index=index, columns=list(symbols))
    panels = {
        "close": close,
        "open": close * 1.0005,
        "high": close * 1.003,
        "low": close * 0.997,
        "volume": pd.DataFrame(1_000_000.0, index=index, columns=close.columns),
        "amount": pd.DataFrame(2e8, index=index, columns=close.columns),
    }
    return panels, index


def _universe() -> Universe:
    return Universe(
        version="u-test",
        etfs=[
            ETF(symbol="510300", name="HS300", category="broad", tracked_index="000300"),
            ETF(
                symbol="511010",
                name="国债ETF",
                category="bond",
                sector="利率债",
                tracked_index="000140",
                effective_from=date(2013, 3, 25),
            ),
            ETF(
                symbol="511260",
                name="十年国债ETF",
                category="bond",
                sector="利率债",
                tracked_index="000012",
                effective_from=date(2022, 1, 4),
            ),
        ],
    )


def test_buy_and_hold_trades_on_the_entry_day_only():
    panels, index = _panels()
    cfg = BacktestConfig(start=index[0], end=index[-1], rebalance_days=10**6)
    strategy = FixedWeightStrategy("hs300_buyhold", {"510300": 1.0})
    result = run_backtest(panels, strategy, cfg, cost_from_bps(7))
    filled = result.fills[result.fills["status"] == "filled"]
    assert set(pd.to_datetime(filled["date"]).unique()) == {index[1]}
    assert filled["side"].tolist() == ["buy"]


def test_sixty_forty_holds_both_legs_and_rebalances():
    panels, index = _panels()
    universe = _universe()
    specs = benchmark_specs(universe, panels["close"], index[0], index[-1])
    assert specs["sixty_forty"].strategy.weights == {"510300": 0.6, "511010": 0.4}
    results = run_benchmarks(panels, specs, BacktestConfig(start=index[0], end=index[-1]), cost_from_bps(7))
    assert results["sixty_forty"].daily["n_holdings"].iloc[-1] == 2
    assert results["hs300_buyhold"].daily["n_holdings"].iloc[-1] == 1


def test_bond_pick_is_rule_based_not_performance_based():
    panels, index = _panels()
    assert pick_bond_etf(_universe(), panels["close"], index[0], index[-1]) == "511010"


def test_bond_pick_rejects_an_etf_with_a_gap():
    panels, index = _panels(symbols=("510300", "511010", "511260"))
    close = panels["close"].copy()
    close.loc[index[40], "511010"] = np.nan
    assert pick_bond_etf(_universe(), close, index[0], index[-1]) == "511260"


def test_worst_rolling_return_and_underwater_stats():
    returns = pd.Series([0.10, -0.20, 0.05])
    assert worst_rolling_return(returns, window=2) == pytest.approx(0.8 * 1.05 - 1.0)
    stats = underwater_stats(returns)
    assert stats["share_underwater"] == pytest.approx(2 / 3, rel=1e-3)
    assert stats["longest_underwater_days"] == 2


def test_relative_metrics_of_a_series_against_itself():
    rng = np.random.default_rng(1)
    returns = pd.Series(rng.normal(0.0005, 0.01, 300))
    stats = relative_metrics(returns, returns)
    assert stats["beta"] == pytest.approx(1.0)
    assert stats["corr"] == pytest.approx(1.0)
    assert stats["tracking_error"] == pytest.approx(0.0, abs=1e-9)


def test_extended_metrics_reports_worst_year_and_underwater():
    rng = np.random.default_rng(2)
    returns = pd.Series(rng.normal(0.0002, 0.01, 600), index=pd.bdate_range("2023-01-02", periods=600))
    out = extended_metrics(returns, returns)
    for key in ("worst_12m", "share_underwater", "longest_underwater_days", "beta", "corr"):
        assert key in out


def test_break_even_interpolates_between_cost_levels():
    levels = [(0.0, 0.10, 0.08), (7.0, 0.05, 0.08)]
    assert break_even_bps(levels) == pytest.approx(2.8, abs=0.01)
    assert break_even_bps([(0.0, 0.05, 0.08), (7.0, 0.03, 0.08)]) is None


def test_cost_sensitivity_hurts_high_turnover_more():
    panels, index = _panels(n=200, symbols=("510300", "511010", "512880"))
    cfg = BacktestConfig(start=index[0], end=index[-1], rebalance_days=1)
    fast = FixedWeightStrategy("flip", {"510300": 1.0})
    strategies = {"fast": fast}
    table = cost_sensitivity(panels, strategies, cfg, bps=(0.0, 50.0))
    assert table["0"]["fast"]["cagr"] >= table["50"]["fast"]["cagr"]


def test_required_settled_matches_normal_approximation():
    assert required_settled(0.10) == 97
    assert required_settled(0.05) == 385


def test_ic_by_year_recovers_a_planted_signal():
    dates = pd.bdate_range("2023-12-01", periods=80)
    symbols = [f"S{i}" for i in range(10)]
    rng = np.random.default_rng(4)
    # A persistent signal: the same cross-sectional ordering every day, so a
    # next-day return linked to it is detectable year by year.
    signal = pd.DataFrame(
        np.tile(rng.normal(size=len(symbols)), (len(dates), 1)), index=dates, columns=symbols
    )
    noise = pd.DataFrame(rng.normal(scale=0.5, size=(len(dates), len(symbols))), index=dates, columns=symbols)
    returns = 0.01 * signal + 0.001 * noise
    # close at t+1 reflects the return from t to t+1
    close = pd.DataFrame(100.0, index=dates, columns=symbols)
    close.iloc[1:] = 100.0 * (1 + returns.iloc[:-1]).cumprod().to_numpy()
    rows = []
    for day in dates:
        for symbol in symbols:
            value = float(signal.loc[day, symbol])
            rows.append(
                {
                    "date": day,
                    "symbol": symbol,
                    "factor": "momentum_20",
                    "value": value,
                    "rank_cs": value,
                    "z_cs": value,
                }
            )
    factors = pd.DataFrame(rows)
    result = ic_by_year(close, factors, ["momentum_20"], horizons=(1,))
    assert {row["year"] for row in result} == {2023, 2024}
    assert all(row["ic_mean"] > 0 for row in result)


def test_ledger_state_reports_the_first_settlement_date(tmp_path):
    from finagent.predictions.ledger import PredictionLedger

    ledger = PredictionLedger(tmp_path / "predictions")
    ledger.append(
        [
            {
                "signal_id": "s1",
                "as_of": "2024-01-02",
                "symbol": "510300",
                "direction": 1,
                "horizon": 5,
                "execution_lag": 1,
            }
        ]
    )
    calendar = pd.bdate_range("2024-01-01", periods=30)
    state = ledger_state(tmp_path / "predictions", "2024-01-31", calendar=calendar)
    assert state["n_predictions"] == 1
    assert state["n_settled"] == 0
    assert state["first_settlement_date"] == calendar[7].date().isoformat()


def test_backtest_checks_catch_a_cost_mismatch():
    panels, index = _panels()
    cfg = BacktestConfig(start=index[0], end=index[-1], rebalance_days=5)
    result = run_backtest(panels, EqualWeightStrategy(_universe()), cfg, cost_from_bps(7))
    assert all(check.ok for check in check_backtest({"eq": result}, panels))
    result.metrics["total_cost"] = float(result.metrics["total_cost"]) + 1.0
    assert not all(check.ok for check in check_backtest({"eq": result}, panels))


def test_pit_rerun_agrees_with_the_full_run():
    panels, index = _panels(n=200)
    cfg = BacktestConfig(start=index[0], end=index[-1], rebalance_days=5)
    strategy = EqualWeightStrategy(_universe())
    check = check_pit_rerun(panels, strategy, cfg, cost_from_bps(7), index[120])
    assert check.ok
    assert check.evidence["max_abs_diff"] <= 1e-9
