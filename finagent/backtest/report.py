"""Run the strategy suite, add overfitting diagnostics, write the report."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pandas as pd

from finagent import config
from finagent.backtest.costs import DEFAULT_COST, CostModel
from finagent.backtest.data import load_price_panels
from finagent.backtest.engine import BacktestConfig, BacktestResult, run_backtest
from finagent.backtest.overfitting import (
    cpcv_sharpes,
    cpcv_summary,
    dsr_table,
    probability_of_backtest_overfitting,
    returns_matrix,
)
from finagent.backtest.strategies import default_strategies
from finagent.data.panel import as_date
from finagent.factors import DEFAULT_FACTORS
from finagent.portfolio.policy import PortfolioPolicy, load_policy
from finagent.research.report import MIN_SYMBOLS, factor_snapshot
from finagent.signals.score import composite_scores

CPCV_GROUPS = 8
CPCV_TEST_BLOCKS = 2
CPCV_EMBARGO = 5
PBO_BLOCKS = 12


def run_backtest_suite(
    universe,
    *,
    start: date | str,
    end: date | str,
    cache_dir: str | Path | None = None,
    cost: CostModel | None = None,
    policy: PortfolioPolicy | None = None,
    rebalance_days: int = config.BACKTEST_REBALANCE_DAYS,
    execution_price: str = "close",
    execution_lag: int = config.EXECUTION_LAG_DAYS,
    top_n: int = 10,
    trials: int | None = None,
    write: bool = True,
    out_dir: str | Path | None = None,
) -> dict:
    start, end = as_date(start), as_date(end)
    cost = cost or DEFAULT_COST
    policy = policy or load_policy()
    cache_dir = Path(cache_dir or config.CACHE_DIR)

    panels = load_price_panels(cache_dir, universe.symbols(end), end)
    close = panels["close"]
    # Factors are causal: a value dated t only uses prices up to t, so computing
    # the whole panel once and slicing per rebalance cannot leak the future.
    factors = factor_snapshot(close, list(DEFAULT_FACTORS), min_obs=MIN_SYMBOLS)
    scores = composite_scores(factors)

    cfg = BacktestConfig(
        start=start,
        end=end,
        rebalance_days=rebalance_days,
        execution_lag=execution_lag,
        execution_price=execution_price,
    )
    strategies = default_strategies(universe, scores, policy, top_n=top_n)
    results: dict[str, BacktestResult] = {}
    for name, strategy in strategies.items():
        result = run_backtest(panels, strategy, cfg, cost)
        results[name] = result

    returns = returns_matrix(list(results.values()))
    diagnostics = _diagnostics(returns, window=max(rebalance_days, 1), trials=trials)

    report = {
        "window": {
            "start": start.isoformat(),
            "end": end.isoformat(),
            "n_days": int(len(returns)),
        },
        "universe_version": getattr(universe, "version", "unknown"),
        "policy": policy.as_dict(),
        "policy_fingerprint": policy.fingerprint(),
        "cost_model": cost.as_dict(),
        "backtest": cfg.as_dict(),
        "strategies": {
            name: {
                "metrics": result.metrics,
                "gross_metrics": result.gross_metrics,
            }
            for name, result in results.items()
        },
        "diagnostics": diagnostics,
        "meta": {
            "execution": f"T close signal -> T+{execution_lag} {execution_price}",
            "returns": "daily, net of commission and slippage",
            "benchmark": "equal_weight over the same universe",
            "annualisation": config.TRADING_DAYS_PER_YEAR,
        },
    }

    if write:
        out_dir = Path(out_dir or config.REPORT_DIR)
        out_dir.mkdir(parents=True, exist_ok=True)
        json_path = out_dir / f"backtest_{end.isoformat()}.json"
        json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        report["report_file"] = str(json_path)

        daily_path = out_dir / f"backtest_{end.isoformat()}_daily.csv"
        nav = pd.DataFrame({name: result.daily["nav"] for name, result in results.items()})
        nav.index.name = "date"
        nav.to_csv(daily_path, float_format="%.6f")
        report["daily_file"] = str(daily_path)

        fills_path = out_dir / f"backtest_{end.isoformat()}_fills.csv"
        frames = []
        for name, result in results.items():
            if result.fills.empty:
                continue
            frame = result.fills.copy()
            frame.insert(0, "strategy", name)
            frames.append(frame)
        if frames:
            pd.concat(frames, ignore_index=True).to_csv(fills_path, index=False, float_format="%.8f")
            report["fills_file"] = str(fills_path)
    return {"report": report, "results": results, "returns": returns}


def _diagnostics(returns: pd.DataFrame, window: int, trials: int | None = None) -> dict:
    out: dict = {"cpcv": {}, "pbo": {}, "dsr": {}}
    if returns.empty or returns.shape[1] < 2:
        return out
    cpcv = cpcv_sharpes(returns, CPCV_GROUPS, CPCV_TEST_BLOCKS, embargo=max(CPCV_EMBARGO, window))
    out["cpcv"] = {
        "groups": CPCV_GROUPS,
        "test_blocks": CPCV_TEST_BLOCKS,
        "embargo": max(CPCV_EMBARGO, window),
        "summary": cpcv_summary(cpcv),
    }
    out["pbo"] = probability_of_backtest_overfitting(returns, n_blocks=PBO_BLOCKS)
    # The trial count is what the researcher admits to having tried; by default
    # it is only the variants in this run, which is the optimistic case.
    out["dsr"] = dsr_table(returns, n_trials=trials or returns.shape[1])
    out["dsr_trials"] = int(trials or returns.shape[1])
    return out


def format_backtest(report: dict) -> str:
    window = report["window"]
    cost = report["cost_model"]
    lines = [
        f"Backtest {window['start']} .. {window['end']}  days={window['n_days']}  "
        f"cost={cost['one_way_bps']:.1f}bp/side  "
        f"rebalance every {report['backtest']['rebalance_days']}d  "
        f"exec=T+{report['backtest']['execution_lag']} {report['backtest']['execution_price']}",
        "",
        f"{'STRATEGY':<16}{'CAGR':>8}{'VOL':>8}{'SHARPE':>8}{'MDD':>8}{'CALMAR':>8}"
        f"{'TURN/yr':>8}{'COST/yr':>9}{'DSR':>7}",
    ]
    dsr = report.get("diagnostics", {}).get("dsr", {})
    for name, block in report["strategies"].items():
        m = block["metrics"]
        lines.append(
            f"{name:<16}{_pct(m['cagr']):>8}{_pct(m['ann_vol']):>8}{_num(m['sharpe']):>8}"
            f"{_pct(m['max_drawdown']):>8}{_num(m['calmar']):>8}"
            f"{_num(m['annual_turnover']):>8}{_pct(m['annual_cost']):>9}"
            f"{_num(dsr.get(name, {}).get('dsr')):>7}"
        )
    pbo = report.get("diagnostics", {}).get("pbo", {})
    if pbo.get("pbo") is not None:
        lines.append("")
        lines.append(
            f"PBO {_pct(pbo.get('pbo'))} over {pbo.get('n_combinations')} splits "
            f"({pbo.get('n_blocks')} blocks x {pbo.get('block_days')}d)  |  "
            f"DSR trials={report['diagnostics'].get('dsr_trials', len(report['strategies']))}"
        )
    cpcv = report.get("diagnostics", {}).get("cpcv", {}).get("summary", {})
    if cpcv:
        lines.append("CPCV test-Sharpe (mean / 5th pct / share>0):")
        for name, stats in cpcv.items():
            lines.append(
                f"  {name:<16}{_num(stats['mean']):>8}  {_num(stats['p05']):>8}  {_pct(stats['positive_fraction']):>8}"
            )
    return "\n".join(lines)


def _pct(value) -> str:
    if value is None or pd.isna(value):
        return "-"
    return f"{float(value) * 100:.1f}%"


def _num(value) -> str:
    if value is None or pd.isna(value):
        return "-"
    return f"{float(value):.2f}"
