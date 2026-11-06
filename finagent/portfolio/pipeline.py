"""End-to-end portfolio run: close panel -> scores -> weights -> report file."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from finagent import config
from finagent.data.panel import as_date
from finagent.factors import DEFAULT_FACTORS, load_close_panel
from finagent.portfolio.construct import build_portfolio
from finagent.portfolio.policy import PortfolioPolicy, load_policy
from finagent.research.report import MIN_SYMBOLS, factor_snapshot
from finagent.signals.score import composite_scores


def run_portfolio(
    universe,
    *,
    as_of: date | str,
    cache_dir: str | Path | None = None,
    policy: PortfolioPolicy | None = None,
    factor_names=None,
    write: bool = True,
    out_dir: str | Path | None = None,
) -> dict:
    as_of = as_date(as_of)
    cache_dir = Path(cache_dir or config.CACHE_DIR)
    policy = policy or load_policy()

    close = load_close_panel(cache_dir, universe.symbols(as_of), as_of)
    factors = factor_snapshot(close, list(factor_names or DEFAULT_FACTORS), min_obs=MIN_SYMBOLS)
    scores = composite_scores(factors)
    result = build_portfolio(close, universe, as_of, scores, policy)

    if write:
        out_dir = Path(out_dir or config.PORTFOLIO_DIR)
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"{as_of.isoformat()}.json"
        path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        result["portfolio_file"] = str(path)
    return result
