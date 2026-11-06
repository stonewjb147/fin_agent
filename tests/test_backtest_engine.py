"""Engine semantics: T+1 fills, costs, blocked fills, no look-ahead."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
import pytest

from finagent.backtest.costs import CostModel, cost_from_bps, zero_cost
from finagent.backtest.engine import BacktestConfig, run_backtest


@dataclass
class Stub:
    name: str
    weights: dict | None = None
    fn: object = None

    def target_weights(self, as_of, close_upto):
        if self.fn is not None:
            return pd.Series(self.fn(as_of, close_upto), dtype=float)
        return pd.Series(self.weights, dtype=float)


def _panels(closes: dict[str, list[float]], volumes: dict[str, list[float]] | None = None) -> dict[str, pd.DataFrame]:
    index = pd.bdate_range("2024-01-01", periods=len(next(iter(closes.values()))))
    close = pd.DataFrame(closes, index=index, dtype=float)
    volume = pd.DataFrame(
        {s: (volumes or {}).get(s, [1_000_000.0] * len(index)) for s in closes},
        index=index,
        dtype=float,
    )
    return {
        "open": close.copy(),
        "close": close,
        "high": close.copy(),
        "low": close.copy(),
        "volume": volume,
        "amount": close * 1e6,
    }


def _run(closes, weights, *, volumes=None, cost=None, **cfg_kwargs):
    panels = _panels(closes, volumes)
    cfg = BacktestConfig(
        start=panels["close"].index[0].date(),
        end=panels["close"].index[-1].date(),
        **cfg_kwargs,
    )
    return run_backtest(panels, Stub("stub", weights=weights), cfg, cost or zero_cost())


def test_first_target_fills_on_the_next_session():
    closes = {"A": [1.0, 1.0, 2.0, 2.0, 2.0], "B": [1.0] * 5}
    result = _run(closes, {"A": 1.0}, rebalance_days=1)

    nav = result.daily["nav"]
    assert nav.iloc[0] == pytest.approx(1.0)  # nothing held on the signal day
    assert result.daily["cash_weight"].iloc[0] == pytest.approx(1.0)
    assert nav.iloc[1] == pytest.approx(1.0)  # bought at 1.0 on day 1
    assert nav.iloc[2] == pytest.approx(2.0)  # A doubled
    assert nav.iloc[-1] == pytest.approx(2.0)
    assert result.metrics["total_return"] == pytest.approx(1.0)


def test_fills_use_the_next_session_price_not_the_signal_price():
    # The signal is generated on day 0 at 1.0; the fill happens on day 1 at 1.05.
    closes = {"A": [1.0, 1.05, 1.05, 1.05]}
    result = _run(closes, {"A": 1.0}, rebalance_days=1)
    assert result.fills.iloc[0]["date"] == result.daily.index[1]
    assert result.fills.iloc[0]["notional"] == pytest.approx(1.0)


def test_execution_at_the_open_uses_the_open_price():
    panels = _panels({"A": [1.0, 1.05, 1.05, 1.05]})
    panels["open"] = panels["open"].copy()
    panels["open"].iloc[1] = 1.02  # small gap at the open; the close is 1.05
    cfg = BacktestConfig(
        start=panels["close"].index[0].date(),
        end=panels["close"].index[-1].date(),
        rebalance_days=1,
        execution_price="open",
    )
    result = run_backtest(panels, Stub("stub", weights={"A": 1.0}), cfg, zero_cost())
    # 1.0 invested at the 1.02 open buys 1/1.02 units, marked at the 1.05 close
    assert result.daily["nav"].iloc[1] == pytest.approx(1.05 / 1.02)


def test_future_prices_never_change_past_nav():
    base = [1.0, 1.01, 0.99, 1.02, 1.0, 1.03, 1.01, 1.05]
    bumped = base[:5] + [2.0, 2.0, 2.0]
    weights = {"A": 0.6, "B": 0.4}
    first = _run({"A": base, "B": [1.0] * len(base)}, weights, rebalance_days=1)
    second = _run({"A": bumped, "B": [1.0] * len(bumped)}, weights, rebalance_days=1)
    assert np.allclose(first.daily["nav"].iloc[:5], second.daily["nav"].iloc[:5])


def test_cost_is_charged_on_traded_notional():
    closes = {"A": [1.0] * 5}
    free = _run(closes, {"A": 1.0}, rebalance_days=1, cost=zero_cost())
    paid = _run(closes, {"A": 1.0}, rebalance_days=1, cost=CostModel(commission=0.001, slippage=0.0))
    assert free.daily["nav"].iloc[-1] == pytest.approx(1.0)
    assert paid.daily["nav"].iloc[-1] == pytest.approx(1.0 - 0.001 / 1.001, rel=1e-3)
    assert paid.metrics["total_cost"] == pytest.approx(0.001 / 1.001, rel=1e-3)


def test_higher_costs_lower_the_sharpe():
    rng = np.random.default_rng(5)
    closes = {"A": list(100 * np.cumprod(1 + rng.normal(0.0005, 0.01, 60)))}
    free = _run(closes, {"A": 1.0}, rebalance_days=1, cost=zero_cost())
    costly = _run(closes, {"A": 1.0}, rebalance_days=1, cost=cost_from_bps(30))
    assert costly.metrics["sharpe"] <= free.metrics["sharpe"]
    assert costly.metrics["total_cost"] > free.metrics["total_cost"]


def test_a_suspended_etf_is_not_bought():
    closes = {"A": [1.0] * 5}
    volumes = {"A": [1e6, 0.0, 1e6, 1e6, 1e6]}
    result = _run(closes, {"A": 1.0}, volumes=volumes, rebalance_days=1)

    day1 = result.daily.index[1]
    assert result.daily.loc[day1, "nav"] == pytest.approx(1.0)
    assert result.daily.loc[day1, "cash_weight"] == pytest.approx(1.0)
    assert result.daily.loc[day1, "blocked"] >= 1
    # retried on day 2, when the ETF trades again
    assert result.daily["n_holdings"].iloc[2] == 1


def test_a_limit_up_day_blocks_the_buy():
    closes = {"A": [1.0, 1.15, 1.15, 1.15]}
    result = _run(closes, {"A": 1.0}, rebalance_days=1)
    day1 = result.daily.index[1]
    assert result.daily.loc[day1, "n_holdings"] == 0
    assert result.daily.loc[day1, "blocked"] >= 1


def test_a_limit_down_day_blocks_the_sell():
    closes = {"A": [1.0, 1.0, 0.9, 0.9, 0.9]}

    def target(as_of, close_upto):
        # hold on day 0, go to cash from day 1 onwards
        return {"A": 1.0} if as_of == close_upto.index[0] else {}

    result = run_backtest(
        _panels(closes),
        Stub("stub", fn=target),
        BacktestConfig(
            start=pd.Timestamp("2024-01-01").date(),
            end=pd.Timestamp("2024-01-05").date(),
            rebalance_days=1,
        ),
        zero_cost(),
    )
    day2 = result.daily.index[2]
    assert result.daily.loc[day2, "n_holdings"] == 1  # sell blocked on -10%
    assert result.daily.loc[day2, "blocked"] >= 1
    assert result.daily["n_holdings"].iloc[-1] == 0  # sold once it traded normally


def test_cash_never_goes_negative_and_nav_adds_up():
    rng = np.random.default_rng(11)
    closes = {f"S{i}": list(10 * np.cumprod(1 + rng.normal(0, 0.01, 40))) for i in range(6)}
    weights = {f"S{i}": 1 / 6 for i in range(6)}
    result = _run(closes, weights, rebalance_days=2, cost=cost_from_bps(10))
    assert (result.daily["cash_weight"] >= -1e-9).all()
    assert np.isfinite(result.daily["nav"]).all()
    assert result.daily["nav"].iloc[0] == pytest.approx(1.0)


def test_turnover_is_zero_when_the_target_does_not_change():
    closes = {"A": [1.0] * 6, "B": [1.0] * 6}
    result = _run(closes, {"A": 0.5, "B": 0.5}, rebalance_days=1)
    assert result.daily["turnover"].iloc[1] == pytest.approx(0.5, rel=0.05)
    assert result.daily["turnover"].iloc[2:].abs().max() < 1e-9


def test_weights_above_one_are_scaled_down():
    closes = {"A": [1.0, 1.0, 1.05, 1.05], "B": [1.0, 1.0, 1.05, 1.05]}
    result = _run(closes, {"A": 1.0, "B": 1.0}, rebalance_days=1)
    assert result.daily["cash_weight"].min() >= -1e-9
    assert result.daily["nav"].iloc[-1] == pytest.approx(1.05)


def test_unknown_symbols_in_targets_are_ignored():
    closes = {"A": [1.0, 1.0, 1.0]}
    result = _run(closes, {"A": 0.5, "ZZZ": 0.5}, rebalance_days=1)
    assert result.daily["cash_weight"].iloc[-1] == pytest.approx(0.5)


def test_negative_or_nan_weights_are_clipped():
    closes = {"A": [1.0] * 4, "B": [1.0] * 4}
    result = _run(closes, {"A": -0.3, "B": float("nan")}, rebalance_days=1)
    assert result.daily["n_holdings"].max() == 0
    assert result.daily["cash_weight"].min() == pytest.approx(1.0)


def test_empty_window_raises():
    panels = _panels({"A": [1.0, 1.1, 1.2]})
    with pytest.raises(ValueError, match="no price data"):
        run_backtest(
            panels,
            Stub("stub", weights={"A": 1.0}),
            BacktestConfig(start=pd.Timestamp("2030-01-01").date(), end=pd.Timestamp("2030-02-01").date()),
        )
