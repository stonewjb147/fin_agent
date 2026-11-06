"""Daily share-based backtest with T+1 execution, costs and blocked fills.

Design choices, all deliberate:

* **Shares, not weights.** Orders change share counts and cash; NAV is measured
  from holdings at the close. Weights alone would quietly assume that an order
  the market could not fill went through anyway.
* **T+1.** A target computed from day T's close is executed on the next
  session, matching `EXECUTION_LAG_DAYS` and the forward-return direction used
  everywhere else in the project (`P(t+1+h)/P(t+1) - 1`).
* **Blocked fills.** A suspended ETF (no price or zero volume) cannot trade; a
  limit-up day blocks buys, a limit-down day blocks sells. The unfilled weight
  simply stays where it was and is retried at the next rebalance.
* **No cash debt.** Sells settle before buys; buys are scaled down when the
  proceeds are not enough, including the cost of the buy itself.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from typing import Any, Protocol

import numpy as np
import pandas as pd

from finagent import config
from finagent.backtest.costs import DEFAULT_COST, CostModel
from finagent.backtest.metrics import performance

EPS = 1e-12


class Strategy(Protocol):
    """Anything that can propose target weights from data up to `as_of`."""

    name: str

    def target_weights(self, as_of: pd.Timestamp, close_upto: pd.DataFrame) -> pd.Series:
        ...


@dataclass(frozen=True)
class BacktestConfig:
    start: date | str
    end: date | str
    rebalance_days: int = config.BACKTEST_REBALANCE_DAYS
    execution_lag: int = config.EXECUTION_LAG_DAYS
    execution_price: str = "close"  # "close" (matches the ledger) or "open"
    limit_move: float = config.LIMIT_MOVE_THRESHOLD
    min_trade_weight: float = config.BACKTEST_MIN_TRADE_WEIGHT
    initial_nav: float = 1.0
    max_invested: float = 1.0

    def __post_init__(self) -> None:
        if self.rebalance_days < 1:
            raise ValueError("rebalance_days must be >= 1")
        if self.execution_lag < 0:
            raise ValueError("execution_lag cannot be negative")
        if self.execution_price not in {"close", "open"}:
            raise ValueError("execution_price must be 'close' or 'open'")
        if not 0.0 < self.max_invested <= 1.0:
            raise ValueError("max_invested must be in (0, 1]")
        if self.initial_nav <= 0:
            raise ValueError("initial_nav must be positive")

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        for key in ("start", "end"):
            payload[key] = _iso(payload[key])
        return payload


@dataclass
class BacktestResult:
    name: str
    daily: pd.DataFrame
    fills: pd.DataFrame
    metrics: dict[str, Any]
    gross_metrics: dict[str, Any]
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "metrics": self.metrics,
            "gross_metrics": self.gross_metrics,
            "diagnostics": self.diagnostics,
        }


def run_backtest(
    panels: Mapping[str, pd.DataFrame],
    strategy: Strategy,
    cfg: BacktestConfig,
    cost: CostModel | None = None,
) -> BacktestResult:
    cost = cost or DEFAULT_COST
    start, end = pd.Timestamp(cfg.start), pd.Timestamp(cfg.end)
    if start > end:
        raise ValueError("start must not be after end")

    close = panels["close"].loc[start:end]
    if close.empty:
        raise ValueError(f"no price data between {start.date()} and {end.date()}")
    # Strategies see everything before `start` as warm-up history; only the P&L
    # window starts at `start`. Trimming history here would leave the first
    # weeks with no volatility estimate and therefore no investable weights.
    history = panels["close"].loc[:end]
    prices = {field: panel.reindex(index=close.index, columns=close.columns) for field, panel in panels.items()}
    fill_panel = prices[cfg.execution_price]
    valuation = prices["close"].ffill()
    volume = prices["volume"].fillna(0.0)
    prev_close = prices["close"].shift(1)

    dates = close.index
    symbols = close.columns
    shares = pd.Series(0.0, index=symbols)
    cash = float(cfg.initial_nav)

    scheduled: dict[int, pd.Series] = {}
    daily_rows: list[dict[str, Any]] = []
    fill_rows: list[dict[str, Any]] = []

    for i, day in enumerate(dates):
        turnover = 0.0
        cost_paid = 0.0
        blocked_count = 0

        target = scheduled.pop(i, None)
        if target is not None:
            nav_ref = _nav(cash, shares, valuation, i if cfg.execution_price == "close" else i - 1)
            result = _execute(
                target=target,
                day=day,
                nav_ref=nav_ref,
                shares=shares,
                cash=cash,
                fill_px=fill_panel.loc[day],
                prev_close=prev_close.loc[day],
                volume=volume.loc[day],
                cfg=cfg,
                cost=cost,
            )
            shares, cash = result["shares"], result["cash"]
            turnover, cost_paid = result["turnover"], result["cost"]
            blocked_count = result["blocked"]
            for row in result["fills"]:
                fill_rows.append({"date": day, **row})

        nav = _nav(cash, shares, valuation, i)
        previous = daily_rows[-1]["nav"] if daily_rows else float(cfg.initial_nav)
        daily_rows.append(
            {
                "date": day,
                "nav": nav,
                "ret": nav / previous - 1.0 if previous > EPS else np.nan,
                "cash_weight": cash / nav if nav > EPS else np.nan,
                "n_holdings": int((shares > EPS).sum()),
                "turnover": turnover,
                "cost": cost_paid,
                "cost_frac": cost_paid / previous if previous > EPS else np.nan,
                "blocked": blocked_count,
            }
        )

        if i % cfg.rebalance_days == 0 and i + cfg.execution_lag < len(dates):
            weights = _clean_weights(strategy.target_weights(day, history.loc[:day]), symbols, cfg)
            scheduled[i + cfg.execution_lag] = weights

    daily = pd.DataFrame(daily_rows).set_index("date")
    daily.index.name = "date"
    fills = pd.DataFrame(
        fill_rows,
        columns=["date", "symbol", "side", "weight_delta", "notional", "cost", "status"],
    )

    net = daily["ret"].fillna(0.0)
    gross = net + daily["cost_frac"].fillna(0.0)
    metrics = performance(net, rf=config.DEFAULT_RISK_FREE_RATE)
    metrics.update(_trading_stats(daily))
    gross_metrics = performance(gross, rf=config.DEFAULT_RISK_FREE_RATE)

    return BacktestResult(
        name=strategy.name,
        daily=daily,
        fills=fills,
        metrics=metrics,
        gross_metrics=gross_metrics,
    )


# ------------------------------------------------------------------ helpers
def _iso(value: date | str) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, datetime):
        return value.date().isoformat()
    return value.isoformat()


def _nav(cash: float, shares: pd.Series, valuation: pd.DataFrame, position: int) -> float:
    """Holdings marked at the latest known close, plus cash."""
    if position < 0:
        return float(cash)
    row = valuation.iloc[position]
    held = shares.reindex(row.index).fillna(0.0)
    prices = row.fillna(0.0)
    return float(cash + (held * prices).sum())


def _clean_weights(weights: pd.Series, symbols: pd.Index, cfg: BacktestConfig) -> pd.Series:
    """Non-negative, universe-only, and never more than `max_invested` in total."""
    weights = pd.Series(weights, dtype=float).reindex(symbols).fillna(0.0)
    weights = weights.where(np.isfinite(weights), 0.0).clip(lower=0.0)
    total = float(weights.sum())
    if total > cfg.max_invested + EPS:
        weights = weights * (cfg.max_invested / total)
    return weights


def _execute(
    *,
    target: pd.Series,
    day: pd.Timestamp,
    nav_ref: float,
    shares: pd.Series,
    cash: float,
    fill_px: pd.Series,
    prev_close: pd.Series,
    volume: pd.Series,
    cfg: BacktestConfig,
    cost: CostModel,
) -> dict[str, Any]:
    shares = shares.copy()
    price = fill_px.reindex(shares.index)
    previous = prev_close.reindex(shares.index)

    suspended = price.isna() | (volume.reindex(shares.index).fillna(0.0) <= 0.0)
    move = price / previous - 1.0
    limit_up = move >= cfg.limit_move
    limit_down = move <= -cfg.limit_move

    opening_value = shares * price.fillna(0.0)
    target_value = target.reindex(shares.index).fillna(0.0) * nav_ref
    delta = target_value - opening_value

    fills: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    traded = 0.0
    paid = 0.0

    def block(symbol: str, side: str, reason: str) -> None:
        blocked.append(
            {
                "symbol": symbol,
                "side": side,
                "weight_delta": delta[symbol] / nav_ref if nav_ref > EPS else np.nan,
                "notional": 0.0,
                "cost": 0.0,
                "status": reason,
            }
        )

    def tradable(symbol: str, side: str) -> bool:
        if suspended.get(symbol, True):
            block(symbol, side, "suspended")
            return False
        if side == "buy" and bool(limit_up.get(symbol, False)):
            block(symbol, side, "limit_up")
            return False
        if side == "sell" and bool(limit_down.get(symbol, False)):
            block(symbol, side, "limit_down")
            return False
        return True

    def too_small(symbol: str, side: str) -> bool:
        if cfg.min_trade_weight <= 0 or nav_ref <= EPS:
            return False
        if abs(delta[symbol]) / nav_ref >= cfg.min_trade_weight:
            return False
        block(symbol, side, "small")
        return True

    # 1) sells first, so their proceeds can fund the buys
    for symbol in shares.index:
        if delta[symbol] >= -EPS or too_small(symbol, "sell") or not tradable(symbol, "sell"):
            continue
        held = float(opening_value[symbol])
        notional = min(-float(delta[symbol]), held)
        if notional <= EPS:
            continue
        px = float(price[symbol])
        shares[symbol] -= notional / px
        charge = cost.cost(notional)
        cash += notional - charge
        traded += notional
        paid += charge
        fills.append(_fill_row(symbol, "sell", notional / nav_ref if nav_ref > EPS else np.nan, notional, charge, "filled"))

    # 2) buys, scaled down if the cash (net of cost) cannot cover them
    wanted = {
        symbol: float(delta[symbol])
        for symbol in shares.index
        if delta[symbol] > EPS and not too_small(symbol, "buy") and tradable(symbol, "buy")
    }
    requested = sum(wanted.values())
    budget = max(cash, 0.0) / (1.0 + cost.one_way) if requested > EPS else 0.0
    scale = min(1.0, budget / requested) if requested > EPS else 0.0
    for symbol, notional in wanted.items():
        notional *= scale
        if notional <= EPS:
            block(symbol, "buy", "cash")
            continue
        px = float(price[symbol])
        shares[symbol] += notional / px
        charge = cost.cost(notional)
        cash -= notional + charge
        traded += notional
        paid += charge
        fills.append(_fill_row(symbol, "buy", notional / nav_ref if nav_ref > EPS else np.nan, notional, charge, "filled"))

    return {
        "shares": shares,
        "cash": cash,
        "turnover": traded / (2.0 * nav_ref) if nav_ref > EPS else 0.0,
        "cost": paid,
        "blocked": len(blocked),
        "fills": fills + blocked,
    }


def _fill_row(symbol: str, side: str, weight_delta: float, notional: float, charge: float, status: str) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "side": side,
        "weight_delta": weight_delta,
        "notional": notional,
        "cost": charge,
        "status": status,
    }


def _trading_stats(daily: pd.DataFrame) -> dict[str, Any]:
    n_days = len(daily)
    years = n_days / config.TRADING_DAYS_PER_YEAR if n_days else np.nan
    turnover = float(daily["turnover"].sum())
    cost_paid = float(daily["cost"].sum())
    return {
        "n_days": n_days,
        "years": round(float(years), 4),
        "annual_turnover": round(turnover / years, 4) if years and years > 0 else np.nan,
        "total_cost": round(cost_paid, 6),
        "annual_cost": round(cost_paid / years, 6) if years and years > 0 else np.nan,
        "avg_cash_weight": round(float(daily["cash_weight"].mean()), 4),
        "avg_holdings": round(float(daily["n_holdings"].mean()), 2),
        "blocked_fills": int(daily["blocked"].sum()),
    }
