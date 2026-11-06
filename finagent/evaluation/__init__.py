"""Phase acceptance and value evaluation.

Unit tests prove the code does what it says on synthetic data; this package
re-runs the same claims on the real cache and puts a number on what the system
is worth. It is deliberately separate from `finagent.evals`, which scores LLM
answers (Phase 6).

Everything here is read-only with respect to `data/cache`; the only writes are
the JSON report under `data/quality/`.
"""

from finagent.evaluation.benchmarks import (
    BenchmarkSpec,
    FixedWeightStrategy,
    benchmark_specs,
    pick_bond_etf,
    run_benchmarks,
)
from finagent.evaluation.checks import (
    Check,
    check_backtest,
    check_data_layer,
    check_factor_kernel,
    check_pit_rerun,
    check_signals_portfolio,
)
from finagent.evaluation.report import format_eval, run_phase_eval
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

__all__ = [
    "BenchmarkSpec",
    "Check",
    "FixedWeightStrategy",
    "benchmark_specs",
    "break_even_bps",
    "check_backtest",
    "check_data_layer",
    "check_factor_kernel",
    "check_pit_rerun",
    "check_signals_portfolio",
    "cost_sensitivity",
    "extended_metrics",
    "format_eval",
    "ic_by_year",
    "ledger_state",
    "pick_bond_etf",
    "relative_metrics",
    "required_settled",
    "run_benchmarks",
    "run_phase_eval",
    "underwater_stats",
    "worst_rolling_return",
]
