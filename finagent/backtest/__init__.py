"""Backtest engine, cost model and overfitting diagnostics (Phase 4).

The engine is share-based rather than weight-arithmetic: orders are filled at
the next session's price after costs, suspensions and limit moves, so a target
weight that could not be reached stays unreached instead of being assumed away.
"""

from finagent.backtest.costs import CostModel
from finagent.backtest.engine import BacktestConfig, BacktestResult, run_backtest

__all__ = ["BacktestConfig", "BacktestResult", "CostModel", "run_backtest"]
