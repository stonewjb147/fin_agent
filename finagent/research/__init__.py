"""Factor evaluation: IC, HAC t-statistics, multiple-testing control."""

from __future__ import annotations

from finagent.research.ic import cross_sectional_ic, ic_summary, quantile_spread_returns
from finagent.research.report import (
    DEFAULT_HORIZONS,
    bh_qvalues,
    evaluate,
    factor_snapshot,
    format_summary,
    run_factor_report,
)
from finagent.research.stats import bh_fdr, deflated_sharpe, newey_west_tstat, sharpe_ratio

__all__ = [
    "DEFAULT_HORIZONS",
    "bh_fdr",
    "bh_qvalues",
    "cross_sectional_ic",
    "deflated_sharpe",
    "evaluate",
    "factor_snapshot",
    "format_summary",
    "ic_summary",
    "newey_west_tstat",
    "quantile_spread_returns",
    "run_factor_report",
    "sharpe_ratio",
]
