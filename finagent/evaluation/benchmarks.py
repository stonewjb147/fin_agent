"""Benchmarks an ordinary investor could actually hold.

The Phase 4 suite only compares strategies inside the 50-ETF pool, which cannot
answer the question that matters: *would simply buying the index have been
better?* These benchmarks run through the same engine, the same cost model and
the same T+1 close execution, so the comparison is like for like.

Two rules are fixed in advance and not tuned to the answer:

* the 60/40 bond leg is the interest-rate bond ETF with full price coverage and
  the earliest listing (tie-break: symbol), not whichever bond ETF performed
  best;
* the 510300 leg is bought once and never rebalanced, so it pays one entry cost.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

import pandas as pd

from finagent.backtest.costs import CostModel
from finagent.backtest.engine import BacktestConfig, BacktestResult, run_backtest
from finagent.data.panel import as_date

HS300 = "510300"
BUY_AND_HOLD_DAYS = 10**6  # only the first session rebalances
SIXTY_FORTY_DAYS = 21


@dataclass(frozen=True)
class FixedWeightStrategy:
    """Constant target weights; the engine supplies execution and costs."""

    name: str
    weights: dict[str, float]

    def target_weights(self, as_of: pd.Timestamp, close_upto: pd.DataFrame) -> pd.Series:
        return pd.Series(self.weights, dtype=float)


@dataclass(frozen=True)
class BenchmarkSpec:
    name: str
    strategy: FixedWeightStrategy
    rebalance_days: int


def pick_bond_etf(universe, close: pd.DataFrame, start, end) -> str:
    """Interest-rate bond ETF with full coverage and the earliest listing."""
    start, end = pd.Timestamp(start), pd.Timestamp(end)
    candidates = []
    for etf in universe.for_date(as_date(end)):
        if etf.category != "bond" or etf.sector != "利率债":
            continue
        if etf.symbol not in close.columns:
            continue
        window = close.loc[start:end, etf.symbol]
        if window.empty or window.isna().any():
            continue
        candidates.append(etf)
    if not candidates:
        raise ValueError("no interest-rate bond ETF covers the whole window")
    candidates.sort(key=lambda e: (e.effective_from or as_date("1900-01-01"), e.symbol))
    return candidates[0].symbol


def benchmark_specs(universe, close: pd.DataFrame, start, end, bond_symbol: str | None = None) -> dict[str, BenchmarkSpec]:
    if HS300 not in close.columns:
        raise ValueError(f"{HS300} is not in the price panel; cannot build a benchmark")
    bond = bond_symbol or pick_bond_etf(universe, close, start, end)
    if bond not in close.columns:
        raise ValueError(f"bond ETF {bond} is not in the price panel")
    return {
        "hs300_buyhold": BenchmarkSpec(
            name="hs300_buyhold",
            strategy=FixedWeightStrategy("hs300_buyhold", {HS300: 1.0}),
            rebalance_days=BUY_AND_HOLD_DAYS,
        ),
        "sixty_forty": BenchmarkSpec(
            name="sixty_forty",
            strategy=FixedWeightStrategy("sixty_forty", {HS300: 0.6, bond: 0.4}),
            rebalance_days=SIXTY_FORTY_DAYS,
        ),
    }


def run_benchmarks(
    panels: dict[str, pd.DataFrame],
    specs: dict[str, BenchmarkSpec],
    cfg: BacktestConfig,
    cost: CostModel,
) -> dict[str, BacktestResult]:
    out: dict[str, BacktestResult] = {}
    for name, spec in specs.items():
        spec_cfg = replace(cfg, rebalance_days=spec.rebalance_days)
        out[name] = run_backtest(panels, spec.strategy, spec_cfg, cost)
    return out
